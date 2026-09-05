# Technographics Benchmark

Open benchmark for evaluating company technographics providers.

## Usage

```bash
export CRUSTDATA_API_KEY=...
export THEIRSTACK_API_KEY=...
export SUMBLE_API_KEY=...
export PREDICT_LEADS_KEY=...
export PREDICT_LEADS_TOKEN=...
export BUILTWITH_API_KEY=...
export ANTHROPIC_API_KEY=...                  # optional, for LLM name normalization

python -m src.collect vercel.com stripe.com   # any companies
python -m src.collect_panel --smoke           # 20-company sample of the panel
python -m src.collect_panel                   # full panel
python -m src.normalize_llm --provider anthropic   # optional; see below
python -m src.score
python -m src.report                          # add --majority for the strict 3-of-5 bar
```

The LLM step also accepts `openai`, `openrouter` and `deepseek` (keys
`OPENAI_API_KEY`, `OPENROUTER_API_KEY`, `DEEPSEEK_API_KEY`; `--model` overrides
the default). **Without it, name merging is limited to the built-in tables, so
scores may read lower than reality for companies outside the benchmark panel.**

## Layout

```
data/panel/panel.json            the eval set: 1,005 companies with stratum, source URL, flags
data/panel/wikidata_established.json  committed Wikidata snapshot the established stratum is drawn from
data/normalization/              alias table, hierarchy, category crosswalk, bucket tables (committed)
data/normalization/llm_extensions/   per-company LLM merges from src.normalize_llm (gitignored)
data/raw/                        cached provider responses (gitignored)
data/results/                    per-company comparisons, aggregates, summary (gitignored)
src/providers/                   one fetch/parse module per provider
```

## Panel

| Stratum | Companies | Source |
|---|---:|---|
| SMB software (10-50 employees) | 401 | YC directory |
| Mid-size tech (51-500 employees) | 261 | YC directory |
| Established (500+ employees, all industries) | 343 | Wikidata |

Sources are provider-neutral: the panel was never drawn from any benchmarked
provider's own index. Every provider was run on every company.

## Name normalization

Providers name the same technology differently, and some report components
where others report the umbrella product. Before comparison every name is
lower-cased, hyphenated and passed through the committed tables under
`data/normalization/`:

| File | Shape | Effect |
|---|---|---|
| `aliases.json` | `{"variant": "canonical"}` | merges two names for one technology |
| `hierarchy.json` | `{"parents": {"child": "parent"}, "cruft_suspects": [...]}` | a provider reporting any child counts as finding the parent; cruft suspects (bare vendor umbrellas) get no such credit |
| `category_crosswalk.json` | provider category -> bucket | maps each provider's own category vocabulary onto six shared buckets |
| `llm_bucket_fallback.json`, `confirmed_bucket_overrides.json` | `{"tech": "bucket"}` | category for techs no provider labelled, used by the per-category view |

These tables were adjudicated by an LLM over the panel's raw names, so they
cover the panel well. For companies outside it, `python -m src.normalize_llm`
makes one LLM call per company (the singleton keys plus the full key list),
keeps only merges whose target exists in that company's list and umbrella
links whose parent is not a bare vendor name, writes them to
`data/normalization/llm_extensions/<domain>.json`, and rebuilds the comparison
from the cached responses. This is the same method as the site's
bring-your-own-key page. Score and report state how many companies had the
LLM step applied.

## Notes

- Consensus, not ground truth. A tech counts when at least 2 of 5 providers
  report it (or a strict majority of 3 with `--majority`). No claim-level
  verification has been performed.
- One panel company is flagged `defunct` (merged into another entity) and is
  excluded from every provider's aggregates: a live-index provider must never
  lose score for correctly not carrying a dead company.
- A Crustdata match row with `company_data: null` is treated as not matched.
- Sumble publishes no dates, so it cannot be scored on the fresh track.
- Latency is client-observed wall time per company, measured identically for
  all providers.
- A provider that fails a company for credit reasons is recorded as not run
  there and drops out of that company's denominators only.
