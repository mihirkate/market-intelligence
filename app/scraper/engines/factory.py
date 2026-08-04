"""Construct scraper engines from runtime configuration."""

from __future__ import annotations

from app.core.config import settings
from app.scraper.engines.base import ScraperEngine
from app.scraper.engines.twscrape_engine import TwscrapeEngine


def build_scraper_engine() -> ScraperEngine:
    """Create the configured scraper engine."""
    if settings.SCRAPER_ENGINE == "twscrape":
        return TwscrapeEngine()

    raise ValueError(
        f"Unsupported SCRAPER_ENGINE={settings.SCRAPER_ENGINE!r}. Supported engines: twscrape."
    )
