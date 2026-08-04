from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import mongomock

from app.processing import TweetProcessingPipeline
from app.scraper.checkpoint import CheckpointStore, ScrapeCheckpoint
from app.scraper.collection_status import CollectionStatusReporter
from app.scraper.models import ScrapeSummary, TweetRecord
from app.storage import TweetRepository


def _record(
    tweet_id: str,
    *,
    timestamp: datetime,
    keyword: str,
    content: str,
    matched_keywords: list[str],
    hashtags: list[str],
) -> TweetRecord:
    return TweetRecord(
        tweet_url=f"https://x.com/demo/status/{tweet_id}",
        tweet_id=tweet_id,
        username=f"user_{tweet_id}",
        display_name=f"User {tweet_id}",
        timestamp_utc=timestamp.isoformat(),
        content=content,
        replies=1,
        reposts=1,
        likes=5,
        views=25,
        mentions=["@Desk"],
        hashtags=hashtags,
        keyword=keyword,
        provider="twscrape",
        raw_metadata={"matched_keywords": matched_keywords, "lang": "en"},
    )


def test_collection_status_report_tracks_target_progress_and_keyword_coverage(tmp_path: Path) -> None:
    repository = TweetRepository(client=mongomock.MongoClient(), database_name="test-collection-status")
    checkpoint_store = CheckpointStore(path=tmp_path / "checkpoint.json")
    pipeline = TweetProcessingPipeline(vector_size=8, top_term_count=3, max_workers=1)
    now = datetime(2026, 8, 4, 12, 0, tzinfo=timezone.utc)

    processed = pipeline.process_records(
        [
            _record(
                "1",
                timestamp=now - timedelta(hours=1),
                keyword="#nifty50",
                content="Bullish move on nifty and banknifty",
                matched_keywords=["#nifty50", "#banknifty"],
                hashtags=["#nifty50", "#banknifty"],
            ),
            _record(
                "2",
                timestamp=now - timedelta(hours=2),
                keyword="#sensex",
                content="Sensex support holds",
                matched_keywords=["#sensex"],
                hashtags=["#sensex"],
            ),
            _record(
                "3",
                timestamp=now - timedelta(hours=26),
                keyword="#intraday",
                content="Older intraday tweet",
                matched_keywords=["#intraday"],
                hashtags=["#intraday"],
            ),
        ]
    )
    repository.upsert_tweets(processed, run_id="run-1")
    repository.scrape_runs.insert_many(
        [
            {
                "run_id": "recent-1",
                "started_at": (now - timedelta(hours=5)).isoformat(),
                "status": "completed",
                "inserted_count": 20,
                "updated_count": 2,
                "duplicate_count": 1,
                "rate_limit_events": 0,
            },
            {
                "run_id": "recent-2",
                "started_at": (now - timedelta(hours=1)).isoformat(),
                "status": "cooldown",
                "inserted_count": 0,
                "updated_count": 0,
                "duplicate_count": 0,
                "rate_limit_events": 1,
            },
        ]
    )
    checkpoint_store.save(
        ScrapeCheckpoint(
            run_id="run-1",
            last_completed_at=(now - timedelta(minutes=5)).isoformat(),
            cooldown_until=(now + timedelta(minutes=20)).isoformat(),
            last_rate_limited_at=(now - timedelta(minutes=10)).isoformat(),
            last_keyword="#sensex",
            last_url="https://x.com/demo/status/2",
        )
    )

    reporter = CollectionStatusReporter(
        repository=repository,
        checkpoint_store=checkpoint_store,
        report_path=tmp_path / "reports" / "data_collection_status.json",
        lookback_hours=24,
        target_tweets=2,
        recent_run_hours=6,
        required_keywords=("#nifty50", "#sensex", "#intraday", "#banknifty"),
        now_provider=lambda: now,
    )

    report_path = reporter.write_report(
        latest_summary=ScrapeSummary(run_id="run-1", status="completed", tweets_collected=2)
    )
    report = json.loads(report_path.read_text(encoding="utf-8"))

    assert report["total_unique_tweets_last_24_hours"] == 2
    assert report["unique_users_last_24_hours"] == 2
    assert report["target_met"] is True
    assert report["assignment_data_collection_ready"] is False
    assert report["missing_required_keywords"] == ["#intraday"]
    assert report["matched_keyword_counts_last_24_hours"] == [
        {"name": "#banknifty", "count": 1},
        {"name": "#nifty50", "count": 1},
        {"name": "#sensex", "count": 1},
    ]
    assert report["recent_run_status_counts"] == {"completed": 1, "cooldown": 1}
    assert report["recent_rate_limit_events"] == 1
    assert report["recent_tweets_per_hour"] == 3.333
    assert report["projected_24h_tweets_recent_rate"] == 80
    assert report["required_tweets_per_hour_for_target"] == 0.083
    assert report["recent_vs_required_rate_ratio"] == 40.0
    assert report["estimated_hours_to_target_at_recent_rate"] == 0.0
    assert report["checkpoint"]["cooldown_until"] == (now + timedelta(minutes=20)).isoformat()
    assert report["latest_summary"]["run_id"] == "run-1"
