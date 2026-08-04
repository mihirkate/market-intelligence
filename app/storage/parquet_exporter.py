"""Chunked parquet export for tweets and aggregated signals."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Sequence

import pyarrow as pa
import pyarrow.parquet as pq

from app.core.config import settings
from app.scraper.models import KeywordSignal, ProcessedTweetRecord
from app.storage.serialization import serialize_keyword_signal, serialize_processed_record


class ParquetExporter:
    """Write bounded parquet chunks for scalable downstream analytics."""

    def __init__(
        self,
        *,
        tweets_path: Path | None = None,
        signals_path: Path | None = None,
        chunk_size: int | None = None,
    ) -> None:
        self.tweets_path = tweets_path or settings.PARQUET_TWEETS_PATH
        self.signals_path = signals_path or settings.PARQUET_SIGNALS_PATH
        self.chunk_size = chunk_size if chunk_size is not None else settings.PARQUET_CHUNK_SIZE
        self.tweets_path.mkdir(parents=True, exist_ok=True)
        self.signals_path.mkdir(parents=True, exist_ok=True)

    def write_tweets(self, records: Sequence[ProcessedTweetRecord], *, run_id: str) -> int:
        """Write only newly inserted tweets as append-only parquet chunks."""
        rows = [serialize_processed_record(record) for record in records]
        self._write_rows(rows, base_path=self.tweets_path, run_id=run_id)
        return len(rows)

    def write_signals(self, signals: Sequence[KeywordSignal], *, run_id: str) -> int:
        """Write keyword signals as parquet chunks."""
        rows = [serialize_keyword_signal(signal) for signal in signals]
        self._write_rows(rows, base_path=self.signals_path, run_id=run_id)
        return len(rows)

    def _write_rows(self, rows: Sequence[dict], *, base_path: Path, run_id: str) -> None:
        if not rows:
            return

        grouped: dict[str, list[dict]] = {}
        for row in rows:
            date_key = row.get("scrape_date") or row.get("generated_date") or "unknown"
            grouped.setdefault(str(date_key), []).append(row)

        for date_key, grouped_rows in grouped.items():
            target_dir = base_path / f"date={date_key}"
            target_dir.mkdir(parents=True, exist_ok=True)
            for index, chunk in enumerate(_chunked_rows(grouped_rows, self.chunk_size)):
                target_file = target_dir / f"{run_id}-part-{index:04d}.parquet"
                table = pa.Table.from_pylist([_ensure_arrow_scalars(row) for row in chunk])
                pq.write_table(table, target_file, compression="zstd")


def _chunked_rows(rows: Sequence[dict], size: int) -> list[Sequence[dict]]:
    return [rows[index : index + size] for index in range(0, len(rows), size)]


def _ensure_arrow_scalars(row: dict) -> dict:
    normalized: dict[str, object] = {}
    for key, value in row.items():
        if isinstance(value, (dict, list)):
            normalized[key] = json.dumps(value, ensure_ascii=False, sort_keys=True)
        else:
            normalized[key] = value
    return normalized
