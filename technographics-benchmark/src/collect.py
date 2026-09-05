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


def run_company(domain: str, force: bool = False):
    print(f"=== {domain} ===")

    cd_env = crustdata.fetch(domain, force=force)
    cd = crustdata.parse(cd_env)
    print(f"  crustdata: cache={cd_env['_from_cache']} matched={cd['matched']} "
          f"techs={len(cd['techs'])} latency={cd_env['latency_ms']}ms" + _http_error(cd_env))

    ts_envs = theirstack.fetch(domain, force=force)
    ts = theirstack.parse(ts_envs)
    print(f"  theirstack: cache={ts_envs[0]['_from_cache']} matched={ts['matched']} "
          f"techs={len(ts['techs'])} pages={ts['meta'].get('pages')} "
          f"latency={ts['meta'].get('latency_ms')}ms" + _http_error(ts_envs[0]))

    sb_bundle = sumble.fetch(domain, force=force)
    sb = sumble.parse(sb_bundle)
    sb_exhausted = not sb["matched"] and sumble.exhausted(sb_bundle)
    sb_env = sb_bundle.get("techs") or sb_bundle.get("match") or {}
    print(f"  sumble: cache={sb_env.get('_from_cache')} matched={sb['matched']} "
          f"techs={len(sb['techs'])} credits_used={sb['meta'].get('credits_used_techs')} "
          f"remaining={sb['meta'].get('credits_remaining')}"
          + ("  [SKIPPED: credits exhausted]" if sb_exhausted else "") + _http_error(sb_env))

    pl_envs = predictleads.fetch(domain, force=force)
    pl = predictleads.parse(pl_envs)
    print(f"  predictleads: cache={pl_envs[0]['_from_cache']} matched={pl['matched']} "
          f"techs={len(pl['techs'])} pages={pl['meta'].get('pages')} "
          f"latency={pl['meta'].get('latency_ms')}ms" + _http_error(pl_envs[0]))

    # a credit-exhausted provider is recorded as NOT RUN for this company, so
    # it drops out of the denominators instead of scoring a coverage miss
    parsed = [cd, ts, pl] if sb_exhausted else [cd, ts, sb, pl]

    bw_env = builtwith.fetch(domain, force=force)
    bw = builtwith.parse(bw_env)
    if bw["meta"].get("skipped"):
        print("  builtwith: skipped (no key)")
    else:
        if bw["meta"].get("errors"):
            print(f"  builtwith: matched=False  !! {json.dumps(bw['meta']['errors'])[:160]}")
        print(f"  builtwith: cache={bw_env['_from_cache']} matched={bw['matched']} "
              f"techs={len(bw['techs'])} "
              f"(noise filtered={bw['meta'].get('noise_rows_filtered')}, "
              f"paths={bw['meta'].get('paths_used')}+{bw['meta'].get('paths_skipped')} skipped) "
              f"latency={bw['meta'].get('latency_ms')}ms")
        parsed.append(bw)

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
    for d in domains:
        run_company(d, force=force)
    if not all(load_extensions(d) for d in domains):
        print(NO_LLM_WARNING)
    print("\nRun `python -m src.score` to rebuild the panel aggregates.")
    return 0


if __name__ == "__main__":
    maybe_help(__doc__)
    sys.exit(main())
