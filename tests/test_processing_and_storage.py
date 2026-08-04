from __future__ import annotations

from pathlib import Path

import mongomock

from app.processing import TweetProcessingPipeline
from app.scraper.models import TweetRecord
from app.signals import KeywordSignalAggregator
from app.storage import ParquetExporter, TweetRepository


def _record(tweet_id: str, content: str, keyword: str = "#nifty50", *, likes: int = 5) -> TweetRecord:
    return TweetRecord(
        tweet_url=f"https://x.com/demo/status/{tweet_id}",
        tweet_id=tweet_id,
        username="TraderOne",
        display_name="Trader One",
        timestamp_utc="2026-08-04T12:00:00+00:00",
        content=content,
        replies=2,
        reposts=3,
        likes=likes,
        views=25,
        mentions=["@Desk"],
        hashtags=[keyword],
        keyword=keyword,
        provider="twscrape",
        raw_metadata={"lang": "hi"},
    )


def test_processing_pipeline_normalizes_unicode_and_builds_vectors() -> None:
    pipeline = TweetProcessingPipeline(vector_size=8, top_term_count=3, max_workers=1)
    record = _record("1", "निफ्टी\u200b  bullish   breakout  @Desk")

    processed = pipeline.process_records([record])[0]

    assert processed.normalized_content == "निफ्टी bullish breakout @Desk"
    assert processed.username_normalized == "traderone"
    assert processed.mentions == ["@desk"]
    assert processed.hashtags == ["#nifty50"]
    assert processed.indian_script_ratio > 0
    assert len(processed.feature_vector) == 8
    assert processed.sentiment_score > 0


def test_repository_deduplicates_and_updates_existing_tweets() -> None:
    repository = TweetRepository(client=mongomock.MongoClient(), database_name="test-processing-storage-1")
    pipeline = TweetProcessingPipeline(vector_size=8, top_term_count=3, max_workers=1)

    first = pipeline.process_records([_record("1", "Bullish breakout on nifty50", likes=4)])
    second = pipeline.process_records([_record("1", "Bullish breakout on nifty50", likes=15)])

    first_result = repository.upsert_tweets(first, run_id="run-1")
    second_result = repository.upsert_tweets(second, run_id="run-2")

    row_count = repository.tweets.count_documents({})
    row = repository.tweets.find_one({"tweet_key": first[0].tweet_key})

    assert first_result.inserted_count == 1
    assert second_result.inserted_count == 0
    assert second_result.updated_count == 1
    assert row_count == 1
    assert row is not None
    assert row["likes"] == 15
    assert row["times_seen"] == 2


def test_repository_deduplicates_duplicate_rows_inside_one_batch() -> None:
    repository = TweetRepository(client=mongomock.MongoClient(), database_name="test-processing-storage-2")
    pipeline = TweetProcessingPipeline(vector_size=8, top_term_count=3, max_workers=1)

    first = pipeline.process_records([_record("1", "Bullish breakout on nifty50", likes=4)])[0]
    duplicate = pipeline.process_records([_record("1", "Bullish breakout on nifty50", likes=7)])[0]
    duplicate.keyword = "#sensex"

    result = repository.upsert_tweets([first, duplicate], run_id="run-1")

    row = repository.tweets.find_one({"tweet_key": first.tweet_key})

    assert result.inserted_count == 1
    assert result.updated_count == 0
    assert row is not None
    assert row["likes"] == 7
    assert row["times_seen"] == 1


def test_signal_aggregation_and_parquet_export_work_together(tmp_path: Path) -> None:
    pipeline = TweetProcessingPipeline(vector_size=8, top_term_count=3, max_workers=1)
    aggregator = KeywordSignalAggregator()
    exporter = ParquetExporter(
        tweets_path=tmp_path / "parquet" / "tweets",
        signals_path=tmp_path / "parquet" / "signals",
        chunk_size=2,
    )
    processed = pipeline.process_records(
        [
            _record("1", "Bullish breakout on nifty50", "#nifty50"),
            _record("2", "Bearish correction on nifty50", "#nifty50"),
            _record("3", "Sensex rebound looks strong", "#sensex"),
        ]
    )

    signals = aggregator.aggregate(processed, run_id="run-3")
    tweet_rows = exporter.write_tweets(processed, run_id="run-3")
    signal_rows = exporter.write_signals(signals, run_id="run-3")

    tweet_files = list((tmp_path / "parquet" / "tweets").rglob("*.parquet"))
    signal_files = list((tmp_path / "parquet" / "signals").rglob("*.parquet"))

    assert tweet_rows == 3
    assert signal_rows == len(signals)
    assert tweet_files
    assert signal_files
    assert all(
        signal.confidence_interval_low <= signal.composite_signal <= signal.confidence_interval_high
        for signal in signals
    )
