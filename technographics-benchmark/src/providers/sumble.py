"""Sumble, two steps:

1. POST /v9/organizations  {"organizations":[{"url": domain}]}  -> numeric id
2. GET  /v9/organizations/{id}/techs -> business_functions -> categories ->
   technologies[] (primary picks, billed per tech) + evidence[] (the full
   ranked superset: name + job_post_used_count)

We parse from `evidence` (the complete set, fairest on recall) and mark which
entries are also `technologies` (primary=True). Sumble exposes no dates, so
freshness is not measurable for it."""

from src.common import key, http_json

API = "https://api.sumble.com/v9"


def _headers():
    return {"Authorization": f"Bearer {key('SUMBLE_API_KEY')}"}


def fetch(domain: str, force: bool = False):
    match_env = http_json(
        "sumble", f"{domain}__match", f"{API}/organizations",
        headers=_headers,
        body={"organizations": [{"url": domain}],
              "select": {"attributes": ["id", "name", "slug", "url", "sumble_url"],
                         "entities": []}},
        force=force,
    )
    org = None
    for r in (match_env["response"] or {}).get("organizations") or []:
        if not isinstance(r, dict):
            continue
        cand = r.get("attributes") or r.get("organization") or r
        if cand.get("id"):
            org = cand
            break
    if not org:
        return {"match": match_env, "techs": None}

    techs_env = http_json(
        "sumble", f"{domain}__techs", f"{API}/organizations/{org['id']}/techs",
        method="GET", headers=_headers, body=None, force=force,
    )
    return {"match": match_env, "techs": techs_env, "org": org}


def exhausted(bundle) -> bool:
    """True when the call failed for credit reasons - recorded as NOT RUN,
    never as a coverage miss."""
    status = ((bundle.get("techs") or bundle.get("match") or {}).get("http_status"))
    return status in (402, 403, 429)


def parse(bundle):
    out = {"provider": "sumble", "matched": False, "techs": [], "meta": {}}
    techs_env = bundle.get("techs")
    if not techs_env:
        return out
    resp = techs_env["response"] or {}
    out["matched"] = True
    out["meta"] = {
        "organization_id": resp.get("organization_id"),
        "organization_slug": resp.get("organization_slug"),
        "credits_used_techs": resp.get("credits_used"),
        "credits_remaining": resp.get("credits_remaining"),
        "latency_ms": techs_env["latency_ms"],
    }
    for bf in resp.get("business_functions") or []:
        for cat in bf.get("categories") or []:
            primary = {t.get("name") for t in cat.get("technologies") or []}
            slug_by_name = {t.get("name"): t.get("slug") for t in cat.get("technologies") or []}
            for ev in cat.get("evidence") or []:
                out["techs"].append({
                    "raw_name": ev.get("name"),
                    "slug": slug_by_name.get(ev.get("name")),
                    "business_function": bf.get("business_function"),
                    "categories": [cat.get("category_slug")],
                    "job_post_used_count": ev.get("job_post_used_count"),
                    "primary": ev.get("name") in primary,
                })
    return out
