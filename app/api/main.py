"""FastAPI application entrypoint."""

from __future__ import annotations

from contextlib import asynccontextmanager
import json

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
import pandas as pd

from app.core.config import settings
from app.core.logging import configure_logging, get_logger
from app.reporting.analysis import AnalysisReporter
from app.scraper.collection_status import CollectionStatusReporter
from app.storage import TweetRepository


def _get_repository(request: Request) -> TweetRepository:
    return request.app.state.repository


def _get_reporter(request: Request) -> CollectionStatusReporter:
    return request.app.state.collection_status_reporter


def _get_analysis_reporter(request: Request) -> AnalysisReporter:
    return request.app.state.analysis_reporter


def _signal_bias_summary(frame: pd.DataFrame) -> dict[str, object]:
    """Return a compact signal-bias summary for lightweight dashboard polling."""
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


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Initialize shared resources for the API lifecycle."""
    settings.ensure_directories()
    configure_logging()
    logger = get_logger(__name__)
    repository = TweetRepository()
    mongo_health = repository.ping()
    reporter = CollectionStatusReporter(repository=repository)
    analysis_reporter = AnalysisReporter(
        repository=repository,
        collection_status_reporter=reporter,
    )
    app.state.repository = repository
    app.state.collection_status_reporter = reporter
    app.state.analysis_reporter = analysis_reporter
    logger.info("App Started")
    logger.info("Scraper Initialized")
    logger.info("MongoDB Ready database=%s", mongo_health["database"])
    try:
        yield
    finally:
        repository.close()


app = FastAPI(title=settings.APP_NAME, lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["GET"],
    allow_headers=["*"],
)


@app.get("/")
def read_status() -> dict[str, str]:
    """Return the current application status."""
    return {"status": settings.API_STATUS}


@app.get("/health")
def read_health(request: Request) -> dict[str, object]:
    """Return service health including MongoDB connectivity."""
    repository = _get_repository(request)
    return {
        "status": settings.API_STATUS,
        "app_name": settings.APP_NAME,
        "mongodb": repository.ping(),
        "collection_status_report_path": str(settings.COLLECTION_STATUS_REPORT_PATH),
    }


@app.get("/stats")
def read_stats(request: Request) -> dict[str, object]:
    """Return operational stats and collection progress."""
    repository = _get_repository(request)
    reporter = _get_reporter(request)
    return {
        "status": settings.API_STATUS,
        "overview": repository.load_dashboard_overview(),
        "collection": reporter.build_status(),
    }


@app.get("/dashboard-state")
def read_dashboard_state(request: Request) -> JSONResponse:
    """Return a lightweight dashboard refresh payload."""
    repository = _get_repository(request)
    overview = repository.load_dashboard_overview()
    latest_run = overview.get("latest_run") or {}
    payload = {
        "total_tweets": int(overview.get("total_tweets") or 0),
        "latest_seen_at": overview.get("latest_seen_at"),
        "latest_run_id": latest_run.get("run_id"),
        "latest_run_status": latest_run.get("status"),
    }
    return JSONResponse(payload, headers={"Cache-Control": "no-store"})


@app.get("/dashboard-summary")
def read_dashboard_summary(request: Request) -> JSONResponse:
    """Return the compact numeric dashboard summary for in-place metric updates."""
    repository = _get_repository(request)
    reporter = _get_reporter(request)
    overview = repository.load_dashboard_overview()
    collection_status = reporter.read_report() or reporter.build_status()
    latest_signals = repository.load_latest_signal_snapshot(limit=settings.REPORT_TOP_LIMIT)
    latest_run = overview.get("latest_run") or {}
    payload = {
        "overview": {
            "total_tweets": int(overview.get("total_tweets") or 0),
            "unique_users": int(overview.get("unique_users") or 0),
            "tracked_keywords": int(overview.get("tracked_keywords") or 0),
            "latest_seen_at": overview.get("latest_seen_at"),
        },
        "latest_run": {
            "run_id": latest_run.get("run_id"),
            "status": latest_run.get("status"),
            "fetched_count": int(latest_run.get("fetched_count") or 0),
            "inserted_count": int(latest_run.get("inserted_count") or 0),
            "updated_count": int(latest_run.get("updated_count") or 0),
            "duplicate_count": int(latest_run.get("duplicate_count") or 0),
        },
        "collection": {
            "total_unique_tweets_last_24_hours": int(
                collection_status.get("total_unique_tweets_last_24_hours", 0) or 0
            ),
            "remaining_tweets_to_target": int(
                collection_status.get("remaining_tweets_to_target", 0) or 0
            ),
            "projected_24h_tweets_recent_rate": int(
                collection_status.get("projected_24h_tweets_recent_rate", 0) or 0
            ),
            "recent_rate_limit_events": int(
                collection_status.get("recent_rate_limit_events", 0) or 0
            ),
            "recent_tweets_per_hour": float(
                collection_status.get("recent_tweets_per_hour", 0) or 0
            ),
            "required_tweets_per_hour_for_target": float(
                collection_status.get("required_tweets_per_hour_for_target", 0) or 0
            ),
            "target_tweets_last_24_hours": int(
                collection_status.get("target_tweets_last_24_hours", 0) or 0
            ),
            "assignment_data_collection_ready": bool(
                collection_status.get("assignment_data_collection_ready", False)
            ),
            "missing_required_keywords": collection_status.get("missing_required_keywords") or [],
        },
        "signal_bias": _signal_bias_summary(latest_signals),
    }
    return JSONResponse(payload, headers={"Cache-Control": "no-store"})


@app.get("/collection-status")
def read_collection_status(request: Request) -> dict[str, object]:
    """Return the latest collection progress report."""
    reporter = _get_reporter(request)
    return reporter.build_status()


@app.get("/analysis-summary")
def read_analysis_summary(request: Request) -> dict[str, object]:
    """Return the latest analytics snapshot used by the dashboard."""
    reporter = _get_analysis_reporter(request)
    return reporter.build_report()


@app.get("/performance-benchmark")
def read_performance_benchmark() -> dict[str, object]:
    """Return the last saved performance benchmark report if it exists."""
    if not settings.PERFORMANCE_REPORT_PATH.exists():
        return {
            "status": "not-generated",
            "report_path": str(settings.PERFORMANCE_REPORT_PATH),
        }
    return json.loads(settings.PERFORMANCE_REPORT_PATH.read_text(encoding="utf-8"))
