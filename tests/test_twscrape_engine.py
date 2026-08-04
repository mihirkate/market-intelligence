from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone

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
    def __init__(self, username: str) -> None:
        self.username = username


class FakePool:
    async def get_all(self) -> list[FakeAccount]:
        return [FakeAccount("demo_account")]


class FakeAPI:
    def __init__(self, plans) -> None:
        self.pool = FakePool()
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
    assert records[0].timestamp_utc == (now - timedelta(hours=2)).isoformat()
    assert records[0].raw_metadata["search_window_start_utc"] == "2026-08-03T15:00:00+00:00"
    assert records[0].raw_metadata["search_window_end_utc"] == "2026-08-04T15:00:00+00:00"
    assert records[0].raw_metadata["matched_keywords"] == ["#nifty50"]


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
