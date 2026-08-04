"""Unicode-safe normalization and feature engineering helpers."""

from __future__ import annotations

import hashlib
import html
import math
import re
import unicodedata
from collections import Counter
from dataclasses import dataclass

from app.scraper.models import ProcessedTweetRecord, TweetRecord

_SPACE_RE = re.compile(r"\s+")
_TOKEN_RE = re.compile(r"[#@]?\w+", re.UNICODE)
_ZERO_WIDTH_TRANSLATION = dict.fromkeys(map(ord, "\u200b\u200c\u200d\ufeff"), None)
_INDIAN_RANGES = (
    (0x0900, 0x097F),  # Devanagari
    (0x0980, 0x09FF),  # Bengali
    (0x0A00, 0x0A7F),  # Gurmukhi
    (0x0A80, 0x0AFF),  # Gujarati
    (0x0B00, 0x0B7F),  # Oriya
    (0x0B80, 0x0BFF),  # Tamil
    (0x0C00, 0x0C7F),  # Telugu
    (0x0C80, 0x0CFF),  # Kannada
    (0x0D00, 0x0D7F),  # Malayalam
)
_BULLISH_TERMS = {
    "accumulate",
    "breakout",
    "bullish",
    "buy",
    "gains",
    "long",
    "momentum",
    "rally",
    "recovery",
    "strong",
    "support",
    "surge",
    "upside",
}
_BEARISH_TERMS = {
    "bearish",
    "breakdown",
    "correction",
    "crash",
    "downside",
    "drop",
    "dump",
    "fall",
    "resistance",
    "sell",
    "short",
    "weak",
}


@dataclass(slots=True)
class PreparedTweet:
    """Normalized intermediate representation used for vectorization."""

    record: TweetRecord
    username_normalized: str
    normalized_content: str
    mentions: list[str]
    hashtags: list[str]
    tokens: list[str]
    token_count: int
    indian_script_ratio: float
    non_ascii_ratio: float
    bullish_term_hits: int
    bearish_term_hits: int
    keyword_match_score: float
    engagement_score: float
    sentiment_score: float
    confidence_score: float


def normalize_text(value: str | None) -> str:
    """Normalize whitespace and Unicode while preserving Indian scripts."""
    if not value:
        return ""

    normalized = unicodedata.normalize("NFKC", html.unescape(value))
    normalized = normalized.translate(_ZERO_WIDTH_TRANSLATION)
    filtered = "".join(
        character
        for character in normalized
        if not unicodedata.category(character).startswith("C") or character in "\t\n\r"
    )
    return _SPACE_RE.sub(" ", filtered).strip()


def normalize_handle(value: str | None) -> str:
    """Normalize usernames and mentions into a canonical lowercase form."""
    if not value:
        return ""
    return normalize_text(value).lstrip("@").casefold()


def normalize_hashtag(value: str) -> str:
    """Normalize hashtags while preserving their original script."""
    cleaned = normalize_text(value).lstrip("#")
    if not cleaned:
        return ""
    return f"#{cleaned.casefold()}"


def extract_tokens(value: str) -> list[str]:
    """Tokenize Unicode text into lowercase, hashable tokens."""
    return [match.casefold() for match in _TOKEN_RE.findall(value)]


def build_document_frequency(items: list[PreparedTweet]) -> Counter[str]:
    """Count unique token occurrences across a batch."""
    frequency: Counter[str] = Counter()
    for item in items:
        frequency.update(set(item.tokens))
    return frequency


def prepare_tweet(record: TweetRecord) -> PreparedTweet:
    """Normalize one raw tweet into an intermediate form."""
    normalized_content = normalize_text(record.content)
    username_normalized = normalize_handle(record.username)
    mentions = sorted({f"@{normalize_handle(value)}" for value in record.mentions if normalize_handle(value)})
    hashtags = sorted({normalize_hashtag(value) for value in record.hashtags if normalize_hashtag(value)})
    tokens = extract_tokens(normalized_content)
    token_count = len(tokens)
    bullish_term_hits = sum(token in _BULLISH_TERMS for token in tokens)
    bearish_term_hits = sum(token in _BEARISH_TERMS for token in tokens)
    keyword_match_score = _keyword_match_score(record.keyword, normalized_content, hashtags)
    engagement_score = _engagement_score(record)
    sentiment_score = _sentiment_score(bullish_term_hits, bearish_term_hits, token_count)
    confidence_score = min(
        1.0,
        0.2 + min(0.5, token_count / 20.0) + min(0.3, engagement_score / 12.0),
    )

    return PreparedTweet(
        record=record,
        username_normalized=username_normalized,
        normalized_content=normalized_content,
        mentions=mentions,
        hashtags=hashtags,
        tokens=tokens,
        token_count=token_count,
        indian_script_ratio=_indian_script_ratio(normalized_content),
        non_ascii_ratio=_non_ascii_ratio(normalized_content),
        bullish_term_hits=bullish_term_hits,
        bearish_term_hits=bearish_term_hits,
        keyword_match_score=keyword_match_score,
        engagement_score=engagement_score,
        sentiment_score=sentiment_score,
        confidence_score=confidence_score,
    )


def build_processed_tweet(
    item: PreparedTweet,
    *,
    doc_frequency: Counter[str],
    corpus_size: int,
    vector_size: int,
    top_term_count: int,
) -> ProcessedTweetRecord:
    """Finalize a prepared tweet into the persistent processed schema."""
    tfidf_scores = _tfidf_scores(item.tokens, doc_frequency=doc_frequency, corpus_size=corpus_size)
    feature_vector = _hashed_vector(tfidf_scores, vector_size=vector_size)
    top_terms = [token for token, _ in tfidf_scores.most_common(top_term_count)]
    record = item.record
    normalized_username = item.username_normalized or normalize_handle(record.username)
    tweet_key = record.tweet_id or _stable_digest(record.tweet_url)

    return ProcessedTweetRecord(
        tweet_key=tweet_key,
        tweet_id=record.tweet_id,
        tweet_url=record.tweet_url,
        username=record.username,
        username_normalized=normalized_username,
        display_name=normalize_text(record.display_name) or None,
        timestamp_utc=record.timestamp_utc,
        content=record.content,
        normalized_content=item.normalized_content,
        content_hash=_stable_digest(f"{normalized_username}|{item.normalized_content}"),
        language=record.raw_metadata.get("lang"),
        keyword=record.keyword,
        provider=record.provider,
        replies=record.replies,
        reposts=record.reposts,
        likes=record.likes,
        views=record.views,
        mentions=item.mentions,
        hashtags=item.hashtags,
        token_count=item.token_count,
        indian_script_ratio=item.indian_script_ratio,
        non_ascii_ratio=item.non_ascii_ratio,
        bullish_term_hits=item.bullish_term_hits,
        bearish_term_hits=item.bearish_term_hits,
        keyword_match_score=item.keyword_match_score,
        engagement_score=item.engagement_score,
        sentiment_score=item.sentiment_score,
        confidence_score=item.confidence_score,
        feature_vector=feature_vector,
        top_terms=top_terms,
        scraped_at=record.scraped_at,
        raw_metadata=record.raw_metadata,
    )


def _stable_digest(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _tfidf_scores(
    tokens: list[str],
    *,
    doc_frequency: Counter[str],
    corpus_size: int,
) -> Counter[str]:
    if not tokens:
        return Counter()

    term_frequency = Counter(tokens)
    score_map: Counter[str] = Counter()
    total = len(tokens)
    for token, count in term_frequency.items():
        inverse_document_frequency = math.log((1 + corpus_size) / (1 + doc_frequency[token])) + 1.0
        score_map[token] = (count / total) * inverse_document_frequency
    return score_map


def _hashed_vector(tfidf_scores: Counter[str], *, vector_size: int) -> list[float]:
    if vector_size <= 0:
        return []

    vector = [0.0] * vector_size
    for token, score in tfidf_scores.items():
        digest = hashlib.blake2b(token.encode("utf-8"), digest_size=8).digest()
        index = int.from_bytes(digest, "big") % vector_size
        vector[index] += float(score)

    norm = math.sqrt(sum(value * value for value in vector))
    if norm:
        vector = [round(value / norm, 6) for value in vector]
    return vector


def _engagement_score(record: TweetRecord) -> float:
    views = float(record.views or 0)
    total = float(record.likes) + (1.5 * float(record.replies)) + (2.0 * float(record.reposts)) + (0.1 * views)
    return round(math.log1p(total), 6)


def _sentiment_score(bullish_hits: int, bearish_hits: int, token_count: int) -> float:
    denominator = max(token_count, 1)
    return round((bullish_hits - bearish_hits) / denominator, 6)


def _keyword_match_score(keyword: str | None, content: str, hashtags: list[str]) -> float:
    if not keyword:
        return 0.0

    target = keyword.lstrip("#").casefold()
    normalized_hashtags = {tag.lstrip("#").casefold() for tag in hashtags}
    if target in normalized_hashtags:
        return 1.0
    if target and target in content.casefold():
        return 0.75
    return 0.0


def _indian_script_ratio(value: str) -> float:
    visible = [character for character in value if not character.isspace()]
    if not visible:
        return 0.0
    matched = sum(_is_indian_script(character) for character in visible)
    return round(matched / len(visible), 6)


def _is_indian_script(character: str) -> bool:
    codepoint = ord(character)
    return any(start <= codepoint <= end for start, end in _INDIAN_RANGES)


def _non_ascii_ratio(value: str) -> float:
    visible = [character for character in value if not character.isspace()]
    if not visible:
        return 0.0
    matched = sum(ord(character) > 127 for character in visible)
    return round(matched / len(visible), 6)
