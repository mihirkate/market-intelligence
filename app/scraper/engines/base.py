"""Common scraper engine interface."""

from __future__ import annotations

from abc import ABC, abstractmethod

from app.scraper.models import TweetRecord


class ScraperEngine(ABC):
    """Produce tweet records for a keyword."""

    name: str

    @abstractmethod
    def search(self, keyword: str, limit: int) -> list[TweetRecord]:
        """Return tweet records for a keyword."""

    def search_many(self, keywords: tuple[str, ...], limit: int) -> dict[str, list[TweetRecord]]:
        """Return tweet records for multiple keywords."""
        return {keyword: self.search(keyword, limit) for keyword in keywords}
