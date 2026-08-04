"""MongoDB-backed operational storage for tweets and derived signals."""

from __future__ import annotations

from collections import Counter
from datetime import datetime, timedelta, timezone
from typing import Any, Iterable, Sequence

import certifi
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
        client_kwargs: dict[str, Any] = {
            "appname": settings.APP_NAME.replace(" ", "-"),
            "tz_aware": True,
            "serverSelectionTimeoutMS": 5000,
        }
        if _requires_tls_ca_file(self.uri):
            client_kwargs["tlsCAFile"] = certifi.where()
        self.client = client or MongoClient(
            self.uri,
            **client_kwargs,
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

    def ping(self) -> dict[str, object]:
        """Verify the MongoDB deployment is reachable."""
        response = self.database.command("ping")
        return {
            "ok": bool(response.get("ok")),
            "database": self.database_name,
            "collections": {
                "tweets": self.tweets.name,
                "runs": self.scrape_runs.name,
                "signals": self.keyword_signals.name,
            },
        }

    def close(self) -> None:
        """Close the underlying MongoDB client."""
        self.client.close()

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
                    "cooldown_until": None,
                    "startup_delay_seconds": 0,
                    "rate_limit_events": 0,
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
                    "cooldown_until": summary.cooldown_until,
                    "startup_delay_seconds": summary.startup_delay_seconds,
                    "rate_limit_events": summary.rate_limit_events,
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
                "cooldown_until": 1,
                "startup_delay_seconds": 1,
                "rate_limit_events": 1,
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

    def load_latest_signal_snapshot(self, *, limit: int) -> pd.DataFrame:
        """Load the latest signal per keyword for ranking and dashboard summaries."""
        pipeline = [
            {"$sort": {"generated_at": DESCENDING}},
            {
                "$group": {
                    "_id": "$keyword",
                    "keyword": {"$first": "$keyword"},
                    "generated_at": {"$first": "$generated_at"},
                    "tweet_count": {"$first": "$tweet_count"},
                    "avg_sentiment": {"$first": "$avg_sentiment"},
                    "avg_engagement": {"$first": "$avg_engagement"},
                    "bullish_ratio": {"$first": "$bullish_ratio"},
                    "bearish_ratio": {"$first": "$bearish_ratio"},
                    "composite_signal": {"$first": "$composite_signal"},
                    "confidence_interval_low": {"$first": "$confidence_interval_low"},
                    "confidence_interval_high": {"$first": "$confidence_interval_high"},
                    "top_terms": {"$first": "$top_terms"},
                }
            },
            {"$sort": {"composite_signal": DESCENDING, "keyword": ASCENDING}},
            {"$limit": limit},
            {"$project": {"_id": 0}},
        ]
        try:
            documents = list(self.keyword_signals.aggregate(pipeline))
            return pd.DataFrame.from_records(documents)
        except Exception:  # noqa: BLE001
            recent = self.load_recent_signals(limit=max(limit * 10, limit))
            if recent.empty:
                return recent
            return (
                recent.sort_values("generated_at", ascending=False)
                .groupby("keyword", as_index=False)
                .head(1)
                .sort_values(["composite_signal", "keyword"], ascending=[False, True])
                .head(limit)
                .reset_index(drop=True)
            )

    def load_top_influencers(
        self,
        *,
        lookback_hours: int,
        limit: int,
        now: datetime | None = None,
    ) -> pd.DataFrame:
        """Return high-signal accounts from the rolling lookback window."""
        now_utc = _normalize_datetime(now or datetime.now(timezone.utc))
        window_query = _timestamp_window_query(now_utc=now_utc, lookback_hours=lookback_hours)
        pipeline = [
            {"$match": window_query},
            {
                "$group": {
                    "_id": "$username_normalized",
                    "username": {"$first": "$username"},
                    "tweet_count": {"$sum": 1},
                    "avg_sentiment": {"$avg": {"$ifNull": ["$sentiment_score", 0]}},
                    "avg_engagement": {"$avg": {"$ifNull": ["$engagement_score", 0]}},
                    "total_engagement": {"$sum": {"$ifNull": ["$engagement_score", 0]}},
                    "latest_timestamp_utc": {"$max": "$timestamp_utc"},
                }
            },
            {"$sort": {"tweet_count": DESCENDING, "total_engagement": DESCENDING, "_id": ASCENDING}},
            {"$limit": limit},
            {"$project": {"_id": 0, "username_normalized": "$_id", "username": 1, "tweet_count": 1, "avg_sentiment": 1, "avg_engagement": 1, "total_engagement": 1, "latest_timestamp_utc": 1}},
        ]
        try:
            documents = list(self.tweets.aggregate(pipeline))
            return pd.DataFrame.from_records(documents)
        except Exception:  # noqa: BLE001
            documents = list(
                self.tweets.find(
                    window_query,
                    projection={
                        "_id": 0,
                        "username": 1,
                        "username_normalized": 1,
                        "timestamp_utc": 1,
                        "sentiment_score": 1,
                        "engagement_score": 1,
                    },
                )
            )
            if not documents:
                return pd.DataFrame()

            grouped: dict[str, dict[str, object]] = {}
            for row in documents:
                key = str(row.get("username_normalized") or row.get("username") or "unknown")
                bucket = grouped.setdefault(
                    key,
                    {
                        "username_normalized": key,
                        "username": row.get("username"),
                        "tweet_count": 0,
                        "avg_sentiment_total": 0.0,
                        "avg_engagement_total": 0.0,
                        "latest_timestamp_utc": row.get("timestamp_utc"),
                    },
                )
                bucket["tweet_count"] = int(bucket["tweet_count"]) + 1
                bucket["avg_sentiment_total"] = float(bucket["avg_sentiment_total"]) + float(row.get("sentiment_score") or 0.0)
                bucket["avg_engagement_total"] = float(bucket["avg_engagement_total"]) + float(row.get("engagement_score") or 0.0)
                bucket["latest_timestamp_utc"] = max(
                    str(bucket.get("latest_timestamp_utc") or ""),
                    str(row.get("timestamp_utc") or ""),
                )

            rows = []
            for bucket in grouped.values():
                tweet_count = max(int(bucket["tweet_count"]), 1)
                total_engagement = float(bucket["avg_engagement_total"])
                rows.append(
                    {
                        "username_normalized": bucket["username_normalized"],
                        "username": bucket["username"],
                        "tweet_count": tweet_count,
                        "avg_sentiment": round(float(bucket["avg_sentiment_total"]) / tweet_count, 6),
                        "avg_engagement": round(total_engagement / tweet_count, 6),
                        "total_engagement": round(total_engagement, 6),
                        "latest_timestamp_utc": bucket["latest_timestamp_utc"],
                    }
                )

            rows.sort(key=lambda row: (-int(row["tweet_count"]), -float(row["total_engagement"]), str(row["username_normalized"])))
            return pd.DataFrame.from_records(rows[:limit])

    def load_hourly_volume(
        self,
        *,
        lookback_hours: int,
        now: datetime | None = None,
    ) -> pd.DataFrame:
        """Return hourly tweet volume for low-memory trend visualizations."""
        now_utc = _normalize_datetime(now or datetime.now(timezone.utc))
        window_query = _timestamp_window_query(now_utc=now_utc, lookback_hours=lookback_hours)
        pipeline = [
            {"$match": window_query},
            {
                "$project": {
                    "hour_bucket": {"$substrBytes": ["$timestamp_utc", 0, 13]},
                    "username_normalized": 1,
                }
            },
            {
                "$group": {
                    "_id": "$hour_bucket",
                    "tweet_count": {"$sum": 1},
                    "users": {"$addToSet": "$username_normalized"},
                }
            },
            {
                "$project": {
                    "_id": 0,
                    "hour_bucket": {"$concat": ["$_id", ":00:00+00:00"]},
                    "tweet_count": 1,
                    "unique_user_count": {"$size": "$users"},
                }
            },
            {"$sort": {"hour_bucket": ASCENDING}},
        ]
        try:
            documents = list(self.tweets.aggregate(pipeline))
            return pd.DataFrame.from_records(documents)
        except Exception:  # noqa: BLE001
            documents = list(
                self.tweets.find(
                    window_query,
                    projection={
                        "_id": 0,
                        "timestamp_utc": 1,
                        "username_normalized": 1,
                    },
                )
            )
            if not documents:
                return pd.DataFrame()

            grouped: dict[str, dict[str, object]] = {}
            for row in documents:
                timestamp = str(row.get("timestamp_utc") or "")
                if len(timestamp) < 13:
                    continue
                hour_bucket = f"{timestamp[:13]}:00:00+00:00"
                bucket = grouped.setdefault(
                    hour_bucket,
                    {
                        "hour_bucket": hour_bucket,
                        "tweet_count": 0,
                        "users": set(),
                    },
                )
                bucket["tweet_count"] = int(bucket["tweet_count"]) + 1
                username = row.get("username_normalized")
                if username:
                    bucket["users"].add(str(username))

            rows = [
                {
                    "hour_bucket": hour_bucket,
                    "tweet_count": bucket["tweet_count"],
                    "unique_user_count": len(bucket["users"]),
                }
                for hour_bucket, bucket in sorted(grouped.items())
            ]
            return pd.DataFrame.from_records(rows)

    def load_collection_progress(
        self,
        *,
        lookback_hours: int,
        target_tweets: int,
        required_keywords: Sequence[str],
        recent_run_hours: int,
        now: datetime | None = None,
    ) -> dict[str, object]:
        """Summarize last-24-hour collection progress against the assignment target."""
        now_utc = _normalize_datetime(now or datetime.now(timezone.utc))
        window_start = now_utc - timedelta(hours=lookback_hours)
        recent_run_start = now_utc - timedelta(hours=recent_run_hours)
        window_query = {
            "timestamp_utc": {
                "$gte": window_start.isoformat(),
                "$lte": now_utc.isoformat(),
            }
        }

        documents = list(
            self.tweets.find(
                window_query,
                projection={
                    "_id": 0,
                    "tweet_key": 1,
                    "timestamp_utc": 1,
                    "username_normalized": 1,
                    "keyword": 1,
                    "provider": 1,
                    "hashtags": 1,
                    "raw_metadata": 1,
                },
            )
        )
        total_tweets = len(documents)
        unique_users = len({doc.get("username_normalized") for doc in documents if doc.get("username_normalized")})

        keyword_counter: Counter[str] = Counter()
        matched_keyword_counter: Counter[str] = Counter()
        hashtag_counter: Counter[str] = Counter()
        provider_counter: Counter[str] = Counter()
        timestamps: list[str] = []

        for document in documents:
            keyword = document.get("keyword")
            if keyword:
                keyword_counter[str(keyword)] += 1

            matched_keywords = {
                str(item)
                for item in document.get("raw_metadata", {}).get("matched_keywords", [])
                if item
            }
            if not matched_keywords and keyword:
                matched_keywords = {str(keyword)}
            for item in matched_keywords:
                matched_keyword_counter[item] += 1

            for hashtag in document.get("hashtags", []):
                if hashtag:
                    hashtag_counter[str(hashtag)] += 1

            provider = document.get("provider")
            if provider:
                provider_counter[str(provider)] += 1

            timestamp = document.get("timestamp_utc")
            if timestamp:
                timestamps.append(str(timestamp))

        recent_runs = list(
            self.scrape_runs.find(
                {
                    "started_at": {
                        "$gte": recent_run_start.isoformat(),
                        "$lte": now_utc.isoformat(),
                    }
                },
                projection={
                    "_id": 0,
                    "run_id": 1,
                    "status": 1,
                    "inserted_count": 1,
                    "updated_count": 1,
                    "duplicate_count": 1,
                    "rate_limit_events": 1,
                },
            )
        )
        run_status_counter: Counter[str] = Counter()
        inserted_recent = 0
        updated_recent = 0
        duplicates_recent = 0
        rate_limit_events_recent = 0
        for run in recent_runs:
            status = str(run.get("status") or "unknown")
            run_status_counter[status] += 1
            inserted_recent += int(run.get("inserted_count") or 0)
            updated_recent += int(run.get("updated_count") or 0)
            duplicates_recent += int(run.get("duplicate_count") or 0)
            rate_limit_events_recent += int(run.get("rate_limit_events") or 0)

        tweets_per_hour_recent = inserted_recent / max(recent_run_hours, 1)
        projected_24h_tweets_recent_rate = int(round(tweets_per_hour_recent * 24))
        matched_counts_map = dict(matched_keyword_counter or keyword_counter)
        covered_keywords = [keyword for keyword in required_keywords if matched_counts_map.get(keyword, 0) > 0]
        missing_keywords = [keyword for keyword in required_keywords if keyword not in covered_keywords]

        completion_ratio = 1.0 if target_tweets <= 0 else round(total_tweets / target_tweets, 6)
        remaining_tweets = max(target_tweets - total_tweets, 0)
        target_met = total_tweets >= target_tweets
        required_tweets_per_hour_exact = target_tweets / max(lookback_hours, 1)
        required_tweets_per_hour = round(required_tweets_per_hour_exact, 3)
        recent_rate_ratio = (
            round(tweets_per_hour_recent / required_tweets_per_hour_exact, 6)
            if required_tweets_per_hour_exact > 0
            else None
        )
        estimated_hours_to_target = (
            round(remaining_tweets / tweets_per_hour_recent, 3)
            if tweets_per_hour_recent > 0
            else None
        )

        return {
            "window_start_utc": window_start.isoformat(),
            "window_end_utc": now_utc.isoformat(),
            "lookback_hours": lookback_hours,
            "target_tweets_last_24_hours": target_tweets,
            "total_unique_tweets_last_24_hours": total_tweets,
            "unique_users_last_24_hours": unique_users,
            "target_completion_ratio": completion_ratio,
            "remaining_tweets_to_target": remaining_tweets,
            "target_met": target_met,
            "required_keywords": list(required_keywords),
            "required_keywords_covered": covered_keywords,
            "missing_required_keywords": missing_keywords,
            "keyword_counts_last_24_hours": _sorted_counter_rows(keyword_counter),
            "matched_keyword_counts_last_24_hours": _sorted_counter_rows(matched_keyword_counter),
            "top_hashtags_last_24_hours": _sorted_counter_rows(hashtag_counter, limit=10),
            "provider_counts_last_24_hours": _sorted_counter_rows(provider_counter),
            "oldest_tweet_timestamp_utc": min(timestamps) if timestamps else None,
            "latest_tweet_timestamp_utc": max(timestamps) if timestamps else None,
            "recent_run_window_hours": recent_run_hours,
            "recent_run_count": len(recent_runs),
            "recent_run_status_counts": dict(run_status_counter),
            "recent_inserted_tweets": inserted_recent,
            "recent_updated_tweets": updated_recent,
            "recent_duplicate_tweets": duplicates_recent,
            "recent_rate_limit_events": rate_limit_events_recent,
            "recent_tweets_per_hour": round(tweets_per_hour_recent, 3),
            "projected_24h_tweets_recent_rate": projected_24h_tweets_recent_rate,
            "required_tweets_per_hour_for_target": required_tweets_per_hour,
            "recent_vs_required_rate_ratio": recent_rate_ratio,
            "estimated_hours_to_target_at_recent_rate": estimated_hours_to_target,
            "assignment_data_collection_ready": target_met and not missing_keywords,
        }

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


def _requires_tls_ca_file(uri: str) -> bool:
    normalized = uri.lower()
    return normalized.startswith("mongodb+srv://") or "tls=true" in normalized


def _normalize_datetime(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def _timestamp_window_query(*, now_utc: datetime, lookback_hours: int) -> dict[str, dict[str, str]]:
    window_start = now_utc - timedelta(hours=lookback_hours)
    return {
        "timestamp_utc": {
            "$gte": window_start.isoformat(),
            "$lte": now_utc.isoformat(),
        }
    }


def _sorted_counter_rows(counter: Counter[str], *, limit: int | None = None) -> list[dict[str, object]]:
    items = sorted(counter.items(), key=lambda item: (-item[1], item[0]))
    if limit is not None:
        items = items[:limit]
    return [{"name": key, "count": value} for key, value in items]
