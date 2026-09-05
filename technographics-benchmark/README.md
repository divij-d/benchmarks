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
export ANTHROPIC_API_KEY=...        # optional

# specific companies
python -m src.collect extern.com atlascard.com

# or the panel
python -m src.collect_panel --limit 20

python -m src.normalize_llm --provider anthropic   # optional
python -m src.score
python -m src.report
```

- `--limit N` - first N panel companies; omit for all 1,004.
- `--provider` - `anthropic`, `openai`, `openrouter` or `deepseek`; `--model` overrides the default. Without this step, name merging is limited to the built-in tables, so scores may read lower than reality for companies outside the panel.
- `--force` - on `collect`, re-fetch cached responses; on `normalize_llm`, redo companies that already have LLM merges.
- `--majority` - on `report`, require a strict majority (3 of 5) instead of 2 of 5 for consensus.

A provider with no key is skipped and recorded as not run for that company. Consensus needs at least two providers. `score` and `report` work on everything collected so far.
