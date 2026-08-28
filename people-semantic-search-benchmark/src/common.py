"""Shared plumbing: paths, API keys, and a disk-cached HTTP helper.

Keys come from the environment first, then a gitignored .env at the benchmark root.
Every response is cached at data/raw/<arm>/<query>.json and re-used unless
--force is passed, so scoring and re-scoring never re-bill a provider."""

import json
import os
import time
import urllib.request
import urllib.error
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent          # benchmark root
PACK = ROOT / "data"                                   # raw captures + results
RAW_DIR = PACK / "raw"

# Whether a metadata kind is scored ("c"), reported but unscorable because no
# arm returns a field that could settle it ("j"), or unscored ("f").
KIND_TYPE = {"role": "c", "location": "c", "topic": "c", "seniority": "c",
             "tenure": "c", "employer": "c", "exclusion": "c", "focus": "c",
             "industry": "f", "stage": "f", "history": "j", "skill": "j"}


def clauses(q):
    """A query's metadata as typed clauses: [{id, kind, value, type}]."""
    return [{"id": f"{q['id']}.{i}", "kind": k, "value": v,
             "type": KIND_TYPE.get(k, "f")}
            for i, (k, v) in enumerate((q.get("metadata") or {}).items(), 1)]


def _load_dotenv():
    env = {}
    p = ROOT / ".env"
    if p.exists():
        for line in p.read_text().splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, v = line.split("=", 1)
            env[k.strip()] = v.strip().strip('"').strip("'")
    return env


_DOTENV = _load_dotenv()


def key(name: str, required: bool = True):
    """Environment wins; .env is the fallback. Never persisted."""
    v = os.environ.get(name) or _DOTENV.get(name)
    if not v and required:
        raise RuntimeError(
            f"{name} not set. export {name}=... before running this arm "
            f"(keys are intentionally not stored in this repo)."
        )
    return v


def cache_path(arm: str, qid: str) -> Path:
    return RAW_DIR / arm / f"{qid}.json"


def http_json(arm, qid, url, *, method="POST", headers=None, body=None,
              force=False, timeout=180):
    """POST/GET JSON with disk cache. Returns the envelope dict."""
    p = cache_path(arm, qid)
    if not force and p.exists():
        try:
            hit = json.loads(p.read_text())
        except json.JSONDecodeError:
            # a crash mid-write leaves a truncated file; treat it as absent
            # rather than poisoning every later score with a parse error
            p.unlink()
        else:
            hit["_from_cache"] = True
            return hit

    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(url, data=data, method=method)
    req.add_header("content-type", "application/json")
    for k, v in (headers or {}).items():
        req.add_header(k, v)

    t0 = time.time()
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            status = resp.status
            payload = json.loads(resp.read().decode())
    except urllib.error.HTTPError as e:
        status = e.code
        try:
            payload = json.loads(e.read().decode())
        except Exception:
            payload = {"error": str(e)}
    except Exception as e:
        status = 0
        payload = {"error": str(e)}
    latency_ms = int((time.time() - t0) * 1000)

    envelope = {
        "arm": arm,
        "query_id": qid,
        "request": {"url": url, "method": method, "body": body},
        "http_status": status,
        "latency_ms": latency_ms,
        "fetched_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "response": payload,
        "_from_cache": False,
    }
    if 200 <= status < 300:  # never cache errors - a retry must hit the API
        p.parent.mkdir(parents=True, exist_ok=True)
        # atomic: a crash mid-write must not leave a truncated envelope
        tmp = p.with_suffix('.json.tmp')
        tmp.write_text(json.dumps(envelope, indent=1))
        tmp.replace(p)
    return envelope


# ---- the common result card -------------------------------------------------
# The four fields every arm can produce. This card is what the explorer and
# reports show; clause verdicts are decided from every claim in the response,
# via facts.py.

CARD_FIELDS = ["name", "title", "company", "location"]


def card(name=None, title=None, company=None, location=None, **extra):
    c = {"name": name, "title": title, "company": company, "location": location}
    c["_extra"] = {k: v for k, v in extra.items() if v not in (None, "", [], {})}
    return c


def maybe_help(doc):
    """Print the module docstring and exit if -h/--help was passed.

    These entry points act on the world - collect_parallel creates billable
    task runs - so an unrecognised flag must never fall through into the run.
    """
    import sys
    if any(a in ("-h", "--help") for a in sys.argv[1:]):
        print((doc or "").strip())
        raise SystemExit(0)


import re as _re
_CONTACT = [
    _re.compile(r"https?://\S+"),                                  # URLs
    _re.compile(r"[a-z0-9._%+-]+@[a-z0-9.-]+\.[a-z]{2,}"),         # email addresses
    _re.compile(r"\b(?:tg|telegram|whatsapp|signal)\s*[:\-]\s*@?\S+"),  # messenger handles
]


def norm_claim(s):
    """Canonical form of a claim string for rubric lookup.

    Lowercased, contact details removed. Scraped headlines occasionally carry a
    person's email, a messenger handle, or a profile URL; those never decide a
    role or location verdict, and stripping them on BOTH the stored and the
    incoming side means the rubric can ship without them.
    """
    t = (s or "").strip().lower()
    for pat in _CONTACT:
        t = pat.sub(" ", t)
    # labels whose value was just removed ("email :", "contact -") and the
    # separator runs left behind
    t = _re.sub(r"\b(?:e-?mail|contact|dm)\s*[:\-]\s*(?=[|·]|$)", " ", t)
    t = _re.sub(r"\s*[|·]\s*(?=[|·])", " ", t)
    t = _re.sub(r"\s+", " ", t)
    return t.strip(" |-·")

