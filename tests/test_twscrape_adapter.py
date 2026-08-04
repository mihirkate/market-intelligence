from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone

from app.scraper.adapters.twscrape_adapter import TwscrapeAdapter


@dataclass
class FakeUserRef:
    username: str


@dataclass
class FakeTextLink:
    url: str
    text: str = ""
    tcourl: str = ""
    indices: tuple[int, int] = (0, 0)


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
    links: list[FakeTextLink]
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


def test_twscrape_adapter_maps_tweet_into_record() -> None:
    adapter = TwscrapeAdapter()
    tweet = FakeTweet(
        id_str="123",
        url="https://x.com/demo/status/123",
        date=datetime(2026, 8, 4, 12, 0, tzinfo=timezone.utc),
        user=FakeUser(username="demo_user", displayname="Demo User"),
        lang="en",
        rawContent="Trend update #nifty50 @alpha",
        replyCount=1,
        retweetCount=2,
        likeCount=3,
        quoteCount=4,
        bookmarkedCount=5,
        conversationIdStr="123",
        hashtags=["nifty50"],
        cashtags=["NIFTY"],
        mentionedUsers=[FakeUserRef(username="alpha")],
        links=[FakeTextLink(url="https://example.com")],
        media=FakeMedia(),
        viewCount=99,
    )

    record = adapter.to_tweet_record(tweet, keyword="#nifty50")

    assert record.tweet_url == "https://x.com/demo/status/123"
    assert record.tweet_id == "123"
    assert record.username == "demo_user"
    assert record.display_name == "Demo User"
    assert record.content == "Trend update #nifty50 @alpha"
    assert record.hashtags == ["#nifty50"]
    assert record.mentions == ["@alpha"]
    assert record.views == 99
    assert record.raw_metadata["quote_count"] == 4
