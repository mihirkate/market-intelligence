from __future__ import annotations

from app.monitoring.health import (
    EndpointStatus,
    HealthSnapshot,
    ServiceStatus,
    _render_email_html,
    _render_snapshot_text,
    _subject,
    detect_service_restarts,
)


def test_detect_service_restarts_returns_only_incremented_services() -> None:
    services = (
        ServiceStatus(
            name="market-intelligence-api.service",
            active_state="active",
            sub_state="running",
            restart_count=2,
            exec_main_status=0,
            exec_main_code=0,
            ok=True,
            detail="ok",
        ),
        ServiceStatus(
            name="market-intelligence-dashboard.service",
            active_state="active",
            sub_state="running",
            restart_count=1,
            exec_main_status=0,
            exec_main_code=0,
            ok=True,
            detail="ok",
        ),
    )

    restarted = detect_service_restarts(
        services,
        previous_counts={
            "market-intelligence-api.service": 1,
            "market-intelligence-dashboard.service": 1,
        },
    )

    assert len(restarted) == 1
    assert restarted[0].name == "market-intelligence-api.service"


def test_monitoring_email_rendering_uses_status_tables_and_subject() -> None:
    snapshot = HealthSnapshot(
        checked_at="2026-08-05T07:38:52.203172+00:00",
        hostname="BOMINO-NW11094",
        endpoints=(
            EndpointStatus(
                name="api",
                url="http://127.0.0.1:8000/health",
                ok=False,
                status_code=None,
                detail="connection refused",
            ),
            EndpointStatus(
                name="dashboard",
                url="http://127.0.0.1:8501/",
                ok=True,
                status_code=200,
                detail="HTTP 200",
            ),
        ),
        services=(
            ServiceStatus(
                name="market-intelligence-api.service",
                active_state="failed",
                sub_state="failed",
                restart_count=3,
                exec_main_status=1,
                exec_main_code=1,
                ok=False,
                detail="active=failed sub=failed restarts=3",
            ),
        ),
        collection_status={
            "target_tweets_last_24_hours": 2000,
            "total_unique_tweets_last_24_hours": 454,
            "remaining_tweets_to_target": 1546,
            "recent_tweets_per_hour": 52.5,
            "assignment_data_collection_ready": False,
            "missing_required_keywords": [],
        },
    )

    subject = _subject(category="Hourly Health", status="DEGRADED", snapshot=snapshot)
    html_body = _render_email_html(
        title="Hourly Health Summary",
        intro="Scheduled monitoring summary for the Market Intelligence deployment.",
        snapshot=snapshot,
    )
    text_body = _render_snapshot_text(snapshot)

    assert subject == "Market Intelligence | Hourly Health | DEGRADED | BOMINO-NW11094"
    assert "<table" in html_body
    assert "Hourly Health Summary" in html_body
    assert "Overall Status" in html_body
    assert "DEGRADED" in html_body
    assert "Collected Tweets (24h)" in html_body
    assert "Overall Status: DEGRADED" in text_body
