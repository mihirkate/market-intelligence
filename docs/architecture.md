# Architecture

## Runtime Flow

1. `cron` runs `python -m app.scheduler.job`.
2. `app.scheduler.job` acquires a filesystem lock so overlapping runs are skipped.
3. `app.scraper.manager.ScraperManager` loads the checkpoint and exits early if a cooldown is active.
4. `app.scraper.engines.twscrape_engine.TwscrapeEngine` fetches recent tweets for:
   - `#nifty50`
   - `#sensex`
   - `#intraday`
   - `#banknifty`
5. Raw tweets are archived as JSONL in `data/raw/`.
6. `app.processing.pipeline.TweetProcessingPipeline` normalizes text and creates hashed TF-IDF-style vectors plus custom market features.
7. `app.storage.mongo_store.TweetRepository` deduplicates and upserts processed tweets into MongoDB.
8. `app.storage.parquet_exporter.ParquetExporter` writes append-only parquet chunks.
9. `app.signals.aggregation.KeywordSignalAggregator` produces keyword-level trading signals with confidence intervals.
10. Reporting modules refresh:
   - `reports/data_collection_status.json`
   - `reports/processing_report.json`
   - `reports/analysis_summary.json`

## Design Choices

- `twscrape` is the only active collector path.
- Collection runs are short-lived and cron-driven instead of long-running.
- Checkpoints store job state and cooldown timing.
- MongoDB is the operational warehouse.
- Parquet is the analytics export format.
- Reports are generated as JSON so the dashboard and API can reuse them.

## Analysis Features

Each processed tweet stores:

- normalized text
- mentions and hashtags
- hashed TF-IDF-style vector
- bullish term hits
- bearish term hits
- keyword match score
- engagement score
- sentiment score
- confidence score

Keyword-level signals aggregate these tweet features into:

- average sentiment
- average engagement
- bullish ratio
- bearish ratio
- composite signal
- confidence interval
- top terms
