"""Streamlit dashboard entrypoint."""

from __future__ import annotations

import sys
from pathlib import Path

import altair as alt
import pandas as pd
import streamlit as st
import streamlit.components.v1 as components

# Streamlit executes this file with `dashboard/` on `sys.path`, so add the
# project root explicitly to make the sibling `app/` package importable.
PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app.core.config import settings
from app.core.logging import configure_logging, get_logger
from app.scraper.collection_status import CollectionStatusReporter
from app.storage import TweetRepository
from app.visualization import downsample_frame

configure_logging()
logger = get_logger(__name__)
logger.info("Dashboard Initialized")

st.set_page_config(page_title=settings.DASHBOARD_TITLE, layout="wide")


def enable_auto_refresh(*, seconds: int) -> None:
    """Reload the browser periodically so new scrape data appears automatically."""
    interval_ms = max(seconds, 5) * 1000
    components.html(
        f"""
        <script>
        window.setTimeout(function() {{
            window.parent.location.reload();
        }}, {interval_ms});
        </script>
        """,
        height=0,
        width=0,
    )

st.title(settings.DASHBOARD_TITLE)
st.subheader(settings.DASHBOARD_STATUS_LABEL)
st.success(settings.DASHBOARD_STATUS)
dashboard_auto_refresh_enabled = getattr(settings, "DASHBOARD_AUTO_REFRESH_ENABLED", True)
dashboard_auto_refresh_seconds = getattr(settings, "DASHBOARD_AUTO_REFRESH_SECONDS", 30)
if dashboard_auto_refresh_enabled:
    enable_auto_refresh(seconds=dashboard_auto_refresh_seconds)
    st.caption(f"Auto refresh enabled every {dashboard_auto_refresh_seconds} seconds.")

try:
    repository = TweetRepository()
    repository.ping()
    reporter = CollectionStatusReporter(repository=repository)
    overview = repository.load_dashboard_overview()
    signal_frame = repository.load_recent_signals(limit=settings.DASHBOARD_SAMPLE_SIZE)
    latest_signal_frame = repository.load_latest_signal_snapshot(limit=settings.REPORT_TOP_LIMIT)
    tweet_frame = repository.load_recent_tweets(limit=settings.DASHBOARD_SAMPLE_SIZE)
    hourly_volume_frame = repository.load_hourly_volume(lookback_hours=settings.LOOKBACK_HOURS)
    influencer_frame = repository.load_top_influencers(
        lookback_hours=settings.LOOKBACK_HOURS,
        limit=settings.REPORT_TOP_LIMIT,
    )
    collection_status = reporter.read_report() or reporter.build_status()
except Exception as error:  # noqa: BLE001
    logger.exception("Dashboard failed to initialize")
    st.error(f"Dashboard data source is unavailable: {error}")
    st.stop()

metrics = st.columns(4)
metrics[0].metric("Stored Tweets", int(overview["total_tweets"] or 0))
metrics[1].metric("Unique Users", int(overview["unique_users"] or 0))
metrics[2].metric("Tracked Keywords", int(overview["tracked_keywords"] or 0))
latest_run = overview.get("latest_run") or {}
metrics[3].metric("Last Run Inserts", int(latest_run.get("inserted_count", 0) or 0))

collection_metrics = st.columns(4)
collection_metrics[0].metric(
    "24h Collected",
    int(collection_status.get("total_unique_tweets_last_24_hours", 0) or 0),
)
collection_metrics[1].metric(
    "To 2000 Target",
    int(collection_status.get("remaining_tweets_to_target", 0) or 0),
)
collection_metrics[2].metric(
    "Projected / 24h",
    int(collection_status.get("projected_24h_tweets_recent_rate", 0) or 0),
)
collection_metrics[3].metric(
    "Recent Rate Limits",
    int(collection_status.get("recent_rate_limit_events", 0) or 0),
)
st.caption(
    "Recent rate "
    f"{collection_status.get('recent_tweets_per_hour', 0)}/hour "
    f"vs required {collection_status.get('required_tweets_per_hour_for_target', 0)}/hour"
)

if latest_run:
    st.caption(
        "Latest run "
        f"{latest_run.get('run_id')} status={latest_run.get('status')} "
        f"fetched={latest_run.get('fetched_count')} "
        f"updated={latest_run.get('updated_count')} "
        f"duplicates={latest_run.get('duplicate_count')}"
    )

st.caption(
    "Collection target "
    f"{collection_status.get('total_unique_tweets_last_24_hours', 0)}/"
    f"{collection_status.get('target_tweets_last_24_hours', 0)} "
    f"ready={collection_status.get('assignment_data_collection_ready')}"
)

missing_keywords = collection_status.get("missing_required_keywords") or []
if missing_keywords:
    st.warning(f"Missing required keyword coverage: {', '.join(missing_keywords)}")

signal_metrics = st.columns(4)
if latest_signal_frame.empty:
    signal_metrics[0].metric("BUY Signals", 0)
    signal_metrics[1].metric("SELL Signals", 0)
    signal_metrics[2].metric("Neutral Signals", 0)
    signal_metrics[3].metric("Avg Signal", 0.0)
else:
    latest_signal_frame = latest_signal_frame.copy()
    signal_metrics[0].metric("BUY Signals", int((latest_signal_frame["composite_signal"] > 0).sum()))
    signal_metrics[1].metric("SELL Signals", int((latest_signal_frame["composite_signal"] < 0).sum()))
    signal_metrics[2].metric("Neutral Signals", int((latest_signal_frame["composite_signal"] == 0).sum()))
    signal_metrics[3].metric("Avg Signal", round(float(latest_signal_frame["composite_signal"].mean()), 3))

if signal_frame.empty:
    st.info("No keyword signals have been generated yet. Run the scraper first.")
else:
    signal_frame["generated_at"] = pd.to_datetime(signal_frame["generated_at"], utc=True)
    signal_frame = signal_frame.sort_values("generated_at")
    chart_frame = downsample_frame(signal_frame, max_points=settings.DASHBOARD_SAMPLE_SIZE)

    signal_chart = (
        alt.Chart(chart_frame)
        .mark_line(point=True)
        .encode(
            x=alt.X("generated_at:T", title="Generated At"),
            y=alt.Y("composite_signal:Q", title="Composite Signal"),
            color=alt.Color("keyword:N", title="Keyword"),
            tooltip=[
                "keyword",
                "tweet_count",
                alt.Tooltip("avg_sentiment:Q", format=".3f"),
                alt.Tooltip("avg_engagement:Q", format=".3f"),
                alt.Tooltip("confidence_interval_low:Q", format=".3f"),
                alt.Tooltip("confidence_interval_high:Q", format=".3f"),
            ],
        )
        .properties(height=320)
    )
    st.altair_chart(signal_chart, width="stretch")

    st.dataframe(
        latest_signal_frame[
            [
                "keyword",
                "tweet_count",
                "avg_sentiment",
                "avg_engagement",
                "composite_signal",
                "confidence_interval_low",
                "confidence_interval_high",
            ]
        ],
        width="stretch",
        hide_index=True,
    )

st.markdown("### Hourly Volume")
if hourly_volume_frame.empty:
    st.info("No hourly volume is available yet.")
else:
    hourly_volume_frame["hour_bucket"] = pd.to_datetime(hourly_volume_frame["hour_bucket"], utc=True)
    volume_chart_frame = downsample_frame(
        hourly_volume_frame.sort_values("hour_bucket"),
        max_points=settings.DASHBOARD_SAMPLE_SIZE,
    )
    volume_chart = (
        alt.Chart(volume_chart_frame)
        .mark_line(point=True)
        .encode(
            x=alt.X("hour_bucket:T", title="Hour"),
            y=alt.Y("tweet_count:Q", title="Tweet Count"),
            tooltip=[
                alt.Tooltip("hour_bucket:T", title="Hour"),
                alt.Tooltip("tweet_count:Q", title="Tweets"),
                alt.Tooltip("unique_user_count:Q", title="Unique Users"),
            ],
        )
        .properties(height=280)
    )
    st.altair_chart(volume_chart, width="stretch")

st.markdown("### Top Influencers")
if influencer_frame.empty:
    st.info("No influencer summary is available yet.")
else:
    st.dataframe(
        influencer_frame[
            [
                "username",
                "tweet_count",
                "avg_sentiment",
                "avg_engagement",
                "total_engagement",
                "latest_timestamp_utc",
            ]
        ],
        width="stretch",
        hide_index=True,
    )

st.markdown("### Recent Tweet Sample")
if tweet_frame.empty:
    st.info("No tweets are stored in the warehouse yet.")
else:
    tweet_frame["timestamp_utc"] = pd.to_datetime(tweet_frame["timestamp_utc"], utc=True, errors="coerce")
    tweet_frame["timestamp_ist"] = (
        tweet_frame["timestamp_utc"]
        .dt.tz_convert("Asia/Kolkata")
        .dt.strftime("%Y-%m-%d %I:%M:%S %p IST")
    )
    tweet_frame["timestamp_ist"] = tweet_frame["timestamp_ist"].where(
        tweet_frame["timestamp_utc"].notna(),
        "",
    )
    sampled_tweets = downsample_frame(
        tweet_frame.sort_values("timestamp_utc", ascending=False),
        max_points=min(50, settings.DASHBOARD_SAMPLE_SIZE),
    )
    st.dataframe(
        sampled_tweets[
            [
                "keyword",
                "username",
                "timestamp_utc",
                "timestamp_ist",
                "normalized_content",
                "sentiment_score",
                "engagement_score",
                "indian_script_ratio",
            ]
        ],
        width="stretch",
        hide_index=True,
    )
