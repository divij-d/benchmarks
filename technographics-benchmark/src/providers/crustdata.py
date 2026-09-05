"""Crustdata: POST /company/enrich with fields=["basic_info","technographics"].

Per-tech: name, categories (category_slug + super_slug), sources (job posting /
web signals), posting_count, and evidence[] with posting URLs and posted_at,
from which first/last seen are reconstructed."""

from src.common import key, http_json

API = "https://api.crustdata.com/company/enrich"


def fetch(domain: str, force: bool = False):
    return http_json(
        "crustdata", domain, API,
        headers=lambda: {"authorization": f"Bearer {key('CRUSTDATA_API_KEY')}",
                         "x-api-version": "2025-11-01"},
        body={"domains": [domain], "fields": ["basic_info", "technographics"]},
        force=force,
    )


def parse(envelope):
    """-> common shape: {provider, matched, techs[], meta}"""
    resp = envelope["response"]
    out = {"provider": "crustdata", "matched": False, "techs": [], "meta": {}}
    if not isinstance(resp, list) or not resp:
        return out
    matches = resp[0].get("matches") or []
    if not matches:
        return out
    m = matches[0]
    cd = m.get("company_data") or {}
    if not cd:
        return out  # a low-confidence match row carrying no data is NOT a match
    tg = cd.get("technographics") or {}
    out["matched"] = True
    out["meta"] = {
        "match_confidence": m.get("confidence_score"),
        "total_technologies": tg.get("total_technologies"),
        "top_technologies": tg.get("top_technologies"),
        "updated_at": tg.get("updated_at"),
        "latency_ms": envelope["latency_ms"],
    }
    for t in tg.get("technologies") or []:
        evidence = t.get("evidence") or []
        dates = [e.get("posted_at") for e in evidence if e.get("posted_at")]
        cats = t.get("categories") or []
        out["techs"].append({
            "raw_name": t.get("name"),
            "sources": t.get("sources") or [],
            "categories": [c.get("category_slug") for c in cats],
            "super_categories": sorted({c.get("super_slug") for c in cats if c.get("super_slug")}),
            "posting_count": t.get("posting_count"),
            "description": t.get("description"),
            "evidence_count": len(evidence),
            "evidence_urls": [e.get("url") for e in evidence if e.get("url")][:10],
            "first_seen": min(dates) if dates else None,
            "last_seen": max(dates) if dates else None,
        })
    return out
