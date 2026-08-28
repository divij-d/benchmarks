"""Exa arm: POST /search with category=people, contents enrichment on."""

from src.common import key, http_json, card

API = "https://api.exa.ai/search"


def fetch(qid, query_text, k=10, force=False, arm="exa", contents=True):
    """`arm` names the capture directory."""
    body = {"query": query_text, "type": "auto",
            "category": "people", "numResults": k}
    if contents:
        # Exa's own documented enrichment. The summary prompt is deliberately
        # generic - it names the two scored clause types, never the query - so
        # Exa gets to make its best case without being handed the answer.
        body["contents"] = {
            "text": {"maxCharacters": 1500},
            "summary": {"query": "This person's current job title, "
                                 "employer, and location"}}
    return http_json(arm, qid, API,
                     headers={"x-api-key": key("EXA_API_KEY")},
                     body=body, force=force)


def parse(envelope):
    r = envelope.get("response") or {}
    out = {"results": [], "meta": {
        "latency_ms": envelope.get("latency_ms"),
        "http_status": envelope.get("http_status"),
        "total_count": None, "total_count_relation": None,
    }}
    if not isinstance(r, dict):
        return out
    for res in (r.get("results") or []):
        ents = res.get("entities") or []
        pr = (ents[0].get("properties") if ents and isinstance(ents[0], dict) else {}) or {}
        wh = pr.get("workHistory") or []
        cur = wh[0] if wh else {}
        # workHistory[0] is occasionally missing title or company while a later
        # entry has one. Same principle as the Crustdata fallback: read the best
        # value this arm's own response offers, rather than only slot zero.
        def _first(key):
            for w in wh:
                v = w.get(key)
                if key == "company" and isinstance(v, dict):
                    v = v.get("name")
                if v:
                    return v
            return None
        title = cur.get("title") or _first("title")
        comp = cur.get("company")
        comp = comp.get("name") if isinstance(comp, dict) else comp
        comp = comp or _first("company")
        url = res.get("url")
        out["results"].append(card(
            name=pr.get("name") or res.get("title"),
            # extra evidence, not shown to a judge as a title, but available when
            # inferring the scored clauses from everything this arm returned
            page_text=res.get("text"),
            page_summary=res.get("summary"),
            education=pr.get("educationHistory"),
            work_history=wh,
            title=title,
            company=comp,
            location=pr.get("location"),
            profile_url=url if url and "linkedin.com/in/" in str(url) else None,
            source_url=url,
            entity_property_keys=sorted(k for k, v in pr.items()
                                        if v not in (None, "", [], {})),
        ))
    return out
