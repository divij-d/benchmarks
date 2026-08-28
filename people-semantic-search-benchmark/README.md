# People Semantic Search Benchmark

Open benchmark for evaluating natural-language people search.

## Usage

```bash
export CRUSTDATA_API_KEY=...
export EXA_API_KEY=...
export PARALLEL_API_KEY=...
export OPENROUTER_API_KEY=...

python -m src.collect crustdata exa --limit 10
python -m src.collect_parallel --limit 10
python -m src.resume_parallel
python -m src.judge --provider openrouter
python -m src.score
python -m src.report
```
