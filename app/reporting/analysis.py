"""Write a compact analysis summary from the latest warehouse state."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable

import pandas as pd

from app.core.config import settings
from app.scraper.collection_status import CollectionStatusReporter
from app.scraper.models import ScrapeSummary
from app.storage import TweetRepository


class AnalysisReporter:
    """Build a readable analysis snapshot for the assignment deliverable."""

    def __init__(
        self,
        *,
        repository: TweetRepository | None = None,
        collection_status_reporter: CollectionStatusReporter | None = None,
        report_path: Path | None = None,
        lookback_hours: int | None = None,
        top_limit: int | None = None,
        now_provider: Callable[[], datetime] | None = None,
    ) -> None:
        self.repository = repository or TweetRepository()
        self.collection_status_reporter = collection_status_reporter or CollectionStatusReporter(
            repository=self.repository
        )
        self.report_path = report_path or settings.ANALYSIS_REPORT_PATH
        self.lookback_hours = lookback_hours if lookback_hours is not None else settings.LOOKBACK_HOURS
        self.top_limit = top_limit if top_limit is not None else settings.REPORT_TOP_LIMIT
        self.now_provider = now_provider or (lambda: datetime.now(timezone.utc))
        self.report_path.parent.mkdir(parents=True, exist_ok=True)

    def build_report(
        self,
        *,
        latest_summary: ScrapeSummary | None = None,
        collection_status: dict[str, object] | None = None,
    ) -> dict[str, object]:
        """Build a JSON-serializable analysis summary."""
        collection_status = collection_status or self.collection_status_reporter.build_status(
            latest_summary=latest_summary
        )
        overview = self.repository.load_dashboard_overview()
        latest_signals = self.repository.load_latest_signal_snapshot(limit=self.top_limit)
        top_influencers = self.repository.load_top_influencers(
            lookback_hours=self.lookback_hours,
            limit=self.top_limit,
            now=self._utc_now(),
        )
        hourly_volume = self.repository.load_hourly_volume(
            lookback_hours=self.lookback_hours,
            now=self._utc_now(),
        )
        signal_bias = _signal_bias_summary(latest_signals)

        return {
            "generated_at": self._utc_now().isoformat(),
            "lookback_hours": self.lookback_hours,
            "overview": overview,
            "collection": {
                "total_unique_tweets_last_24_hours": collection_status.get("total_unique_tweets_last_24_hours"),
                "unique_users_last_24_hours": collection_status.get("unique_users_last_24_hours"),
                "required_keywords_covered": collection_status.get("required_keywords_covered"),
                "missing_required_keywords": collection_status.get("missing_required_keywords"),
                "top_hashtags_last_24_hours": collection_status.get("top_hashtags_last_24_hours"),
                "keyword_counts_last_24_hours": collection_status.get("keyword_counts_last_24_hours"),
            },
            "signal_bias": signal_bias,
            "latest_signals": _frame_to_records(latest_signals),
            "top_influencers": _frame_to_records(top_influencers),
            "hourly_volume": _frame_to_records(hourly_volume),
        }

    def write_report(
        self,
        *,
        latest_summary: ScrapeSummary | None = None,
        collection_status: dict[str, object] | None = None,
    ) -> Path:
        """Persist the analysis report as JSON."""
        payload = self.build_report(
            latest_summary=latest_summary,
            collection_status=collection_status,
        )
        self.report_path.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True),
            encoding="utf-8",
        )
        return self.report_path

    def _utc_now(self) -> datetime:
        now = self.now_provider()
        if now.tzinfo is None:
            return now.replace(tzinfo=timezone.utc)
        return now.astimezone(timezone.utc)


def _signal_bias_summary(frame: pd.DataFrame) -> dict[str, object]:
    if frame.empty or "composite_signal" not in frame.columns:
        return {
            "buy_keywords": 0,
            "sell_keywords": 0,
            "neutral_keywords": 0,
            "avg_composite_signal": 0.0,
        }

    composite = frame["composite_signal"].fillna(0.0)
    return {
        "buy_keywords": int((composite > 0).sum()),
        "sell_keywords": int((composite < 0).sum()),
        "neutral_keywords": int((composite == 0).sum()),
        "avg_composite_signal": round(float(composite.mean()), 6),
    }


def _frame_to_records(frame: pd.DataFrame) -> list[dict[str, object]]:
    if frame.empty:
        return []

    rows: list[dict[str, object]] = []
    for record in frame.to_dict(orient="records"):
        normalized: dict[str, object] = {}
        for key, value in record.items():
            if isinstance(value, (list, dict)):
                normalized[key] = value
            elif pd.isna(value):
                normalized[key] = None
            else:
                normalized[key] = value
        rows.append(normalized)
    return rows
