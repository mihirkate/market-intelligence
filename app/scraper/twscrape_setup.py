"""One-time account bootstrap for the twscrape engine."""

from __future__ import annotations

from app.core.config import settings
from app.core.logging import configure_logging, get_logger
from app.scraper.engines.twscrape_engine import TwscrapeEngine

logger = get_logger(__name__)


def main() -> None:
    """Seed the local twscrape account DB from configured env values."""
    settings.ensure_directories()
    configure_logging()

    engine = TwscrapeEngine()
    engine.bootstrap_account(force=True)
    logger.info("twscrape account bootstrap completed db=%s", settings.TWSCRAPE_ACCOUNTS_DB)


if __name__ == "__main__":
    main()
