"""Shared scraper data models."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Any


def utc_now_iso() -> str:
    """Return the current UTC time in ISO format."""
    return datetime.now(timezone.utc).isoformat()


@dataclass(slots=True)
class TweetRecord:
    """Raw tweet record extracted from a tweet page."""

    tweet_url: str
    tweet_id: str | None
    username: str
    display_name: str | None
    timestamp_utc: str | None
    content: str
    replies: int
    reposts: int
    likes: int
    views: int | None
    mentions: list[str] = field(default_factory=list)
    hashtags: list[str] = field(default_factory=list)
    keyword: str | None = None
    provider: str | None = None
    scraped_at: str = field(default_factory=utc_now_iso)
    raw_metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        """Serialize the record for JSON storage."""
        return asdict(self)


@dataclass(slots=True)
class ProcessedTweetRecord:
    """Normalized tweet ready for durable storage and analytics."""

    tweet_key: str
    tweet_id: str | None
    tweet_url: str
    username: str
    username_normalized: str
    display_name: str | None
    timestamp_utc: str | None
    content: str
    normalized_content: str
    content_hash: str
    language: str | None
    keyword: str | None
    provider: str | None
    replies: int
    reposts: int
    likes: int
    views: int | None
    mentions: list[str] = field(default_factory=list)
    hashtags: list[str] = field(default_factory=list)
    token_count: int = 0
    indian_script_ratio: float = 0.0
    non_ascii_ratio: float = 0.0
    bullish_term_hits: int = 0
    bearish_term_hits: int = 0
    keyword_match_score: float = 0.0
    engagement_score: float = 0.0
    sentiment_score: float = 0.0
    confidence_score: float = 0.0
    feature_vector: list[float] = field(default_factory=list)
    top_terms: list[str] = field(default_factory=list)
    scraped_at: str = field(default_factory=utc_now_iso)
    raw_metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        """Serialize the processed record for parquet export."""
        return asdict(self)


@dataclass(slots=True)
class KeywordSignal:
    """Aggregated trading signal derived from a keyword's tweets."""

    run_id: str
    keyword: str
    generated_at: str
    tweet_count: int
    unique_user_count: int
    avg_sentiment: float
    avg_engagement: float
    bullish_ratio: float
    bearish_ratio: float
    keyword_match_rate: float
    composite_signal: float
    confidence_interval_low: float
    confidence_interval_high: float
    top_terms: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        """Serialize the signal for parquet export."""
        return asdict(self)


@dataclass(slots=True)
class StorageBatchResult:
    """Result of persisting a processed tweet batch."""

    fetched_count: int = 0
    inserted_count: int = 0
    updated_count: int = 0
    duplicate_count: int = 0
    inserted_records: list[ProcessedTweetRecord] = field(default_factory=list)
    updated_records: list[ProcessedTweetRecord] = field(default_factory=list)


@dataclass(slots=True)
class ScrapeSummary:
    """End-of-run summary for the scraper manager."""

    run_id: str | None = None
    status: str = "pending"
    cooldown_until: str | None = None
    startup_delay_seconds: int = 0
    rate_limit_events: int = 0
    tweets_collected: int = 0
    urls_discovered: int = 0
    tweets_updated: int = 0
    duplicate_tweets: int = 0
    raw_rows_written: int = 0
    parquet_rows_written: int = 0
    signal_rows_written: int = 0
    keywords_processed: list[str] = field(default_factory=list)
    providers_used: list[str] = field(default_factory=list)
