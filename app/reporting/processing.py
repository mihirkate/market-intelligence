"""Write a small, human-readable processing report after each scrape run."""

from __future__ import annotations

import json
from pathlib import Path

from app.core.config import settings
from app.scraper.models import ScrapeSummary, utc_now_iso


class ProcessingReportWriter:
    """Persist the latest scrape run as a compact processing summary."""

    def __init__(self, *, report_path: Path | None = None) -> None:
        self.report_path = report_path or settings.PROCESSING_REPORT_PATH
        self.report_path.parent.mkdir(parents=True, exist_ok=True)

    def build_report(
        self,
        *,
        summary: ScrapeSummary,
        collection_status: dict[str, object] | None = None,
    ) -> dict[str, object]:
        """Build a small JSON report describing the latest scrape run."""
        report = {
            "generated_at": utc_now_iso(),
            "run_id": summary.run_id,
            "status": summary.status,
            "cooldown_until": summary.cooldown_until,
            "startup_delay_seconds": summary.startup_delay_seconds,
            "rate_limit_events": summary.rate_limit_events,
            "raw": summary.raw_rows_written,
            "selected": summary.urls_discovered,
            "valid": summary.tweets_collected + summary.tweets_updated,
            "inserted": summary.tweets_collected,
            "updated": summary.tweets_updated,
            "duplicates": summary.duplicate_tweets,
            "invalid": max(summary.raw_rows_written - summary.urls_discovered, 0),
            "stored": summary.tweets_collected,
            "parquet_rows": summary.parquet_rows_written,
            "signal_rows": summary.signal_rows_written,
            "keywords_processed": list(summary.keywords_processed),
            "providers_used": list(summary.providers_used),
            "paths": {
                "raw_output": str(settings.RAW_OUTPUT),
                "parquet_tweets": str(settings.PARQUET_TWEETS_PATH),
                "parquet_signals": str(settings.PARQUET_SIGNALS_PATH),
            },
        }
        if collection_status is not None:
            report["collection_status"] = {
                "total_unique_tweets_last_24_hours": collection_status.get("total_unique_tweets_last_24_hours"),
                "remaining_tweets_to_target": collection_status.get("remaining_tweets_to_target"),
                "assignment_data_collection_ready": collection_status.get("assignment_data_collection_ready"),
                "recent_tweets_per_hour": collection_status.get("recent_tweets_per_hour"),
                "required_tweets_per_hour_for_target": collection_status.get("required_tweets_per_hour_for_target"),
                "recent_vs_required_rate_ratio": collection_status.get("recent_vs_required_rate_ratio"),
            }
        return report

    def write_report(
        self,
        *,
        summary: ScrapeSummary,
        collection_status: dict[str, object] | None = None,
    ) -> Path:
        """Write the current processing report to disk."""
        payload = self.build_report(summary=summary, collection_status=collection_status)
        self.report_path.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True),
            encoding="utf-8",
        )
        return self.report_path
