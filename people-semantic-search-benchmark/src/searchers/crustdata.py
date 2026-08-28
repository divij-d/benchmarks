"""Crustdata arm: POST /person/search with a natural-language query,
search.mode=hybrid (the documented default)."""

import json

from src.common import key, http_json, card, PACK

API = "https://api.crustdata.com/person/search"
# Every selectable field group. Role and location are the only scored clauses,
# but they are read from ALL returned evidence - title, headline, normalised
# title, past roles, education - so each arm is judged on the best case its
# own response can make.
FIELDS = ["fit", "basic_profile", "experience", "education", "social_handles",
          "years_of_experience", "years_of_experience_raw", "crustdata_person_id"]


def _headers():
    return {"authorization": f"Bearer {key('CRUSTDATA_API_KEY')}",
            "x-api-version": "2025-11-01"}




def fetch_semantic(qid, query_text, k=10, force=False, arm="crustdata",
                   search_mode="hybrid"):
    """`arm` names the capture directory."""
    search = {"query": query_text, "mode": search_mode}
    body = {"search": search, "fields": FIELDS, "limit": k}
    return http_json(arm, qid, API, headers=_headers(), body=body, force=force)




def parse(envelope):
    """-> {results:[card], meta:{}}"""
    r = envelope.get("response") or {}
    out = {"results": [], "meta": {
        "latency_ms": envelope.get("latency_ms"),
        "http_status": envelope.get("http_status"),
        "total_count": r.get("total_count") if isinstance(r, dict) else None,
        "total_count_relation": r.get("total_count_relation") if isinstance(r, dict) else None,
    }}
    if not isinstance(r, dict):
        return out
    for p in (r.get("profiles") or []):
        bp = p.get("basic_profile") or {}
        cur = ((p.get("experience") or {}).get("employment_details") or {}).get("current")
        cur = cur[0] if isinstance(cur, list) and cur else (cur if isinstance(cur, dict) else {})
        loc = bp.get("location") or {}
        loc = loc.get("full_location") if isinstance(loc, dict) else loc
        # Some profiles carry no current employment record at all, so
        # current_title / current.title are both absent while the person's role
        # sits in basic_profile.normalized_title at high confidence. Reading only
        # one of the two places under-reads this arm.
        # Guarded on `confident` so we never invent a role.
        nt = bp.get("normalized_title") or {}
        title = bp.get("current_title") or cur.get("title")
        if not title and nt.get("confident") and nt.get("matched_title"):
            title = nt["matched_title"]
        soc = p.get("social_handles") or {}
        li = ((soc.get("professional_network_identifier") or {}) or {}).get("profile_url")
        out["results"].append(card(
            name=bp.get("name"),
            title=title,
            company=cur.get("name"),
            location=loc,
            # carried through for joins and reporting, not shown as a claim
            profile_url=li,
            fit=p.get("fit"),
            seniority_level=cur.get("seniority_level"),
            title_from_normalized=bool(
                not (bp.get("current_title") or cur.get("title")) and title),
            company_website=cur.get("company_website"),
            company_headcount=cur.get("company_headcount_latest"),
            company_industries=cur.get("company_industries"),
        ))
    return out
