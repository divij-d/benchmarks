"""Run the benchmark over the panel (data/panel/panel.json).

Usage:
    python -m src.collect_panel --smoke        # first 8 SMB / 5 mid-size / 7 established
    python -m src.collect_panel --limit 100    # first 100 runnable rows
    python -m src.collect_panel                # full panel, then score

Cache-first end to end: every provider response is written to data/raw/
before parsing, so re-running is free and resumes where it stopped. One
company's error never kills the batch; failures are logged to
data/results/panel_run_failures.json and retried on the next run. Companies
flagged `defunct` in the panel are skipped - a live-index provider must never
lose score for correctly not carrying a dead company."""

import json
import sys
import time

from src.common import RESULTS, load_panel, maybe_help
from src.collect import run_company
from src import score

FAILLOG = RESULTS / "panel_run_failures.json"
PACE_SLEEP = 1.0   # seconds between companies, on top of sequential provider calls
SMOKE = {"smb_software": 8, "midsize_tech": 5, "established": 7}


def pick(rows, smoke=False, limit=None):
    rows = [r for r in rows if r.get("domain") and not r.get("defunct")]
    if smoke:
        out, taken = [], {k: 0 for k in SMOKE}
        for r in rows:
            s = r["stratum"]
            if taken.get(s, 99) < SMOKE.get(s, 0):
                out.append(r)
                taken[s] += 1
        return out
    return rows[:limit] if limit else rows


def main():
    smoke = "--smoke" in sys.argv
    limit = int(sys.argv[sys.argv.index("--limit") + 1]) if "--limit" in sys.argv else None
    todo = pick(load_panel(), smoke=smoke, limit=limit)
    print(f"running {len(todo)} companies ({'smoke' if smoke else 'panel'}), "
          f"pacing {PACE_SLEEP}s\n")

    failures = {}
    t0 = time.time()
    for i, row in enumerate(todo, 1):
        dom = row["domain"]
        print(f"[{i}/{len(todo)}] {dom} ({row['stratum']})")
        try:
            run_company(dom)
        except Exception as e:
            print(f"  !! FAILED: {e}")
            failures[dom] = str(e)
        time.sleep(PACE_SLEEP)

    FAILLOG.parent.mkdir(parents=True, exist_ok=True)
    FAILLOG.write_text(json.dumps(failures, indent=1))
    mins = (time.time() - t0) / 60
    print(f"\ndone: {len(todo) - len(failures)} ok, {len(failures)} failed "
          f"(logged to {FAILLOG.name}) in {mins:.1f} min")
    score.main()
    return 0


if __name__ == "__main__":
    maybe_help(__doc__)
    sys.exit(main())
