"""Print the leaderboard as tables, and write it as Markdown.

    python -m src.report              consensus = agreed by >=2 of 5 providers
    python -m src.report --majority   consensus = strict majority, >=3 of 5

Reads data/results/aggregates.json and writes data/results/summary.md."""

import json
import sys

from src.common import RESULTS, PROVIDERS, maybe_help

LABEL = {"crustdata": "Crustdata", "theirstack": "TheirStack", "sumble": "Sumble",
         "predictleads": "PredictLeads", "builtwith": "BuiltWith"}

# (header, aggregates field, format) per track and consensus bar
TRACKS = {
    "pair": {
        "all": [("F1", "mean_f1_pair", "pct"), ("Recall", "mean_ucs_pair", "pct"),
                ("Precision", "mean_precision_pair", "pct"), ("Matched", "match_rate", "pct"),
                ("Techs / co", "median_techs", "int"), ("Latency p50", "median_latency_ms", "secs")],
        "fresh": [("F1", "mean_f1_fresh_pair", "pct"), ("Recall", "mean_ucs_fresh_pair", "pct"),
                  ("Precision", "mean_precision_fresh_pair", "pct")],
    },
    "maj": {
        "all": [("F1", "mean_f1_majority", "pct"), ("Recall", "mean_ucs_majority", "pct"),
                ("Precision", "mean_precision_majority", "pct"), ("Matched", "match_rate", "pct"),
                ("Techs / co", "median_techs", "int"), ("Latency p50", "median_latency_ms", "secs")],
        "fresh": [("F1", "mean_f1_fresh_majority", "pct"), ("Recall", "mean_ucs_fresh", "pct"),
                  ("Precision", "mean_precision_fresh", "pct")],
    },
}


def fmt(kind, v):
    if v is None:
        return "n/a"
    if kind == "pct":
        return f"{v * 100:.1f}%"
    if kind == "int":
        return f"{v:d}"
    return f"{v / 1000:.1f}s"


def table(agg, cols):
    rows = sorted(PROVIDERS, key=lambda p: -(agg["providers"][p]["all"].get(cols[0][1]) or -1))
    return [(LABEL[p], [fmt(k, agg["providers"][p]["all"].get(f)) for _, f, k in cols])
            for p in rows]


def main():
    bar = "maj" if "--majority" in sys.argv else "pair"
    p = RESULTS / "aggregates.json"
    if not p.exists():
        print(f"{p} not found - run `python -m src.score` first.", file=sys.stderr)
        return 1
    agg = json.loads(p.read_text())
    n = agg["n_companies"]
    bar_txt = ("a tech counts when >=2 of 5 providers report it" if bar == "pair"
               else "a tech counts when a strict majority (>=3 of 5) reports it")
    llm_n = agg.get("llm_normalized_companies", 0)
    norm_txt = (f"LLM name normalization applied to {llm_n} of {n} companies" if llm_n else
                "No LLM name normalization: merging limited to the built-in tables; scores may "
                "read lower than reality for companies outside the benchmark panel")
    md = ["# Results", "", f"{n} companies · consensus bar: {bar_txt}", "", norm_txt, ""]
    print(f"\n{n} companies · {bar_txt}\n{norm_txt}")
    for track, title in (("all", "All-time"), ("fresh", "Fresh (seen in the last 12 months)")):
        cols = TRACKS[bar][track]
        rows = table(agg, cols)
        head = f"{'Provider':<14}" + "".join(f"{c[0]:>13}" for c in cols)
        print(f"\n{title}\n{head}\n{'-' * len(head)}")
        for name, vals in rows:
            print(f"{name:<14}" + "".join(f"{v:>13}" for v in vals))
        md += [f"**{title}**", "",
               "| Provider | " + " | ".join(c[0] for c in cols) + " |",
               "|---" + "|---:" * len(cols) + "|"]
        md += [f"| {name} | " + " | ".join(vals) + " |" for name, vals in rows]
        md.append("")
    # per-category F1: rows are the six buckets, columns the providers
    cat = agg.get("f1_pair_by_bucket" if bar == "pair" else "f1_by_bucket") or {}
    labels, counts = agg.get("bucket_labels") or {}, agg.get("bucket_company_counts") or {}
    if cat:
        head = f"{'Category':<30}{'Companies':>10}" + "".join(f"{LABEL[p]:>14}" for p in PROVIDERS)
        print(f"\nBy category (F1)\n{head}\n{'-' * len(head)}")
        md += ["**By category (F1)**", "",
               "| Category | Companies | " + " | ".join(LABEL[p] for p in PROVIDERS) + " |",
               "|---|---:" + "|---:" * len(PROVIDERS) + "|"]
        for b, provs in cat.items():
            vals = [provs.get(p) for p in PROVIDERS]
            best = max((v for v in vals if v is not None), default=None)
            print(f"{labels.get(b, b):<30}{counts.get(b, 0):>10}" + "".join(f"{fmt('pct', v):>14}" for v in vals))
            md.append(f"| {labels.get(b, b)} | {counts.get(b, 0)} | " +
                      " | ".join(f"**{fmt('pct', v)}**" if v is not None and v == best else fmt("pct", v)
                                 for v in vals) + " |")
        md.append("")
        print("A category is graded for a company only when it holds 3+ consensus techs; "
              "Companies = how many qualified.")
    print("\nRecall: share of consensus techs found. Precision: share of the provider's claims "
          "other providers confirm.\nn/a: provider publishes no dates, so it cannot be scored "
          "on freshness.")
    out = RESULTS / "summary.md"
    out.write_text("\n".join(md))
    print(f"\nWritten to {out}")
    return 0


if __name__ == "__main__":
    maybe_help(__doc__)
    sys.exit(main())
