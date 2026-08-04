"""MongoDB-backed operational storage for tweets and derived signals."""

from __future__ import annotations

from typing import Any, Iterable, Sequence

import pandas as pd
from pymongo import ASCENDING, DESCENDING, MongoClient
from pymongo.collection import Collection
from pymongo.database import Database

from app.core.config import settings
from app.scraper.models import KeywordSignal, ProcessedTweetRecord, ScrapeSummary, StorageBatchResult, utc_now_iso
from app.storage.serialization import serialize_keyword_signal_document, serialize_processed_document


class TweetRepository:
    """Persist and query operational tweet data in MongoDB."""

    def __init__(
        self,
        *,
        uri: str | None = None,
        database_name: str | None = None,
        client: MongoClient[dict[str, Any]] | None = None,
    ) -> None:
        self.uri = uri or settings.MONGODB_URI
        self.database_name = database_name or settings.MONGODB_DATABASE
        self.client = client or MongoClient(
            self.uri,
            appname=settings.APP_NAME.replace(" ", "-"),
            tz_aware=True,
            serverSelectionTimeoutMS=5000,
        )
        self.database: Database[dict[str, Any]] = self.client[self.database_name]
        self.tweets: Collection[dict[str, Any]] = self.database[settings.MONGODB_TWEETS_COLLECTION]
        self.scrape_runs: Collection[dict[str, Any]] = self.database[settings.MONGODB_RUNS_COLLECTION]
        self.keyword_signals: Collection[dict[str, Any]] = self.database[
            settings.MONGODB_SIGNALS_COLLECTION
        ]
        self.initialize()

    def initialize(self) -> None:
        """Ensure collections and indexes exist."""
        self.tweets.create_index("tweet_key", unique=True, name="tweet_key_unique")
        self.tweets.create_index("tweet_url", unique=True, name="tweet_url_unique")
        self.tweets.create_index(
            [("keyword", ASCENDING), ("timestamp_utc", DESCENDING)],
            name="keyword_timestamp_desc",
        )
        self.tweets.create_index("last_seen_at", name="last_seen_at_idx")
        self.tweets.create_index("content_hash", name="content_hash_idx")
        self.scrape_runs.create_index("started_at", name="started_at_idx")
        self.keyword_signals.create_index(
            [("run_id", ASCENDING), ("keyword", ASCENDING)],
            unique=True,
            name="run_keyword_unique",
        )
        self.keyword_signals.create_index(
            [("keyword", ASCENDING), ("generated_at", DESCENDING)],
            name="keyword_generated_desc",
        )

    def record_run_start(self, *, run_id: str, keywords: Sequence[str], target_tweets: int) -> None:
        """Create or replace a scrape-run document."""
        self.scrape_runs.update_one(
            {"run_id": run_id},
            {
                "$set": {
                    "run_id": run_id,
                    "started_at": utc_now_iso(),
                    "completed_at": None,
                    "status": "running",
                    "keywords": list(keywords),
                    "target_tweets": target_tweets,
                    "fetched_count": 0,
                    "inserted_count": 0,
                    "updated_count": 0,
                    "duplicate_count": 0,
                    "raw_rows_written": 0,
                    "parquet_rows_written": 0,
                    "signal_rows_written": 0,
                    "notes": None,
                }
            },
            upsert=True,
        )

    def finalize_run(self, summary: ScrapeSummary, *, status: str = "completed", notes: str | None = None) -> None:
        """Mark a scrape run as complete and persist its counters."""
        if summary.run_id is None:
            return

        self.scrape_runs.update_one(
            {"run_id": summary.run_id},
            {
                "$set": {
                    "completed_at": utc_now_iso(),
                    "status": status,
                    "fetched_count": summary.urls_discovered,
                    "inserted_count": summary.tweets_collected,
                    "updated_count": summary.tweets_updated,
                    "duplicate_count": summary.duplicate_tweets,
                    "raw_rows_written": summary.raw_rows_written,
                    "parquet_rows_written": summary.parquet_rows_written,
                    "signal_rows_written": summary.signal_rows_written,
                    "notes": notes,
                }
            },
        )

    def upsert_tweets(self, records: Sequence[ProcessedTweetRecord], *, run_id: str) -> StorageBatchResult:
        """Insert new tweets and update existing ones while deduplicating repeated records."""
        result = StorageBatchResult(fetched_count=len(records))
        if not records:
            return result

        records = self._deduplicate_batch(records)
        now = utc_now_iso()
        serialized = [serialize_processed_document(record) for record in records]
        existing_keys = self._existing_tweet_keys(record["tweet_key"] for record in serialized)

        new_rows = [row for row in serialized if row["tweet_key"] not in existing_keys]
        existing_rows = [row for row in serialized if row["tweet_key"] in existing_keys]
        inserted_records = [record for record in records if record.tweet_key not in existing_keys]
        updated_records = [record for record in records if record.tweet_key in existing_keys]

        if new_rows:
            self.tweets.insert_many(
                [
                    {
                        **row,
                        "first_seen_at": now,
                        "last_seen_at": now,
                        "times_seen": 1,
                        "scrape_run_id": run_id,
                    }
                    for row in new_rows
                ],
                ordered=False,
            )

        if existing_rows:
            for row in existing_rows:
                self.tweets.update_one(
                    {"tweet_key": row["tweet_key"]},
                    {
                        "$set": {
                            **row,
                            "last_seen_at": now,
                            "scrape_run_id": run_id,
                        },
                        "$inc": {"times_seen": 1},
                    },
                )

        result.inserted_count = len(new_rows)
        result.updated_count = len(existing_rows)
        result.duplicate_count = len(existing_rows)
        result.inserted_records = inserted_records
        result.updated_records = updated_records
        return result

    def replace_keyword_signals(self, signals: Sequence[KeywordSignal]) -> int:
        """Replace signal documents for the run/keyword pairs in the batch."""
        if not signals:
            return 0

        rows = [serialize_keyword_signal_document(signal) for signal in signals]
        for row in rows:
            self.keyword_signals.replace_one(
                {"run_id": row["run_id"], "keyword": row["keyword"]},
                row,
                upsert=True,
            )
        return len(rows)

    def load_dashboard_overview(self) -> dict[str, object]:
        """Return summary counts and latest run metadata for the dashboard."""
        total_tweets = self.tweets.count_documents({})
        unique_users = len(self.tweets.distinct("username_normalized"))
        tracked_keywords = len(
            [keyword for keyword in self.tweets.distinct("keyword") if keyword not in (None, "")]
        )
        latest_tweet = self.tweets.find_one(
            {},
            projection={"_id": 0, "last_seen_at": 1},
            sort=[("last_seen_at", DESCENDING)],
        )
        latest_run = self.scrape_runs.find_one(
            {},
            projection={
                "_id": 0,
                "run_id": 1,
                "started_at": 1,
                "completed_at": 1,
                "status": 1,
                "fetched_count": 1,
                "inserted_count": 1,
                "updated_count": 1,
                "duplicate_count": 1,
                "raw_rows_written": 1,
                "parquet_rows_written": 1,
                "signal_rows_written": 1,
            },
            sort=[("started_at", DESCENDING)],
        )

        return {
            "total_tweets": total_tweets,
            "unique_users": unique_users,
            "tracked_keywords": tracked_keywords,
            "latest_seen_at": latest_tweet["last_seen_at"] if latest_tweet else None,
            "latest_run": latest_run,
        }

    def load_recent_signals(self, *, limit: int) -> pd.DataFrame:
        """Load recent keyword signals in a dashboard-friendly frame."""
        documents = list(
            self.keyword_signals.find(
                {},
                projection={
                    "_id": 0,
                    "keyword": 1,
                    "generated_at": 1,
                    "tweet_count": 1,
                    "avg_sentiment": 1,
                    "avg_engagement": 1,
                    "composite_signal": 1,
                    "confidence_interval_low": 1,
                    "confidence_interval_high": 1,
                    "top_terms": 1,
                },
            )
            .sort("generated_at", DESCENDING)
            .limit(limit)
        )
        return pd.DataFrame.from_records(documents)

    def load_recent_tweets(self, *, limit: int) -> pd.DataFrame:
        """Load a recent tweet sample without scanning the full dataset in memory."""
        documents = list(
            self.tweets.find(
                {},
                projection={
                    "_id": 0,
                    "keyword": 1,
                    "username": 1,
                    "timestamp_utc": 1,
                    "normalized_content": 1,
                    "sentiment_score": 1,
                    "engagement_score": 1,
                    "indian_script_ratio": 1,
                    "non_ascii_ratio": 1,
                },
            )
            .sort("last_seen_at", DESCENDING)
            .limit(limit)
        )
        return pd.DataFrame.from_records(documents)

    def _deduplicate_batch(self, records: Sequence[ProcessedTweetRecord]) -> list[ProcessedTweetRecord]:
        unique: dict[str, ProcessedTweetRecord] = {}

        for record in records:
            key = record.tweet_key or record.tweet_url
            if key in unique:
                primary = unique[key]
                primary.likes = max(primary.likes, record.likes)
                primary.replies = max(primary.replies, record.replies)
                primary.reposts = max(primary.reposts, record.reposts)
                primary.views = max(primary.views or 0, record.views or 0) or None
                primary.mentions = sorted(set(primary.mentions) | set(record.mentions))
                primary.hashtags = sorted(set(primary.hashtags) | set(record.hashtags))
                primary.top_terms = sorted(set(primary.top_terms) | set(record.top_terms))
                matched_keywords = set(primary.raw_metadata.get("matched_keywords", []))
                if primary.keyword:
                    matched_keywords.add(primary.keyword)
                if record.keyword:
                    matched_keywords.add(record.keyword)
                primary.raw_metadata["matched_keywords"] = sorted(matched_keywords)
                continue

            unique[key] = record

        return list(unique.values())

    def _existing_tweet_keys(self, keys: Iterable[str]) -> set[str]:
        key_list = list(keys)
        if not key_list:
            return set()

        found: set[str] = set()
        for chunk in _chunked(key_list, 500):
            rows = self.tweets.find(
                {"tweet_key": {"$in": list(chunk)}},
                projection={"_id": 0, "tweet_key": 1},
            )
            found.update(row["tweet_key"] for row in rows)
        return found


def _chunked(values: Sequence[str], size: int) -> list[Sequence[str]]:
    return [values[index : index + size] for index in range(0, len(values), size)]
