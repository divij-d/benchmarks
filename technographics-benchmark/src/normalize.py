"""Tech-name normalization and the cross-provider comparison builder.

norm_key: casefold, strip punctuation/whitespace, apply the alias table.
Deliberately conservative - unresolved variants stay separate (provider-unique)
rather than being force-merged.

The committed tables under data/normalization/ were built by an LLM
adjudication pass over the panel's raw tech names. They cover the panel well;
for companies outside it, run src.normalize_llm to extend them per company.
Every file is optional and the scorer runs with whatever is present:

  aliases.json            {"variant-key": "canonical-key"}  same technology
                          under two names ("amazon-web-services" -> "aws")
  hierarchy.json          {"parents": {"child-key": "parent-key"},
                           "cruft_suspects": ["microsoft", "google", ...]}
                          child is a distinct product under the parent
                          umbrella; cruft suspects are bare vendor umbrellas
                          that get no rollup credit
  category_crosswalk.json each provider's category vocabulary -> 6 buckets
                          (committed)
  llm_bucket_fallback.json / confirmed_bucket_overrides.json
                          {"tech-key": "bucket"}  used by score.py for techs
                          no provider categorised
  llm_extensions/<domain>.json
                          per-company merges + parents produced by
                          src.normalize_llm for the run at hand (gitignored)

Keys in every file are norm_key outputs (lowercase, hyphenated).
"""

import json
import re

from src.common import NORM_DIR

ALIAS_PATH = NORM_DIR / "aliases.json"
HIERARCHY_PATH = NORM_DIR / "hierarchy.json"
CROSSWALK_PATH = NORM_DIR / "category_crosswalk.json"

# Seed aliases: only unambiguous, well-known identities.
SEED_ALIASES = {
    "reactjs": "react", "react.js": "react",
    "nodejs": "node-js", "node.js": "node-js", "node": "node-js",
    "nextjs": "next-js", "next.js": "next-js",
    "vuejs": "vue", "vue.js": "vue",
    "postgres": "postgresql",
    "k8s": "kubernetes",
    "amazon web services": "aws", "amazon web services (aws)": "aws",
    "google cloud": "google-cloud-platform", "gcp": "google-cloud-platform",
    "google cloud platform": "google-cloud-platform",
    "microsoft azure": "azure",
    "ms sql server": "sql-server", "microsoft sql server": "sql-server", "mssql": "sql-server",
    "golang": "go",
    "tailwindcss": "tailwind-css", "tailwind": "tailwind-css",
    "vs code": "visual-studio-code", "vscode": "visual-studio-code",
    "github actions": "github-actions",
    "elasticsearch": "elastic-search",
}


def load_aliases():
    table = dict(SEED_ALIASES)
    if ALIAS_PATH.exists():
        table.update({k: v for k, v in json.loads(ALIAS_PATH.read_text()).items()
                      if not k.startswith("_")})
    return table


def _hierarchy():
    return json.loads(HIERARCHY_PATH.read_text()) if HIERARCHY_PATH.exists() else {}


_ALIASES = load_aliases()
_PARENTS = _hierarchy().get("parents", {})        # child key -> parent key
_CRUFT = set(_hierarchy().get("cruft_suspects", []))
CRUFT = _CRUFT
EXT_DIR = NORM_DIR / "llm_extensions"


def load_extensions(domain: str):
    """Run-local LLM merges/parents for one company, or None."""
    p = EXT_DIR / f"{domain}.json"
    return json.loads(p.read_text()) if p.exists() else None

# Freshness view: a claim is "fresh" if last seen within 12 months of panel
# collection. Crustdata web-signal techs inherit crawl recency (a web signal
# means the tech is on the live site). Sumble exposes no dates anywhere in its
# schema, so it cannot participate in a freshness-conditioned metric - its
# fresh recall is null by policy, and that fact is itself a published finding.
FRESH_CUTOFF = "2025-08-26"
UNDATED_PROVIDERS = {"sumble"}

# Category buckets: each provider's top-level taxonomy maps into 6 shared
# buckets. A tech's bucket is the modal vote of the business-taxonomy providers
# (Crustdata / TheirStack / Sumble); BuiltWith's web-centric tag only votes when
# no one else does. PredictLeads exposes no categories at all - its claims
# inherit the tech's bucket from other voters (see score.py for the fallback).
_XWALK = json.loads(CROSSWALK_PATH.read_text()) if CROSSWALK_PATH.exists() else {}
BUCKETS = _XWALK.get("buckets", {})


def _entry_bucket_vote(prov, e):
    """Return (bucket, is_fallback) for one provider's entry, or (None, _)."""
    if prov == "crustdata":
        for s in e.get("super_categories") or []:
            b = _XWALK.get("crustdata", {}).get(s)
            if b:
                return b, False
    elif prov == "theirstack":
        b = _XWALK.get("theirstack", {}).get(e.get("parent_category"))
        if b:
            return b, False
    elif prov == "sumble":
        b = _XWALK.get("sumble", {}).get(e.get("business_function"))
        if b:
            return b, False
    elif prov == "builtwith":
        b = _XWALK.get("builtwith_tag", {}).get(e.get("tag"))
        if b:
            return b, True  # fallback vote only
    return None, False


def _row_bucket(by_provider):
    votes, fallback = [], []
    for prov, slot in by_provider.items():
        if not slot["entries"]:
            continue
        b, is_fb = _entry_bucket_vote(prov, slot["entries"][0])
        if b:
            (fallback if is_fb else votes).append(b)
    pool = votes or fallback
    if not pool:
        return None
    return max(set(pool), key=lambda b: (pool.count(b), b))


def _entry_fresh(prov, e):
    ls = e.get("last_seen")
    if ls:
        return str(ls)[:10] >= FRESH_CUTOFF
    return prov == "crustdata" and "web signals" in (e.get("sources") or [])


def norm_key(raw_name: str) -> str:
    if not raw_name:
        return ""
    s = raw_name.casefold().strip()
    s = _ALIASES.get(s, s)
    s = re.sub(r"[^a-z0-9+#. ]", " ", s)
    s = re.sub(r"\s+", " ", s).strip()
    s = _ALIASES.get(s, s)
    s = s.replace(" ", "-")
    return _ALIASES.get(s, s)  # final alias pass on the hyphenated key


def build_comparison(domain: str, parsed_list, extensions=None):
    """Merge per-provider parses into one comparison record keyed by norm_key.

    `extensions` is the optional per-company output of src.normalize_llm:
    {"merges": {from: to}, "parents": {child: parent}}. Merges are applied on
    top of the alias table; parents extend the hierarchy for this company."""
    ext = extensions or {}
    merges = ext.get("merges") or {}
    parents = dict(_PARENTS)
    parents.update({c: p for c, p in (ext.get("parents") or {}).items() if p not in _CRUFT})

    def K(t):
        k = norm_key(t.get("raw_name"))
        return merges.get(k, k)

    providers = [p["provider"] for p in parsed_list]
    merged = {}
    for p in parsed_list:
        for t in p["techs"]:
            k = K(t)
            if not k:
                continue
            row = merged.setdefault(k, {"key": k, "by_provider": {}})
            slot = row["by_provider"].setdefault(p["provider"], {"entries": []})
            slot["entries"].append(t)

    # Hierarchy rollup (umbrella credit), asymmetric by design: a provider
    # reporting any CHILD of key K counts as having found K ("uses S3" =>
    # "uses AWS"); reporting the PARENT never grants a child. Rollup
    # detections count toward corroboration too - a child report is
    # independent evidence of the parent.
    # EXCEPTION: parents on the cruft_suspects list (bare vendor umbrellas like
    # "microsoft" / "google" - claims true of nearly every company) receive NO
    # rollup credit; such rows score on direct detections only.
    direct_found = {p["provider"]: set() for p in parsed_list}
    for p in parsed_list:
        for t in p["techs"]:
            k = K(t)
            if k:
                direct_found[p["provider"]].add(k)

    children_of = {}
    for child, parent in parents.items():
        children_of.setdefault(parent, []).append(child)

    dated = [p["provider"] for p in parsed_list if p["provider"] not in UNDATED_PROVIDERS]
    fresh_direct = {prov: set() for prov in dated}
    for p in parsed_list:
        if p["provider"] not in fresh_direct:
            continue
        for t in p["techs"]:
            k = K(t)
            if k and _entry_fresh(p["provider"], t):
                fresh_direct[p["provider"]].add(k)

    rows = []
    for k, row in merged.items():
        found_by = sorted(row["by_provider"].keys())
        rollup_via = {}
        fresh_by = set()
        if k not in _CRUFT:
            for prov in providers:
                if prov in found_by:
                    continue
                via = sorted(c for c in children_of.get(k, []) if c in direct_found[prov])
                if via:
                    rollup_via[prov] = via
        for prov in dated:
            direct_fresh = k in fresh_direct[prov]
            child_fresh = (k not in _CRUFT and
                           any(c in fresh_direct[prov] for c in children_of.get(k, [])))
            if direct_fresh or child_fresh:
                fresh_by.add(prov)
        effective = sorted(set(found_by) | set(rollup_via.keys()))
        rows.append({
            "key": k,
            "found_by": found_by,
            "rollup_via": rollup_via,
            "effective_found_by": effective,
            "corroboration": len(effective),
            "fresh_found_by": sorted(fresh_by),
            "bucket": _row_bucket(row["by_provider"]),
            "by_provider": row["by_provider"],
        })
    rows.sort(key=lambda r: (-r["corroboration"], r["key"]))

    per_provider_counts = {p["provider"]: len(p["techs"]) for p in parsed_list}
    per_provider_matched = {p["provider"]: p["matched"] for p in parsed_list}

    def recall_at(thr):
        ref = [r for r in rows if r["corroboration"] >= thr]
        return len(ref), {
            prov: (sum(1 for r in ref if prov in r["effective_found_by"]) / len(ref)
                   if ref else None)
            for prov in providers
        }

    # Threshold views: "2" = any pair agrees (loose; shared-corpus pairs can
    # self-corroborate), "majority" = ceil((n_providers+1)/2), robust default.
    majority_thr = len(providers) // 2 + 1
    corroborated, recall = recall_at(2)
    corroborated_maj, recall_maj = recall_at(majority_thr)

    fresh_thr = len(dated) // 2 + 1 if dated else 0
    fresh_ref = [r for r in rows if len(r["fresh_found_by"]) >= fresh_thr]
    recall_fresh = {}
    for prov in providers:
        if prov in UNDATED_PROVIDERS or not fresh_ref:
            recall_fresh[prov] = None
        else:
            recall_fresh[prov] = (sum(1 for r in fresh_ref if prov in r["fresh_found_by"])
                                  / len(fresh_ref))

    # per-bucket view: within each category bucket, recall / precision / F1 per
    # provider (None when the denominator is empty or too thin)
    maj_ref = [r for r in rows if r["corroboration"] >= majority_thr]
    ucs_by_bucket = {}
    for b in BUCKETS:
        ref_b = [r for r in maj_ref if r["bucket"] == b]
        ref2_b = [r for r in rows if r["bucket"] == b and r["corroboration"] >= 2]
        recall_b, prec_b, prec2_b, f1_b, f12_b = {}, {}, {}, {}, {}
        for prov in providers:
            r_maj = (sum(1 for r in ref_b if prov in r["effective_found_by"]) / len(ref_b)
                     if ref_b else None)
            claims = [r for r in rows if r["bucket"] == b and prov in r["effective_found_by"]]
            p_maj = (sum(1 for r in claims if r["corroboration"] >= majority_thr) / len(claims)
                     if len(claims) >= 3 else None)
            p_pair = (sum(1 for r in claims if r["corroboration"] >= 2) / len(claims)
                      if len(claims) >= 3 else None)
            r_pair = (sum(1 for r in ref2_b if prov in r["effective_found_by"]) / len(ref2_b)
                      if ref2_b else None)
            recall_b[prov] = r_maj
            prec_b[prov] = p_maj
            prec2_b[prov] = p_pair
            f1_b[prov] = (2 * r_maj * p_maj / (r_maj + p_maj)
                          if r_maj is not None and p_maj is not None and (r_maj + p_maj) > 0 else None)
            f12_b[prov] = (2 * r_pair * p_pair / (r_pair + p_pair)
                           if r_pair is not None and p_pair is not None and (r_pair + p_pair) > 0 else None)
        ucs_by_bucket[b] = {"n": len(ref_b), "recall": recall_b, "precision": prec_b,
                            "f1": f1_b, "f1_pair": f12_b}

    return {
        "domain": domain,
        "providers": providers,
        "matched": per_provider_matched,
        "summary": {
            "union_size": len(rows),
            "corroborated": corroborated,
            "tech_counts": per_provider_counts,
            "recall_vs_corroborated_union": recall,
            "majority_threshold": majority_thr,
            "corroborated_majority": corroborated_maj,
            "recall_vs_majority_union": recall_maj,
            "fresh_cutoff": FRESH_CUTOFF,
            "majority_threshold_fresh": fresh_thr,
            "corroborated_majority_fresh": len(fresh_ref),
            "recall_vs_majority_union_fresh": recall_fresh,
            "ucs_by_bucket": ucs_by_bucket,
        },
        "meta": {p["provider"]: p["meta"] for p in parsed_list},
        "normalization": {"llm": ({k: ext.get(k) for k in ("provider", "model")}
                                  if ext else None),
                          "merges_applied": len(merges),
                          "parents_added": len(parents) - len(_PARENTS)},
        "rows": rows,
    }
