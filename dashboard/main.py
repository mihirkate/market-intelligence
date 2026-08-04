"""Streamlit dashboard entrypoint."""

from __future__ import annotations

import sys
from pathlib import Path

import altair as alt
import pandas as pd
import streamlit as st

# Streamlit executes this file with `dashboard/` on `sys.path`, so add the
# project root explicitly to make the sibling `app/` package importable.
PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app.core.config import settings
from app.core.logging import configure_logging, get_logger
from app.storage import TweetRepository
from app.visualization import downsample_frame

configure_logging()
logger = get_logger(__name__)
logger.info("Dashboard Initialized")
repository = TweetRepository()
overview = repository.load_dashboard_overview()
signal_frame = repository.load_recent_signals(limit=settings.DASHBOARD_SAMPLE_SIZE)
tweet_frame = repository.load_recent_tweets(limit=settings.DASHBOARD_SAMPLE_SIZE)

st.set_page_config(page_title=settings.DASHBOARD_TITLE, layout="wide")

st.title(settings.DASHBOARD_TITLE)
st.subheader(settings.DASHBOARD_STATUS_LABEL)
st.success(settings.DASHBOARD_STATUS)

metrics = st.columns(4)
metrics[0].metric("Stored Tweets", int(overview["total_tweets"] or 0))
metrics[1].metric("Unique Users", int(overview["unique_users"] or 0))
metrics[2].metric("Tracked Keywords", int(overview["tracked_keywords"] or 0))
latest_run = overview.get("latest_run") or {}
metrics[3].metric("Last Run Inserts", int(latest_run.get("inserted_count", 0) or 0))

if latest_run:
    st.caption(
        "Latest run "
        f"{latest_run.get('run_id')} status={latest_run.get('status')} "
        f"fetched={latest_run.get('fetched_count')} "
        f"updated={latest_run.get('updated_count')} "
        f"duplicates={latest_run.get('duplicate_count')}"
    )

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
    st.altair_chart(signal_chart, use_container_width=True)

    latest_signal_frame = (
        signal_frame.sort_values("generated_at")
        .groupby("keyword", as_index=False)
        .tail(1)
        .sort_values("composite_signal", ascending=False)
    )
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
        use_container_width=True,
        hide_index=True,
    )

st.markdown("### Recent Tweet Sample")
if tweet_frame.empty:
    st.info("No tweets are stored in the warehouse yet.")
else:
    tweet_frame["timestamp_utc"] = pd.to_datetime(tweet_frame["timestamp_utc"], utc=True, errors="coerce")
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
                "normalized_content",
                "sentiment_score",
                "engagement_score",
                "indian_script_ratio",
            ]
        ],
        use_container_width=True,
        hide_index=True,
    )
