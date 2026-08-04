"""Centralized application configuration."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parents[2]
load_dotenv(BASE_DIR / ".env")

def _read_required(name: str) -> str:
    value = os.getenv(name)
    if value is None or value.strip() == "":
        raise ValueError(f"Missing required environment variable: {name}")
    return value.strip()


def _read_optional(name: str) -> str | None:
    value = os.getenv(name, "").strip()
    return value or None


def _read_default(name: str, default: str) -> str:
    value = os.getenv(name, default)
    return value.strip()


def _read_int(name: str) -> int:
    return int(_read_required(name))


def _read_default_int(name: str, default: int) -> int:
    return int(_read_default(name, str(default)))


def _read_default_float(name: str, default: float) -> float:
    return float(_read_default(name, str(default)))


def _read_path(name: str) -> Path:
    value = Path(_read_required(name))
    return value if value.is_absolute() else BASE_DIR / value


def _read_default_path(name: str, default: str) -> Path:
    value = Path(_read_default(name, default))
    return value if value.is_absolute() else BASE_DIR / value


def _read_csv(name: str) -> tuple[str, ...]:
    raw = _read_required(name)
    return tuple(item.strip() for item in raw.split(",") if item.strip())


@dataclass(frozen=True, slots=True)
class Settings:
    """Immutable runtime settings loaded from environment."""

    BASE_DIR: Path
    APP_NAME: str
    SCRAPE_INTERVAL: int
    LOG_LEVEL: str
    DATA_PATH: Path
    LOG_FILE_PATH: Path
    API_HOST: str
    API_PORT: int
    API_STATUS: str
    DASHBOARD_HOST: str
    DASHBOARD_PORT: int
    DASHBOARD_TITLE: str
    DASHBOARD_STATUS_LABEL: str
    DASHBOARD_STATUS: str
    SCRAPER_ENGINE: str
    SCRAPER_KEYWORDS: tuple[str, ...]
    DISCOVERY_LIMIT_PER_KEYWORD: int
    TARGET_TWEETS: int
    RAW_OUTPUT: Path
    CHECKPOINT_PATH: Path
    TWSCRAPE_ACCOUNTS_DB: Path
    MONGODB_URI: str
    MONGODB_DATABASE: str
    MONGODB_TWEETS_COLLECTION: str
    MONGODB_RUNS_COLLECTION: str
    MONGODB_SIGNALS_COLLECTION: str
    PARQUET_TWEETS_PATH: Path
    PARQUET_SIGNALS_PATH: Path
    KEYWORD_CONCURRENCY: int
    LOOKBACK_HOURS: int
    SEARCH_FETCH_MULTIPLIER: int
    SEARCH_RETRY_ATTEMPTS: int
    SEARCH_RETRY_BASE_SECONDS: float
    SEARCH_RETRY_MAX_SECONDS: float
    TWSCRAPE_WAIT_TIMEOUT: int
    TWSCRAPE_WAIT_INTERVAL: float
    DEBUG_ARTIFACTS_PATH: Path
    FEATURE_VECTOR_SIZE: int
    FEATURE_TOP_TERMS: int
    PARQUET_CHUNK_SIZE: int
    DASHBOARD_SAMPLE_SIZE: int
    X_USERNAME: str | None
    X_PASSWORD: str | None
    X_EMAIL: str | None
    X_EMAIL_PASSWORD: str | None
    X_COOKIES: str | None
    X_AUTH_TOKEN: str | None
    X_CT0: str | None

    def ensure_directories(self) -> None:
        """Create runtime directories expected by the application."""
        self.DATA_PATH.mkdir(parents=True, exist_ok=True)
        self.RAW_OUTPUT.mkdir(parents=True, exist_ok=True)
        self.LOG_FILE_PATH.parent.mkdir(parents=True, exist_ok=True)
        self.CHECKPOINT_PATH.parent.mkdir(parents=True, exist_ok=True)
        self.TWSCRAPE_ACCOUNTS_DB.parent.mkdir(parents=True, exist_ok=True)
        self.PARQUET_TWEETS_PATH.mkdir(parents=True, exist_ok=True)
        self.PARQUET_SIGNALS_PATH.mkdir(parents=True, exist_ok=True)
        self.DEBUG_ARTIFACTS_PATH.mkdir(parents=True, exist_ok=True)


settings = Settings(
    BASE_DIR=BASE_DIR,
    APP_NAME=_read_required("APP_NAME"),
    SCRAPE_INTERVAL=_read_int("SCRAPE_INTERVAL"),
    LOG_LEVEL=_read_required("LOG_LEVEL").upper(),
    DATA_PATH=_read_path("DATA_PATH"),
    LOG_FILE_PATH=_read_path("LOG_FILE_PATH"),
    API_HOST=_read_required("API_HOST"),
    API_PORT=_read_int("API_PORT"),
    API_STATUS=_read_required("API_STATUS"),
    DASHBOARD_HOST=_read_required("DASHBOARD_HOST"),
    DASHBOARD_PORT=_read_int("DASHBOARD_PORT"),
    DASHBOARD_TITLE=_read_required("DASHBOARD_TITLE"),
    DASHBOARD_STATUS_LABEL=_read_required("DASHBOARD_STATUS_LABEL"),
    DASHBOARD_STATUS=_read_required("DASHBOARD_STATUS"),
    SCRAPER_ENGINE=_read_default("SCRAPER_ENGINE", "twscrape").lower(),
    SCRAPER_KEYWORDS=_read_csv("SCRAPER_KEYWORDS"),
    DISCOVERY_LIMIT_PER_KEYWORD=_read_int("DISCOVERY_LIMIT_PER_KEYWORD"),
    TARGET_TWEETS=_read_int("TARGET_TWEETS"),
    RAW_OUTPUT=_read_path("RAW_OUTPUT"),
    CHECKPOINT_PATH=_read_path("CHECKPOINT_PATH"),
    TWSCRAPE_ACCOUNTS_DB=_read_default_path("TWSCRAPE_ACCOUNTS_DB", "data/twscrape/accounts.db"),
    MONGODB_URI=_read_default("MONGODB_URI", "mongodb://localhost:27017/"),
    MONGODB_DATABASE=_read_default("MONGODB_DATABASE", "market-intelligence"),
    MONGODB_TWEETS_COLLECTION=_read_default("MONGODB_TWEETS_COLLECTION", "tweets"),
    MONGODB_RUNS_COLLECTION=_read_default("MONGODB_RUNS_COLLECTION", "scrape_runs"),
    MONGODB_SIGNALS_COLLECTION=_read_default("MONGODB_SIGNALS_COLLECTION", "keyword_signals"),
    PARQUET_TWEETS_PATH=_read_default_path("PARQUET_TWEETS_PATH", "data/parquet/tweets"),
    PARQUET_SIGNALS_PATH=_read_default_path("PARQUET_SIGNALS_PATH", "data/parquet/signals"),
    KEYWORD_CONCURRENCY=_read_default_int("KEYWORD_CONCURRENCY", 2),
    LOOKBACK_HOURS=_read_default_int("LOOKBACK_HOURS", 24),
    SEARCH_FETCH_MULTIPLIER=_read_default_int("SEARCH_FETCH_MULTIPLIER", 3),
    SEARCH_RETRY_ATTEMPTS=_read_default_int("SEARCH_RETRY_ATTEMPTS", 3),
    SEARCH_RETRY_BASE_SECONDS=_read_default_float("SEARCH_RETRY_BASE_SECONDS", 2.0),
    SEARCH_RETRY_MAX_SECONDS=_read_default_float("SEARCH_RETRY_MAX_SECONDS", 20.0),
    TWSCRAPE_WAIT_TIMEOUT=_read_default_int("TWSCRAPE_WAIT_TIMEOUT", 30),
    TWSCRAPE_WAIT_INTERVAL=_read_default_float("TWSCRAPE_WAIT_INTERVAL", 1.0),
    DEBUG_ARTIFACTS_PATH=_read_default_path("DEBUG_ARTIFACTS_PATH", "data/raw/debug"),
    FEATURE_VECTOR_SIZE=_read_default_int("FEATURE_VECTOR_SIZE", 32),
    FEATURE_TOP_TERMS=_read_default_int("FEATURE_TOP_TERMS", 8),
    PARQUET_CHUNK_SIZE=_read_default_int("PARQUET_CHUNK_SIZE", 500),
    DASHBOARD_SAMPLE_SIZE=_read_default_int("DASHBOARD_SAMPLE_SIZE", 200),
    X_USERNAME=_read_optional("X_USERNAME"),
    X_PASSWORD=_read_optional("X_PASSWORD"),
    X_EMAIL=_read_optional("X_EMAIL"),
    X_EMAIL_PASSWORD=_read_optional("X_EMAIL_PASSWORD"),
    X_COOKIES=_read_optional("X_COOKIES"),
    X_AUTH_TOKEN=_read_optional("X_AUTH_TOKEN"),
    X_CT0=_read_optional("X_CT0"),
)
