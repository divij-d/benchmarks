"""Refuse to certify a run whose verdicts rest on unjudged pairs.

Walks every scored clause against every claim the providers returned. Any
(constraint, claim) pair absent from the rubric is reported and the process
exits non-zero, because an unjudged pair scores false and a false that nobody
decided is not a measurement."""
import json
import sys

from src.common import PACK, ROOT, clauses, maybe_help, norm_claim
from src.searchers import crustdata, exa, parallel
from src import roles, geo, employer
from src import facts as pfacts

# Must mirror score.py's ARMS exactly. A new arm (or a re-run under changed
# request settings) surfaces strings no judged table has seen; if this list
# lags, those strings auto-fail and the guard reports clean while it happens.
import os
ARMS = {"crustdata": crustdata.parse, "exa": exa.parse,
        "parallel": parallel.parse}


def audit():
    key = {q["id"]: q for q in json.loads(
        (ROOT / "data" / "queries" / "queries.json").read_text())["queries"]}
    _base = ROOT / "data" / "rubric"
    rp = _base / "reviewed_pairs.json"
    rev = json.loads(rp.read_text()) if rp.exists() else {"role": [], "location": []}
    seen = {k: {(a, b) for a, b in v} for k, v in rev.items()}
    out = {}
    for arm, fn in ARMS.items():
        unrev, total = set(), 0
        for qid, kq in key.items():
            p = PACK / "raw" / arm / f"{qid}.json"
            if not p.exists():
                continue
            env = json.loads(p.read_text())
            rs = fn(env)["results"]
            # Must enumerate the same candidate set the scorer judges, or the
            # guard reports clean on strings the scorer is failing.
            cl = pfacts.claims(arm, env)
            if len(cl) != len(rs):
                cl = [{"roles": [], "locations": []}] * len(rs)
            for c in [c for c in clauses(kq) if c["type"] == "c"]:
                for i, r in enumerate(rs):
                    ev = cl[i] if i < len(cl) else {"roles": [], "locations": []}
                    if c["kind"] == "location":
                        cands = ev["locations"] or [("location", r.get("location"))]
                        tbl, pool = geo._JUDGED, "location"
                    elif c["kind"] == "employer":
                        continue
                    else:
                        cands = ev["roles"] or [("title", r.get("title"))]
                        tbl, pool = roles._JUDGED, "role"
                    # a claim that is empty after normalization ("--", a bare
                    # URL) can never be judged into the table; skip it here the
                    # same way the write side drops it
                    vals = [(_v or "").strip() for _p, _v in cands]
                    vals = [v for v in vals if norm_claim(v)]
                    if not vals or c["value"] not in tbl:
                        continue
                    total += 1
                    if any(norm_claim(v) in tbl[c["value"]] for v in vals):
                        continue                      # accepted by some claim
                    for v in vals:                    # failed on every claim
                        if (c["value"], norm_claim(v)) not in seen[pool]:
                            unrev.add((pool, c["value"], v))
        out[arm] = {"verdicts": total, "unreviewed_pairs": sorted(unrev)}
    return out


if __name__ == "__main__":
    maybe_help(__doc__)
    o = audit()
    if not any(v["verdicts"] for v in o.values()):
        print("No scored verdicts found - collect captures before auditing.")
        raise SystemExit(2)
    bad = sum(len(v["unreviewed_pairs"]) for v in o.values())
    print(f"{'arm':<24}{'verdicts':>10}{'unreviewed pairs':>19}")
    for arm, v in o.items():
        print(f"{arm:<24}{v['verdicts']:>10}{len(v['unreviewed_pairs']):>19}")
    if bad:
        print(f"\n!! {bad} verdicts rest on pairs that were never reviewed. "
              f"They currently score FALSE. Judge them before trusting any number.\n")
        for arm, v in o.items():
            for pool, cv, val in v["unreviewed_pairs"][:8]:
                print(f"   [{arm.split('_')[0][:4]}] {pool:<9} {cv[:34]:<36} {val[:44]}")
    else:
        print("\nOK - every scored verdict rests on a reviewed pair.")
    sys.exit(1 if bad else 0)
