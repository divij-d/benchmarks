"""PredictLeads: GET /api/v3/companies/{domain}/technology_detections.

Auth: X-Api-Key + X-Api-Token headers. JSON:API - data[] holds detections
(first/last_seen_at, behind_firewall, score, source_count,
department_onet_codes); technology names resolve from included[].
behind_firewall=false means detected via the website (a web signal)."""

from src.common import key, http_json

API = "https://predictleads.com/api/v3"
PAGE_LIMIT = 1000   # documented maximum; one request covers all but the largest stacks


def _headers():
    return {"X-Api-Key": key("PREDICT_LEADS_KEY"),
            "X-Api-Token": key("PREDICT_LEADS_TOKEN")}


def fetch(domain: str, force: bool = False):
    envs, page = [], 1
    while True:
        env = http_json(
            "predictleads", f"{domain}__l{PAGE_LIMIT}_p{page}",
            f"{API}/companies/{domain}/technology_detections?page={page}&limit={PAGE_LIMIT}",
            method="GET", headers=_headers, body=None, force=force,
        )
        envs.append(env)
        data = (env["response"] or {}).get("data") or []
        if not data:
            break
        count = ((env["response"] or {}).get("meta") or {}).get("count")
        got = sum(len((e["response"] or {}).get("data") or []) for e in envs)
        if count is not None and got >= count:
            break
        if count is None and len(data) < PAGE_LIMIT:
            break
        page += 1
        if page > 30:
            break
    declared = ((envs[0]["response"] or {}).get("meta") or {}).get("count")
    got = sum(len((e["response"] or {}).get("data") or []) for e in envs)
    if declared is not None and got != declared:
        print(f"  ! predictleads integrity: fetched {got} != meta.count {declared} for {domain}")
    return envs


def parse(envs):
    out = {"provider": "predictleads", "matched": False, "techs": [], "meta": {}}
    if not envs:
        return out
    tech_index = {}
    for env in envs:
        for inc in (env["response"] or {}).get("included") or []:
            if inc.get("type") == "technology":
                tech_index[inc["id"]] = inc.get("attributes") or {}
    for env in envs:
        for row in (env["response"] or {}).get("data") or []:
            att = row.get("attributes") or {}
            rel = (((row.get("relationships") or {}).get("technology") or {}).get("data") or {})
            tech = tech_index.get(rel.get("id"), {})
            sources = ["job posting"] if att.get("behind_firewall") else ["web signals"]
            if att.get("behind_firewall") is False and att.get("department_onet_codes"):
                sources = ["web signals", "job posting"]  # found both ways
            out["techs"].append({
                "raw_name": tech.get("name"),
                "slug": tech.get("slug") or tech.get("technology_slug"),
                "categories": tech.get("categories") or [],
                "sources": sources,
                "score": att.get("score"),
                "source_count": att.get("source_count"),
                "department_onet_codes": att.get("department_onet_codes") or [],
                "first_seen": att.get("first_seen_at"),
                "last_seen": att.get("last_seen_at"),
            })
    out["matched"] = bool(out["techs"])
    out["meta"] = {"latency_ms": sum(e["latency_ms"] for e in envs), "pages": len(envs)}
    return out
