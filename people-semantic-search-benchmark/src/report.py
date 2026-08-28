"""Print the scoreboard as a table, and write it as Markdown.

    python -m src.report              latest run
    python -m src.report --history    one line per archived run

Reads data/results/scoreboard.json and writes data/results/summary.md."""
import json
import sys

from src.common import PACK, maybe_help

LABEL = {"crustdata": "crustdata",
         "exa": "exa",
         "parallel": "parallel"}
COLS = [("strict", "strict_pass_rate", "pct"),
        ("R@1", "recall_at_1", "pct"),
        ("R@10", "recall_at_k", "pct"),
        ("usable/q", "passing_results_per_query", "dec"),
        ("role", "role_adherence", "pct"),
        ("location", "location_adherence", "pct"),
        ("p50", "latency_p50_ms", "secs")]


def fmt(kind, v):
    if v is None:
        return "-"
    if kind == "pct":
        return f"{v * 100:.1f}%"
    if kind == "dec":
        return f"{v:.2f}"
    return (f"{v / 1000:.1f}s" if v < 60_000
            else f"{int(v // 60_000)}m {v % 60_000 / 1000:.0f}s")


def history():
    """One line per archived run, oldest first, so drift is visible."""
    runs = sorted((PACK / "runs").glob("*.json")) if (PACK / "runs").exists() else []
    if not runs:
        print("No archived runs yet - run `python -m src.score`.", file=sys.stderr)
        return 1
    names, rows = [], []
    for f in runs:
        sb = json.loads(f.read_text())
        arms = [a for a in LABEL if a in sb.get("arms", {})]
        if not arms:
            continue          # a run that scored nothing has nothing to show
        names = names or arms
        rows.append((f.stem, sb["arms"][arms[0]].get("scored_queries"),
                     {a: sb["arms"][a].get("strict_pass_rate") for a in arms}))
    if not rows:
        print("No scored runs archived yet.", file=sys.stderr)
        return 1
    print(f"\n{len(rows)} run(s)\n")
    head = f"{'run':<24}{'queries':>8}" + "".join(f"{LABEL[a][:15]:>17}" for a in names)
    print(head); print("-" * len(head))
    for rid, q, vals in rows:
        print(f"{rid:<24}{q:>8}" + "".join(f"{fmt('pct', vals.get(a)):>17}" for a in names))
    return 0


def main():
    if "--history" in sys.argv:
        return history()
    p = PACK / "results" / "scoreboard.json"
    if not p.exists():
        print(f"{p} not found - run `python -m src.score` first.", file=sys.stderr)
        return 1
    sb = json.loads(p.read_text())
    arms = [a for a in LABEL if a in sb["arms"]]
    if not arms:
        print("No arms scored yet.", file=sys.stderr)
        return 1
    arms.sort(key=lambda a: -(sb["arms"][a].get("strict_pass_rate") or 0))
    denoms = {sb["arms"][a].get("strict_denominator") for a in arms}
    n = sb["arms"][arms[0]].get("strict_denominator")
    if len(denoms) > 1:
        n = f"{min(d for d in denoms if d is not None)}-{max(d for d in denoms if d is not None)}"
    q = sb["arms"][arms[0]].get("scored_queries")

    head = f"{'provider':<26}" + "".join(f"{c[0]:>11}" for c in COLS)
    rows = [f"{LABEL[a]:<26}" + "".join(f"{fmt(k, sb['arms'][a].get(f)):>11}"
                                        for _, f, k in [(c[0], c[1], c[2]) for c in COLS])
            for a in arms]
    print(f"\n{q} queries · {n} graded results per provider\n")
    print(head); print("-" * len(head))
    for r in rows: print(r)
    print("\nStrict pass = the result satisfies EVERY scored clause of the query.")
    print("Run-to-run noise is around ±0.4 points; gaps under a point are not real.")

    md = [f"# Results", "",
          f"{q} queries · {n} graded results per provider", "",
          "| Provider | " + " | ".join(c[0] for c in COLS) + " |",
          "|---" * (len(COLS) + 1) + "|"]
    for a in arms:
        md.append(f"| {LABEL[a]} | " +
                  " | ".join(fmt(k, sb["arms"][a].get(f)) for _, f, k in COLS) + " |")
    out = PACK / "results" / "summary.md"
    out.write_text("\n".join(md) + "\n")
    print(f"\nWritten to {out}")
    return 0


if __name__ == "__main__":
    maybe_help(__doc__)
    sys.exit(main())
