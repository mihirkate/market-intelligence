from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import mongomock

from app.processing import TweetProcessingPipeline
from app.reporting.analysis import AnalysisReporter
from app.reporting.performance import PerformanceBenchmarkRunner
from app.reporting.processing import ProcessingReportWriter
from app.scraper.checkpoint import CheckpointStore
from app.scraper.collection_status import CollectionStatusReporter
from app.scraper.models import KeywordSignal, ScrapeSummary, TweetRecord
from app.storage import TweetRepository


def _record(tweet_id: str, *, timestamp: datetime, keyword: str, content: str) -> TweetRecord:
    return TweetRecord(
        tweet_url=f"https://x.com/demo/status/{tweet_id}",
        tweet_id=tweet_id,
        username=f"user_{tweet_id}",
        display_name=f"User {tweet_id}",
        timestamp_utc=timestamp.isoformat(),
        content=content,
        replies=1,
        reposts=2,
        likes=5,
        views=20,
        mentions=["@Desk"],
        hashtags=[keyword, "#market"],
        keyword=keyword,
        provider="twscrape",
        raw_metadata={"matched_keywords": [keyword], "lang": "en"},
    )


def test_analysis_reporter_builds_snapshot_with_influencers_and_volume(tmp_path: Path) -> None:
    now = datetime(2026, 8, 4, 12, 0, tzinfo=timezone.utc)
    repository = TweetRepository(client=mongomock.MongoClient(), database_name="test-analysis-report")
    pipeline = TweetProcessingPipeline(vector_size=8, top_term_count=3, max_workers=1)
    checkpoint_store = CheckpointStore(path=tmp_path / "checkpoint.json")
    status_reporter = CollectionStatusReporter(
        repository=repository,
        checkpoint_store=checkpoint_store,
        report_path=tmp_path / "reports" / "collection.json",
        lookback_hours=24,
        required_keywords=("#nifty50", "#sensex"),
        now_provider=lambda: now,
    )

    processed = pipeline.process_records(
        [
            _record(
                "1",
                timestamp=now - timedelta(hours=2),
                keyword="#nifty50",
                content="Bullish breakout on nifty50",
            ),
            _record(
                "2",
                timestamp=now - timedelta(hours=1),
                keyword="#sensex",
                content="Sensex rebound and bullish recovery",
            ),
        ]
    )
    repository.upsert_tweets(processed, run_id="run-1")
    repository.replace_keyword_signals(
        [
            KeywordSignal(
                run_id="run-1",
                keyword="#nifty50",
                generated_at=now.isoformat(),
                tweet_count=1,
                unique_user_count=1,
                avg_sentiment=0.1,
                avg_engagement=1.0,
                bullish_ratio=1.0,
                bearish_ratio=0.0,
                keyword_match_rate=1.0,
                composite_signal=0.2,
                confidence_interval_low=0.1,
                confidence_interval_high=0.3,
                top_terms=["bullish", "breakout"],
            )
        ]
    )

    reporter = AnalysisReporter(
        repository=repository,
        collection_status_reporter=status_reporter,
        report_path=tmp_path / "reports" / "analysis.json",
        top_limit=5,
        now_provider=lambda: now,
    )

    payload = reporter.build_report(latest_summary=ScrapeSummary(run_id="run-1", status="completed"))
    path = reporter.write_report(latest_summary=ScrapeSummary(run_id="run-1", status="completed"))

    assert payload["collection"]["total_unique_tweets_last_24_hours"] == 2
    assert payload["signal_bias"]["buy_keywords"] == 1
    assert payload["top_influencers"]
    assert payload["hourly_volume"]
    assert path.exists()


def test_processing_report_writer_saves_latest_run_summary(tmp_path: Path) -> None:
    writer = ProcessingReportWriter(report_path=tmp_path / "reports" / "processing.json")
    summary = ScrapeSummary(
        run_id="run-1",
        status="completed",
        tweets_collected=12,
        tweets_updated=2,
        duplicate_tweets=3,
        urls_discovered=14,
        raw_rows_written=20,
        parquet_rows_written=12,
        signal_rows_written=4,
        keywords_processed=["#nifty50"],
        providers_used=["twscrape"],
    )

    path = writer.write_report(
        summary=summary,
        collection_status={
            "total_unique_tweets_last_24_hours": 47,
            "remaining_tweets_to_target": 1953,
            "assignment_data_collection_ready": False,
            "recent_tweets_per_hour": 7.833,
            "required_tweets_per_hour_for_target": 83.333,
            "recent_vs_required_rate_ratio": 0.094,
        },
    )
    payload = json.loads(path.read_text(encoding="utf-8"))

    assert payload["inserted"] == 12
    assert payload["updated"] == 2
    assert payload["duplicates"] == 3
    assert payload["valid"] == 14
    assert payload["stored"] == 12
    assert payload["collection_status"]["remaining_tweets_to_target"] == 1953


def test_performance_benchmark_runner_writes_scaling_report(tmp_path: Path) -> None:
    runner = PerformanceBenchmarkRunner(
        record_counts=(5, 10),
        report_path=tmp_path / "reports" / "performance.json",
    )

    path = runner.write_report()
    payload = json.loads(path.read_text(encoding="utf-8"))

    assert len(payload["scenarios"]) == 2
    assert payload["scenarios"][0]["record_count"] == 5
    assert payload["scenarios"][1]["record_count"] == 10
    assert "scale_summary" in payload
