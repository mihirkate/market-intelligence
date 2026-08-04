"""Append-only raw JSONL storage for fetched tweet records."""

from __future__ import annotations

import json
from collections import defaultdict
from pathlib import Path
from threading import Lock
from typing import Sequence

from app.core.config import settings
from app.scraper.models import TweetRecord


class RawTweetArchive:
    """Persist raw fetched tweets as newline-delimited JSON grouped by run and date."""

    def __init__(self, *, output_dir: Path | None = None) -> None:
        self.output_dir = output_dir or settings.RAW_OUTPUT
        self.output_dir.mkdir(parents=True, exist_ok=True)
        self._lock = Lock()

    def write_records(self, records: Sequence[TweetRecord], *, run_id: str) -> int:
        """Append all fetched records to run-scoped JSONL files."""
        if not records:
            return 0

        grouped: dict[str, list[TweetRecord]] = defaultdict(list)
        for record in records:
            date_key = (record.timestamp_utc or record.scraped_at)[:10]
            grouped[date_key].append(record)

        rows_written = 0
        with self._lock:
            for date_key, items in grouped.items():
                target_dir = self.output_dir / f"date={date_key}"
                target_dir.mkdir(parents=True, exist_ok=True)
                target_file = target_dir / f"{run_id}.jsonl"
                with target_file.open("a", encoding="utf-8") as file_handle:
                    for record in items:
                        payload = {"run_id": run_id, **record.to_dict()}
                        file_handle.write(json.dumps(payload, ensure_ascii=False, sort_keys=True))
                        file_handle.write("\n")
                        rows_written += 1
        return rows_written
