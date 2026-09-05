# Crustdata Benchmarks

Open benchmarks for evaluating people search and company data APIs.

## Benchmarks

| Benchmark | Queries | Tracks | Description |
|-----------|---------|--------|-------------|
| [People Semantic Search](people-semantic-search-benchmark/) | 100 | Retrieval | Find people by role, location, seniority, industry, and work history from natural-language queries |
| [Technographics](technographics-benchmark/) | 1,004 companies | All-time, Fresh | Which provider knows a company's tech stack: five providers scored on recall, precision, and F1 against cross-provider consensus |

## People Semantic Search Results

| Searcher | Strict pass | R@1 | R@10 | Latency p50 | Fields / record |
|---|---:|---:|---:|---:|---:|
| **crustdata** | **95.5%** | 95.0% | 100.0% | 3.7s | 80 |
| exa | 83.7% | 88.0% | 98.0% | 3.8s | 25 |
| parallel | 83.7% | 90.0% | 95.0% | 687s* | 10† |

Sorted by strict pass. 100 scored queries, k=10.

- **Strict pass** - % of returned people satisfying every scored clause of their query.
- **R@1 / R@10** - % of queries with a fully passing result at rank 1 / in the top 10.
- **Latency p50** - median per-query wall time. *\*Parallel's is async Task-API duration, not blocking-fetch time.*
- **Fields / record** - median populated field types per record (response shape). *†Parallel's schema is authored by us. If a schema is not authored, Parallel provides answers in natural language rather than structured fields.*

## Technographics Results

Five providers run on the same 1,004 companies (SMB software, mid-size tech, and established strata). There is no ground truth for a company's stack, so a tech counts as **consensus** when at least 2 of the 5 providers independently report it. Recall is the share of a company's consensus techs a provider reports; precision is the share of the provider's own claims that other providers confirm.

**All-time** - every tech a provider has ever detected

| Provider | F1 | Recall | Precision | Matched | Techs / company | Latency p50 |
|---|---:|---:|---:|---:|---:|---:|
| **crustdata** | **65.9%** | 57.9% | **82.2%** | 96.1% | 43 | 1.6s |
| predictleads | 62.1% | **75.1%** | 54.1% | 96.8% | 91 | 1.4s |
| theirstack | 42.3% | 36.7% | 55.3% | 81.3% | 46 | **1.0s** |
| builtwith | 35.3% | 68.5% | 24.8% | **99.4%** | 198 | 1.8s |
| sumble | 30.6% | 14.8% | 80.3% | 91.7% | 13 | 1.4s |

**Fresh** - restricted to techs seen in the last 12 months

| Provider | F1 | Recall | Precision |
|---|---:|---:|---:|
| **crustdata** | **76.8%** | 72.3% | **81.3%** |
| predictleads | 55.3% | 67.9% | 47.7% |
| builtwith | 48.4% | **75.3%** | 37.1% |
| theirstack | 42.4% | 29.1% | 55.7% |
| sumble | n/a* | n/a* | n/a* |

Sorted by F1. Per-company scores averaged across the panel; a company counts toward a provider's recall only when it has at least 5 consensus techs, and toward precision only when the provider made at least 5 claims there.

- **F1** - harmonic mean of recall and precision, per company.
- **Matched** - % of panel companies the provider returned a record for.
- **Techs / company** - median technologies reported per matched company.
- **Latency p50** - median client-observed wall time per company, measured identically for all providers.
- *\*Sumble publishes no dates, so it cannot be scored on the fresh track.*
- Under the strict 3-of-5 bar (`python -m src.report --majority`) Crustdata still leads on F1; the order below it changes.

See [technographics-benchmark/](technographics-benchmark/) for the panel, normalization tables, and methodology notes.

## Quick Start

```bash
git clone https://github.com/crustdata/benchmarks.git
cd benchmarks
```

### People Semantic Search Benchmark

```bash
cd people-semantic-search-benchmark

export CRUSTDATA_API_KEY="your-key"
export EXA_API_KEY="your-key"
export PARALLEL_API_KEY="your-key"
export OPENROUTER_API_KEY="your-key"

python -m src.collect crustdata exa --limit 10
python -m src.collect_parallel --limit 10
python -m src.resume_parallel
python -m src.judge --provider openrouter
python -m src.score
python -m src.report
```

The judge also supports `anthropic`, `openai`, and `deepseek` as providers.

### Technographics Benchmark

```bash
cd technographics-benchmark

export CRUSTDATA_API_KEY="your-key"
export THEIRSTACK_API_KEY="your-key"
export SUMBLE_API_KEY="your-key"
export PREDICT_LEADS_KEY="your-key"
export PREDICT_LEADS_TOKEN="your-token"
export BUILTWITH_API_KEY="your-key"
export ANTHROPIC_API_KEY="your-key"     # optional, for LLM name normalization
```

Specific companies:

```bash
python -m src.collect extern.com atlascard.com
python -m src.normalize_llm --provider anthropic   # optional
python -m src.score
python -m src.report
```

The panel:

```bash
python -m src.collect_panel --limit 20     # omit --limit for all 1,004
python -m src.normalize_llm --provider anthropic   # optional
python -m src.score
python -m src.report
```

`score` and `report` work on everything collected so far. Every response is cached under `data/raw/`, so re-runs are free. The LLM step (also `openai`, `openrouter`, `deepseek`) merges leftover tech-name variants per company; without it, scores may read lower than reality for companies outside the benchmark panel.

## Implementing Your Own Searcher or Provider

### People search

Add a module under `people-semantic-search-benchmark/src/searchers/` exposing `fetch` and `parse`:

```python
def fetch(query: str, k: int = 10) -> dict:
    return my_api.search(query, limit=k)

def parse(envelope: dict) -> dict:
    return {"results": [
        {"name": r["name"], "title": r["title"],
         "company": r["company"], "location": r["location"]}
        for r in envelope["results"]
    ]}
```

The `fetch` method captures the raw response envelope; `parse` maps it to the
common result card that judging and scoring consume.

### Technographics

Add a module under `technographics-benchmark/src/providers/` with the same two functions, keyed by domain:

```python
def fetch(domain: str, force: bool = False) -> dict:
    return http_json("my-provider", domain, MY_URL, headers=..., body={"domain": domain})

def parse(envelope: dict) -> dict:
    return {"provider": "my-provider", "matched": True, "meta": {"latency_ms": envelope["latency_ms"]},
            "techs": [{"raw_name": t["name"], "categories": t.get("categories", []),
                       "first_seen": t.get("first_seen"), "last_seen": t.get("last_seen")}
                      for t in envelope["response"]["technologies"]]}
```

Tech names are lower-cased, hyphenated and passed through the committed alias and
hierarchy tables (plus the optional per-company LLM step) before comparison, so a
new provider is scored on the same consensus as the others.
`last_seen` is what places a claim on the fresh track.

## Requirements

- Python 3.9+ (standard library only - no third-party dependencies)
- LLM API key (people benchmark grading; optional name normalization in technographics)
- Search and data API credentials

## License

MIT
