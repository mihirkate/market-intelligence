"""Aggregate processed tweets into keyword-level trading signals."""

from __future__ import annotations

import math
from collections import Counter, defaultdict
from statistics import mean, pstdev
from typing import Sequence

from app.scraper.models import KeywordSignal, ProcessedTweetRecord, utc_now_iso


class KeywordSignalAggregator:
    """Combine text and engagement features into composite keyword signals."""

    def aggregate(self, records: Sequence[ProcessedTweetRecord], *, run_id: str) -> list[KeywordSignal]:
        """Build one signal per keyword for the current batch."""
        grouped: dict[str, list[ProcessedTweetRecord]] = defaultdict(list)
        for record in records:
            keyword = record.keyword or "unassigned"
            grouped[keyword].append(record)

        generated_at = utc_now_iso()
        return [
            self._build_keyword_signal(keyword, items, run_id=run_id, generated_at=generated_at)
            for keyword, items in sorted(grouped.items())
        ]

    def _build_keyword_signal(
        self,
        keyword: str,
        records: Sequence[ProcessedTweetRecord],
        *,
        run_id: str,
        generated_at: str,
    ) -> KeywordSignal:
        raw_scores = [
            (0.65 * record.sentiment_score)
            + (0.2 * math.tanh(record.engagement_score / 4.0))
            + (0.15 * record.keyword_match_score)
            for record in records
        ]
        composite_signal = mean(raw_scores) if raw_scores else 0.0
        standard_error = 0.0
        if len(raw_scores) > 1:
            standard_error = pstdev(raw_scores) / math.sqrt(len(raw_scores))

        term_counts: Counter[str] = Counter()
        for record in records:
            term_counts.update(record.top_terms)

        bullish_count = sum(record.sentiment_score > 0 for record in records)
        bearish_count = sum(record.sentiment_score < 0 for record in records)
        keyword_match_rate = mean(record.keyword_match_score for record in records) if records else 0.0

        return KeywordSignal(
            run_id=run_id,
            keyword=keyword,
            generated_at=generated_at,
            tweet_count=len(records),
            unique_user_count=len({record.username_normalized for record in records}),
            avg_sentiment=round(mean(record.sentiment_score for record in records), 6) if records else 0.0,
            avg_engagement=round(mean(record.engagement_score for record in records), 6) if records else 0.0,
            bullish_ratio=round(bullish_count / len(records), 6) if records else 0.0,
            bearish_ratio=round(bearish_count / len(records), 6) if records else 0.0,
            keyword_match_rate=round(keyword_match_rate, 6),
            composite_signal=round(composite_signal, 6),
            confidence_interval_low=round(composite_signal - (1.96 * standard_error), 6),
            confidence_interval_high=round(composite_signal + (1.96 * standard_error), 6),
            top_terms=[token for token, _ in term_counts.most_common(8)],
        )
