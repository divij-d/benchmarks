"""Re-fetch Parallel runs that timed out, using their stored run ids.

Parallel stops waiting after about 595 seconds and returns an error while the
run continues, so a share of queries come back ERR. Re-fetching by run id
costs nothing and returns in seconds. Ids live in
data/results/parallel_progress.json, so this works even if the collector
process has exited."""
import json, os, sys, time
from concurrent.futures import ThreadPoolExecutor, as_completed

from pathlib import Path

from src.common import PACK, cache_path, ROOT, maybe_help
from src.searchers import parallel

ARM = "parallel"               # must match src.score.ARMS
PROGRESS = PACK / "results" / "parallel_progress.json"


def main():
    rounds = 4
    if "--rounds" in sys.argv:
        rounds = int(sys.argv[sys.argv.index("--rounds") + 1])
    spec = json.loads((ROOT / "data" / "queries" / "queries.json").read_text())
    qtext = {q["id"]: q["text"] for q in spec["queries"]}

    for rnd in range(1, rounds + 1):
        state = json.loads(PROGRESS.read_text())
        pending = {qid: v["run_id"] for qid, v in state["queries"].items()
                   if v.get("status") != "done" and v.get("run_id")
                   and not cache_path(ARM, qid).exists()}
        if not pending:
            print("nothing pending")
            return
        print(f"\n--- round {rnd}: re-fetching {len(pending)} run(s) ---", flush=True)

        def harvest(qid, rid):
            st, resp, ms = parallel.fetch_result(rid)
            env = {"arm": ARM, "query_id": qid,
                   "request": {"url": parallel.CREATE, "method": "POST",
                               "body": {"input": parallel.PROMPT.format(q=qtext[qid]),
                                        "processor": parallel.PROCESSOR},
                               "run_id": rid, "_resumed": True},
                   "http_status": st, "latency_ms": ms,
                   "fetched_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                   "response": resp, "_from_cache": False}
            if 200 <= st < 300:
                p = cache_path(ARM, qid); p.parent.mkdir(parents=True, exist_ok=True)
                p.write_text(json.dumps(env, indent=1))
            return qid, rid, env

        still = 0
        with ThreadPoolExecutor(max_workers=8) as ex:
            futs = [ex.submit(harvest, q, r) for q, r in pending.items()]
            for fut in as_completed(futs):
                qid, rid, env = fut.result()
                ok = 200 <= (env["http_status"] or 0) < 300
                n = len(parallel.parse(env)["results"]) if ok else 0
                state = json.loads(PROGRESS.read_text())
                if ok:
                    state["queries"][qid] = {"run_id": rid, "status": "done",
                                             "n_results": n, "latency_ms": env["latency_ms"],
                                             "resumed": True}
                    state["completed"] = sum(1 for v in state["queries"].values() if v.get("status") == "done")
                    state["failed"] = sum(1 for v in state["queries"].values() if v.get("status") not in ("done", "running"))
                else:
                    still += 1
                    state["queries"][qid]["http_status"] = env["http_status"]
                PROGRESS.write_text(json.dumps(state, indent=1))
                print(f"  [{qid:>3}] {'ok ' if ok else 'still active'} {n:>2} people  "
                      f"{env['latency_ms']/1000:.0f}s", flush=True)
        if not still:
            print("all resumed")
            return
    print("rounds exhausted; some runs still active")


if __name__ == "__main__":
    maybe_help(__doc__)
    main()
