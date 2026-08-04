"""Serialization helpers for storage backends."""

from __future__ import annotations

import json
from typing import Any

from app.scraper.models import KeywordSignal, ProcessedTweetRecord


def serialize_processed_record(record: ProcessedTweetRecord) -> dict[str, Any]:
    """Convert a processed tweet into flat, backend-friendly columns."""
    return {
        "tweet_key": record.tweet_key,
        "tweet_id": record.tweet_id,
        "tweet_url": record.tweet_url,
        "username": record.username,
        "username_normalized": record.username_normalized,
        "display_name": record.display_name,
        "timestamp_utc": record.timestamp_utc,
        "content": record.content,
        "normalized_content": record.normalized_content,
        "content_hash": record.content_hash,
        "language": record.language,
        "keyword": record.keyword,
        "provider": record.provider,
        "replies": record.replies,
        "reposts": record.reposts,
        "likes": record.likes,
        "views": record.views,
        "mentions_json": _json_dumps(record.mentions),
        "hashtags_json": _json_dumps(record.hashtags),
        "token_count": record.token_count,
        "indian_script_ratio": record.indian_script_ratio,
        "non_ascii_ratio": record.non_ascii_ratio,
        "bullish_term_hits": record.bullish_term_hits,
        "bearish_term_hits": record.bearish_term_hits,
        "keyword_match_score": record.keyword_match_score,
        "engagement_score": record.engagement_score,
        "sentiment_score": record.sentiment_score,
        "confidence_score": record.confidence_score,
        "feature_vector_json": _json_dumps(record.feature_vector),
        "top_terms_json": _json_dumps(record.top_terms),
        "raw_metadata_json": _json_dumps(record.raw_metadata),
        "scraped_at": record.scraped_at,
        "scrape_date": record.scraped_at[:10],
    }


def serialize_processed_document(record: ProcessedTweetRecord) -> dict[str, Any]:
    """Convert a processed tweet into a Mongo-friendly document."""
    return {
        "tweet_key": record.tweet_key,
        "tweet_id": record.tweet_id,
        "tweet_url": record.tweet_url,
        "username": record.username,
        "username_normalized": record.username_normalized,
        "display_name": record.display_name,
        "timestamp_utc": record.timestamp_utc,
        "content": record.content,
        "normalized_content": record.normalized_content,
        "content_hash": record.content_hash,
        "language": record.language,
        "keyword": record.keyword,
        "provider": record.provider,
        "replies": record.replies,
        "reposts": record.reposts,
        "likes": record.likes,
        "views": record.views,
        "mentions": list(record.mentions),
        "hashtags": list(record.hashtags),
        "token_count": record.token_count,
        "indian_script_ratio": record.indian_script_ratio,
        "non_ascii_ratio": record.non_ascii_ratio,
        "bullish_term_hits": record.bullish_term_hits,
        "bearish_term_hits": record.bearish_term_hits,
        "keyword_match_score": record.keyword_match_score,
        "engagement_score": record.engagement_score,
        "sentiment_score": record.sentiment_score,
        "confidence_score": record.confidence_score,
        "feature_vector": list(record.feature_vector),
        "top_terms": list(record.top_terms),
        "raw_metadata": dict(record.raw_metadata),
        "scraped_at": record.scraped_at,
        "scrape_date": record.scraped_at[:10],
    }


def serialize_keyword_signal(signal: KeywordSignal) -> dict[str, Any]:
    """Convert a keyword signal into flat, backend-friendly columns."""
    return {
        "run_id": signal.run_id,
        "keyword": signal.keyword,
        "generated_at": signal.generated_at,
        "generated_date": signal.generated_at[:10],
        "tweet_count": signal.tweet_count,
        "unique_user_count": signal.unique_user_count,
        "avg_sentiment": signal.avg_sentiment,
        "avg_engagement": signal.avg_engagement,
        "bullish_ratio": signal.bullish_ratio,
        "bearish_ratio": signal.bearish_ratio,
        "keyword_match_rate": signal.keyword_match_rate,
        "composite_signal": signal.composite_signal,
        "confidence_interval_low": signal.confidence_interval_low,
        "confidence_interval_high": signal.confidence_interval_high,
        "top_terms_json": _json_dumps(signal.top_terms),
    }


def serialize_keyword_signal_document(signal: KeywordSignal) -> dict[str, Any]:
    """Convert a keyword signal into a Mongo-friendly document."""
    return {
        "run_id": signal.run_id,
        "keyword": signal.keyword,
        "generated_at": signal.generated_at,
        "generated_date": signal.generated_at[:10],
        "tweet_count": signal.tweet_count,
        "unique_user_count": signal.unique_user_count,
        "avg_sentiment": signal.avg_sentiment,
        "avg_engagement": signal.avg_engagement,
        "bullish_ratio": signal.bullish_ratio,
        "bearish_ratio": signal.bearish_ratio,
        "keyword_match_rate": signal.keyword_match_rate,
        "composite_signal": signal.composite_signal,
        "confidence_interval_low": signal.confidence_interval_low,
        "confidence_interval_high": signal.confidence_interval_high,
        "top_terms": list(signal.top_terms),
    }


def _json_dumps(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True)
