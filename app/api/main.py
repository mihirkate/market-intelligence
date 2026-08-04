"""FastAPI application entrypoint."""

from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.core.config import settings
from app.core.logging import configure_logging, get_logger


@asynccontextmanager
async def lifespan(_: FastAPI):
    """Initialize shared resources for the API lifecycle."""
    configure_logging()
    logger = get_logger(__name__)
    logger.info("App Started")
    logger.info("Scraper Initialized")
    yield


app = FastAPI(title=settings.APP_NAME, lifespan=lifespan)


@app.get("/")
def read_status() -> dict[str, str]:
    """Return the current application status."""
    return {"status": settings.API_STATUS}
