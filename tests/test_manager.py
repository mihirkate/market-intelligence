from __future__ import annotations

import json
from pathlib import Path

import mongomock

from app.processing import TweetProcessingPipeline
from app.scraper.checkpoint import CheckpointStore
from app.scraper.engines.base import ScraperEngine
from app.scraper.manager import ScraperManager
from app.scraper.models import TweetRecord
from app.signals import KeywordSignalAggregator
from app.storage import DebugArtifactStore, ParquetExporter, RawTweetArchive, TweetRepository


class FakeScraperEngine(ScraperEngine):
    name = "fake-engine"

    def __init__(self, records_by_keyword: dict[str, list[TweetRecord]]) -> None:
        self.records_by_keyword = records_by_keyword

    def search(self, keyword: str, limit: int) -> list[TweetRecord]:
        return self.records_by_keyword.get(keyword, [])[:limit]


def _tweet(tweet_id: str, keyword: str, content: str, *, likes: int = 1) -> TweetRecord:
    return TweetRecord(
        tweet_url=f"https://x.com/demo/status/{tweet_id}",
        tweet_id=tweet_id,
        username=f"user_{tweet_id}",
        display_name=f"User {tweet_id}",
        timestamp_utc="2026-08-04T10:30:00+00:00",
        content=content,
        replies=1,
        reposts=1,
        likes=likes,
        views=10,
        keyword=keyword,
        provider="twscrape",
    )


def test_manager_reruns_collect_fresh_data_without_stopping_on_old_checkpoint(tmp_path: Path) -> None:
    repository = TweetRepository(client=mongomock.MongoClient(), database_name="test-manager-1")
    checkpoint_store = CheckpointStore(path=tmp_path / "checkpoint.json")
    pipeline = TweetProcessingPipeline(vector_size=8, top_term_count=4, max_workers=1)
    aggregator = KeywordSignalAggregator()
    exporter = ParquetExporter(
        tweets_path=tmp_path / "parquet" / "tweets",
        signals_path=tmp_path / "parquet" / "signals",
        chunk_size=10,
    )
    raw_archive = RawTweetArchive(output_dir=tmp_path / "raw")
    artifact_store = DebugArtifactStore(output_dir=tmp_path / "debug")

    first_engine = FakeScraperEngine(
        {
            "#nifty50": [
                _tweet("1", "#nifty50", "Bullish breakout on nifty50"),
                _tweet("2", "#nifty50", "Support building for nifty50"),
            ],
            "#sensex": [
                _tweet("3", "#sensex", "Bearish correction on sensex"),
                _tweet("4", "#sensex", "Sensex rebound looks strong"),
            ],
        }
    )

    first_manager = ScraperManager(
        keywords=("#nifty50", "#sensex"),
        discovery_limit=2,
        target_tweets=4,
        checkpoint_store=checkpoint_store,
        scraper_engine=first_engine,
        repository=repository,
        processing_pipeline=pipeline,
        signal_aggregator=aggregator,
        parquet_exporter=exporter,
        raw_archive=raw_archive,
        artifact_store=artifact_store,
    )
    first_summary = first_manager.run()

    second_engine = FakeScraperEngine(
        {
            "#nifty50": [
                _tweet("1", "#nifty50", "Bullish breakout on nifty50", likes=9),
                _tweet("5", "#nifty50", "Fresh momentum in nifty50"),
            ],
            "#sensex": [
                _tweet("3", "#sensex", "Bearish correction on sensex", likes=7),
                _tweet("6", "#sensex", "Sensex buyers returning"),
            ],
        }
    )

    second_manager = ScraperManager(
        keywords=("#nifty50", "#sensex"),
        discovery_limit=2,
        target_tweets=4,
        checkpoint_store=checkpoint_store,
        scraper_engine=second_engine,
        repository=repository,
        processing_pipeline=pipeline,
        signal_aggregator=aggregator,
        parquet_exporter=exporter,
        raw_archive=raw_archive,
        artifact_store=artifact_store,
    )
    second_summary = second_manager.run()

    checkpoint = json.loads((tmp_path / "checkpoint.json").read_text(encoding="utf-8"))
    total_rows = repository.tweets.count_documents({})
    raw_files = list((tmp_path / "raw").rglob("*.jsonl"))

    assert first_summary.tweets_collected == 4
    assert second_summary.tweets_collected == 2
    assert second_summary.tweets_updated == 2
    assert second_summary.urls_discovered == 4
    assert second_summary.raw_rows_written == 4
    assert total_rows == 6
    assert sorted(second_summary.keywords_processed) == ["#nifty50", "#sensex"]
    assert checkpoint["run_id"] == second_summary.run_id
    assert checkpoint["last_completed_at"] is not None
    assert raw_files


def test_manager_deduplicates_same_tweet_across_keywords_in_one_run(tmp_path: Path) -> None:
    repository = TweetRepository(client=mongomock.MongoClient(), database_name="test-manager-2")
    checkpoint_store = CheckpointStore(path=tmp_path / "checkpoint.json")
    pipeline = TweetProcessingPipeline(vector_size=8, top_term_count=4, max_workers=1)
    aggregator = KeywordSignalAggregator()
    exporter = ParquetExporter(
        tweets_path=tmp_path / "parquet" / "tweets",
        signals_path=tmp_path / "parquet" / "signals",
        chunk_size=10,
    )
    raw_archive = RawTweetArchive(output_dir=tmp_path / "raw")
    artifact_store = DebugArtifactStore(output_dir=tmp_path / "debug")

    duplicate = _tweet("100", "#nifty50", "Breakout on nifty and sensex")
    engine = FakeScraperEngine(
        {
            "#nifty50": [duplicate],
            "#sensex": [
                TweetRecord(
                    tweet_url=duplicate.tweet_url,
                    tweet_id=duplicate.tweet_id,
                    username=duplicate.username,
                    display_name=duplicate.display_name,
                    timestamp_utc=duplicate.timestamp_utc,
                    content=duplicate.content,
                    replies=duplicate.replies,
                    reposts=duplicate.reposts,
                    likes=duplicate.likes,
                    views=duplicate.views,
                    keyword="#sensex",
                    provider="twscrape",
                )
            ],
        }
    )

    manager = ScraperManager(
        keywords=("#nifty50", "#sensex"),
        discovery_limit=1,
        target_tweets=2,
        checkpoint_store=checkpoint_store,
        scraper_engine=engine,
        repository=repository,
        processing_pipeline=pipeline,
        signal_aggregator=aggregator,
        parquet_exporter=exporter,
        raw_archive=raw_archive,
        artifact_store=artifact_store,
    )
    summary = manager.run()

    total_rows = repository.tweets.count_documents({})

    assert summary.urls_discovered == 2
    assert summary.tweets_collected == 1
    assert summary.duplicate_tweets == 1
    assert summary.raw_rows_written == 2
    assert total_rows == 1
