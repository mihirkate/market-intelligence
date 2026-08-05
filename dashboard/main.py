"""Streamlit dashboard entrypoint."""

from __future__ import annotations

import json
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


def _signal_bias_summary(frame: pd.DataFrame) -> dict[str, object]:
    """Return the compact signal metrics displayed in the dashboard header."""
    if frame.empty or "composite_signal" not in frame.columns:
        return {
            "buy_keywords": 0,
            "sell_keywords": 0,
            "neutral_keywords": 0,
            "avg_composite_signal": 0.0,
        }

    composite = frame["composite_signal"].fillna(0.0)
    return {
        "buy_keywords": int((composite > 0).sum()),
        "sell_keywords": int((composite < 0).sum()),
        "neutral_keywords": int((composite == 0).sum()),
        "avg_composite_signal": round(float(composite.mean()), 3),
    }


def build_live_summary_payload(
    *,
    overview: dict[str, object],
    collection_status: dict[str, object],
    latest_signal_frame: pd.DataFrame,
) -> dict[str, object]:
    """Build the lightweight summary rendered by the live metrics panel."""
    latest_run = overview.get("latest_run") or {}
    return {
        "overview": {
            "total_tweets": int(overview.get("total_tweets") or 0),
            "unique_users": int(overview.get("unique_users") or 0),
            "tracked_keywords": int(overview.get("tracked_keywords") or 0),
            "latest_seen_at": overview.get("latest_seen_at"),
        },
        "latest_run": {
            "run_id": latest_run.get("run_id"),
            "status": latest_run.get("status"),
            "fetched_count": int(latest_run.get("fetched_count") or 0),
            "inserted_count": int(latest_run.get("inserted_count") or 0),
            "updated_count": int(latest_run.get("updated_count") or 0),
            "duplicate_count": int(latest_run.get("duplicate_count") or 0),
        },
        "collection": {
            "total_unique_tweets_last_24_hours": int(
                collection_status.get("total_unique_tweets_last_24_hours", 0) or 0
            ),
            "remaining_tweets_to_target": int(
                collection_status.get("remaining_tweets_to_target", 0) or 0
            ),
            "projected_24h_tweets_recent_rate": int(
                collection_status.get("projected_24h_tweets_recent_rate", 0) or 0
            ),
            "recent_rate_limit_events": int(
                collection_status.get("recent_rate_limit_events", 0) or 0
            ),
            "recent_tweets_per_hour": float(
                collection_status.get("recent_tweets_per_hour", 0) or 0
            ),
            "required_tweets_per_hour_for_target": float(
                collection_status.get("required_tweets_per_hour_for_target", 0) or 0
            ),
            "target_tweets_last_24_hours": int(
                collection_status.get("target_tweets_last_24_hours", 0) or 0
            ),
            "assignment_data_collection_ready": bool(
                collection_status.get("assignment_data_collection_ready", False)
            ),
            "missing_required_keywords": collection_status.get("missing_required_keywords") or [],
        },
        "signal_bias": _signal_bias_summary(latest_signal_frame),
    }


def render_live_summary_panel(
    *,
    api_port: int,
    initial_payload: dict[str, object],
    seconds: int,
    enable_polling: bool,
) -> None:
    """Render an in-place updating metrics panel without reloading the page."""
    interval_ms = max(seconds, 5) * 1000
    summary_endpoint = "/dashboard-summary"
    components.html(
        f"""
        <style>
        :root {{
            color-scheme: light;
        }}
        body {{
            margin: 0;
            font-family: "Segoe UI", system-ui, -apple-system, BlinkMacSystemFont, sans-serif;
            color: #0f172a;
            background: transparent;
        }}
        .mi-wrap {{
            padding: 0.25rem 0 0.5rem 0;
        }}
        .mi-meta {{
            display: flex;
            flex-wrap: wrap;
            gap: 0.75rem;
            align-items: center;
            justify-content: space-between;
            margin-bottom: 0.85rem;
        }}
        .mi-meta-text {{
            font-size: 0.88rem;
            color: #475569;
        }}
        .mi-status-pill {{
            display: inline-flex;
            align-items: center;
            gap: 0.35rem;
            padding: 0.35rem 0.7rem;
            border-radius: 999px;
            font-size: 0.78rem;
            font-weight: 600;
            background: #e2e8f0;
            color: #0f172a;
        }}
        .mi-grid {{
            display: grid;
            grid-template-columns: repeat(4, minmax(0, 1fr));
            gap: 0.9rem;
            margin-bottom: 0.95rem;
        }}
        .mi-card {{
            background: linear-gradient(180deg, #ffffff 0%, #f8fafc 100%);
            border: 1px solid #e2e8f0;
            border-radius: 16px;
            padding: 0.95rem 1rem;
            box-shadow: 0 12px 30px rgba(15, 23, 42, 0.05);
        }}
        .mi-label {{
            font-size: 0.82rem;
            font-weight: 600;
            color: #64748b;
            text-transform: uppercase;
            letter-spacing: 0.04em;
            margin-bottom: 0.5rem;
        }}
        .mi-value {{
            font-size: 1.8rem;
            font-weight: 700;
            line-height: 1.1;
            color: #0f172a;
        }}
        .mi-detail {{
            margin-top: 0.25rem;
            font-size: 0.8rem;
            color: #64748b;
        }}
        .mi-line {{
            margin: 0.32rem 0;
            font-size: 0.88rem;
            color: #334155;
        }}
        .mi-alert {{
            display: none;
            margin-top: 0.7rem;
            padding: 0.75rem 0.9rem;
            border-radius: 12px;
            border: 1px solid #facc15;
            background: #fef9c3;
            color: #854d0e;
            font-size: 0.88rem;
            font-weight: 600;
        }}
        @media (max-width: 960px) {{
            .mi-grid {{
                grid-template-columns: repeat(2, minmax(0, 1fr));
            }}
        }}
        @media (max-width: 560px) {{
            .mi-grid {{
                grid-template-columns: 1fr;
            }}
            .mi-meta {{
                align-items: flex-start;
                flex-direction: column;
            }}
        }}
        </style>
        <div class="mi-wrap">
            <div class="mi-meta">
                <div id="mi-sync-text" class="mi-meta-text"></div>
                <div id="mi-ready-pill" class="mi-status-pill"></div>
            </div>
            <div class="mi-grid">
                <div class="mi-card"><div class="mi-label">Stored Tweets</div><div id="metric-total-tweets" class="mi-value">0</div></div>
                <div class="mi-card"><div class="mi-label">Unique Users</div><div id="metric-unique-users" class="mi-value">0</div></div>
                <div class="mi-card"><div class="mi-label">Tracked Keywords</div><div id="metric-tracked-keywords" class="mi-value">0</div></div>
                <div class="mi-card"><div class="mi-label">Last Run Inserts</div><div id="metric-last-run-inserts" class="mi-value">0</div></div>
                <div class="mi-card"><div class="mi-label">24h Collected</div><div id="metric-collected-24h" class="mi-value">0</div></div>
                <div class="mi-card"><div class="mi-label">To 2000 Target</div><div id="metric-remaining-target" class="mi-value">0</div></div>
                <div class="mi-card"><div class="mi-label">Projected / 24h</div><div id="metric-projected-24h" class="mi-value">0</div></div>
                <div class="mi-card"><div class="mi-label">Recent Rate Limits</div><div id="metric-rate-limits" class="mi-value">0</div></div>
                <div class="mi-card"><div class="mi-label">BUY Signals</div><div id="metric-buy-signals" class="mi-value">0</div></div>
                <div class="mi-card"><div class="mi-label">SELL Signals</div><div id="metric-sell-signals" class="mi-value">0</div></div>
                <div class="mi-card"><div class="mi-label">Neutral Signals</div><div id="metric-neutral-signals" class="mi-value">0</div></div>
                <div class="mi-card"><div class="mi-label">Avg Signal</div><div id="metric-avg-signal" class="mi-value">0.000</div></div>
            </div>
            <div id="mi-rate-line" class="mi-line"></div>
            <div id="mi-run-line" class="mi-line"></div>
            <div id="mi-target-line" class="mi-line"></div>
            <div id="mi-missing-keywords" class="mi-alert"></div>
        </div>
        <script>
        const targetWindow = window.parent;
        const pollIntervalMs = {json.dumps(interval_ms)};
        const apiPort = {json.dumps(api_port)};
        const summaryEndpoint = {json.dumps(summary_endpoint)};
        const protocol = targetWindow.location.protocol || window.location.protocol;
        const hostname = targetWindow.location.hostname || window.location.hostname;
        const apiUrl = `${{protocol}}//${{hostname}}:${{apiPort}}${{summaryEndpoint}}`;
        const pollingEnabled = {json.dumps(enable_polling)};
        const initialPayload = {json.dumps(initial_payload)};

        function setText(id, value) {{
            const element = document.getElementById(id);
            if (element) {{
                element.textContent = value;
            }}
        }}

        function setAlert(visible, message) {{
            const element = document.getElementById("mi-missing-keywords");
            if (!element) {{
                return;
            }}
            element.style.display = visible ? "block" : "none";
            element.textContent = message || "";
        }}

        function formatInteger(value) {{
            const numeric = Number(value ?? 0);
            return Number.isFinite(numeric) ? Math.round(numeric).toLocaleString() : "0";
        }}

        function formatDecimal(value, digits = 1) {{
            const numeric = Number(value ?? 0);
            return Number.isFinite(numeric) ? numeric.toFixed(digits) : (0).toFixed(digits);
        }}

        function updateSummary(payload, syncLabel) {{
            const overview = payload.overview || {{}};
            const latestRun = payload.latest_run || {{}};
            const collection = payload.collection || {{}};
            const signalBias = payload.signal_bias || {{}};

            setText("metric-total-tweets", formatInteger(overview.total_tweets));
            setText("metric-unique-users", formatInteger(overview.unique_users));
            setText("metric-tracked-keywords", formatInteger(overview.tracked_keywords));
            setText("metric-last-run-inserts", formatInteger(latestRun.inserted_count));
            setText("metric-collected-24h", formatInteger(collection.total_unique_tweets_last_24_hours));
            setText("metric-remaining-target", formatInteger(collection.remaining_tweets_to_target));
            setText("metric-projected-24h", formatInteger(collection.projected_24h_tweets_recent_rate));
            setText("metric-rate-limits", formatInteger(collection.recent_rate_limit_events));
            setText("metric-buy-signals", formatInteger(signalBias.buy_keywords));
            setText("metric-sell-signals", formatInteger(signalBias.sell_keywords));
            setText("metric-neutral-signals", formatInteger(signalBias.neutral_keywords));
            setText("metric-avg-signal", formatDecimal(signalBias.avg_composite_signal, 3));

            setText(
                "mi-rate-line",
                `Recent rate ${{formatDecimal(collection.recent_tweets_per_hour, 1)}}/hour vs required ` +
                `${{formatDecimal(collection.required_tweets_per_hour_for_target, 1)}}/hour`
            );
            setText(
                "mi-run-line",
                `Latest run ${{latestRun.run_id || "n/a"}} status=${{latestRun.status || "unknown"}} ` +
                `fetched=${{formatInteger(latestRun.fetched_count)}} updated=${{formatInteger(latestRun.updated_count)}} ` +
                `duplicates=${{formatInteger(latestRun.duplicate_count)}}`
            );
            setText(
                "mi-target-line",
                `Collection target ${{formatInteger(collection.total_unique_tweets_last_24_hours)}}/` +
                `${{formatInteger(collection.target_tweets_last_24_hours)}} ready=${{collection.assignment_data_collection_ready ? "yes" : "no"}}`
            );

            const readyPill = document.getElementById("mi-ready-pill");
            if (readyPill) {{
                const ready = Boolean(collection.assignment_data_collection_ready);
                readyPill.textContent = ready ? "Collection Ready" : "Collection In Progress";
                readyPill.style.background = ready ? "#dcfce7" : "#fee2e2";
                readyPill.style.color = ready ? "#166534" : "#991b1b";
            }}

            const missingKeywords = Array.isArray(collection.missing_required_keywords)
                ? collection.missing_required_keywords.filter(Boolean)
                : [];
            if (missingKeywords.length > 0) {{
                setAlert(true, `Missing required keyword coverage: ${{missingKeywords.join(", ")}}`);
            }} else {{
                setAlert(false, "");
            }}

            setText("mi-sync-text", syncLabel);
        }}

        async function refreshSummary() {{
            try {{
                const response = await fetch(apiUrl, {{
                    method: "GET",
                    headers: {{ "Accept": "application/json" }},
                    cache: "no-store",
                    mode: "cors",
                }});
                if (!response.ok) {{
                    return;
                }}

                const payload = await response.json();
                updateSummary(payload, `Live metrics synced at ${{new Date().toLocaleTimeString()}}`);
            }} catch (error) {{
                console.debug("Dashboard summary poll failed", error);
                setText("mi-sync-text", "Live metrics sync unavailable. Showing the last loaded snapshot.");
            }}
        }}

        updateSummary(
            initialPayload,
            pollingEnabled
                ? `Live metrics watch for updates every ${{Math.round(pollIntervalMs / 1000)}}s`
                : "Live metrics auto-sync is disabled."
        );

        if (targetWindow.__marketIntelligenceSummaryWatcher) {{
            window.clearInterval(targetWindow.__marketIntelligenceSummaryWatcher);
        }}
        if (pollingEnabled) {{
            targetWindow.__marketIntelligenceSummaryWatcher = window.setInterval(
                refreshSummary,
                pollIntervalMs
            );
        }}
        </script>
        """,
        height=520,
        width=0,
    )

st.title(settings.DASHBOARD_TITLE)
st.subheader(settings.DASHBOARD_STATUS_LABEL)
st.success(settings.DASHBOARD_STATUS)

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

dashboard_auto_refresh_enabled = getattr(settings, "DASHBOARD_AUTO_REFRESH_ENABLED", True)
dashboard_auto_refresh_seconds = getattr(settings, "DASHBOARD_AUTO_REFRESH_SECONDS", 30)
live_summary_payload = build_live_summary_payload(
    overview=overview,
    collection_status=collection_status,
    latest_signal_frame=latest_signal_frame,
)
render_live_summary_panel(
    api_port=settings.API_PORT,
    initial_payload=live_summary_payload,
    seconds=dashboard_auto_refresh_seconds,
    enable_polling=dashboard_auto_refresh_enabled,
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
