"""Collect the Parallel arm, which is asynchronous.

Creates one task run per query, then polls. Run ids are written to
data/results/parallel_progress.json as soon as they exist, so a run that
outlives this process can still be recovered by src.resume_parallel.

Usage:  python3 -m src.collect_parallel [--limit N] [--workers N] [--force]"""

import json
import os
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed

from pathlib import Path

from src.common import PACK, cache_path, ROOT, maybe_help
from src.searchers import parallel

ARM = "parallel"               # must match src.score.ARMS
PROGRESS = PACK / "results" / "parallel_progress.json"


def write_progress(state):
    """Merge into the existing file rather than replacing it.

    Per-query entries are never dropped, so a partial run cannot discard run
    ids belonging to a batch that is still executing."""
    PROGRESS.parent.mkdir(parents=True, exist_ok=True)
    merged = {}
    if PROGRESS.exists():
        try:
            merged = json.loads(PROGRESS.read_text())
        except Exception:
            merged = {}
    q = dict(merged.get("queries") or {})
    q.update(state.get("queries") or {})
    out = {**merged, **state, "queries": q}
    PROGRESS.write_text(json.dumps(out, indent=1))


def _flag_value(name):
    """Value of --name N or --name=N; SystemExit(2) on a dangling flag."""
    for i, a in enumerate(sys.argv):
        if a == name:
            if i + 1 >= len(sys.argv):
                raise SystemExit(f"{name} needs a value")
            return sys.argv[i + 1]
        if a.startswith(name + "="):
            return a.split("=", 1)[1]
    return None


KNOWN = {"--force", "--workers", "--limit", "--only", "-h", "--help"}


def _validate_argv():
    """Reject anything unrecognised BEFORE a single billable run is created."""
    expect_value = False
    for a in sys.argv[1:]:
        if expect_value:
            expect_value = False
            continue
        base = a.split("=", 1)[0]
        if base not in KNOWN:
            raise SystemExit(f"unknown flag {a!r} - refusing to start a paid "
                             f"collection. Known: {' '.join(sorted(KNOWN))}")
        if base in ("--workers", "--limit", "--only") and "=" not in a:
            expect_value = True


def main():
    _validate_argv()
    force = "--force" in sys.argv
    workers = int(_flag_value("--workers") or 8)

    spec = json.loads((ROOT / "data" / "queries" / "queries.json").read_text())
    only = None
    ov = _flag_value("--only")
    if ov:
        only = set(ov.split(","))
    lv = _flag_value("--limit")
    if lv is not None:
        n = int(lv)
        if n < 1:
            raise SystemExit("--limit must be at least 1")
        spec["queries"] = spec["queries"][:n]
    todo = []
    for q in spec["queries"]:
        if only and q["id"] not in only:
            continue
        p = cache_path(ARM, q["id"])
        if p.exists() and not force:
            continue
        todo.append(q)

    state = {"arm": ARM, "processor": parallel.PROCESSOR,
             "total": len(spec["queries"]), "skipped_cached": len(spec["queries"]) - len(todo),
             "created": 0, "completed": 0, "failed": 0,
             "started_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
             "queries": {}}
    write_progress(state)
    if not todo:
        print("nothing to do - all queries cached")
        return

    # ---- phase 1: create every run up front -------------------------------
    print(f"creating {len(todo)} runs (processor={parallel.PROCESSOR}) ...", flush=True)
    runs = {}
    t_create = time.time()
    lock = threading.Lock()

    def create_one(q):
        # The run id is money: record it from inside the worker, so an
        # interrupt in the main loop cannot orphan a run a thread already paid
        # for.
        st, rid, raw = parallel.create_run(q["text"])
        with lock:
            if rid:
                runs[q["id"]] = rid
                state["created"] += 1
                state["queries"][q["id"]] = {"run_id": rid, "status": "running"}
            else:
                state["failed"] += 1
                state["queries"][q["id"]] = {"status": "create_failed",
                                             "http_status": st,
                                             "error": json.dumps(raw)[:300]}
                print(f"  [{q['id']}] CREATE FAILED {st}: {json.dumps(raw)[:180]}", flush=True)
            write_progress(state)

    with ThreadPoolExecutor(max_workers=workers) as ex:
        list(ex.map(create_one, todo))
    print(f"created {len(runs)}/{len(todo)} in {int(time.time()-t_create)}s\n", flush=True)

    # ---- phase 2: harvest concurrently, writing each as it lands ----------
    qtext = {q["id"]: q["text"] for q in spec["queries"]}
    t0 = time.time()

    def harvest(qid, rid):
        st, resp, ms = parallel.fetch_result(rid)
        env = {
            "arm": ARM, "query_id": qid,
            "request": {"url": parallel.CREATE, "method": "POST",
                        "body": {"input": parallel.PROMPT.format(q=qtext[qid]),
                                 "processor": parallel.PROCESSOR,
                                 "output_schema": "people[] (see searchers/parallel.py)"},
                        "run_id": rid},
            "http_status": st, "latency_ms": ms,
            "fetched_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "response": resp, "_from_cache": False,
        }
        if 200 <= st < 300:
            p = cache_path(ARM, qid)
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(json.dumps(env, indent=1))
        return qid, env

    with ThreadPoolExecutor(max_workers=workers) as ex:
        futs = [ex.submit(harvest, qid, rid) for qid, rid in runs.items()]
        for fut in as_completed(futs):
            qid, env = fut.result()
            ok = 200 <= (env["http_status"] or 0) < 300
            n = len(parallel.parse(env)["results"]) if ok else 0
            if ok:
                state["completed"] += 1
                state["queries"][qid] = {"run_id": runs[qid], "status": "done",
                                         "n_results": n, "latency_ms": env["latency_ms"]}
            else:
                state["failed"] += 1
                state["queries"][qid] = {"run_id": runs[qid], "status": "failed",
                                         "http_status": env["http_status"],
                                         "error": json.dumps(env["response"])[:300]}
            state["elapsed_s"] = int(time.time() - t0)
            write_progress(state)
            done = state["completed"] + state["failed"]
            print(f"  [{qid:>3}] {'ok ' if ok else 'ERR'} {n:>2} people  "
                  f"{env['latency_ms']/1000:6.1f}s   ({done}/{len(runs)} done, "
                  f"{int(time.time()-t0)}s elapsed)", flush=True)

    state["finished_at"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    write_progress(state)
    print(f"\n{ARM}: {state['completed']} ok, {state['failed']} failed, "
          f"{int(time.time()-t0)}s wall")


if __name__ == "__main__":
    maybe_help(__doc__)
    main()
