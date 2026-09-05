"""Run all five providers on one or more companies.

Usage:
    python -m src.collect vercel.com [more.com ...] [--force]

Cache-first: a company already captured for a provider is never re-queried
without --force. Writes data/results/companies/<domain>.json - the normalized
per-provider parse plus the cross-provider comparison. Run `python -m src.score`
afterwards to rebuild the panel aggregates.

Name normalization uses the committed alias and hierarchy tables. They were
built over the benchmark panel, so for other companies run
`python -m src.normalize_llm --provider <llm>` between collect and score to
merge leftover name variants with an LLM; without it scores may read lower
than reality."""

import json
import sys

from src.common import COMPANIES, ROOT, maybe_help
from src.providers import crustdata, theirstack, sumble, predictleads, builtwith
from src.normalize import build_comparison, load_extensions


NO_LLM_WARNING = ("\nNo LLM normalization: name merging is limited to the built-in tables, "
                  "so scores may read lower than reality for companies outside the "
                  "benchmark panel. Run `python -m src.normalize_llm --provider "
                  "anthropic|openai|openrouter|deepseek` before scoring.")


def _http_error(env):
    """'HTTP <status>: <snippet>' for a failed envelope, else ''. Errors are never
    cached, so a failed provider retries on the next run - but it must be visible
    now, or the provider silently scores as 'not matched'."""
    if not env or 200 <= (env.get("http_status") or 0) < 300:
        return ""
    return f"  !! HTTP {env.get('http_status')}: {json.dumps(env.get('response'))[:160]}"


def _first(env):
    """The envelope to report on: a list's first page, a Sumble bundle's techs/match."""
    if isinstance(env, list):
        return env[0] if env else None
    if isinstance(env, dict) and "match" in env:
        return env.get("techs") or env.get("match")
    return env


def run_company(domain: str, force: bool = False):
    """Fetch + parse every provider. A provider whose key is not set (and whose
    response is not cached) is skipped and recorded as NOT RUN for this company,
    so it drops out of the denominators instead of scoring a miss."""
    print(f"=== {domain} ===")
    parsed = []
    for mod in (crustdata, theirstack, sumble, predictleads, builtwith):
        name = mod.__name__.rsplit(".", 1)[-1]
        try:
            env = mod.fetch(domain, force=force)
        except RuntimeError as e:  # missing API key
            if "not set" not in str(e):
                raise
            print(f"  {name}: skipped (no key)")
            continue
        out = mod.parse(env)
        if out["meta"].get("skipped"):
            print(f"  {name}: skipped (no key)")
            continue
        first = _first(env)
        m = out["meta"]
        extra = ""
        if name == "sumble":
            extra = f" credits_used={m.get('credits_used_techs')} remaining={m.get('credits_remaining')}"
            if not out["matched"] and mod.exhausted(env):
                print(f"  {name}: skipped (credits exhausted)")
                continue  # credit exhaustion is NOT RUN, never a coverage miss
        elif name in ("theirstack", "predictleads"):
            extra = f" pages={m.get('pages')}"
        elif name == "builtwith":
            if m.get("errors"):
                extra = f"  !! {json.dumps(m['errors'])[:160]}"
            else:
                extra = (f" (noise filtered={m.get('noise_rows_filtered')}, "
                         f"paths={m.get('paths_used')}+{m.get('paths_skipped')} skipped)")
        print(f"  {name}: cache={(first or {}).get('_from_cache')} matched={out['matched']} "
              f"techs={len(out['techs'])}{extra} latency={m.get('latency_ms')}ms"
              + _http_error(first))
        parsed.append(out)

    if len(parsed) < 2:
        print(f"  !! only {len(parsed)} provider(s) ran for {domain} - consensus needs at least two. "
              "Nothing written; set more provider keys (or fix the errors above) and re-run.")
        return None
    ext = load_extensions(domain)
    comparison = build_comparison(domain, parsed, ext)
    if ext:
        print(f"  llm normalization: {comparison['normalization']['merges_applied']} merges, "
              f"{comparison['normalization']['parents_added']} umbrella links "
              f"({ext.get('provider')}/{ext.get('model')})")
    COMPANIES.mkdir(parents=True, exist_ok=True)
    out_path = COMPANIES / f"{domain}.json"
    out_path.write_text(json.dumps(comparison, indent=1))
    print(f"  -> {out_path.relative_to(ROOT)}  "
          f"(union={comparison['summary']['union_size']}, "
          f"corroborated={comparison['summary']['corroborated']})")
    return comparison


def main():
    domains = [a for a in sys.argv[1:] if not a.startswith("--")]
    force = "--force" in sys.argv
    if not domains:
        print(__doc__.strip())
        return 1
    failed = [d for d in domains if run_company(d, force=force) is None]
    if not all(load_extensions(d) for d in domains):
        print(NO_LLM_WARNING)
    if failed:
        print(f"\n!! not compared (fewer than two providers ran): {', '.join(failed)}. "
              "Set at least two provider keys and re-run; cached responses are reused.")
        return 1
    print("\nRun `python -m src.score` to aggregate everything collected so far.")
    return 0


if __name__ == "__main__":
    maybe_help(__doc__)
    sys.exit(main())
