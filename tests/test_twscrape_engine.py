from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest
from twscrape import NoAccountError

import app.scraper.engines.twscrape_engine as twscrape_engine_module
from app.core.config import TwscrapeAccountSettings
from app.scraper.engines.base import ScraperRateLimitError
from app.scraper.engines.twscrape_engine import TwscrapeEngine
from app.storage import DebugArtifactStore


@dataclass
class FakeUserRef:
    username: str


@dataclass
class FakeMedia:
    photos: list[dict] = field(default_factory=list)
    videos: list[dict] = field(default_factory=list)
    animated: list[dict] = field(default_factory=list)


@dataclass
class FakeUser:
    username: str
    displayname: str
    id_str: str = "42"
    url: str = "https://x.com/demo"
    verified: bool = False
    followersCount: int = 10
    friendsCount: int = 20


@dataclass
class FakeTweet:
    id_str: str
    url: str
    date: datetime
    user: FakeUser
    lang: str
    rawContent: str
    replyCount: int
    retweetCount: int
    likeCount: int
    quoteCount: int
    bookmarkedCount: int
    conversationIdStr: str
    hashtags: list[str]
    cashtags: list[str]
    mentionedUsers: list[FakeUserRef]
    links: list[dict]
    media: FakeMedia
    viewCount: int | None = None
    coordinates: dict | None = None
    place: dict | None = None
    inReplyToTweetIdStr: str | None = None
    inReplyToScreenName: str | None = None
    quotedTweet: object | None = None
    retweetedTweet: object | None = None
    source: str | None = "web"
    sourceUrl: str | None = "https://x.com"
    sourceLabel: str | None = "X Web App"
    possibly_sensitive: bool | None = False


class FakeAccount:
    def __init__(
        self,
        username: str,
        *,
        locks: dict[str, datetime] | None = None,
        active: bool = True,
        error_msg: str | None = None,
        last_used: datetime | None = None,
    ) -> None:
        self.username = username
        self.locks = locks or {}
        self.active = active
        self.error_msg = error_msg
        self.last_used = last_used


class FakePool:
    def __init__(self, accounts: list[FakeAccount] | None = None) -> None:
        self.accounts = accounts or [FakeAccount("demo_account")]
        self.cookie_accounts: list[tuple[str, str]] = []
        self.credential_accounts: list[dict[str, object]] = []
        self.deleted_usernames: list[str] = []
        self.logged_in_usernames: list[str] = []

    async def get_all(self) -> list[FakeAccount]:
        return self.accounts

    async def delete_accounts(self, usernames):
        if isinstance(usernames, str):
            self.deleted_usernames.append(usernames)
        else:
            self.deleted_usernames.extend(usernames)

    async def add_account_cookies(self, username: str, cookies: str) -> None:
        self.cookie_accounts.append((username, cookies))

    async def add_account(
        self,
        username: str,
        password: str,
        email: str,
        email_password: str,
        user_agent: str | None = None,
        proxy: str | None = None,
        cookies: str | None = None,
        mfa_code: str | None = None,
    ) -> None:
        self.credential_accounts.append(
            {
                "username": username,
                "password": password,
                "email": email,
                "email_password": email_password,
                "user_agent": user_agent,
                "proxy": proxy,
                "cookies": cookies,
                "mfa_code": mfa_code,
            }
        )

    async def login_all(self, usernames: list[str] | None = None) -> None:
        self.logged_in_usernames.extend(usernames or [])


class FakeAPI:
    def __init__(self, plans, *, accounts: list[FakeAccount] | None = None) -> None:
        self.pool = FakePool(accounts=accounts)
        self._plans = list(plans)
        self.queries: list[tuple[str, int]] = []

    async def search(self, q: str, limit: int = -1):
        self.queries.append((q, limit))
        plan = self._plans.pop(0)
        if isinstance(plan, Exception):
            raise plan
        for item in plan:
            yield item


def _tweet(tweet_id: str, *, timestamp: datetime, content: str = "Market update #nifty50") -> FakeTweet:
    return FakeTweet(
        id_str=tweet_id,
        url=f"https://x.com/demo/status/{tweet_id}",
        date=timestamp,
        user=FakeUser(username="demo_user", displayname="Demo User"),
        lang="en",
        rawContent=content,
        replyCount=1,
        retweetCount=2,
        likeCount=3,
        quoteCount=4,
        bookmarkedCount=5,
        conversationIdStr=tweet_id,
        hashtags=["nifty50"],
        cashtags=[],
        mentionedUsers=[FakeUserRef(username="alpha")],
        links=[],
        media=FakeMedia(),
        viewCount=99,
    )


def test_twscrape_engine_filters_to_last_24_hours_and_decorates_metadata(tmp_path) -> None:
    now = datetime(2026, 8, 4, 15, 0, tzinfo=timezone.utc)
    api = FakeAPI(
        [
            [
                _tweet("1", timestamp=now - timedelta(hours=2)),
                _tweet("2", timestamp=now - timedelta(hours=30), content="Older tweet #nifty50"),
            ]
        ]
    )
    engine = TwscrapeEngine(
        api=api,
        artifact_store=DebugArtifactStore(output_dir=tmp_path / "debug"),
        retry_attempts=1,
        now_provider=lambda: now,
    )

    records = engine.search("#nifty50", limit=5)

    assert len(records) == 1
    assert api.queries
    assert "since:2026-08-03" in api.queries[0][0]
    assert api.queries[0][1] == 15
    assert records[0].timestamp_utc == (now - timedelta(hours=2)).isoformat()
    assert records[0].raw_metadata["search_window_start_utc"] == "2026-08-03T15:00:00+00:00"
    assert records[0].raw_metadata["search_window_end_utc"] == "2026-08-04T15:00:00+00:00"
    assert records[0].raw_metadata["matched_keywords"] == ["#nifty50"]
    assert records[0].raw_metadata["search_limit_requested"] == 15


def test_twscrape_engine_retries_failed_search_and_writes_artifact(tmp_path) -> None:
    now = datetime(2026, 8, 4, 15, 0, tzinfo=timezone.utc)
    api = FakeAPI(
        [
            RuntimeError("rate limited"),
            [_tweet("3", timestamp=now - timedelta(hours=1), content="Sensex rebound #sensex")],
        ]
    )
    debug_dir = tmp_path / "debug"
    engine = TwscrapeEngine(
        api=api,
        artifact_store=DebugArtifactStore(output_dir=debug_dir),
        retry_attempts=2,
        retry_base_seconds=0,
        retry_max_seconds=0,
        now_provider=lambda: now,
    )

    records = engine.search("#sensex", limit=2)
    artifacts = list(debug_dir.glob("*.json"))

    assert len(records) == 1
    assert len(api.queries) == 2
    assert artifacts
    assert any("keyword_search_failure" in path.name for path in artifacts)


def test_twscrape_engine_raises_structured_rate_limit_error_with_unlock_time(tmp_path) -> None:
    now = datetime(2026, 8, 4, 15, 0, tzinfo=timezone.utc)
    lock_until = now + timedelta(minutes=12)
    api = FakeAPI(
        [NoAccountError("No account available for queue SearchTimeline")],
        accounts=[FakeAccount("demo_account", locks={"SearchTimeline": lock_until}, last_used=now)],
    )
    engine = TwscrapeEngine(
        api=api,
        artifact_store=DebugArtifactStore(output_dir=tmp_path / "debug"),
        retry_attempts=1,
        retry_base_seconds=0,
        retry_max_seconds=0,
        now_provider=lambda: now,
    )

    with pytest.raises(ScraperRateLimitError) as error_info:
        engine.search("#sensex", limit=2)

    error = error_info.value
    assert error.cooldown_until == lock_until
    assert error.account_states
    assert error.account_states[0]["username"] == "demo_account"


def test_twscrape_engine_bootstraps_multiple_accounts(monkeypatch: pytest.MonkeyPatch) -> None:
    api = FakeAPI([])
    engine = TwscrapeEngine(api=api)
    monkeypatch.setattr(
        twscrape_engine_module,
        "settings",
        SimpleNamespace(
            X_ACCOUNTS=(
                TwscrapeAccountSettings(
                    username="cookie_user",
                    auth_token="token-1",
                    ct0="ct0-1",
                ),
                TwscrapeAccountSettings(
                    username="credential_user",
                    password="secret",
                    email="user@example.com",
                    email_password="mail-secret",
                    user_agent="agent-1",
                    proxy="http://proxy.local:8080",
                    mfa_code="123456",
                ),
            )
        ),
        raising=False,
    )

    engine.bootstrap_account(force=True)

    assert api.pool.deleted_usernames == []
    assert api.pool.cookie_accounts == [("cookie_user", "auth_token=token-1; ct0=ct0-1")]
    assert api.pool.credential_accounts == [
        {
            "username": "credential_user",
            "password": "secret",
            "email": "user@example.com",
            "email_password": "mail-secret",
            "user_agent": "agent-1",
            "proxy": "http://proxy.local:8080",
            "cookies": None,
            "mfa_code": "123456",
        }
    ]
    assert api.pool.logged_in_usernames == ["credential_user"]
