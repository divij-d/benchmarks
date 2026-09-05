"""Collect the benchmark panel (data/panel/panel.json).

Usage:
    python -m src.collect_panel --limit 20    # first 20 panel companies
    python -m src.collect_panel               # the whole panel

Runs all five providers on each company, exactly like `src.collect`, and
writes one comparison file per company to data/results/companies/. Cache-first
end to end: every provider response is written to data/raw/ before parsing, so
re-running is free and resumes where it stopped. One company's error never
kills the batch; failures are logged to data/results/panel_run_failures.json
and retried on the next run. A company where fewer than two providers ran
(missing keys or failed calls) is also logged as a failure.

Then: python -m src.normalize_llm --provider <llm>  (optional)
      python -m src.score
      python -m src.report"""

import json
import sys
import time

from src.common import RESULTS, load_panel, maybe_help
from src.collect import run_company, NO_LLM_WARNING

FAILLOG = RESULTS / "panel_run_failures.json"
PACE_SLEEP = 1.0   # seconds between companies, on top of sequential provider calls


def main():
    rows = [r for r in load_panel() if r.get("domain")]
    limit = None
    if "--limit" in sys.argv:
        try:
            limit = int(sys.argv[sys.argv.index("--limit") + 1])
        except (IndexError, ValueError):
            print("--limit needs a number", file=sys.stderr)
            return 1
        if not 0 < limit <= len(rows):
            print(f"--limit must be between 1 and {len(rows)} (the runnable panel)", file=sys.stderr)
            return 1
    todo = rows[:limit] if limit else rows
    print(f"collecting {len(todo)} of {len(rows)} panel companies, pacing {PACE_SLEEP}s\n")

    failures = {}
    t0 = time.time()
    for i, row in enumerate(todo, 1):
        dom = row["domain"]
        print(f"[{i}/{len(todo)}] {dom} ({row['stratum']})")
        try:
            if run_company(dom) is None:
                failures[dom] = "fewer than two providers ran"
        except Exception as e:
            print(f"  !! FAILED: {e}")
            failures[dom] = str(e)
        time.sleep(PACE_SLEEP)

    FAILLOG.parent.mkdir(parents=True, exist_ok=True)
    FAILLOG.write_text(json.dumps(failures, indent=1))
    mins = (time.time() - t0) / 60
    print(f"\ndone: {len(todo) - len(failures)} ok, {len(failures)} failed "
          f"(logged to {FAILLOG.name}) in {mins:.1f} min")
    print(NO_LLM_WARNING)
    print("\nRun `python -m src.score` to aggregate everything collected so far.")
    return 0


if __name__ == "__main__":
    maybe_help(__doc__)
    sys.exit(main())
