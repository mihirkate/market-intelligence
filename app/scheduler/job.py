"""Run the scraper manager as a cron-friendly, lock-protected job."""

from __future__ import annotations

import fcntl
from pathlib import Path
from typing import Callable

from app.core.config import settings
from app.core.logging import configure_logging, get_logger
from app.scraper.manager import ScraperManager
from app.scraper.models import ScrapeSummary

logger = get_logger(__name__)


class SchedulerLock:
    """Simple non-blocking filesystem lock for scheduled jobs."""

    def __init__(self, path: Path) -> None:
        self.path = path
        self._handle = None

    def acquire(self) -> bool:
        """Try to acquire the job lock without blocking."""
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._handle = self.path.open("a+", encoding="utf-8")
        try:
            fcntl.flock(self._handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            self._handle.close()
            self._handle = None
            return False
        return True

    def release(self) -> None:
        """Release the job lock if it is currently held."""
        if self._handle is None:
            return
        fcntl.flock(self._handle.fileno(), fcntl.LOCK_UN)
        self._handle.close()
        self._handle = None


def run_scheduled_scrape(
    *,
    manager_factory: Callable[[], ScraperManager] = ScraperManager,
    lock_factory: Callable[[Path], SchedulerLock] = SchedulerLock,
) -> ScrapeSummary | None:
    """Run one scheduled scrape, skipping if another instance is already active."""
    lock = lock_factory(settings.CRON_LOCK_PATH)
    if not lock.acquire():
        logger.info("Skipping scheduled scrape because lock is active path=%s", settings.CRON_LOCK_PATH)
        return None

    manager = manager_factory()
    try:
        return manager.run()
    finally:
        try:
            manager.close()
        finally:
            lock.release()


def main() -> int:
    """CLI entrypoint for the cron-targeted scraper job."""
    settings.ensure_directories()
    configure_logging()
    try:
        summary = run_scheduled_scrape()
    except Exception:
        logger.exception("Scheduled scrape failed")
        return 1

    if summary is None:
        return 0

    logger.info(
        "Scheduled scrape finished status=%s inserted=%s updated=%s duplicates=%s",
        summary.status,
        summary.tweets_collected,
        summary.tweets_updated,
        summary.duplicate_tweets,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
