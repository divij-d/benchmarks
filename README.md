# Crustdata Benchmarks

Open benchmarks for evaluating people search APIs.

## Benchmarks

| Benchmark | Queries | Tracks | Description |
|-----------|---------|--------|-------------|
| [People Semantic Search](people-semantic-search-benchmark/) | 100 | Retrieval | Find people by role, location, seniority, industry, and work history from natural-language queries |

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

## Implementing Your Own Searcher

Add a module under `src/searchers/` exposing `fetch` and `parse`:

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

## Requirements

- Python 3.9+ (standard library only - no third-party dependencies)
- LLM API key (for grading)
- Search API credentials

## License

MIT
