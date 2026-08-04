"""Scraping components."""

__all__ = ["ScraperManager"]


def __getattr__(name: str):
    if name == "ScraperManager":
        from app.scraper.manager import ScraperManager

        return ScraperManager
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
