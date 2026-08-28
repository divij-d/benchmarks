"""Score every collected arm against the rubric.

Strict pass means a returned person satisfies every scored clause of the query;
there is no partial credit. A clause passes if any claim the provider made
satisfies it, and an unjudged pair scores false.

Writes data/results/scoreboard.json and archives a copy under data/runs/."""

import json
import statistics
from collections import Counter

from src.common import PACK, ROOT, clauses, maybe_help
from src.searchers import crustdata, exa, parallel
from src import geo, roles, employer
from src import facts as pfacts
from src import tenure as ptenure

# Every arm requests everything it can return, with symmetric prompts and a
# fixed k=10.
ARMS = {
    "crustdata": crustdata.parse,
    "exa": exa.parse,
    "parallel": parallel.parse,
}
RESULTS = PACK / "results"


def load(arm, qid):
    p = PACK / "raw" / arm / f"{qid}.json"
    return json.loads(p.read_text()) if p.exists() else None


def _any(matcher, val, cands):
    """True if any claim satisfies; False if some claim was checkable and none
    did; None only when nothing was checkable at all. An arm that populates more
    fields gets more chances to satisfy - which is the point: it said more."""
    best = None
    for _path, cand in cands:
        v = matcher(val, cand)
        if v is True:
            return True
        if v is False:
            best = False
    return best


def _all(matcher, val, cands):
    """For exclusions: False if ANY claim is incompatible, True if at least one
    was checkable and none disqualified, None if nothing was checkable."""
    saw = False
    for _path, cand in cands:
        v = matcher(val, cand)
        if v is False:
            return False
        if v is True:
            saw = True
    return True if saw else None


def satisfying(matcher, val, cands):
    """Which claim carried the pass - kept so every verdict stays auditable."""
    for path, cand in cands:
        if matcher(val, cand) is True:
            return path, cand
    return None


def norm_person(c):
    n = (c.get("name") or "").strip().lower()
    co = (c.get("company") or "").strip().lower()
    return f"{n}|{co}"


def score():
    spec = json.loads((ROOT / "data" / "queries" / "queries.json").read_text())
    key = {"queries": {q["id"]: q for q in spec["queries"]}}
    out = {"k": spec.get("k", 10), "arms": {}, "per_query": {}}

    for arm, parser in ARMS.items():
        agg = {
            "queries": 0, "results": 0, "zero": 0, "thin": 0,
            "latencies": [], "dupes": 0, "with_profile_url": 0,
            "loc_pass": 0, "loc_fail": 0, "loc_na": 0,
            "role_pass": 0, "role_fail": 0, "role_na": 0,
            "strict_pass": 0, "strict_total": 0,
            "unscorable": 0, "unjudged": 0, "scored_queries": 0,
            "no_title": 0,
        }
        for q in spec["queries"]:
            qid = q["id"]
            env = load(arm, qid)
            if env is None:
                continue
            parsed = parser(env)
            rs = parsed["results"]
            # Every location/role claim the provider actually made, with the
            # path it came from - a clause passes if ANY of them satisfies it.
            cl = pfacts.claims(arm, env)
            if len(cl) != len(rs):
                cl = [{"roles": [], "locations": [], "tenure": []}] * len(rs)
            kq = key["queries"][qid]
            agg["queries"] += 1
            agg["results"] += len(rs)
            lat = parsed.get("meta", {}).get("latency_ms") or env.get("latency_ms") or 0
            agg["latencies"].append(lat)
            if len(rs) == 0:
                agg["zero"] += 1
            if len(rs) < out["k"]:
                agg["thin"] += 1
            for c in rs:
                if not (c.get("title") or "").strip():
                    # the card carries no title. Reported because it is a
                    # failure mode of the data, not the ranking; role clauses
                    # may still pass on other claims (headline, history).
                    agg["no_title"] += 1
            seen = Counter(norm_person(c) for c in rs)
            agg["dupes"] += sum(v - 1 for v in seen.values() if v > 1)
            agg["with_profile_url"] += sum(
                1 for c in rs if c["_extra"].get("profile_url"))
            pq = {"n": len(rs), "latency_ms": lat,
                  "constraints": {}, "strict_pass": 0, "rank1_pass": False}
            checkable = []
            for con in clauses(kq):
                cid, kind, val, typ = con["id"], con["kind"], con["value"], con["type"]
                verdicts = []
                for i, c in enumerate(rs):
                    ev = cl[i] if i < len(cl) else {"roles": [], "locations": [], "tenure": []}
                    if typ == "f":
                        v = None          # clause type this rubric does not define
                    elif typ == "j":
                        v = None
                    elif kind == "location":
                        v = _any(geo.match, val,
                                 ev["locations"] or [("location", c.get("location"))])
                    elif kind == "tenure":
                        # objective and numeric, so no judged pairs - but still
                        # `any`, because a record may support several figures
                        v = _any(ptenure.match, val, ev.get("tenure", []))
                    elif kind == "employer":
                        v = employer.match(val, c.get("company"))
                    elif kind == "exclusion":
                        # An exclusion inverts the union: the person passes only
                        # if NOTHING they claim indicates the excluded role. Under
                        # `any`, a recruiter whose seniority field reads "Entry
                        # Level" would be cleared by that one harmless string.
                        v = _all(roles.exclusion_match, val,
                                 ev["roles"] or [("title", c.get("title"))])
                    elif kind in ("role", "seniority", "topic", "focus"):
                        # topic/focus are assertions about what the person works
                        # on, and every arm returns a headline in which to assert
                        # it. Same claim set and same judged table as role: a
                        # title that merely permits the topic is not evidence for
                        # it, and that reading is applied to every arm alike.
                        v = _any(roles.match, val,
                                 ev["roles"] or [("title", c.get("title"))])
                    else:
                        v = None
                    verdicts.append(v)
                npass = sum(1 for v in verdicts if v is True)
                nfail = sum(1 for v in verdicts if v is False)
                nna = sum(1 for v in verdicts if v is None)
                pq["constraints"][cid] = {
                    "kind": kind, "value": val, "type": typ,
                    "pass": npass, "fail": nfail, "unchecked": nna,
                }
                if typ == "f":
                    agg["unscorable"] += nna
                    if nna < len(rs) and (npass + nfail):
                        checkable.append(verdicts)
                elif typ == "j":
                    agg["unjudged"] += len(rs)
                elif kind == "location":
                    agg["loc_pass"] += npass; agg["loc_fail"] += nfail; agg["loc_na"] += nna
                    # A clause counts toward strict if the arm could check it
                    # for ANY result. An unchecked result is a fail, the same
                    # way a record with no title auto-fails every role clause;
                    # otherwise one record missing a field would excuse the
                    # whole clause. Only a clause nothing could be checked
                    # against is dropped.
                    if nna < len(rs): checkable.append(verdicts)
                else:
                    agg["role_pass"] += npass; agg["role_fail"] += nfail; agg["role_na"] += nna
                    if nna < len(rs): checkable.append(verdicts)

            # strict = passes every *checkable* constraint on this query
            if checkable:
                agg["scored_queries"] += 1
                for i in range(len(rs)):
                    agg["strict_total"] += 1
                    if all(v[i] is True for v in checkable):
                        agg["strict_pass"] += 1
                        pq["strict_pass"] += 1
                        if i == 0:
                            pq["rank1_pass"] = True
            pq["checkable_constraints"] = len(checkable)
            if not checkable and len(rs) == 0 and any(
                    c["type"] == "c" for c in clauses(kq)):
                # Zero results on a gradable query is a failure, not an
                # excusal: count the query (0 passes over 0 returned results)
                # so rivals keep it in their strict set and this arm's
                # usable-per-query is dragged down instead of quietly skipped.
                agg["scored_queries"] += 1
                pq["checkable_constraints"] = sum(
                    1 for c in clauses(kq) if c["type"] == "c")
            out["per_query"].setdefault(qid, {})[arm] = pq

        if agg["queries"] == 0:
            continue  # arm not collected yet
        lat = sorted(agg["latencies"])
        def pct(p):
            return lat[min(len(lat) - 1, int(len(lat) * p))] if lat else None
        loc_tot = agg["loc_pass"] + agg["loc_fail"]
        role_tot = agg["role_pass"] + agg["role_fail"]
        out["arms"][arm] = {
            "queries": agg["queries"],
            "results_returned": agg["results"],
            "yield_per_query": round(agg["results"] / agg["queries"], 2) if agg["queries"] else 0,
            "zero_result_queries": agg["zero"],
            "thin_queries": agg["thin"],
            "duplicate_results": agg["dupes"],
            "profile_url_coverage": round(agg["with_profile_url"] / agg["results"], 4) if agg["results"] else 0,
            "latency_p50_ms": pct(0.5),
            "latency_p95_ms": pct(0.95),
            "latency_min_ms": lat[0] if lat else None,
            "latency_max_ms": lat[-1] if lat else None,
            "location_adherence": round(agg["loc_pass"] / loc_tot, 4) if loc_tot else None,
            "location_checks": loc_tot,
            "role_adherence": round(agg["role_pass"] / role_tot, 4) if role_tot else None,
            "role_checks": role_tot,
            "strict_pass_rate": round(agg["strict_pass"] / agg["strict_total"], 4) if agg["strict_total"] else None,
            "strict_denominator": agg["strict_total"],
            "strict_passes": agg["strict_pass"],
            "no_title_results": agg["no_title"],
            "no_title_rate": round(agg["no_title"] / agg["results"], 4) if agg["results"] else None,
            # yield-adjusted: precision alone rewards an arm for returning less.
            # An arm that attempts fewer results otherwise looks more accurate.
            "passing_results_per_query": round(agg["strict_pass"] / agg["scored_queries"], 2) if agg["scored_queries"] else None,
            "scored_queries": agg["scored_queries"],
            "unscored_judged_checks": agg["unjudged"],
        }

    # ---- strict is recomputed on the COMMON query set -----------------------
    # A query counts toward strict only if EVERY arm can check at least one
    # constraint on it. Otherwise an arm gets scored on a query its rivals are
    # excused from - which is the asymmetry this scorer exists to prevent.
    # (A query whose only checkable constraint resolves for some arms and not
    # others would otherwise be scored for some and skipped for the rest.)
    arm_ids = list(out["arms"].keys())
    scorable = {a: {qid for qid, per in out["per_query"].items()
                    if (pq := per.get(a)) and pq.get("checkable_constraints")}
                for a in arm_ids}
    common = set.intersection(*scorable.values()) if scorable else set()
    for a in arm_ids:
        passes = sum(out["per_query"][q][a]["strict_pass"] for q in common)
        denom = sum(out["per_query"][q][a]["n"] for q in common)
        # recall@k: a query is a hit if a strictly-passing person appears at
        # rank 1 (R@1) or anywhere in the returned k (R@k)
        r1 = sum(1 for q in common if out["per_query"][q][a].get("rank1_pass"))
        rk = sum(1 for q in common if out["per_query"][q][a]["strict_pass"])
        out["arms"][a].update({
            "recall_at_1": round(r1 / len(common), 4) if common else None,
            "recall_at_k": round(rk / len(common), 4) if common else None,
            "strict_passes": passes,
            "strict_denominator": denom,
            "scored_queries": len(common),
            "strict_pass_rate": round(passes / denom, 4) if denom else None,
            "passing_results_per_query": round(passes / len(common), 2) if common else None,
            "excluded_from_strict": sorted(scorable[a] - common),
        })
    out["common_scored_queries"] = sorted(common)
    out["strict_excluded_queries"] = sorted(set().union(*scorable.values()) - common)

    if not out["arms"]:
        # nothing collected - do not write an empty scoreboard or archive it
        return out
    RESULTS.mkdir(parents=True, exist_ok=True)
    (RESULTS / "scoreboard.json").write_text(json.dumps(out, indent=1))

    # scoreboard.json is overwritten every run, so also keep an immutable copy
    # per run - otherwise comparing today against last week is impossible.
    from datetime import datetime, timezone
    runs = PACK / "runs"
    runs.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    out["run_id"] = stamp
    (runs / f"{stamp}.json").write_text(json.dumps(out, indent=1))
    return out


if __name__ == "__main__":
    maybe_help(__doc__)
    o = score()
    if not o["arms"]:
        print("No captures found under data/raw - run src.collect first.")
        raise SystemExit(1)
    n = len(o["arms"])
    print(f"Scored {n} arm(s) over {len(o['common_scored_queries'])} queries")
    print(f"  latest   -> {RESULTS / 'scoreboard.json'}")
    print(f"  archived -> {PACK / 'runs' / (o['run_id'] + '.json')}")
    print("Run `python -m src.report` for a readable table, "
          "`--history` to compare runs.")
