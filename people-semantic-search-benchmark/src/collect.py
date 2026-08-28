"""Collect one or more arms across the query set.

Usage:
    python3 -m src.collect <arm> [<arm> ...] [--limit N] [--force]

Arms:
    crustdata    POST /person/search
    exa          POST /search, category=people

Parallel is asynchronous; use src.collect_parallel for it. Responses are
cached per (arm, query), so re-running costs nothing. --limit N runs the first
N queries."""

import json
import sys
import time

from pathlib import Path

from src.common import PACK, maybe_help, ROOT
from src.searchers import crustdata, exa

import os
QUERIES = ROOT / "data" / "queries" / "queries.json"


def load_queries():
    return json.loads(QUERIES.read_text())




def collect(arm, spec, force=False, limit=None):
    qs = spec["queries"][:limit] if limit else spec["queries"]
    k = spec.get("k", 10)
    n_cached = n_new = n_err = 0
    t0 = time.time()
    for q in qs:
        qid, text = q["id"], q["text"]
        if arm == "crustdata":
            env = crustdata.fetch_semantic(qid, text, k=k, force=force, arm=arm)
            parsed = crustdata.parse(env)
        elif arm == "exa":
            env = exa.fetch(qid, text, k=k, force=force, arm=arm)
            parsed = exa.parse(env)
        else:
            raise SystemExit(f"unknown arm: {arm}")

        if env.get("_from_cache"):
            n_cached += 1
        else:
            n_new += 1
        ok = 200 <= (env.get("http_status") or 0) < 300
        if not ok:
            n_err += 1
        n = len(parsed["results"])
        flag = "" if ok else f"  !! HTTP {env.get('http_status')}"
        cache = "cached" if env.get("_from_cache") else f"{env.get('latency_ms')}ms"
        print(f"  [{qid:>3}] {n:>2} results  ({cache}){flag}  {text[:58]}")
    print(f"\n{arm}: {len(qs)} queries - {n_new} fetched, {n_cached} cached, "
          f"{n_err} errors, {int(time.time()-t0)}s wall")


VALID_ARMS = ("crustdata", "exa")


def main():
    maybe_help(__doc__)
    args, limit, force = [], None, False
    it = iter(range(1, len(sys.argv)))
    skip = False
    for i in range(1, len(sys.argv)):
        if skip:
            skip = False
            continue
        a = sys.argv[i]
        if a == "--force":
            force = True
        elif a == "--limit":
            if i + 1 >= len(sys.argv):
                raise SystemExit("--limit needs a value")
            limit = int(sys.argv[i + 1]); skip = True
        elif a.startswith("--limit="):
            limit = int(a.split("=", 1)[1])
        elif a.startswith("-"):
            # every fetch below is billable: refuse anything unrecognised
            raise SystemExit(f"unknown flag {a!r} - known: --limit N, --force")
        elif a in VALID_ARMS:
            args.append(a)
        else:
            raise SystemExit(f"unknown arm {a!r} - valid: {', '.join(VALID_ARMS)}")
    if limit is not None and limit < 1:
        raise SystemExit("--limit must be at least 1")
    if not args:
        print(__doc__)
        sys.exit(0)
    spec = load_queries()
    for arm in args:
        print(f"=== {arm} ===")
        collect(arm, spec, force=force, limit=limit)


if __name__ == "__main__":
    main()
