"""twscrape-backed scraper engine."""

from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone
from typing import Callable

from twscrape import API, NoAccountError

from app.core.config import TwscrapeAccountSettings, settings
from app.core.logging import get_logger
from app.scraper.adapters import TwscrapeAdapter
from app.scraper.engines.base import ScraperEngine
from app.scraper.models import TweetRecord
from app.storage import DebugArtifactStore

logger = get_logger(__name__)


class TwscrapeEngine(ScraperEngine):
    """Collect tweets through twscrape's authenticated API layer."""

    name = "twscrape"

    def __init__(
        self,
        *,
        api: API | None = None,
        adapter: TwscrapeAdapter | None = None,
        artifact_store: DebugArtifactStore | None = None,
        lookback_hours: int | None = None,
        search_fetch_multiplier: int | None = None,
        retry_attempts: int | None = None,
        retry_base_seconds: float | None = None,
        retry_max_seconds: float | None = None,
        now_provider: Callable[[], datetime] | None = None,
    ) -> None:
        self.adapter = adapter or TwscrapeAdapter()
        self.api = api or API(
            str(settings.TWSCRAPE_ACCOUNTS_DB),
            raise_when_no_account=True,
            wait_timeout=settings.TWSCRAPE_WAIT_TIMEOUT,
            wait_interval=settings.TWSCRAPE_WAIT_INTERVAL,
        )
        self.artifact_store = artifact_store or DebugArtifactStore()
        self.lookback_hours = lookback_hours if lookback_hours is not None else settings.LOOKBACK_HOURS
        self.search_fetch_multiplier = (
            search_fetch_multiplier
            if search_fetch_multiplier is not None
            else settings.SEARCH_FETCH_MULTIPLIER
        )
        self.retry_attempts = (
            retry_attempts if retry_attempts is not None else settings.SEARCH_RETRY_ATTEMPTS
        )
        self.retry_base_seconds = (
            retry_base_seconds
            if retry_base_seconds is not None
            else settings.SEARCH_RETRY_BASE_SECONDS
        )
        self.retry_max_seconds = (
            retry_max_seconds
            if retry_max_seconds is not None
            else settings.SEARCH_RETRY_MAX_SECONDS
        )
        self.now_provider = now_provider or (lambda: datetime.now(timezone.utc))
        self._account_ready = False

    def search(self, keyword: str, limit: int) -> list[TweetRecord]:
        """Fetch tweets for a keyword and map them into TweetRecord values."""
        return asyncio.run(self._search_async(keyword, limit))

    def search_many(self, keywords: tuple[str, ...], limit: int) -> dict[str, list[TweetRecord]]:
        """Fetch tweets for multiple keywords concurrently."""
        return asyncio.run(self._search_many_async(keywords, limit))

    def bootstrap_account(self, *, force: bool = False) -> None:
        """Seed the twscrape accounts DB from env if needed."""
        asyncio.run(self._ensure_account_async(force=force))

    async def _search_async(self, keyword: str, limit: int) -> list[TweetRecord]:
        await self._ensure_account_async()
        window_start, window_end = self._window_bounds()
        query = self._build_query(keyword, window_start=window_start)
        return await self._fetch_keyword_records(
            keyword,
            query=query,
            limit=limit,
            window_start=window_start,
            window_end=window_end,
        )

    async def _search_many_async(self, keywords: tuple[str, ...], limit: int) -> dict[str, list[TweetRecord]]:
        await self._ensure_account_async()
        semaphore = asyncio.Semaphore(max(1, settings.KEYWORD_CONCURRENCY))
        window_start, window_end = self._window_bounds()

        async def fetch(keyword: str) -> tuple[str, list[TweetRecord]]:
            async with semaphore:
                query = self._build_query(keyword, window_start=window_start)
                records = await self._fetch_keyword_records(
                    keyword,
                    query=query,
                    limit=limit,
                    window_start=window_start,
                    window_end=window_end,
                )
                return keyword, records

        pairs = await asyncio.gather(*(fetch(keyword) for keyword in keywords))
        return dict(pairs)

    async def _fetch_keyword_records(
        self,
        keyword: str,
        *,
        query: str,
        limit: int,
        window_start: datetime,
        window_end: datetime,
    ) -> list[TweetRecord]:
        fetch_limit = max(limit, limit * max(1, self.search_fetch_multiplier))
        last_error: Exception | None = None

        for attempt in range(1, self.retry_attempts + 1):
            try:
                records: list[TweetRecord] = []
                seen_keys: set[str] = set()
                skipped_out_of_window = 0
                skipped_missing_timestamp = 0

                async for tweet in self.api.search(query, limit=fetch_limit):
                    tweet_timestamp = self._tweet_timestamp(tweet)
                    if tweet_timestamp is None:
                        skipped_missing_timestamp += 1
                        continue
                    if tweet_timestamp < window_start or tweet_timestamp > window_end:
                        skipped_out_of_window += 1
                        continue

                    try:
                        record = self.adapter.to_tweet_record(tweet, keyword=keyword, provider=self.name)
                    except Exception as error:  # noqa: BLE001
                        self.artifact_store.write_event(
                            "tweet_mapping_failure",
                            payload={
                                "engine": self.name,
                                "keyword": keyword,
                                "query": query,
                                "tweet": self._tweet_snapshot(tweet),
                            },
                            error=error,
                        )
                        logger.warning(
                            "Failed to map tweet keyword=%s tweet_id=%s error=%s",
                            keyword,
                            getattr(tweet, "id_str", None),
                            error,
                        )
                        continue

                    key = record.tweet_id or record.tweet_url
                    if key in seen_keys:
                        continue
                    seen_keys.add(key)
                    self._decorate_record(
                        record,
                        keyword=keyword,
                        query=query,
                        fetch_limit=fetch_limit,
                        window_start=window_start,
                        window_end=window_end,
                    )
                    records.append(record)
                    if len(records) >= limit:
                        break

                logger.info(
                    "Engine=%s keyword=%s query=%s fetched=%s filtered_out_of_window=%s missing_timestamp=%s",
                    self.name,
                    keyword,
                    query,
                    len(records),
                    skipped_out_of_window,
                    skipped_missing_timestamp,
                )
                return records
            except Exception as error:  # noqa: BLE001
                last_error = error
                artifact_path = self.artifact_store.write_event(
                    "keyword_search_failure",
                    payload={
                        "engine": self.name,
                        "keyword": keyword,
                        "query": query,
                        "attempt": attempt,
                        "fetch_limit": fetch_limit,
                        "window_start_utc": window_start.isoformat(),
                        "window_end_utc": window_end.isoformat(),
                        "accounts": await self._account_snapshot(),
                    },
                    error=error,
                )
                logger.warning(
                    "Search failed engine=%s keyword=%s attempt=%s/%s artifact=%s error=%s",
                    self.name,
                    keyword,
                    attempt,
                    self.retry_attempts,
                    artifact_path,
                    error,
                )
                if attempt >= self.retry_attempts:
                    break
                if isinstance(error, NoAccountError):
                    logger.warning(
                        "No account available for keyword=%s; retrying after %.2fs",
                        keyword,
                        self._retry_delay(attempt),
                    )
                await asyncio.sleep(self._retry_delay(attempt))

        raise RuntimeError(
            f"twscrape search failed for keyword={keyword!r} after {self.retry_attempts} attempts"
        ) from last_error

    async def _ensure_account_async(self, *, force: bool = False) -> None:
        if self._account_ready and not force:
            return

        accounts = await self.api.pool.get_all()
        if accounts and not force:
            self._account_ready = True
            logger.info(
                "Using twscrape account pool size=%s usernames=%s",
                len(accounts),
                [account.username for account in accounts],
            )
            return

        configured_accounts = settings.X_ACCOUNTS
        configured_usernames = [account.username for account in configured_accounts]

        if force and accounts and configured_usernames:
            existing = [account.username for account in accounts if account.username in configured_usernames]
            if existing:
                await self.api.pool.delete_accounts(existing)
                logger.info("Removed existing twscrape accounts usernames=%s", existing)

        if configured_accounts:
            await self._bootstrap_configured_accounts(configured_accounts)
            self._account_ready = True
            return

        raise RuntimeError(self._missing_account_message())

    def _missing_account_message(self) -> str:
        """Explain the accepted account bootstrap inputs."""
        return (
            "No twscrape account bootstrap data was found in .env. "
            "Set X_ACCOUNTS_JSON with one or more accounts, or set X_USERNAME plus "
            "either X_COOKIES, or X_AUTH_TOKEN and X_CT0, or set X_USERNAME, "
            "X_PASSWORD, X_EMAIL, and X_EMAIL_PASSWORD, "
            "then rerun `python -m app.scraper.twscrape_setup`."
        )

    async def _bootstrap_configured_accounts(
        self,
        accounts: tuple[TwscrapeAccountSettings, ...],
    ) -> None:
        login_usernames: list[str] = []

        for account in accounts:
            cookies = account.cookies_value()
            if cookies:
                await self.api.pool.add_account_cookies(account.username, cookies)
                logger.info("Configured twscrape account from cookies username=%s", account.username)
                continue

            if account.has_password_auth():
                await self.api.pool.add_account(
                    account.username,
                    account.password or "",
                    account.email or "",
                    account.email_password or "",
                    user_agent=account.user_agent,
                    proxy=account.proxy,
                    cookies=account.cookies,
                    mfa_code=account.mfa_code,
                )
                login_usernames.append(account.username)
                logger.info("Configured twscrape account from credentials username=%s", account.username)
                continue

            raise RuntimeError(
                "Configured X account is missing usable auth fields "
                f"username={account.username!r}."
            )

        if login_usernames:
            await self.api.pool.login_all(usernames=login_usernames)
            logger.info("Logged into twscrape credential accounts usernames=%s", login_usernames)

    def _window_bounds(self) -> tuple[datetime, datetime]:
        window_end = self.now_provider()
        if window_end.tzinfo is None:
            window_end = window_end.replace(tzinfo=timezone.utc)
        else:
            window_end = window_end.astimezone(timezone.utc)
        return window_end - timedelta(hours=self.lookback_hours), window_end

    def _build_query(self, keyword: str, *, window_start: datetime) -> str:
        normalized_keyword = keyword.strip()
        return f"({normalized_keyword}) since:{window_start.date().isoformat()}"

    def _retry_delay(self, attempt: int) -> float:
        delay = self.retry_base_seconds * (2 ** max(0, attempt - 1))
        return min(delay, self.retry_max_seconds)

    def _tweet_timestamp(self, tweet) -> datetime | None:
        timestamp = getattr(tweet, "date", None)
        if timestamp is None:
            return None
        if timestamp.tzinfo is None:
            return timestamp.replace(tzinfo=timezone.utc)
        return timestamp.astimezone(timezone.utc)

    def _decorate_record(
        self,
        record: TweetRecord,
        *,
        keyword: str,
        query: str,
        fetch_limit: int,
        window_start: datetime,
        window_end: datetime,
    ) -> None:
        record.raw_metadata.update(
            {
                "matched_keywords": sorted({keyword, *record.raw_metadata.get("matched_keywords", [])}),
                "search_query": query,
                "search_window_start_utc": window_start.isoformat(),
                "search_window_end_utc": window_end.isoformat(),
                "lookback_hours": self.lookback_hours,
                "search_limit_requested": fetch_limit,
            }
        )

    async def _account_snapshot(self) -> list[dict[str, object]]:
        accounts = await self.api.pool.get_all()
        return [
            {
                "username": account.username,
                "active": getattr(account, "active", None),
                "error_msg": getattr(account, "error_msg", None),
                "last_used": self._serialize_datetime(getattr(account, "last_used", None)),
                "locks": {
                    queue_name: self._serialize_datetime(lock_until)
                    for queue_name, lock_until in getattr(account, "locks", {}).items()
                },
            }
            for account in accounts
        ]

    def _tweet_snapshot(self, tweet) -> dict[str, object]:
        return {
            "id_str": getattr(tweet, "id_str", None),
            "url": getattr(tweet, "url", None),
            "date": getattr(getattr(tweet, "date", None), "isoformat", lambda: None)(),
            "lang": getattr(tweet, "lang", None),
            "rawContent": getattr(tweet, "rawContent", None),
            "username": getattr(getattr(tweet, "user", None), "username", None),
        }

    def _serialize_datetime(self, value: object) -> str | None:
        return value.isoformat() if isinstance(value, datetime) else None
