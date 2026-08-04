"""Build and persist a data-collection progress report."""

from __future__ import annotations

import json
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable

from app.core.config import settings
from app.core.logging import configure_logging, get_logger
from app.scraper.checkpoint import CheckpointStore
from app.scraper.models import ScrapeSummary
from app.storage import TweetRepository

logger = get_logger(__name__)


class CollectionStatusReporter:
    """Summarize collection progress toward the assignment target."""

    def __init__(
        self,
        *,
        repository: TweetRepository | None = None,
        checkpoint_store: CheckpointStore | None = None,
        report_path: Path | None = None,
        lookback_hours: int | None = None,
        target_tweets: int | None = None,
        recent_run_hours: int | None = None,
        required_keywords: tuple[str, ...] | None = None,
        now_provider: Callable[[], datetime] | None = None,
    ) -> None:
        self.repository = repository or TweetRepository()
        self.checkpoint_store = checkpoint_store or CheckpointStore()
        self.report_path = report_path or settings.COLLECTION_STATUS_REPORT_PATH
        self.lookback_hours = lookback_hours if lookback_hours is not None else settings.LOOKBACK_HOURS
        self.target_tweets = (
            target_tweets
            if target_tweets is not None
            else settings.COLLECTION_TARGET_TWEETS_LAST_24_HOURS
        )
        self.recent_run_hours = (
            recent_run_hours
            if recent_run_hours is not None
            else settings.COLLECTION_PROGRESS_RECENT_RUN_HOURS
        )
        self.required_keywords = required_keywords or settings.SCRAPER_KEYWORDS
        self.now_provider = now_provider or (lambda: datetime.now(timezone.utc))
        self.report_path.parent.mkdir(parents=True, exist_ok=True)

    def build_status(self, *, latest_summary: ScrapeSummary | None = None) -> dict[str, object]:
        """Build a JSON-serializable data collection status snapshot."""
        now = self._utc_now()
        checkpoint = self.checkpoint_store.load()
        progress = self.repository.load_collection_progress(
            lookback_hours=self.lookback_hours,
            target_tweets=self.target_tweets,
            required_keywords=self.required_keywords,
            recent_run_hours=self.recent_run_hours,
            now=now,
        )
        progress.update(
            {
                "status_generated_at": now.isoformat(),
                "checkpoint": {
                    "run_id": checkpoint.run_id,
                    "last_started_at": checkpoint.last_started_at,
                    "last_completed_at": checkpoint.last_completed_at,
                    "cooldown_until": checkpoint.cooldown_until,
                    "last_rate_limited_at": checkpoint.last_rate_limited_at,
                    "last_keyword": checkpoint.last_keyword,
                    "last_url": checkpoint.last_url,
                },
            }
        )
        if latest_summary is not None:
            progress["latest_summary"] = asdict(latest_summary)
        return progress

    def write_report(self, *, latest_summary: ScrapeSummary | None = None) -> Path:
        """Persist the current collection status as JSON."""
        payload = self.build_status(latest_summary=latest_summary)
        return self.save_report(payload)

    def save_report(self, payload: dict[str, object]) -> Path:
        """Persist an already-built collection status payload."""
        self.report_path.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True),
            encoding="utf-8",
        )
        logger.info("Wrote data collection status report path=%s", self.report_path)
        return self.report_path

    def read_report(self) -> dict[str, object] | None:
        """Load the latest saved report if it exists."""
        if not self.report_path.exists():
            return None
        return json.loads(self.report_path.read_text(encoding="utf-8"))

    def _utc_now(self) -> datetime:
        now = self.now_provider()
        if now.tzinfo is None:
            return now.replace(tzinfo=timezone.utc)
        return now.astimezone(timezone.utc)


def main() -> None:
    """CLI entrypoint to generate the collection progress report."""
    settings.ensure_directories()
    configure_logging()
    reporter = CollectionStatusReporter()
    path = reporter.write_report()
    print(path)


if __name__ == "__main__":
    main()
