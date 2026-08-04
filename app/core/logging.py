"""Shared logging configuration."""

from __future__ import annotations

import logging

from app.core.config import settings

_FORMAT = "%(asctime)s | %(levelname)s | %(name)s | %(message)s"


def configure_logging() -> None:
    """Configure root logging once for the full application."""
    settings.ensure_directories()

    root_logger = logging.getLogger()
    if getattr(root_logger, "_market_intelligence_configured", False):
        return

    root_logger.setLevel(settings.LOG_LEVEL)

    formatter = logging.Formatter(_FORMAT)

    file_handler = logging.FileHandler(settings.LOG_FILE_PATH)
    file_handler.setFormatter(formatter)

    stream_handler = logging.StreamHandler()
    stream_handler.setFormatter(formatter)

    root_logger.handlers.clear()
    root_logger.addHandler(file_handler)
    root_logger.addHandler(stream_handler)
    root_logger._market_intelligence_configured = True


def get_logger(name: str) -> logging.Logger:
    """Return a module logger using the shared configuration."""
    return logging.getLogger(name)
