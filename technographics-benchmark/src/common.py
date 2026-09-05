"""Shared plumbing: paths, API keys, and a disk-cached HTTP helper.

Keys come from the environment first, then a gitignored .env at the benchmark
root. Every provider response is cached at data/raw/<provider>/<key>.json
BEFORE parsing and re-used unless --force is passed, so a company is never
re-billed. Cache files hold the full envelope (request, response, http_status,
latency_ms, fetched_at) so every published number traces back to a raw file."""

import json
import os
import sys
import time
import urllib.request
import urllib.error
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent          # benchmark root
DATA = ROOT / "data"
RAW_DIR = DATA / "raw"
PANEL = DATA / "panel" / "panel.json"
NORM_DIR = DATA / "normalization"
RESULTS = DATA / "results"
COMPANIES = RESULTS / "companies"

PROVIDERS = ["crustdata", "theirstack", "sumble", "predictleads", "builtwith"]


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
            f"{name} not set. export {name}=... before running this provider "
            f"(keys are intentionally not stored in this repo)."
        )
    return v


def cache_path(provider: str, cache_key: str) -> Path:
    safe = cache_key.replace("/", "_").replace(":", "_")
    return RAW_DIR / provider / f"{safe}.json"


def cached(provider: str, cache_key: str):
    p = cache_path(provider, cache_key)
    if p.exists():
        try:
            return json.loads(p.read_text())
        except json.JSONDecodeError:
            p.unlink()  # truncated by a crash mid-write; treat as absent
    return None


def write_cache(provider: str, cache_key: str, envelope: dict):
    p = cache_path(provider, cache_key)
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_suffix(".json.tmp")   # atomic: never leave a truncated envelope
    tmp.write_text(json.dumps(envelope, indent=1))
    tmp.replace(p)


def http_json(provider: str, cache_key: str, url: str, *, method="POST",
              headers=None, body=None, force=False, timeout=120):
    """POST/GET JSON with disk cache. Returns the envelope dict.

    `headers` may be a callable; it is only evaluated on a cache miss, so a
    cached company can be re-parsed and re-scored without any API key set."""
    if not force:
        hit = cached(provider, cache_key)
        if hit is not None:
            hit["_from_cache"] = True
            return hit
    if callable(headers):
        headers = headers()

    data = json.dumps(body).encode() if body is not None else None

    t0 = time.time()
    status, payload, retry_after = None, None, 0
    for attempt in range(4):  # 1 try + 3 retries on throttle / server errors
        req = urllib.request.Request(url, data=data, method=method)
        req.add_header("content-type", "application/json")
        for k, v in (headers or {}).items():
            req.add_header(k, v)
        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                status = resp.status
                payload = json.loads(resp.read().decode())
        except urllib.error.HTTPError as e:
            status = e.code
            try:
                retry_after = int(e.headers.get("Retry-After", 0))
            except Exception:
                retry_after = 0
            try:
                payload = json.loads(e.read().decode())
            except Exception:
                payload = {"error": str(e)}
        except Exception as e:  # timeouts, connection resets
            status = 0
            payload = {"error": str(e)}
        if status == 200 or (300 <= status < 429 and status != 408):
            break
        wait = max(2 ** attempt * 5, retry_after)
        print(f"    ! {provider} {status} on {cache_key} - retry {attempt + 1}/3 in {wait}s")
        time.sleep(wait)
    latency_ms = int((time.time() - t0) * 1000)

    envelope = {
        "provider": provider,
        "key": cache_key,
        "request": {"url": url, "method": method, "body": body},
        "http_status": status,
        "latency_ms": latency_ms,
        "fetched_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "response": payload,
        "_from_cache": False,
    }
    if 200 <= status < 300:  # never cache errors - a retry must hit the API
        write_cache(provider, cache_key, envelope)
    return envelope


def load_panel():
    return json.loads(PANEL.read_text())["companies"]


def maybe_help(doc):
    """Print the module docstring and exit if -h/--help was passed.

    These entry points act on the world - collect bills five providers - so an
    unrecognised flag must never fall through into the run."""
    if any(a in ("-h", "--help") for a in sys.argv[1:]):
        print((doc or "").strip())
        raise SystemExit(0)
