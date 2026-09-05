"""TheirStack: POST /v1/companies/technologies with company_domain.

Per-tech: confidence (low/medium/high), jobs, first/last_date_found,
relative_occurrence_within_category, rank, category. Paginated; one request
is billed flat regardless of limit, so a large page size is both cheaper and
avoids offset-pagination drift."""

from src.common import key, http_json

API = "https://api.theirstack.com/v1/companies/technologies"
PAGE_LIMIT = 1000


def fetch(domain: str, force: bool = False):
    envs, page = [], 0
    while True:
        env = http_json(
            "theirstack", f"{domain}__l{PAGE_LIMIT}_p{page}", API,
            headers=lambda: {"Authorization": f"Bearer {key('THEIRSTACK_API_KEY')}"},
            body={"company_domain": domain, "limit": PAGE_LIMIT, "page": page},
            force=force,
        )
        envs.append(env)
        data = (env["response"] or {}).get("data") or []
        if len(data) < PAGE_LIMIT or page >= 10:
            break
        page += 1
    return envs


def parse(envs):
    out = {"provider": "theirstack", "matched": False, "techs": [], "meta": {}}
    if not envs:
        return out
    for env in envs:
        for row in (env["response"] or {}).get("data") or []:
            tech = row.get("technology") or {}
            out["techs"].append({
                "raw_name": tech.get("name"),
                "slug": tech.get("slug"),
                "categories": [c for c in [tech.get("category_slug")] if c],
                "parent_category": tech.get("parent_category_slug"),
                "confidence": row.get("confidence"),
                "jobs": row.get("jobs"),
                "jobs_last_30_days": row.get("jobs_last_30_days"),
                "jobs_last_180_days": row.get("jobs_last_180_days"),
                "rank": row.get("rank_within_category"),
                "relative_occurrence": row.get("relative_occurrence_within_category"),
                "first_seen": row.get("first_date_found"),
                "last_seen": row.get("last_date_found"),
            })
    out["matched"] = bool(out["techs"])
    out["meta"] = {"latency_ms": sum(e["latency_ms"] for e in envs),
                   "pages": len(envs),
                   "metadata": (envs[0]["response"] or {}).get("metadata") or {}}
    return out
