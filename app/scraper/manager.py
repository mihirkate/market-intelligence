"""Orchestration layer for tweet collection."""

from __future__ import annotations

from collections import deque
from dataclasses import asdict
from uuid import uuid4

from app.core.config import settings
from app.core.logging import configure_logging, get_logger
from app.processing import TweetProcessingPipeline
from app.scraper.checkpoint import CheckpointStore, ScrapeCheckpoint
from app.scraper.engines import ScraperEngine, build_scraper_engine
from app.scraper.models import ScrapeSummary, utc_now_iso
from app.signals import KeywordSignalAggregator
from app.storage import DebugArtifactStore, ParquetExporter, RawTweetArchive, TweetRepository

logger = get_logger(__name__)


class ScraperManager:
    """Collect tweets through the configured scraper engine and persist them to the warehouse."""

    def __init__(
        self,
        *,
        keywords: tuple[str, ...] | None = None,
        discovery_limit: int | None = None,
        target_tweets: int | None = None,
        checkpoint_store: CheckpointStore | None = None,
        scraper_engine: ScraperEngine | None = None,
        repository: TweetRepository | None = None,
        processing_pipeline: TweetProcessingPipeline | None = None,
        signal_aggregator: KeywordSignalAggregator | None = None,
        parquet_exporter: ParquetExporter | None = None,
        raw_archive: RawTweetArchive | None = None,
        artifact_store: DebugArtifactStore | None = None,
    ) -> None:
        self.keywords = keywords or settings.SCRAPER_KEYWORDS
        self.discovery_limit = (
            discovery_limit
            if discovery_limit is not None
            else settings.DISCOVERY_LIMIT_PER_KEYWORD
        )
        self.target_tweets = target_tweets if target_tweets is not None else settings.TARGET_TWEETS
        self.checkpoint_store = checkpoint_store or CheckpointStore()
        self.scraper_engine = scraper_engine or build_scraper_engine()
        self.repository = repository or TweetRepository()
        self.processing_pipeline = processing_pipeline or TweetProcessingPipeline()
        self.signal_aggregator = signal_aggregator or KeywordSignalAggregator()
        self.parquet_exporter = parquet_exporter or ParquetExporter()
        self.raw_archive = raw_archive or RawTweetArchive()
        self.artifact_store = artifact_store or DebugArtifactStore()
        self.summary = ScrapeSummary()
        self._started_at: str | None = None
        self._last_keyword: str | None = None
        self._last_url: str | None = None

    def run(self) -> ScrapeSummary:
        """Run the configured scraping engine and persist fresh data."""
        checkpoint = self.checkpoint_store.load()
        self._restore_checkpoint(checkpoint)
        self.summary = ScrapeSummary(run_id=uuid4().hex)
        self._started_at = utc_now_iso()
        self._last_keyword = None
        self._last_url = None
        self.repository.record_run_start(
            run_id=self.summary.run_id,
            keywords=self.keywords,
            target_tweets=self.target_tweets,
        )
        self._save_checkpoint()

        logger.info(
            "Starting scraper keywords=%s target=%s engine=%s",
            list(self.keywords),
            self.target_tweets,
            self.scraper_engine.name,
        )

        if self.scraper_engine.name not in self.summary.providers_used:
            self.summary.providers_used.append(self.scraper_engine.name)

        try:
            results_by_keyword = self.scraper_engine.search_many(self.keywords, limit=self.discovery_limit)
            for keyword, records in results_by_keyword.items():
                logger.info(
                    "Engine=%s keyword=%s returned=%s",
                    self.scraper_engine.name,
                    keyword,
                    len(records),
                )

            fetched_records = [record for records in results_by_keyword.values() for record in records]
            self.summary.raw_rows_written = self.raw_archive.write_records(
                fetched_records,
                run_id=self.summary.run_id,
            )
            logger.info(
                "Run=%s archived raw rows=%s",
                self.summary.run_id,
                self.summary.raw_rows_written,
            )
            selected_records = self._interleave_keyword_results(results_by_keyword, limit=self.target_tweets)
            self.summary.urls_discovered = len(selected_records)
            self.summary.keywords_processed = [
                keyword for keyword, records in results_by_keyword.items() if records
            ]
            unique_records, batch_duplicate_count = self._deduplicate_selected_records(selected_records)

            processed_records = self.processing_pipeline.process_records(unique_records)
            storage_result = self.repository.upsert_tweets(
                processed_records,
                run_id=self.summary.run_id,
            )
            signals = self.signal_aggregator.aggregate(processed_records, run_id=self.summary.run_id)
            signal_rows_written = self.repository.replace_keyword_signals(signals)
            parquet_rows_written = self.parquet_exporter.write_tweets(
                storage_result.inserted_records,
                run_id=self.summary.run_id,
            )
            signal_parquet_rows = self.parquet_exporter.write_signals(
                signals,
                run_id=self.summary.run_id,
            )

            self.summary.tweets_collected = storage_result.inserted_count
            self.summary.tweets_updated = storage_result.updated_count
            self.summary.duplicate_tweets = batch_duplicate_count + storage_result.duplicate_count
            self.summary.parquet_rows_written = parquet_rows_written
            self.summary.signal_rows_written = signal_parquet_rows

            if processed_records:
                self._last_keyword = processed_records[-1].keyword
                self._last_url = processed_records[-1].tweet_url

            logger.info(
                "Run=%s fetched=%s inserted=%s updated=%s duplicates=%s signals=%s",
                self.summary.run_id,
                self.summary.urls_discovered,
                self.summary.tweets_collected,
                self.summary.tweets_updated,
                self.summary.duplicate_tweets,
                signal_rows_written,
            )
            self._save_checkpoint(completed=True)
            self.repository.finalize_run(self.summary)
            logger.info("Scrape finished summary=%s", asdict(self.summary))
            return self.summary
        except Exception as error:
            artifact_path = self.artifact_store.write_event(
                "scrape_run_failure",
                run_id=self.summary.run_id,
                payload={
                    "engine": self.scraper_engine.name,
                    "keywords": list(self.keywords),
                    "target_tweets": self.target_tweets,
                    "last_keyword": self._last_keyword,
                    "last_url": self._last_url,
                    "summary": asdict(self.summary),
                },
                error=error,
            )
            self.repository.finalize_run(
                self.summary,
                status="failed",
                notes=f"{error} | artifact={artifact_path}",
            )
            self._save_checkpoint(completed=True)
            raise

    def _restore_checkpoint(self, checkpoint: ScrapeCheckpoint) -> None:
        self._last_keyword = checkpoint.last_keyword
        self._last_url = checkpoint.last_url

    def _save_checkpoint(self, *, completed: bool = False) -> None:
        checkpoint = ScrapeCheckpoint(
            run_id=self.summary.run_id,
            last_started_at=self._started_at,
            last_completed_at=None,
            last_keyword=self._last_keyword,
            last_url=self._last_url,
            tweets_collected=self.summary.tweets_collected,
            urls_discovered=self.summary.urls_discovered,
            tweets_updated=self.summary.tweets_updated,
            duplicate_tweets=self.summary.duplicate_tweets,
            raw_rows_written=self.summary.raw_rows_written,
            parquet_rows_written=self.summary.parquet_rows_written,
            signal_rows_written=self.summary.signal_rows_written,
        )
        if completed:
            checkpoint.last_completed_at = checkpoint.updated_at
        self.checkpoint_store.save(checkpoint)

    def _interleave_keyword_results(
        self,
        results_by_keyword: dict[str, list],
        *,
        limit: int,
    ) -> list:
        active = deque(
            (keyword, deque(records))
            for keyword, records in results_by_keyword.items()
            if records
        )
        selected = []

        while active and len(selected) < limit:
            keyword, records = active.popleft()
            selected.append(records.popleft())
            if records and len(selected) < limit:
                active.append((keyword, records))

        return selected

    def _deduplicate_selected_records(self, records: list) -> tuple[list, int]:
        deduplicated = []
        seen: dict[str, object] = {}

        for record in records:
            key = record.tweet_id or record.tweet_url
            if key in seen:
                primary = seen[key]
                matched_keywords = set(primary.raw_metadata.get("matched_keywords", []))
                if primary.keyword:
                    matched_keywords.add(primary.keyword)
                if record.keyword:
                    matched_keywords.add(record.keyword)
                primary.raw_metadata["matched_keywords"] = sorted(matched_keywords)
                continue

            if record.keyword:
                record.raw_metadata["matched_keywords"] = [record.keyword]
            seen[key] = record
            deduplicated.append(record)

        return deduplicated, len(records) - len(deduplicated)


def main() -> None:
    """CLI entrypoint for raw collection."""
    settings.ensure_directories()
    configure_logging()
    manager = ScraperManager()
    manager.run()


if __name__ == "__main__":
    main()
