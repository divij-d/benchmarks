"""BuiltWith Domain API: GET /v23/api.json?KEY=...&LOOKUP={domain}.

Full profile in one response. Results[0].Result.Paths[] holds one entry per
(Domain, SubDomain, Url), each with its own Technologies[] (Name, Tag,
Categories[], FirstDetected/LastDetected in epoch ms, Parent).

- Paths: root plus non-infrastructure subdomains; dev/staging/tracking
  subdomains are skipped (stale-tech noise). The same tech on several paths
  merges, keeping earliest FirstDetected / latest LastDetected.
- Noise: BuiltWith emits signal-class rows that are not technologies
  (languages, currencies, copyright years, link mentions, CrUX ranks, ads.txt
  rows). Filtered by tag + name pattern; the raw cache keeps everything and
  the parse records how many rows were filtered.
- Domains on BuiltWith's published Ignore List are recorded as not indexed
  without spending a lookup."""

import json
import re
import time
import urllib.request

from src.common import key, cached, write_cache, RAW_DIR

API = "https://api.builtwith.com/v23/api.json"
IGNORE_LIST_URL = "https://api.builtwith.com/ignoresv1/api.json"   # free, no key

_SKIP_SUBDOMAIN = re.compile(
    r"(^|\.)?(staging|preprod|prod|dev\d*|development|sandbox|test|"
    r"legacy-|trk\.|click\.|webdav|kibana|octopus|generic-haproxy|mail\.)",
    re.IGNORECASE)
_NOISE_TAGS = {"language", "payment", "copyright", "link", "robots"}
_NOISE_NAME = re.compile(
    r"(HREF LANG$|^Copyright Year |^CrUX |^Cloudflare Radar|^Domain Not Resolving$"
    r"|Reseller$|Direct$|^COVID-19$|^Artificial Intelligence$|^Gambling Content$"
    r"|^Ads\.txt$|^Cart Functionality$|^\d+ to \d+ ccTLD Redirects$"
    r"|^Common ?Crawl)")

_IGNORE_CACHE = RAW_DIR / "builtwith" / "_ignore_list.json"


def ignore_list():
    """BuiltWith's published list of domains they refuse to index. Cached
    locally; delete the cache file to refresh."""
    if _IGNORE_CACHE.exists():
        return set(json.loads(_IGNORE_CACHE.read_text()))
    try:
        with urllib.request.urlopen(IGNORE_LIST_URL, timeout=60) as r:
            domains = json.loads(r.read().decode())
        _IGNORE_CACHE.parent.mkdir(parents=True, exist_ok=True)
        _IGNORE_CACHE.write_text(json.dumps(domains))
        return set(domains)
    except Exception:
        return set()


def fetch(domain: str, force: bool = False):
    if not force:  # cache first, so re-parsing needs no key
        hit = cached("builtwith", domain)
        if hit is not None:
            hit["_from_cache"] = True
            return hit
    api_key = key("BUILTWITH_API_KEY", required=False)
    if not api_key:
        return None  # collect.py reports 'skipped (no key)'
    if domain in ignore_list():
        return {"provider": "builtwith", "key": domain, "_from_cache": True,
                "latency_ms": 0, "response": {"Errors": [{
                    "Message": "domain is on BuiltWith's published Ignore List "
                               "(not indexed by provider)", "Code": -8}]}}
    url = f"{API}?KEY={api_key}&LOOKUP={domain}"
    t0 = time.time()
    with urllib.request.urlopen(urllib.request.Request(url), timeout=120) as r:
        payload = json.loads(r.read().decode())
        credits = {h: r.headers.get(h) for h in
                   ("X-API-CREDITS-AVAILABLE", "X-API-CREDITS-REMAINING",
                    "X-API-CREDITS-USED") if r.headers.get(h)}
    env = {
        "provider": "builtwith", "key": domain,
        "request": {"url": url.replace(api_key, "***"), "method": "GET", "body": None},
        "http_status": 200, "latency_ms": int((time.time() - t0) * 1000),
        "fetched_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "credit_headers": credits, "response": payload, "_from_cache": False,
    }
    write_cache("builtwith", domain, env)
    return env


def _ms_to_date(ms):
    return time.strftime("%Y-%m-%d", time.gmtime(ms / 1000)) if ms else None


def parse(env):
    out = {"provider": "builtwith", "matched": False, "techs": [], "meta": {}}
    if env is None:
        out["meta"]["skipped"] = "no BUILTWITH_API_KEY"
        return out
    errors = (env["response"] or {}).get("Errors") or []
    if errors:
        out["meta"] = {"errors": errors, "latency_ms": env.get("latency_ms")}
        return out
    results = (env["response"] or {}).get("Results") or []
    if not results:
        return out
    result = results[0].get("Result") or {}
    merged, filtered, paths_used, paths_skipped = {}, 0, 0, 0
    for path in result.get("Paths") or []:
        sub = path.get("SubDomain") or ""
        if sub and _SKIP_SUBDOMAIN.search(sub):
            paths_skipped += 1
            continue
        paths_used += 1
        for t in path.get("Technologies") or []:
            name = t.get("Name")
            if not name:
                continue
            if (t.get("Tag") or "").lower() in _NOISE_TAGS or _NOISE_NAME.search(name):
                filtered += 1
                continue
            rec = merged.setdefault(name, {
                "raw_name": name, "categories": t.get("Categories") or [],
                "tag": t.get("Tag"), "parent": t.get("Parent"),
                "sources": ["web signals"], "first_seen": None, "last_seen": None,
                "paths": [],
            })
            fd, ld = _ms_to_date(t.get("FirstDetected")), _ms_to_date(t.get("LastDetected"))
            if fd and (rec["first_seen"] is None or fd < rec["first_seen"]):
                rec["first_seen"] = fd
            if ld and (rec["last_seen"] is None or ld > rec["last_seen"]):
                rec["last_seen"] = ld
            if (sub or "root") not in rec["paths"]:
                rec["paths"].append(sub or "root")
    out["techs"] = list(merged.values())
    out["matched"] = bool(out["techs"])
    out["meta"] = {
        "latency_ms": env["latency_ms"],
        "credit_headers": env.get("credit_headers"),
        "paths_used": paths_used, "paths_skipped": paths_skipped,
        "noise_rows_filtered": filtered,
        "spend_estimate_usd": result.get("Spend"),
    }
    return out
