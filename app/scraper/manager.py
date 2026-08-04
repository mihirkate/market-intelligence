"""Orchestration layer for tweet collection."""

from __future__ import annotations

from collections import deque
from dataclasses import asdict
from datetime import datetime, timedelta, timezone
import random
import time
from typing import Callable
from uuid import uuid4

from app.core.config import settings
from app.core.logging import configure_logging, get_logger
from app.processing import TweetProcessingPipeline
from app.reporting.analysis import AnalysisReporter
from app.reporting.processing import ProcessingReportWriter
from app.scraper.checkpoint import CheckpointStore, ScrapeCheckpoint
from app.scraper.collection_status import CollectionStatusReporter
from app.scraper.engines import ScraperEngine, build_scraper_engine
from app.scraper.engines.base import ScraperRateLimitError
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
        max_tweets_per_run: int | None = None,
        checkpoint_store: CheckpointStore | None = None,
        scraper_engine: ScraperEngine | None = None,
        repository: TweetRepository | None = None,
        processing_pipeline: TweetProcessingPipeline | None = None,
        signal_aggregator: KeywordSignalAggregator | None = None,
        parquet_exporter: ParquetExporter | None = None,
        raw_archive: RawTweetArchive | None = None,
        artifact_store: DebugArtifactStore | None = None,
        collection_status_reporter: CollectionStatusReporter | None = None,
        analysis_reporter: AnalysisReporter | None = None,
        processing_report_writer: ProcessingReportWriter | None = None,
        startup_jitter_min_seconds: int | None = None,
        startup_jitter_max_seconds: int | None = None,
        rate_limit_cooldown_min_seconds: int | None = None,
        rate_limit_cooldown_max_seconds: int | None = None,
        sleep_fn: Callable[[float], None] | None = None,
        randint_fn: Callable[[int, int], int] | None = None,
        now_provider: Callable[[], datetime] | None = None,
    ) -> None:
        self.keywords = keywords or settings.SCRAPER_KEYWORDS
        self.discovery_limit = (
            discovery_limit
            if discovery_limit is not None
            else settings.DISCOVERY_LIMIT_PER_KEYWORD
        )
        self.target_tweets = (
            target_tweets
            if target_tweets is not None
            else max_tweets_per_run
            if max_tweets_per_run is not None
            else settings.MAX_TWEETS_PER_RUN
        )
        self.checkpoint_store = checkpoint_store or CheckpointStore()
        self.scraper_engine = scraper_engine or build_scraper_engine()
        self.repository = repository or TweetRepository()
        self.processing_pipeline = processing_pipeline or TweetProcessingPipeline()
        self.signal_aggregator = signal_aggregator or KeywordSignalAggregator()
        self.parquet_exporter = parquet_exporter or ParquetExporter()
        self.raw_archive = raw_archive or RawTweetArchive()
        self.artifact_store = artifact_store or DebugArtifactStore()
        self.startup_jitter_min_seconds = (
            startup_jitter_min_seconds
            if startup_jitter_min_seconds is not None
            else settings.RUN_STARTUP_JITTER_MIN_SECONDS
        )
        self.startup_jitter_max_seconds = (
            startup_jitter_max_seconds
            if startup_jitter_max_seconds is not None
            else settings.RUN_STARTUP_JITTER_MAX_SECONDS
        )
        self.rate_limit_cooldown_min_seconds = (
            rate_limit_cooldown_min_seconds
            if rate_limit_cooldown_min_seconds is not None
            else settings.RATE_LIMIT_COOLDOWN_MIN_SECONDS
        )
        self.rate_limit_cooldown_max_seconds = (
            rate_limit_cooldown_max_seconds
            if rate_limit_cooldown_max_seconds is not None
            else settings.RATE_LIMIT_COOLDOWN_MAX_SECONDS
        )
        self.sleep_fn = sleep_fn or time.sleep
        self.randint_fn = randint_fn or random.randint
        self.now_provider = now_provider or (lambda: datetime.now(timezone.utc))
        self.collection_status_reporter = collection_status_reporter or CollectionStatusReporter(
            repository=self.repository,
            checkpoint_store=self.checkpoint_store,
            required_keywords=self.keywords,
            now_provider=self.now_provider,
        )
        self.analysis_reporter = analysis_reporter or AnalysisReporter(
            repository=self.repository,
            collection_status_reporter=self.collection_status_reporter,
            now_provider=self.now_provider,
        )
        self.processing_report_writer = processing_report_writer or ProcessingReportWriter()
        self.summary = ScrapeSummary()
        self._started_at: str | None = None
        self._last_keyword: str | None = None
        self._last_url: str | None = None
        self._cooldown_until: str | None = None

    def run(self) -> ScrapeSummary:
        """Run the configured scraping engine and persist fresh data."""
        checkpoint = self.checkpoint_store.load()
        self._restore_checkpoint(checkpoint)
        cooldown_until = self._parse_utc_datetime(checkpoint.cooldown_until)
        now = self._utc_now()
        if cooldown_until and cooldown_until > now:
            logger.info(
                "Skipping scraper run because cooldown is active until=%s",
                checkpoint.cooldown_until,
            )
            self.summary = ScrapeSummary(
                status="cooldown",
                cooldown_until=checkpoint.cooldown_until,
            )
            self._write_operational_reports()
            return self.summary

        self._cooldown_until = None
        self.summary = ScrapeSummary(run_id=uuid4().hex)
        self.summary.status = "starting"
        self.summary.startup_delay_seconds = self._maybe_apply_startup_jitter()
        self._started_at = utc_now_iso()
        self._last_keyword = None
        self._last_url = None
        self.summary.status = "running"
        self.repository.record_run_start(
            run_id=self.summary.run_id,
            keywords=self.keywords,
            target_tweets=self.target_tweets,
        )
        self._save_checkpoint()

        logger.info(
            "Starting scraper keywords=%s batch_limit=%s engine=%s startup_delay=%ss",
            list(self.keywords),
            self.target_tweets,
            self.scraper_engine.name,
            self.summary.startup_delay_seconds,
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
            self.summary.status = "completed"
            self.summary.cooldown_until = None
            self._save_checkpoint(completed=True)
            self.repository.finalize_run(self.summary)
            self._write_operational_reports()
            logger.info("Scrape finished summary=%s", asdict(self.summary))
            return self.summary
        except ScraperRateLimitError as error:
            return self._handle_rate_limit(error)
        except Exception as error:
            self.summary.status = "failed"
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
            self._write_operational_reports()
            raise

    def close(self) -> None:
        """Release resources owned by the manager."""
        close = getattr(self.repository, "close", None)
        if callable(close):
            close()

    def _restore_checkpoint(self, checkpoint: ScrapeCheckpoint) -> None:
        self._last_keyword = checkpoint.last_keyword
        self._last_url = checkpoint.last_url
        self._cooldown_until = checkpoint.cooldown_until

    def _save_checkpoint(self, *, completed: bool = False, rate_limited: bool = False) -> None:
        checkpoint = ScrapeCheckpoint(
            run_id=self.summary.run_id,
            last_started_at=self._started_at,
            last_completed_at=None,
            cooldown_until=self._cooldown_until,
            last_rate_limited_at=None,
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
            checkpoint.last_completed_at = utc_now_iso()
        if rate_limited:
            checkpoint.last_rate_limited_at = utc_now_iso()
        self.checkpoint_store.save(checkpoint)

    def _handle_rate_limit(self, error: ScraperRateLimitError) -> ScrapeSummary:
        cooldown_until = self._resolve_cooldown_until(error.cooldown_until)
        self._cooldown_until = cooldown_until
        self.summary.status = "cooldown"
        self.summary.rate_limit_events += 1
        self.summary.cooldown_until = cooldown_until
        artifact_path = self.artifact_store.write_event(
            "scrape_rate_limited",
            run_id=self.summary.run_id,
            payload={
                "engine": self.scraper_engine.name,
                "keywords": list(self.keywords),
                "batch_limit": self.target_tweets,
                "cooldown_until": cooldown_until,
                "account_states": error.account_states,
                "summary": asdict(self.summary),
            },
            error=error,
        )
        self.repository.finalize_run(
            self.summary,
            status="cooldown",
            notes=f"{error} | cooldown_until={cooldown_until} | artifact={artifact_path}",
        )
        self._save_checkpoint(completed=True, rate_limited=True)
        self._write_operational_reports()
        logger.warning(
            "Scrape hit rate limit run=%s cooldown_until=%s artifact=%s",
            self.summary.run_id,
            cooldown_until,
            artifact_path,
        )
        return self.summary

    def _write_operational_reports(self, summary: ScrapeSummary | None = None) -> None:
        try:
            active_summary = summary or self.summary
            status_payload = self.collection_status_reporter.build_status(latest_summary=active_summary)
            self.collection_status_reporter.save_report(status_payload)
            self.processing_report_writer.write_report(
                summary=active_summary,
                collection_status=status_payload,
            )
            self.analysis_reporter.write_report(
                latest_summary=active_summary,
                collection_status=status_payload,
            )
        except Exception as error:  # noqa: BLE001
            logger.warning("Failed to write operational reports error=%s", error)

    def _maybe_apply_startup_jitter(self) -> int:
        lower, upper = self._normalized_bounds(
            self.startup_jitter_min_seconds,
            self.startup_jitter_max_seconds,
        )
        if upper <= 0:
            return 0

        delay_seconds = self.randint_fn(lower, upper)
        if delay_seconds <= 0:
            return 0

        logger.info("Applying startup jitter seconds=%s", delay_seconds)
        self.sleep_fn(delay_seconds)
        return delay_seconds

    def _resolve_cooldown_until(self, engine_cooldown_until: datetime | None) -> str:
        now = self._utc_now()
        lower, upper = self._normalized_bounds(
            self.rate_limit_cooldown_min_seconds,
            self.rate_limit_cooldown_max_seconds,
        )
        random_delay_seconds = self.randint_fn(lower, upper) if upper > 0 else 0
        random_cooldown_until = now + timedelta(seconds=random_delay_seconds)
        effective_until = random_cooldown_until
        if engine_cooldown_until is not None and engine_cooldown_until > effective_until:
            effective_until = engine_cooldown_until
        return effective_until.isoformat()

    def _normalized_bounds(self, lower: int, upper: int) -> tuple[int, int]:
        if lower < 0:
            lower = 0
        if upper < lower:
            upper = lower
        return lower, upper

    def _utc_now(self) -> datetime:
        now = self.now_provider()
        if now.tzinfo is None:
            return now.replace(tzinfo=timezone.utc)
        return now.astimezone(timezone.utc)

    def _parse_utc_datetime(self, value: str | None) -> datetime | None:
        if not value:
            return None
        parsed = datetime.fromisoformat(value)
        if parsed.tzinfo is None:
            return parsed.replace(tzinfo=timezone.utc)
        return parsed.astimezone(timezone.utc)

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
    try:
        manager.run()
    finally:
        manager.close()


if __name__ == "__main__":
    main()
