"""Map twscrape tweet objects into the project's TweetRecord model."""

from __future__ import annotations

from dataclasses import asdict, is_dataclass
from datetime import timezone
from typing import Any

from app.scraper.models import TweetRecord


class TwscrapeAdapter:
    """Convert twscrape tweet models into the project's storage format."""

    def to_tweet_record(self, tweet, *, keyword: str | None = None, provider: str = "twscrape") -> TweetRecord:
        mentions = []
        for user in getattr(tweet, "mentionedUsers", []):
            username = getattr(user, "username", None)
            if username:
                mentions.append(f"@{username.lstrip('@')}")

        hashtags = [f"#{tag.lstrip('#')}" for tag in getattr(tweet, "hashtags", [])]
        timestamp = tweet.date.astimezone(timezone.utc).isoformat() if getattr(tweet, "date", None) else None

        return TweetRecord(
            tweet_url=tweet.url,
            tweet_id=tweet.id_str,
            username=tweet.user.username,
            display_name=getattr(tweet.user, "displayname", None),
            timestamp_utc=timestamp,
            content=tweet.rawContent,
            replies=tweet.replyCount,
            reposts=tweet.retweetCount,
            likes=tweet.likeCount,
            views=tweet.viewCount,
            mentions=mentions,
            hashtags=hashtags,
            keyword=keyword,
            provider=provider,
            raw_metadata=self._raw_metadata(tweet),
        )

    def _raw_metadata(self, tweet) -> dict[str, Any]:
        media = getattr(tweet, "media", None)
        coordinates = getattr(tweet, "coordinates", None)
        place = getattr(tweet, "place", None)

        return {
            "lang": getattr(tweet, "lang", None),
            "quote_count": getattr(tweet, "quoteCount", None),
            "bookmarked_count": getattr(tweet, "bookmarkedCount", None),
            "conversation_id": getattr(tweet, "conversationIdStr", None),
            "source": getattr(tweet, "source", None),
            "source_url": getattr(tweet, "sourceUrl", None),
            "source_label": getattr(tweet, "sourceLabel", None),
            "cashtags": list(getattr(tweet, "cashtags", [])),
            "links": [self._serialize_model(link) for link in getattr(tweet, "links", [])],
            "media": {
                "photos": [self._serialize_model(item) for item in getattr(media, "photos", [])],
                "videos": [self._serialize_model(item) for item in getattr(media, "videos", [])],
                "animated": [self._serialize_model(item) for item in getattr(media, "animated", [])],
            },
            "coordinates": self._serialize_model(coordinates),
            "place": self._serialize_model(place),
            "user": {
                "id": getattr(tweet.user, "id_str", None),
                "url": getattr(tweet.user, "url", None),
                "verified": getattr(tweet.user, "verified", None),
                "followers_count": getattr(tweet.user, "followersCount", None),
                "friends_count": getattr(tweet.user, "friendsCount", None),
            },
            "in_reply_to_tweet_id": getattr(tweet, "inReplyToTweetIdStr", None),
            "in_reply_to_screen_name": getattr(tweet, "inReplyToScreenName", None),
            "quoted_tweet_id": getattr(getattr(tweet, "quotedTweet", None), "id_str", None),
            "retweeted_tweet_id": getattr(getattr(tweet, "retweetedTweet", None), "id_str", None),
            "possibly_sensitive": getattr(tweet, "possibly_sensitive", None),
        }

    def _serialize_model(self, value: Any) -> Any:
        if value is None:
            return None
        if is_dataclass(value):
            return asdict(value)
        if hasattr(value, "__dict__"):
            return {
                key: data
                for key, data in vars(value).items()
                if not key.startswith("_")
            }
        return value
