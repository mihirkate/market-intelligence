"""Checkpoint persistence for resumable scraping."""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field, fields
from pathlib import Path
from threading import Lock

from app.core.config import settings
from app.scraper.models import utc_now_iso


@dataclass(slots=True)
class ScrapeCheckpoint:
    """Serializable checkpoint state."""

    run_id: str | None = None
    last_started_at: str | None = None
    last_completed_at: str | None = None
    cooldown_until: str | None = None
    last_rate_limited_at: str | None = None
    last_keyword: str | None = None
    last_url: str | None = None
    tweets_collected: int = 0
    urls_discovered: int = 0
    tweets_updated: int = 0
    duplicate_tweets: int = 0
    raw_rows_written: int = 0
    parquet_rows_written: int = 0
    signal_rows_written: int = 0
    discovered_keywords: list[str] = field(default_factory=list)
    seen_tweet_urls: list[str] = field(default_factory=list)
    updated_at: str = field(default_factory=utc_now_iso)


class CheckpointStore:
    """Read and write scraper checkpoints atomically."""

    def __init__(self, path: Path | None = None) -> None:
        self.path = path or settings.CHECKPOINT_PATH
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = Lock()

    def load(self) -> ScrapeCheckpoint:
        """Load checkpoint state or return an empty checkpoint."""
        if not self.path.exists():
            return ScrapeCheckpoint()

        payload = json.loads(self.path.read_text(encoding="utf-8"))
        valid_names = {item.name for item in fields(ScrapeCheckpoint)}
        filtered = {key: value for key, value in payload.items() if key in valid_names}
        return ScrapeCheckpoint(**filtered)

    def save(self, checkpoint: ScrapeCheckpoint) -> Path:
        """Persist checkpoint state using an atomic replace."""
        checkpoint.updated_at = utc_now_iso()
        temp_path = self.path.with_suffix(".tmp")
        payload = json.dumps(asdict(checkpoint), ensure_ascii=False, indent=2)

        with self._lock:
            temp_path.write_text(payload, encoding="utf-8")
            temp_path.replace(self.path)

        return self.path

    def clear(self) -> None:
        """Delete the checkpoint file if it exists."""
        with self._lock:
            if self.path.exists():
                self.path.unlink()
