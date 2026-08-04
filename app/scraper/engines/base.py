"""Common scraper engine interface."""

from __future__ import annotations

from abc import ABC, abstractmethod
from datetime import datetime

from app.scraper.models import TweetRecord


class ScraperRateLimitError(RuntimeError):
    """Raised when the scraper is temporarily blocked by upstream rate limits."""

    def __init__(
        self,
        message: str,
        *,
        cooldown_until: datetime | None = None,
        account_states: list[dict[str, object]] | None = None,
    ) -> None:
        super().__init__(message)
        self.cooldown_until = cooldown_until
        self.account_states = account_states or []


class ScraperEngine(ABC):
    """Produce tweet records for a keyword."""

    name: str

    @abstractmethod
    def search(self, keyword: str, limit: int) -> list[TweetRecord]:
        """Return tweet records for a keyword."""

    def search_many(self, keywords: tuple[str, ...], limit: int) -> dict[str, list[TweetRecord]]:
        """Return tweet records for multiple keywords."""
        return {keyword: self.search(keyword, limit) for keyword in keywords}
