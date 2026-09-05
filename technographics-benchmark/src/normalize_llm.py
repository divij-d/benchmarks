"""Extend name normalization per company with an LLM (optional).

    python -m src.normalize_llm --provider anthropic
    python -m src.normalize_llm --provider openrouter --model deepseek/deepseek-chat
    python -m src.normalize_llm --provider openai --domains stripe.com vercel.com
    python -m src.normalize_llm --provider deepseek --dry-run

Run after `src.collect` and before `src.score`. The committed alias and
hierarchy tables were adjudicated over the benchmark panel; for other companies
leftover name variants stay unmerged and scores read lower than reality. This
step mirrors the site's bring-your-own-key page: one call per company, given
the keys claimed by a single provider and the full key list, returns

  merges   singleton key -> the key it is the same product as
  parents  key -> umbrella key it is a component of

Only merges whose target exists in the company's key list are kept; parents
must both exist and the parent may not be a bare vendor umbrella (cruft list).
Results are written to data/normalization/llm_extensions/<domain>.json and the
company's comparison is rebuilt from the cached provider responses, so nothing
is re-billed. Companies with an extension file are skipped unless --force.
Keys: ANTHROPIC_API_KEY, OPENAI_API_KEY, OPENROUTER_API_KEY or DEEPSEEK_API_KEY."""

import argparse
import json
import re
import sys
import urllib.error
import urllib.request

from src.common import COMPANIES, key as _key, maybe_help
from src.normalize import EXT_DIR, CRUFT

PROVIDERS = {
    "anthropic": {"url": "https://api.anthropic.com/v1/messages",
                  "env": "ANTHROPIC_API_KEY", "model": "claude-sonnet-5"},
    "openai":    {"url": "https://api.openai.com/v1/chat/completions",
                  "env": "OPENAI_API_KEY", "model": "gpt-4o"},
    "deepseek":  {"url": "https://api.deepseek.com/v1/chat/completions",
                  "env": "DEEPSEEK_API_KEY", "model": "deepseek-chat"},
    "openrouter": {"url": "https://openrouter.ai/api/v1/chat/completions",
                   "env": "OPENROUTER_API_KEY", "model": "deepseek/deepseek-chat",
                   "headers": {"HTTP-Referer": "https://github.com",
                               "X-Title": "technographics-bench"}},
}

PROMPT = """These are normalized technology-name keys from different vendor APIs describing one company's tech stack.

Singleton keys (claimed by one provider only):
{singles}

All keys:
{all_keys}

Return ONLY a JSON object with two fields, no prose, no code fences:
{{"merges": {{...}}, "parents": {{...}}}}

merges: map each singleton key that is the SAME PRODUCT as another key under a different name (e.g. "apache-airflow" vs "airflow", "ms-teams" vs "microsoft-teams") to the key it should merge into (from the all-keys list). Near-certain duplicates only.

parents: map a key that is a COMPONENT OR SUB-PRODUCT of another key in the list to that umbrella key (e.g. "amazon-s3" -> "aws", "salesforce-service-cloud" -> "salesforce"). Both sides must be keys from the list. Never use a bare vendor name that sells unrelated product lines (microsoft, google, apple, amazon, cisco, oracle, ibm, adobe, sap) as a parent. Omit anything uncertain."""

MAX_SINGLES, MAX_KEYS = 400, 900


def _post(url, headers, body, timeout=120):
    r = urllib.request.Request(url, data=json.dumps(body).encode(), headers=headers, method="POST")
    try:
        with urllib.request.urlopen(r, timeout=timeout) as resp:
            return resp.status, json.loads(resp.read().decode())
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode()[:400]


def call(provider, model, prompt, api_key, post=_post):
    """-> raw assistant text. `post` is injectable so the caller can be tested."""
    cfg = PROVIDERS[provider]
    if provider == "anthropic":
        st, r = post(cfg["url"],
                     {"x-api-key": api_key, "anthropic-version": "2023-06-01",
                      "content-type": "application/json"},
                     {"model": model, "max_tokens": 4096,
                      "messages": [{"role": "user", "content": prompt}]})
        if st != 200:
            raise RuntimeError(f"{provider} HTTP {st}: {str(r)[:200]}")
        return "".join(b.get("text", "") for b in r.get("content", []))
    headers = {"authorization": f"Bearer {api_key}", "content-type": "application/json"}
    headers.update(cfg.get("headers", {}))
    st, r = post(cfg["url"], headers,
                 {"model": model, "temperature": 0,
                  "messages": [{"role": "user", "content": prompt}]})
    if st != 200:
        raise RuntimeError(f"{provider} HTTP {st}: {str(r)[:200]}")
    return r["choices"][0]["message"]["content"]


def parse(text):
    text = re.sub(r"^```(?:json)?\s*|```\s*$", "", (text or "").strip())
    try:
        o = json.loads(text)
    except json.JSONDecodeError:
        return {}, {}
    return (o.get("merges") or {}), (o.get("parents") or {})


def key_sets(comparison):
    """Per-provider sets of directly detected keys (no rollup credit)."""
    sets = {p: set() for p in comparison["providers"]}
    for r in comparison["rows"]:
        for p in r["found_by"]:
            if p in sets:
                sets[p].add(r["key"])
    return sets


def validate(merges, parents, universe):
    """Keep only what the site's BYOK page would apply."""
    ok_m = {f: t for f, t in merges.items()
            if isinstance(t, str) and f != t and f in universe and t in universe}
    ok_p = {c: p for c, p in parents.items()
            if isinstance(p, str) and c != p and c in universe and p in universe and p not in CRUFT}
    return ok_m, ok_p


def extend(domain, comparison, provider, model, api_key, dry_run=False, post=_post):
    ran = [p for p in comparison["providers"] if comparison["matched"].get(p)]
    if len(ran) < 2:
        return None, "needs 2+ matched providers"
    sets = key_sets(comparison)
    universe = sorted(set().union(*(sets[p] for p in ran)))
    singles = [k for k in universe if sum(k in sets[p] for p in ran) == 1]
    if not singles:
        return None, "no singleton keys"
    prompt = PROMPT.format(singles="\n".join(singles[:MAX_SINGLES]),
                           all_keys="\n".join(universe[:MAX_KEYS]))
    if dry_run:
        return None, f"{len(singles)} singletons of {len(universe)} keys (dry run)"
    text = call(provider, model, prompt, api_key, post=post)
    merges, parents = validate(*parse(text), set(universe))
    ext = {"domain": domain, "provider": provider, "model": model,
           "merges": merges, "parents": parents, "raw_response": text}
    EXT_DIR.mkdir(parents=True, exist_ok=True)
    (EXT_DIR / f"{domain}.json").write_text(json.dumps(ext, indent=1))
    return ext, f"{len(merges)} merges, {len(parents)} umbrella links"


def main(argv=None):
    ap = argparse.ArgumentParser(add_help=False)
    ap.add_argument("--provider", required=True, choices=sorted(PROVIDERS))
    ap.add_argument("--model", help="override the provider default")
    ap.add_argument("--domains", nargs="*", help="default: every collected company")
    ap.add_argument("--force", action="store_true", help="redo companies that already have an extension")
    ap.add_argument("--dry-run", action="store_true", help="build prompts, call nothing")
    a = ap.parse_args(argv)
    cfg = PROVIDERS[a.provider]
    model = a.model or cfg["model"]
    api_key = None if a.dry_run else _key(cfg["env"])

    from src.collect import run_company   # rebuilds a comparison from cache
    files = ([COMPANIES / f"{d}.json" for d in a.domains] if a.domains
             else sorted(COMPANIES.glob("*.json")))
    done = skipped = 0
    for f in files:
        if not f.exists():
            print(f"{f.stem}: not collected yet - run `python -m src.collect {f.stem}` first")
            continue
        if not a.force and (EXT_DIR / f.name).exists():
            skipped += 1
            continue
        c = json.loads(f.read_text())
        try:
            ext, note = extend(f.stem, c, a.provider, model, api_key, dry_run=a.dry_run)
        except Exception as e:
            print(f"{f.stem}: FAILED {e}")
            continue
        print(f"{f.stem}: {note}")
        if ext:
            run_company(f.stem)
            done += 1
    print(f"\n{done} companies extended, {skipped} already had extensions"
          + ("" if a.dry_run else ". Run `python -m src.score` to rebuild the aggregates."))
    return 0


if __name__ == "__main__":
    maybe_help(__doc__)
    sys.exit(main())
