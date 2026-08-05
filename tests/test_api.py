from __future__ import annotations

import json
from pathlib import Path

from fastapi.testclient import TestClient

import app.api.main as api_main


class FakeRepository:
    def __init__(self) -> None:
        self.closed = False

    def ping(self) -> dict[str, object]:
        return {
            "ok": True,
            "database": "market-intelligence",
            "collections": {
                "tweets": "tweets",
                "runs": "scrape_runs",
                "signals": "keyword_signals",
            },
        }

    def close(self) -> None:
        self.closed = True

    def load_dashboard_overview(self) -> dict[str, object]:
        return {
            "total_tweets": 42,
            "unique_users": 10,
            "tracked_keywords": 4,
            "latest_seen_at": "2026-08-04T12:00:00+00:00",
            "latest_run": {
                "run_id": "run-1",
                "status": "completed",
                "fetched_count": 50,
                "inserted_count": 8,
                "updated_count": 5,
                "duplicate_count": 2,
            },
        }


class FakeReporter:
    def __init__(self, repository=None) -> None:
        self.repository = repository

    def build_status(self, latest_summary=None) -> dict[str, object]:
        return {
            "total_unique_tweets_last_24_hours": 42,
            "target_tweets_last_24_hours": 2000,
            "assignment_data_collection_ready": False,
            "remaining_tweets_to_target": 1958,
            "projected_24h_tweets_recent_rate": 120,
            "recent_rate_limit_events": 3,
            "recent_tweets_per_hour": 55.5,
            "required_tweets_per_hour_for_target": 83.3,
            "missing_required_keywords": ["#banknifty"],
        }


class FakeAnalysisReporter:
    def build_report(self) -> dict[str, object]:
        return {
            "signal_bias": {"buy_keywords": 2, "sell_keywords": 1},
            "latest_signals": [{"keyword": "#nifty50", "composite_signal": 0.2}],
        }


def test_health_endpoint_reports_mongodb_status(monkeypatch) -> None:
    repository = FakeRepository()
    reporter = FakeReporter(repository=repository)
    analysis_reporter = FakeAnalysisReporter()
    monkeypatch.setattr(api_main, "TweetRepository", lambda: repository)
    monkeypatch.setattr(api_main, "CollectionStatusReporter", lambda repository=None: reporter)
    monkeypatch.setattr(
        api_main,
        "AnalysisReporter",
        lambda repository=None, collection_status_reporter=None: analysis_reporter,
    )

    with TestClient(api_main.app) as client:
        response = client.get("/health")

    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "running"
    assert payload["mongodb"]["ok"] is True
    assert repository.closed is True


def test_stats_endpoint_returns_overview_and_collection_status(monkeypatch) -> None:
    repository = FakeRepository()
    reporter = FakeReporter(repository=repository)
    analysis_reporter = FakeAnalysisReporter()
    monkeypatch.setattr(api_main, "TweetRepository", lambda: repository)
    monkeypatch.setattr(api_main, "CollectionStatusReporter", lambda repository=None: reporter)
    monkeypatch.setattr(
        api_main,
        "AnalysisReporter",
        lambda repository=None, collection_status_reporter=None: analysis_reporter,
    )

    with TestClient(api_main.app) as client:
        response = client.get("/stats")

    assert response.status_code == 200
    payload = response.json()
    assert payload["overview"]["total_tweets"] == 42
    assert payload["collection"]["total_unique_tweets_last_24_hours"] == 42
    assert payload["collection"]["assignment_data_collection_ready"] is False


def test_dashboard_state_endpoint_returns_lightweight_refresh_payload(monkeypatch) -> None:
    repository = FakeRepository()
    reporter = FakeReporter(repository=repository)
    analysis_reporter = FakeAnalysisReporter()
    monkeypatch.setattr(api_main, "TweetRepository", lambda: repository)
    monkeypatch.setattr(api_main, "CollectionStatusReporter", lambda repository=None: reporter)
    monkeypatch.setattr(
        api_main,
        "AnalysisReporter",
        lambda repository=None, collection_status_reporter=None: analysis_reporter,
    )

    with TestClient(api_main.app) as client:
        response = client.get("/dashboard-state")

    assert response.status_code == 200
    payload = response.json()
    assert payload["total_tweets"] == 42
    assert payload["latest_seen_at"] == "2026-08-04T12:00:00+00:00"
    assert payload["latest_run_id"] == "run-1"
    assert payload["latest_run_status"] == "completed"
    assert response.headers["cache-control"] == "no-store"


def test_analysis_and_performance_endpoints_return_reports(monkeypatch, tmp_path: Path) -> None:
    repository = FakeRepository()
    reporter = FakeReporter(repository=repository)
    analysis_reporter = FakeAnalysisReporter()
    performance_path = tmp_path / "performance_benchmark.json"
    performance_path.write_text(
        json.dumps({"scenarios": [{"record_count": 10, "total_seconds": 0.1}]}),
        encoding="utf-8",
    )

    monkeypatch.setattr(api_main, "TweetRepository", lambda: repository)
    monkeypatch.setattr(api_main, "CollectionStatusReporter", lambda repository=None: reporter)
    monkeypatch.setattr(
        api_main,
        "AnalysisReporter",
        lambda repository=None, collection_status_reporter=None: analysis_reporter,
    )
    original_path = api_main.settings.PERFORMANCE_REPORT_PATH
    object.__setattr__(api_main.settings, "PERFORMANCE_REPORT_PATH", performance_path)
    try:
        with TestClient(api_main.app) as client:
            analysis_response = client.get("/analysis-summary")
            performance_response = client.get("/performance-benchmark")
    finally:
        object.__setattr__(api_main.settings, "PERFORMANCE_REPORT_PATH", original_path)

    assert analysis_response.status_code == 200
    assert performance_response.status_code == 200
    assert analysis_response.json()["signal_bias"]["buy_keywords"] == 2
    assert performance_response.json()["scenarios"][0]["record_count"] == 10
