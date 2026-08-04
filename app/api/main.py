"""FastAPI application entrypoint."""

from __future__ import annotations

from contextlib import asynccontextmanager
import json

from fastapi import FastAPI, Request

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
