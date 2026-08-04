"""Benchmark the processing pipeline at multiple scales."""

from __future__ import annotations

import json
from pathlib import Path
from tempfile import TemporaryDirectory
from time import perf_counter
import tracemalloc
from uuid import uuid4

import mongomock

from app.core.config import settings
from app.core.logging import configure_logging
from app.processing import TweetProcessingPipeline
from app.scraper.models import TweetRecord, utc_now_iso
from app.signals import KeywordSignalAggregator
from app.storage import ParquetExporter, TweetRepository


class PerformanceBenchmarkRunner:
    """Measure throughput and peak memory for the local analytics pipeline."""

    def __init__(
        self,
        *,
        record_counts: tuple[int, ...] | None = None,
        report_path: Path | None = None,
    ) -> None:
        self.record_counts = record_counts or settings.BENCHMARK_RECORD_COUNTS
        self.report_path = report_path or settings.PERFORMANCE_REPORT_PATH
        self.report_path.parent.mkdir(parents=True, exist_ok=True)

    def build_report(self) -> dict[str, object]:
        """Run the benchmark suite and return a JSON-serializable report."""
        sample_pipeline = TweetProcessingPipeline()
        scenarios = [self._run_scenario(record_count) for record_count in self.record_counts]
        baseline = scenarios[0] if scenarios else None
        largest = scenarios[-1] if scenarios else None

        summary = {
            "generated_at": utc_now_iso(),
            "record_counts": list(self.record_counts),
            "storage_backend": "mongomock + parquet",
            "processing_workers": sample_pipeline.max_workers,
            "scenarios": scenarios,
            "scale_summary": {},
        }
        if baseline and largest and baseline["record_count"] > 0:
            summary["scale_summary"] = {
                "largest_record_count": largest["record_count"],
                "throughput_ratio_vs_smallest": round(
                    largest["records_per_second_total"] / max(baseline["records_per_second_total"], 1e-9),
                    6,
                ),
                "peak_memory_ratio_vs_smallest": round(
                    largest["peak_memory_mb"] / max(baseline["peak_memory_mb"], 1e-9),
                    6,
                ),
                "notes": [
                    "Processing uses bounded worker pools.",
                    "Parquet export writes chunked files instead of one large file.",
                    "Benchmark uses in-memory Mongo mocking to isolate pipeline cost.",
                ],
            }
        return summary

    def write_report(self) -> Path:
        """Run the benchmark and persist the result as JSON."""
        payload = self.build_report()
        self.report_path.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True),
            encoding="utf-8",
        )
        return self.report_path

    def _run_scenario(self, record_count: int) -> dict[str, object]:
        records = _build_synthetic_records(record_count)
        pipeline = TweetProcessingPipeline(max_workers=min(4, settings.KEYWORD_CONCURRENCY or 1))
        aggregator = KeywordSignalAggregator()
        repository = TweetRepository(
            client=mongomock.MongoClient(),
            database_name=f"benchmark-{record_count}",
        )

        with TemporaryDirectory() as temp_dir:
            exporter = ParquetExporter(
                tweets_path=Path(temp_dir) / "tweets",
                signals_path=Path(temp_dir) / "signals",
                chunk_size=min(settings.PARQUET_CHUNK_SIZE, max(1, record_count)),
            )
            run_id = uuid4().hex
            tracemalloc.start()
            total_started = perf_counter()

            processing_started = perf_counter()
            processed = pipeline.process_records(records)
            processing_seconds = perf_counter() - processing_started

            signal_started = perf_counter()
            signals = aggregator.aggregate(processed, run_id=run_id)
            signal_seconds = perf_counter() - signal_started

            storage_started = perf_counter()
            storage_result = repository.upsert_tweets(processed, run_id=run_id)
            repository.replace_keyword_signals(signals)
            parquet_tweet_rows = exporter.write_tweets(storage_result.inserted_records, run_id=run_id)
            parquet_signal_rows = exporter.write_signals(signals, run_id=run_id)
            storage_seconds = perf_counter() - storage_started

            total_seconds = perf_counter() - total_started
            _, peak_memory_bytes = tracemalloc.get_traced_memory()
            tracemalloc.stop()

        repository.close()
        records_per_second = record_count / max(total_seconds, 1e-9)
        return {
            "record_count": record_count,
            "processing_seconds": round(processing_seconds, 6),
            "signal_seconds": round(signal_seconds, 6),
            "storage_seconds": round(storage_seconds, 6),
            "total_seconds": round(total_seconds, 6),
            "records_per_second_total": round(records_per_second, 3),
            "peak_memory_mb": round(peak_memory_bytes / (1024 * 1024), 3),
            "inserted_records": storage_result.inserted_count,
            "signal_count": len(signals),
            "parquet_tweet_rows": parquet_tweet_rows,
            "parquet_signal_rows": parquet_signal_rows,
        }


def _build_synthetic_records(record_count: int) -> list[TweetRecord]:
    keywords = ("#nifty50", "#sensex", "#intraday", "#banknifty")
    templates = (
        "Bullish breakout on {keyword} with strong momentum and institutional buying",
        "Bearish correction on {keyword} after weak global cues and profit booking",
        "Intraday traders watching support and resistance on {keyword} closely",
        "Options data suggests volatility expansion in {keyword} into close",
    )
    records: list[TweetRecord] = []
    for index in range(record_count):
        keyword = keywords[index % len(keywords)]
        content = templates[index % len(templates)].format(keyword=keyword)
        records.append(
            TweetRecord(
                tweet_url=f"https://x.com/demo/status/{record_count}-{index}",
                tweet_id=f"{record_count}{index:05d}",
                username=f"user_{index % 250}",
                display_name=f"User {index % 250}",
                timestamp_utc="2026-08-04T12:00:00+00:00",
                content=content,
                replies=index % 8,
                reposts=index % 5,
                likes=5 + (index % 21),
                views=50 + (index % 200),
                mentions=[f"@desk{index % 7}"],
                hashtags=[keyword, "#stockmarket"],
                keyword=keyword,
                provider="benchmark",
                raw_metadata={"lang": "en"},
            )
        )
    return records


def main() -> None:
    """CLI entrypoint for writing a performance benchmark report."""
    settings.ensure_directories()
    configure_logging()
    runner = PerformanceBenchmarkRunner()
    path = runner.write_report()
    print(path)


if __name__ == "__main__":
    main()
