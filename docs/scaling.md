# Scaling Notes

## Current Performance Strategy

- Scrape jobs are bounded by `MAX_TWEETS_PER_RUN`, so one run cannot grow without limit.
- Processing uses a small `ThreadPoolExecutor` for parallel normalization.
- MongoDB writes deduplicate by `tweet_key`, so repeated runs do not multiply storage linearly.
- Parquet export writes chunked files instead of one large file.
- Dashboard queries use bounded result sets and downsampling for visualization.

## 10x Data Volume Strategy

If tweet volume grows from roughly `2,000/day` to `20,000/day`, the current path scales by:

1. Increasing cron frequency only if the X account can support it.
2. Keeping per-run batches bounded so memory stays predictable.
3. Relying on MongoDB indexes for recent-window queries and dedupe.
4. Writing many small parquet chunks instead of rewriting historical files.
5. Using report queries that aggregate in MongoDB before data reaches Python.

## Benchmark Command

Run:

```bash
source .venv/bin/activate
python -m app.reporting.performance
```

This writes `reports/performance_benchmark.json`.

The benchmark uses:

- synthetic tweet records
- the real processing pipeline
- the real signal aggregator
- `mongomock` for isolated storage benchmarking
- real parquet chunk writing

The goal is not to model network latency. The goal is to measure how the local
pipeline behaves as record count increases.
