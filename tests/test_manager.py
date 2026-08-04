from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import mongomock

from app.processing import TweetProcessingPipeline
from app.scraper.checkpoint import CheckpointStore, ScrapeCheckpoint
from app.scraper.collection_status import CollectionStatusReporter
from app.scraper.engines.base import ScraperEngine, ScraperRateLimitError
from app.scraper.manager import ScraperManager
from app.scraper.models import TweetRecord
from app.signals import KeywordSignalAggregator
from app.storage import DebugArtifactStore, ParquetExporter, RawTweetArchive, TweetRepository


class FakeScraperEngine(ScraperEngine):
    name = "fake-engine"

    def __init__(self, records_by_keyword: dict[str, list[TweetRecord]]) -> None:
        self.records_by_keyword = records_by_keyword
        self.search_calls = 0

    def search(self, keyword: str, limit: int) -> list[TweetRecord]:
        self.search_calls += 1
        return self.records_by_keyword.get(keyword, [])[:limit]


class RateLimitedScraperEngine(ScraperEngine):
    name = "rate-limited-engine"

    def __init__(self, *, cooldown_until: datetime | None) -> None:
        self.cooldown_until = cooldown_until
        self.search_calls = 0

    def search(self, keyword: str, limit: int) -> list[TweetRecord]:
        self.search_calls += 1
        raise ScraperRateLimitError(
            "rate limited",
            cooldown_until=self.cooldown_until,
            account_states=[{"username": "demo", "locks": {"SearchTimeline": self.cooldown_until.isoformat() if self.cooldown_until else None}}],
        )


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


def _reporter(
    tmp_path: Path,
    *,
    repository: TweetRepository,
    checkpoint_store: CheckpointStore,
    required_keywords: tuple[str, ...],
    now_provider=None,
) -> CollectionStatusReporter:
    return CollectionStatusReporter(
        repository=repository,
        checkpoint_store=checkpoint_store,
        report_path=tmp_path / "reports" / "data_collection_status.json",
        required_keywords=required_keywords,
        now_provider=now_provider,
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
    reporter = _reporter(
        tmp_path,
        repository=repository,
        checkpoint_store=checkpoint_store,
        required_keywords=("#nifty50", "#sensex"),
    )

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
        collection_status_reporter=reporter,
        startup_jitter_min_seconds=0,
        startup_jitter_max_seconds=0,
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
        collection_status_reporter=reporter,
        startup_jitter_min_seconds=0,
        startup_jitter_max_seconds=0,
    )
    second_summary = second_manager.run()

    checkpoint = json.loads((tmp_path / "checkpoint.json").read_text(encoding="utf-8"))
    total_rows = repository.tweets.count_documents({})
    raw_files = list((tmp_path / "raw").rglob("*.jsonl"))
    report = json.loads((tmp_path / "reports" / "data_collection_status.json").read_text(encoding="utf-8"))

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
    assert report["total_unique_tweets_last_24_hours"] == 6
    assert report["assignment_data_collection_ready"] is False


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
    reporter = _reporter(
        tmp_path,
        repository=repository,
        checkpoint_store=checkpoint_store,
        required_keywords=("#nifty50", "#sensex"),
    )

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
        collection_status_reporter=reporter,
        startup_jitter_min_seconds=0,
        startup_jitter_max_seconds=0,
    )
    summary = manager.run()

    total_rows = repository.tweets.count_documents({})
    report = json.loads((tmp_path / "reports" / "data_collection_status.json").read_text(encoding="utf-8"))

    assert summary.urls_discovered == 2
    assert summary.tweets_collected == 1
    assert summary.duplicate_tweets == 1
    assert summary.raw_rows_written == 2
    assert total_rows == 1
    assert report["matched_keyword_counts_last_24_hours"] == [
        {"name": "#nifty50", "count": 1},
        {"name": "#sensex", "count": 1},
    ]


def test_manager_skips_run_when_checkpoint_cooldown_is_active(tmp_path: Path) -> None:
    repository = TweetRepository(client=mongomock.MongoClient(), database_name="test-manager-3")
    checkpoint_store = CheckpointStore(path=tmp_path / "checkpoint.json")
    active_cooldown_until = "2026-08-04T12:00:00+00:00"
    checkpoint_store.save(
        ScrapeCheckpoint(
            cooldown_until=active_cooldown_until,
            last_rate_limited_at="2026-08-04T11:00:00+00:00",
        )
    )
    engine = FakeScraperEngine({"#nifty50": [_tweet("1", "#nifty50", "Should not run")]})
    reporter = _reporter(
        tmp_path,
        repository=repository,
        checkpoint_store=checkpoint_store,
        required_keywords=("#nifty50",),
        now_provider=lambda: datetime(2026, 8, 4, 11, 30, tzinfo=timezone.utc),
    )

    manager = ScraperManager(
        keywords=("#nifty50",),
        discovery_limit=1,
        target_tweets=1,
        checkpoint_store=checkpoint_store,
        scraper_engine=engine,
        repository=repository,
        collection_status_reporter=reporter,
        now_provider=lambda: datetime(2026, 8, 4, 11, 30, tzinfo=timezone.utc),
        startup_jitter_min_seconds=0,
        startup_jitter_max_seconds=0,
    )

    summary = manager.run()
    report = json.loads((tmp_path / "reports" / "data_collection_status.json").read_text(encoding="utf-8"))

    assert summary.status == "cooldown"
    assert summary.cooldown_until == active_cooldown_until
    assert engine.search_calls == 0
    assert repository.scrape_runs.count_documents({}) == 0
    assert report["checkpoint"]["cooldown_until"] == active_cooldown_until


def test_manager_rate_limit_sets_checkpoint_cooldown_and_returns_cleanly(tmp_path: Path) -> None:
    repository = TweetRepository(client=mongomock.MongoClient(), database_name="test-manager-4")
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
    now = datetime(2026, 8, 4, 10, 0, tzinfo=timezone.utc)
    engine_cooldown_until = now + timedelta(minutes=10)
    engine = RateLimitedScraperEngine(cooldown_until=engine_cooldown_until)
    sleep_calls: list[float] = []
    reporter = _reporter(
        tmp_path,
        repository=repository,
        checkpoint_store=checkpoint_store,
        required_keywords=("#nifty50",),
        now_provider=lambda: now,
    )

    manager = ScraperManager(
        keywords=("#nifty50",),
        discovery_limit=2,
        target_tweets=2,
        checkpoint_store=checkpoint_store,
        scraper_engine=engine,
        repository=repository,
        processing_pipeline=pipeline,
        signal_aggregator=aggregator,
        parquet_exporter=exporter,
        raw_archive=raw_archive,
        artifact_store=artifact_store,
        collection_status_reporter=reporter,
        startup_jitter_min_seconds=5,
        startup_jitter_max_seconds=5,
        rate_limit_cooldown_min_seconds=1800,
        rate_limit_cooldown_max_seconds=1800,
        now_provider=lambda: now,
        randint_fn=lambda lower, upper: lower,
        sleep_fn=sleep_calls.append,
    )

    summary = manager.run()
    checkpoint = json.loads((tmp_path / "checkpoint.json").read_text(encoding="utf-8"))
    latest_run = repository.scrape_runs.find_one({}, sort=[("started_at", -1)])
    debug_files = list((tmp_path / "debug").glob("*.json"))
    report = json.loads((tmp_path / "reports" / "data_collection_status.json").read_text(encoding="utf-8"))

    assert summary.status == "cooldown"
    assert summary.rate_limit_events == 1
    assert summary.startup_delay_seconds == 5
    assert summary.cooldown_until == "2026-08-04T10:30:00+00:00"
    assert sleep_calls == [5]
    assert checkpoint["cooldown_until"] == "2026-08-04T10:30:00+00:00"
    assert checkpoint["last_rate_limited_at"] is not None
    assert latest_run is not None
    assert latest_run["status"] == "cooldown"
    assert latest_run["startup_delay_seconds"] == 5
    assert latest_run["rate_limit_events"] == 1
    assert any("scrape_rate_limited" in path.name for path in debug_files)
    assert report["checkpoint"]["cooldown_until"] == "2026-08-04T10:30:00+00:00"
