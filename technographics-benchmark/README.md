# Technographics Benchmark

Open benchmark for evaluating company technographics providers.

## Setup

```bash
export CRUSTDATA_API_KEY=...
export THEIRSTACK_API_KEY=...
export SUMBLE_API_KEY=...
export PREDICT_LEADS_KEY=...
export PREDICT_LEADS_TOKEN=...
export BUILTWITH_API_KEY=...
export ANTHROPIC_API_KEY=...        # optional, for the LLM name-normalization step
```

Python 3.9+, standard library only. Keys can also live in a gitignored `.env`
in this folder. Any provider whose key is unset is skipped: its data is not
fetched and it is recorded as not run for that company, so it drops out of the
denominators rather than scoring a miss. Consensus needs at least two
providers; a company where fewer than two ran is reported as an error and no
comparison is written. Every response is cached under `data/raw/`, so
re-running anything is free.

## Run specific companies

```bash
python -m src.collect extern.com atlascard.com
python -m src.normalize_llm --provider anthropic   # optional
python -m src.score
python -m src.report
```

## Run the panel

```bash
python -m src.collect_panel --limit 20     # first 20 panel companies; omit for all 1,004
python -m src.normalize_llm --provider anthropic   # optional
python -m src.score
python -m src.report                       # add --majority for the strict 3-of-5 bar
```

`collect` and `collect_panel` only differ in where the company list comes
from: your arguments, or `data/panel/panel.json` (failures logged to
`data/results/panel_run_failures.json` and retried next run). Both write one comparison file per company to `data/results/companies/`.
Every step after that works on whatever has been collected so far:
`normalize_llm` makes one LLM call per company to merge tech-name variants the
built-in tables missed (also `openai`, `openrouter`, `deepseek`; `--model`
overrides the default), `score` aggregates, `report` prints the tables.
**Without the LLM step, name merging is limited to the built-in tables, so
scores may read lower than reality for companies outside the benchmark
panel.** Small runs are noisy; the published numbers average 1,004 companies.

## Layout

```
data/panel/panel.json            the eval set: 1,004 companies with stratum, source URL, flags
data/panel/wikidata_established.json  committed Wikidata snapshot the established stratum is drawn from
data/normalization/              alias table, hierarchy, category mapping, LLM tech categories (committed)
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
| Established (500+ employees, all industries) | 342 | Wikidata |

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
| `category_crosswalk.json` | provider category -> bucket, plus `tech_overrides` `{"tech": "bucket"}` | maps each provider's own category vocabulary onto six shared buckets; the overrides pin audit-confirmed corrections ahead of the vote |
| `llm_tech_categories.json` | `{"tech": "bucket"}` | LLM-assigned category for techs no provider labelled anywhere in the panel, so unconfirmed claims of them still count against per-category precision |

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
- One originally selected company had merged into another entity; it was
  removed from the panel so that a live-index provider never loses score for
  correctly not carrying a dead company.
- A Crustdata match row with `company_data: null` is treated as not matched.
- Sumble publishes no dates, so it cannot be scored on the fresh track.
- Latency is client-observed wall time per company, measured identically for
  all providers.
- A provider that was not run on a company (no key, or credit exhaustion) is
  recorded as not run there and drops out of that company's denominators only.
