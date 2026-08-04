"""Batch-oriented normalization pipeline for scraped tweets."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from os import cpu_count
from typing import Sequence

from app.core.config import settings
from app.processing.normalization import (
    build_document_frequency,
    build_processed_tweet,
    prepare_tweet,
)
from app.scraper.models import ProcessedTweetRecord, TweetRecord


class TweetProcessingPipeline:
    """Normalize raw tweets into analytics-ready rows."""

    def __init__(
        self,
        *,
        vector_size: int | None = None,
        top_term_count: int | None = None,
        max_workers: int | None = None,
    ) -> None:
        self.vector_size = vector_size if vector_size is not None else settings.FEATURE_VECTOR_SIZE
        self.top_term_count = top_term_count if top_term_count is not None else settings.FEATURE_TOP_TERMS
        default_workers = max(1, min(4, cpu_count() or 1))
        self.max_workers = max_workers if max_workers is not None else default_workers

    def process_records(self, records: Sequence[TweetRecord]) -> list[ProcessedTweetRecord]:
        """Normalize and featurize a batch of raw records."""
        if not records:
            return []

        with ThreadPoolExecutor(max_workers=self.max_workers) as executor:
            prepared = list(executor.map(prepare_tweet, records))

        doc_frequency = build_document_frequency(prepared)
        corpus_size = len(prepared)
        return [
            build_processed_tweet(
                item,
                doc_frequency=doc_frequency,
                corpus_size=corpus_size,
                vector_size=self.vector_size,
                top_term_count=self.top_term_count,
            )
            for item in prepared
        ]
