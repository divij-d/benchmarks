"""Parallel arm: the asynchronous Task API, processor=pro.

Create a run, then poll for the result. Without a task_spec the API returns
prose rather than fields, so this sends an explicit output schema - every
structured field scored for this arm comes from that schema, which is ours,
not Parallel's default.

Latency is taken from the run object's own created_at/modified_at, not from
how long a fetch blocked."""

import json
import time
import urllib.request
import urllib.error

from src.common import key, card

CREATE = "https://api.parallel.ai/v1/tasks/runs"
RESULT = "https://api.parallel.ai/v1/tasks/runs/{rid}/result"
PROCESSOR = "pro"

SCHEMA = {
    "type": "object",
    "properties": {
        "people": {
            "type": "array",
            # NOTE: minItems/maxItems are REJECTED by this API - creating a run
            # with them returns 422 "Unsupported keyword 'minItems'". So there is
            # no structural way to pin the count, unlike Crustdata's `limit: 10`
            # and Exa's `numResults: 10`, which are hard parameters. The count can
            # only be requested in prose (schema description + input), which means
            # this arm's yield is advisory where the others' is enforced - a
            # residual asymmetry the harness cannot remove.
            "description": ("exactly 10 people - always return 10 entries, never "
                            "fewer, ranked best match first"),
            "items": {
                "type": "object",
                "properties": {
                    "name": {"type": "string"},
                    "current_title": {"type": "string"},
                    "current_company": {"type": "string"},
                    "location": {"type": "string"},
                    "linkedin_url": {"type": "string"},
                    "headline": {"type": "string",
                                 "description": "their profile headline or tagline"},
                    "seniority": {"type": "string"},
                    "past_roles": {"type": "string",
                                   "description": "previous job titles and employers"},
                    "education": {"type": "string"},
                    "years_experience": {"type": "string"},
                },
                "required": ["name", "current_title", "current_company"],
            },
        }
    },
    "required": ["people"],
}

    # The other arms take a hard `limit: 10` / `numResults: 10`. This API has no
    # numeric equivalent and rejects minItems/maxItems, so the count is stated
    # twice in prose, with an explicit instruction to fill short lists with
    # partial matches rather than withhold them. That mirrors the other arms,
    # which return their top 10 regardless of confidence and leave the grader
    # to decide what counts.
PROMPT = ("Find exactly 10 people matching this description: {q}\n"
          "Return each person's name, current title, current company, location, "
          "LinkedIn URL, headline, seniority, past roles, education and years of "
          "experience.\n"
          "Always return 10 people, ranked best match first. If fewer than 10 "
          "fully satisfy every part of the description, fill the remaining places "
          "with the closest partial matches rather than returning a shorter list.")


def _req(url, body=None, method="GET", timeout=900):
    data = json.dumps(body).encode() if body is not None else None
    r = urllib.request.Request(url, data=data, method=method)
    r.add_header("content-type", "application/json")
    r.add_header("x-api-key", key("PARALLEL_API_KEY"))
    try:
        with urllib.request.urlopen(r, timeout=timeout) as resp:
            return resp.status, json.loads(resp.read().decode())
    except urllib.error.HTTPError as e:
        try:
            return e.code, json.loads(e.read().decode())
        except Exception:
            return e.code, {"error": str(e)}
    except Exception as e:
        return 0, {"error": str(e)}


def create_run(query_text):
    st, r = _req(CREATE, {
        "task_spec": {"output_schema": {"type": "json", "json_schema": SCHEMA}},
        "input": PROMPT.format(q=query_text),
        "processor": PROCESSOR,
    }, "POST", timeout=120)
    rid = ((r or {}).get("run_id") or (r or {}).get("id")) if isinstance(r, dict) else None
    return st, rid, r


def fetch_result(rid):
    t0 = time.time()
    st, r = _req(RESULT.format(rid=rid), timeout=900)
    return st, r, int((time.time() - t0) * 1000)


def run_duration_ms(envelope):
    """Server-side duration from the run object, not our fetch timing.

    The Task API is async: whatever a worker measures around its GET is the
    time to collect an answer that may already be finished. created_at ->
    modified_at on a completed run is what a caller actually waits for.
    """
    from datetime import datetime
    r = ((envelope.get("response") or {}).get("run") or {})
    if r.get("status") != "completed":
        return None
    a, b = r.get("created_at"), r.get("modified_at")
    if not (a and b):
        return None
    try:
        f = lambda t: datetime.fromisoformat(t.replace("Z", "+00:00"))
        return int((f(b) - f(a)).total_seconds() * 1000)
    except Exception:
        return None


def parse(envelope):
    r = envelope.get("response") or {}
    out = {"results": [], "meta": {
        "latency_ms": run_duration_ms(envelope) or envelope.get("latency_ms"),
        "http_status": envelope.get("http_status"),
        "total_count": None, "total_count_relation": None,
        "processor": PROCESSOR,
    }}
    if not isinstance(r, dict):
        return out
    content = (r.get("output") or {})
    content = content.get("content") if isinstance(content, dict) else content
    people = (content or {}).get("people") if isinstance(content, dict) else None
    for p in (people or []):
        li = p.get("linkedin_url")
        out["results"].append(card(
            name=p.get("name"),
            title=p.get("current_title"),
            company=p.get("current_company"),
            location=p.get("location"),
            profile_url=li if li and "linkedin.com/in/" in str(li) else None,
        ))
    return out
