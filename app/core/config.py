"""Centralized application configuration."""

from __future__ import annotations

import json
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


def _read_int_csv(name: str, default: str) -> tuple[int, ...]:
    raw = _read_default(name, default)
    values = [int(item.strip()) for item in raw.split(",") if item.strip()]
    return tuple(values)


@dataclass(frozen=True, slots=True)
class TwscrapeAccountSettings:
    """One X account configuration that can seed the local twscrape pool."""

    username: str
    password: str | None = None
    email: str | None = None
    email_password: str | None = None
    cookies: str | None = None
    auth_token: str | None = None
    ct0: str | None = None
    mfa_code: str | None = None
    user_agent: str | None = None
    proxy: str | None = None

    def cookies_value(self) -> str | None:
        """Return a cookie string accepted by twscrape, if configured."""
        if self.cookies:
            return self.cookies
        if self.auth_token and self.ct0:
            return f"auth_token={self.auth_token}; ct0={self.ct0}"
        return None

    def has_cookie_auth(self) -> bool:
        return self.cookies_value() is not None

    def has_password_auth(self) -> bool:
        return all([self.password, self.email, self.email_password])


def _parse_twscrape_accounts(raw: str | None) -> tuple[TwscrapeAccountSettings, ...]:
    """Parse JSON-encoded X account config from `.env`."""
    if raw is None or raw.strip() == "":
        return ()

    try:
        payload = json.loads(raw)
    except json.JSONDecodeError as error:
        raise ValueError("X_ACCOUNTS_JSON must be valid JSON.") from error

    if not isinstance(payload, list):
        raise ValueError("X_ACCOUNTS_JSON must decode to a JSON array.")

    accounts: list[TwscrapeAccountSettings] = []
    for index, item in enumerate(payload):
        if not isinstance(item, dict):
            raise ValueError(f"X_ACCOUNTS_JSON[{index}] must be a JSON object.")

        username = str(item.get("username", "")).strip()
        if not username:
            raise ValueError(f"X_ACCOUNTS_JSON[{index}] is missing 'username'.")

        account = TwscrapeAccountSettings(
            username=username,
            password=_clean_optional_value(item.get("password")),
            email=_clean_optional_value(item.get("email")),
            email_password=_clean_optional_value(item.get("email_password")),
            cookies=_clean_optional_value(item.get("cookies")),
            auth_token=_clean_optional_value(item.get("auth_token")),
            ct0=_clean_optional_value(item.get("ct0")),
            mfa_code=_clean_optional_value(item.get("mfa_code")),
            user_agent=_clean_optional_value(item.get("user_agent")),
            proxy=_clean_optional_value(item.get("proxy")),
        )
        if not (account.has_cookie_auth() or account.has_password_auth()):
            raise ValueError(
                "Each X account must provide either cookies/auth_token+ct0 or "
                "password+email+email_password."
            )
        accounts.append(account)

    return tuple(accounts)


def _clean_optional_value(value: object) -> str | None:
    if value is None:
        return None
    cleaned = str(value).strip()
    return cleaned or None


def _single_twscrape_account_from_env() -> tuple[TwscrapeAccountSettings, ...]:
    username = _read_optional("X_USERNAME")
    if not username:
        return ()

    account = TwscrapeAccountSettings(
        username=username,
        password=_read_optional("X_PASSWORD"),
        email=_read_optional("X_EMAIL"),
        email_password=_read_optional("X_EMAIL_PASSWORD"),
        cookies=_read_optional("X_COOKIES"),
        auth_token=_read_optional("X_AUTH_TOKEN"),
        ct0=_read_optional("X_CT0"),
    )
    return (account,) if (account.has_cookie_auth() or account.has_password_auth()) else ()


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
    MAX_TWEETS_PER_RUN: int
    CRON_SCHEDULE: str
    CRON_LOG_PATH: Path
    CRON_LOCK_PATH: Path
    RUN_STARTUP_JITTER_MIN_SECONDS: int
    RUN_STARTUP_JITTER_MAX_SECONDS: int
    RATE_LIMIT_COOLDOWN_MIN_SECONDS: int
    RATE_LIMIT_COOLDOWN_MAX_SECONDS: int
    RAW_OUTPUT: Path
    CHECKPOINT_PATH: Path
    TWSCRAPE_ACCOUNTS_DB: Path
    COLLECTION_TARGET_TWEETS_LAST_24_HOURS: int
    COLLECTION_PROGRESS_RECENT_RUN_HOURS: int
    COLLECTION_STATUS_REPORT_PATH: Path
    PROCESSING_REPORT_PATH: Path
    ANALYSIS_REPORT_PATH: Path
    PERFORMANCE_REPORT_PATH: Path
    REPORT_TOP_LIMIT: int
    BENCHMARK_RECORD_COUNTS: tuple[int, ...]
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
    X_ACCOUNTS: tuple[TwscrapeAccountSettings, ...]
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
        self.CRON_LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
        self.CRON_LOCK_PATH.parent.mkdir(parents=True, exist_ok=True)
        self.CHECKPOINT_PATH.parent.mkdir(parents=True, exist_ok=True)
        self.TWSCRAPE_ACCOUNTS_DB.parent.mkdir(parents=True, exist_ok=True)
        self.COLLECTION_STATUS_REPORT_PATH.parent.mkdir(parents=True, exist_ok=True)
        self.PROCESSING_REPORT_PATH.parent.mkdir(parents=True, exist_ok=True)
        self.ANALYSIS_REPORT_PATH.parent.mkdir(parents=True, exist_ok=True)
        self.PERFORMANCE_REPORT_PATH.parent.mkdir(parents=True, exist_ok=True)
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
    MAX_TWEETS_PER_RUN=_read_default_int("MAX_TWEETS_PER_RUN", _read_int("TARGET_TWEETS")),
    CRON_SCHEDULE=_read_default("CRON_SCHEDULE", "*/10 * * * *"),
    CRON_LOG_PATH=_read_default_path("CRON_LOG_PATH", "logs/cron.log"),
    CRON_LOCK_PATH=_read_default_path("CRON_LOCK_PATH", "data/raw/cron.lock"),
    RUN_STARTUP_JITTER_MIN_SECONDS=_read_default_int("RUN_STARTUP_JITTER_MIN_SECONDS", 0),
    RUN_STARTUP_JITTER_MAX_SECONDS=_read_default_int("RUN_STARTUP_JITTER_MAX_SECONDS", 120),
    RATE_LIMIT_COOLDOWN_MIN_SECONDS=_read_default_int("RATE_LIMIT_COOLDOWN_MIN_SECONDS", 1800),
    RATE_LIMIT_COOLDOWN_MAX_SECONDS=_read_default_int("RATE_LIMIT_COOLDOWN_MAX_SECONDS", 3600),
    RAW_OUTPUT=_read_path("RAW_OUTPUT"),
    CHECKPOINT_PATH=_read_path("CHECKPOINT_PATH"),
    TWSCRAPE_ACCOUNTS_DB=_read_default_path("TWSCRAPE_ACCOUNTS_DB", "data/twscrape/accounts.db"),
    COLLECTION_TARGET_TWEETS_LAST_24_HOURS=_read_default_int("COLLECTION_TARGET_TWEETS_LAST_24_HOURS", 2000),
    COLLECTION_PROGRESS_RECENT_RUN_HOURS=_read_default_int("COLLECTION_PROGRESS_RECENT_RUN_HOURS", 6),
    COLLECTION_STATUS_REPORT_PATH=_read_default_path(
        "COLLECTION_STATUS_REPORT_PATH",
        "reports/data_collection_status.json",
    ),
    PROCESSING_REPORT_PATH=_read_default_path(
        "PROCESSING_REPORT_PATH",
        "reports/processing_report.json",
    ),
    ANALYSIS_REPORT_PATH=_read_default_path(
        "ANALYSIS_REPORT_PATH",
        "reports/analysis_summary.json",
    ),
    PERFORMANCE_REPORT_PATH=_read_default_path(
        "PERFORMANCE_REPORT_PATH",
        "reports/performance_benchmark.json",
    ),
    REPORT_TOP_LIMIT=_read_default_int("REPORT_TOP_LIMIT", 10),
    BENCHMARK_RECORD_COUNTS=_read_int_csv("BENCHMARK_RECORD_COUNTS", "100,1000,2000"),
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
    X_ACCOUNTS=_parse_twscrape_accounts(_read_optional("X_ACCOUNTS_JSON")) or _single_twscrape_account_from_env(),
    X_USERNAME=_read_optional("X_USERNAME"),
    X_PASSWORD=_read_optional("X_PASSWORD"),
    X_EMAIL=_read_optional("X_EMAIL"),
    X_EMAIL_PASSWORD=_read_optional("X_EMAIL_PASSWORD"),
    X_COOKIES=_read_optional("X_COOKIES"),
    X_AUTH_TOKEN=_read_optional("X_AUTH_TOKEN"),
    X_CT0=_read_optional("X_CT0"),
)
