"""Aggregate the per-company comparisons into the panel leaderboard.

    python -m src.score

Reads data/results/companies/*.json and data/panel/panel.json, writes
data/results/index.json (one line per company) and data/results/aggregates.json
(per-provider metrics, overall and per stratum).

Consensus, not ground truth. A tech counts as consensus when independent
providers agree on it - at least 2 of 5 ("pair"), or a strict majority of 3
("majority"). Both views are computed for every metric:

  recall     share of the company's consensus techs the provider reports
  precision  share of the provider's own claims that reach consensus
  F1         harmonic mean of the two, per company, then averaged
  fresh      the same three restricted to techs seen in the last 12 months
             (providers that publish no dates score null here)

Guards: a company contributes to a provider's recall / F1 only when it has at
least MIN_CONSENSUS consensus techs; to precision only when the provider made
at least MIN_CLAIMS claims there. Companies flagged `defunct` in the panel are
excluded for every provider; a provider that was not run on a company (credit
exhaustion) is excluded from that company's denominators only.

Per-category F1 buckets every claim before scoring: a row keeps the bucket its
own providers voted for; a row with no vote inherits the panel-wide modal
bucket for that tech, then the LLM category table, so providers that publish
no category metadata still pay for unconfirmed claims. A category is graded
for a company only when it holds at least MIN_BUCKET_N consensus techs."""

import json
import sys
from collections import Counter, defaultdict

from src.common import COMPANIES, RESULTS, NORM_DIR, PROVIDERS, load_panel, maybe_help
from src.normalize import BUCKETS, UNDATED_PROVIDERS

MIN_CONSENSUS = 5   # consensus techs a company needs to count toward recall / F1
MIN_CLAIMS = 5      # claims a provider needs at a company to count toward precision
MIN_BUCKET_N = 3    # consensus techs in a bucket for the company to vote there

STRATA_DEFS = {
    "smb_software": "SMB software - 10-50 employees (YC directory)",
    "midsize_tech": "Mid-size tech - 51-500 employees (YC directory)",
    "established": "Established - 500+ employees, all industries (Wikidata)",
}

# aggregate slot -> (sum key, count key); rendered as mean of per-company ratios
MEANS = {
    "mean_ucs_majority": "ucs_maj", "mean_ucs_pair": "ucs_pair",
    "mean_ucs_fresh": "ucs_fresh", "mean_ucs_fresh_pair": "ucs_fresh_pair",
    "mean_precision_majority": "prec", "mean_precision_pair": "prec_pair",
    "mean_precision_fresh": "prec_fresh", "mean_precision_fresh_pair": "prec_fresh_pair",
    "mean_f1_majority": "f1_maj", "mean_f1_pair": "f1_pair",
    "mean_f1_fresh_majority": "f1_fresh_maj", "mean_f1_fresh_pair": "f1_fresh_pair",
}


def _bucket():
    b = {"run": 0, "matched": 0, "techs": [], "latency": []}
    for k in MEANS.values():
        b[k + "_sum"], b[k + "_n"] = 0.0, 0
    return b


def _add(b, slot, v):
    if v is not None:
        b[slot + "_sum"] += v
        b[slot + "_n"] += 1


def _f1(r, p):
    if r is None or p is None or (r + p) <= 0:
        return None
    return 2 * r * p / (r + p)


def _ratio(num, den, floor):
    return (num / den) if den >= floor else None


def company_files():
    for f in sorted(COMPANIES.glob("*.json")):
        try:
            c = json.loads(f.read_text())
        except json.JSONDecodeError:
            continue
        if "rows" in c and "summary" in c:
            yield c


def main():
    panel = {r["domain"]: r for r in load_panel()}
    agg = {p: {"all": _bucket()} for p in PROVIDERS}
    strata_counts = Counter()
    ov_sizes = {p: [0, 0] for p in PROVIDERS}   # mean techs claimed per company
    ov_pairs = {}                                # "a|b" -> mean techs claimed in common
    agreed = [0, 0, 0]                           # sum pair-agreed, sum majority-agreed, n
    index = []
    llm_normalized = 0
    slim = []                                    # per-company rows kept for the bucket pass
    votes = defaultdict(Counter)                 # tech key -> bucket votes across the panel

    for c in company_files():
        row = panel.get(c["domain"], {})
        if row.get("defunct"):
            continue
        index.append({
            "domain": c["domain"],
            "name": row.get("name") or c["domain"],
            "stratum": row.get("stratum") or "pilot",
            "matched": c["matched"],
            "tech_counts": c["summary"]["tech_counts"],
            "union_size": c["summary"]["union_size"],
            "corroborated": c["summary"]["corroborated"],
        })
        stratum = row.get("stratum") or "pilot"
        strata_counts[stratum] += 1
        llm_normalized += bool((c.get("normalization") or {}).get("llm"))
        s = c["summary"]
        providers = c["providers"]
        rows = c.get("rows", [])
        maj_thr = s.get("majority_threshold") or 3
        fresh_thr = s.get("majority_threshold_fresh") or 3
        maj = s.get("recall_vs_majority_union") or {}
        pair = s.get("recall_vs_corroborated_union") or {}
        fresh = s.get("recall_vs_majority_union_fresh") or {}
        meaningful = s.get("corroborated_majority", 0) >= MIN_CONSENSUS
        meaningful_pair = s.get("corroborated", 0) >= MIN_CONSENSUS
        meaningful_fresh = s.get("corroborated_majority_fresh", 0) >= MIN_CONSENSUS
        fresh_ref2 = [r for r in rows if len(r.get("fresh_found_by") or []) >= 2]

        # per-provider precision (all-time and fresh, both bars) at this company
        prec, prec_pair, prec_fresh, prec_fresh_pair, fresh_pair_recall = {}, {}, {}, {}, {}
        for p in providers:
            den = num = num2 = fden = fnum = fnum2 = 0
            for r in rows:
                fb = r.get("effective_found_by") or r.get("found_by") or []
                if p in fb:
                    den += 1
                    num += r.get("corroboration", 0) >= maj_thr
                    num2 += r.get("corroboration", 0) >= 2
                ffb = r.get("fresh_found_by") or []
                if p in ffb:
                    fden += 1
                    fnum += len(ffb) >= fresh_thr
                    fnum2 += len(ffb) >= 2
            prec[p] = _ratio(num, den, MIN_CLAIMS)
            prec_pair[p] = _ratio(num2, den, MIN_CLAIMS)
            prec_fresh[p] = _ratio(fnum, fden, MIN_CLAIMS)
            prec_fresh_pair[p] = _ratio(fnum2, fden, MIN_CLAIMS)
            fresh_pair_recall[p] = (
                sum(1 for r in fresh_ref2 if p in r["fresh_found_by"]) / len(fresh_ref2)
                if len(fresh_ref2) >= MIN_CONSENSUS and p not in UNDATED_PROVIDERS else None)

        for p in providers:
            if p not in agg:
                continue
            lat = (c.get("meta", {}).get(p) or {}).get("latency_ms")
            for b in (agg[p]["all"], agg[p].setdefault(stratum, _bucket())):
                b["run"] += 1
                if lat:
                    b["latency"].append(lat)
                if not c["matched"].get(p):
                    continue
                b["matched"] += 1
                b["techs"].append(s["tech_counts"].get(p, 0))
                if meaningful:
                    _add(b, "ucs_maj", maj.get(p))
                    _add(b, "ucs_pair", pair.get(p))
                    _add(b, "f1_maj", _f1(maj.get(p), prec.get(p)))
                if meaningful_fresh:
                    _add(b, "ucs_fresh", fresh.get(p))
                    _add(b, "f1_fresh_maj", _f1(fresh.get(p), prec_fresh.get(p)))
                if meaningful_pair:
                    _add(b, "f1_pair", _f1(pair.get(p), prec_pair.get(p)))
                _add(b, "prec", prec.get(p))
                _add(b, "prec_pair", prec_pair.get(p))
                _add(b, "prec_fresh", prec_fresh.get(p))
                _add(b, "prec_fresh_pair", prec_fresh_pair.get(p))
                _add(b, "ucs_fresh_pair", fresh_pair_recall.get(p))
                if fresh_pair_recall.get(p) is not None:
                    _add(b, "f1_fresh_pair", _f1(fresh_pair_recall[p], prec_fresh_pair.get(p)))

        # overlap: how much of each provider's list the others share
        sets = {p: set() for p in providers}
        for ri, r in enumerate(rows):
            for p in (r.get("effective_found_by") or r.get("found_by") or []):
                if p in sets:
                    sets[p].add(ri)
        for p in providers:
            if p in ov_sizes and c["matched"].get(p):
                ov_sizes[p][0] += len(sets[p]); ov_sizes[p][1] += 1
        for ai, a in enumerate(PROVIDERS):
            for bb in PROVIDERS[ai + 1:]:
                if a in sets and bb in sets and c["matched"].get(a) and c["matched"].get(bb):
                    k = a + "|" + bb
                    ov_pairs.setdefault(k, [0, 0])
                    ov_pairs[k][0] += len(sets[a] & sets[bb]); ov_pairs[k][1] += 1
        agreed[0] += s.get("corroborated", 0)
        agreed[1] += s.get("corroborated_majority", 0)
        agreed[2] += 1

        for r in rows:
            if r.get("bucket"):
                votes[r["key"]][r["bucket"]] += 1
        slim.append((providers, c["matched"], maj_thr,
                     [(r["key"], r.get("bucket"), r["corroboration"],
                       set(r.get("effective_found_by") or r.get("found_by") or []))
                      for r in rows]))

    # ---- per-category F1 (fair: every claim bucketed before scoring) ----
    def _load(name, section=None):
        p = NORM_DIR / name
        d = json.loads(p.read_text()) if p.exists() else {}
        d = d.get(section) or {} if section else d
        return {k: v for k, v in d.items() if v in BUCKETS}
    llm_bucket = _load("llm_tech_categories.json")                          # lowest precedence
    overrides = _load("category_crosswalk.json", "tech_overrides")         # audit-confirmed; outrank all
    global_bucket = {k: min(sorted(v.items(), key=lambda kv: (-kv[1], kv[0])))[0]
                     for k, v in votes.items()}
    cat = {bk: defaultdict(lambda: {"r": [0.0, 0], "f": [0.0, 0], "f2": [0.0, 0]})
           for bk in BUCKETS}
    for providers, matched, maj_thr, rows in slim:
        bucketed = []
        for k, own, corr, fb in rows:
            b = overrides.get(k) or own or global_bucket.get(k) or llm_bucket.get(k)
            bucketed.append((b, corr, fb))
        for bk in BUCKETS:
            ref_maj = [x for x in bucketed if x[0] == bk and x[1] >= maj_thr]
            ref_pair = [x for x in bucketed if x[0] == bk and x[1] >= 2]
            if len(ref_maj) < MIN_BUCKET_N:
                continue
            for p in providers:
                if not matched.get(p):
                    continue
                claims = [x for x in bucketed if x[0] == bk and p in x[2]]
                r_maj = sum(1 for x in ref_maj if p in x[2]) / len(ref_maj)
                r_pair = (sum(1 for x in ref_pair if p in x[2]) / len(ref_pair)
                          if ref_pair else None)
                p_maj = _ratio(sum(1 for x in claims if x[1] >= maj_thr), len(claims), 3)
                p_pair = _ratio(sum(1 for x in claims if x[1] >= 2), len(claims), 3)
                for slot, v in (("r", r_maj), ("f", _f1(r_maj, p_maj)), ("f2", _f1(r_pair, p_pair))):
                    if v is not None:
                        cat[bk][p][slot][0] += v
                        cat[bk][p][slot][1] += 1

    def render_cat(slot):
        return {bk: {p: (a[slot][0] / a[slot][1] if a[slot][1] else None)
                     for p, a in provmap.items()}
                for bk, provmap in cat.items()}

    def render(b):
        techs, lat = sorted(b["techs"]), sorted(b["latency"])
        out = {"run": b["run"],
               "match_rate": b["matched"] / b["run"] if b["run"] else None,
               "median_techs": techs[len(techs) // 2] if techs else None,
               "median_latency_ms": lat[len(lat) // 2] if lat else None}
        for name, slot in MEANS.items():
            out[name] = b[slot + "_sum"] / b[slot + "_n"] if b[slot + "_n"] else None
        return out

    aggregates = {
        "n_companies": sum(strata_counts.values()),
        "llm_normalized_companies": llm_normalized,
        "strata_counts": dict(strata_counts),
        "strata_defs": STRATA_DEFS,
        "providers": {p: {s: render(b) for s, b in buckets.items()} for p, buckets in agg.items()},
        "overlap": {"sizes": {p: (s / n if n else None) for p, (s, n) in ov_sizes.items()},
                    "pairs": {k: (s / n if n else None) for k, (s, n) in ov_pairs.items()},
                    "mean_agreed_pair": agreed[0] / agreed[2] if agreed[2] else None,
                    "mean_agreed_majority": agreed[1] / agreed[2] if agreed[2] else None},
        "bucket_labels": BUCKETS,
        "ucs_by_bucket": render_cat("r"),
        "f1_by_bucket": render_cat("f"),
        "f1_pair_by_bucket": render_cat("f2"),
        "bucket_company_counts": {bk: max((a["r"][1] for a in provmap.values()), default=0)
                                  for bk, provmap in cat.items()},
        "bucket_f1_method": ("fair-v2: unbucketed claims inherit the panel-wide modal "
                             "category vote for their tech, so providers without "
                             "category metadata still pay for unconfirmed claims"),
    }
    RESULTS.mkdir(parents=True, exist_ok=True)
    (RESULTS / "index.json").write_text(json.dumps(index, indent=1))
    (RESULTS / "aggregates.json").write_text(json.dumps(aggregates, indent=1))
    n = aggregates["n_companies"]
    print(f"scored {n} companies -> {RESULTS / 'aggregates.json'}")
    print(f"LLM name normalization applied to {llm_normalized} of {n} companies"
          + ("" if llm_normalized else " - name merging is limited to the built-in tables, "
             "so scores may read lower than reality for companies outside the benchmark "
             "panel (see `python -m src.normalize_llm --help`)."))
    return 0


if __name__ == "__main__":
    maybe_help(__doc__)
    sys.exit(main())
