"""Service health checks, alerting, and recovery helpers."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from email.message import EmailMessage
from html import escape
import json
import smtplib
import socket
import subprocess
import time
from pathlib import Path
from typing import Any
from urllib import error, request

from app.core.config import settings
from app.core.logging import configure_logging, get_logger

logger = get_logger(__name__)


def utc_now_iso() -> str:
    """Return the current UTC timestamp in ISO-8601 format."""
    return datetime.now(timezone.utc).isoformat()


@dataclass(frozen=True, slots=True)
class EndpointStatus:
    """HTTP reachability result for one local endpoint."""

    name: str
    url: str
    ok: bool
    status_code: int | None
    detail: str


@dataclass(frozen=True, slots=True)
class ServiceStatus:
    """systemd status snapshot for one managed service."""

    name: str
    active_state: str
    sub_state: str
    restart_count: int
    exec_main_status: int
    exec_main_code: int
    ok: bool
    detail: str


@dataclass(frozen=True, slots=True)
class HealthSnapshot:
    """Combined service and endpoint health view."""

    checked_at: str
    hostname: str
    endpoints: tuple[EndpointStatus, ...]
    services: tuple[ServiceStatus, ...]
    collection_status: dict[str, Any] | None

    def overall_ok(self) -> bool:
        """Return whether all endpoints and services look healthy."""
        return all(endpoint.ok for endpoint in self.endpoints) and all(service.ok for service in self.services)


def _privileged_prefix() -> list[str]:
    """Return the command prefix used for privileged service operations."""
    if not settings.MONITOR_USE_SUDO:
        return []
    return ["sudo", "-n"]


def _run_command(command: list[str]) -> tuple[int, str]:
    """Execute a command and return its status code plus combined output."""
    result = subprocess.run(command, capture_output=True, text=True, check=False)
    output = "\n".join(part for part in [result.stdout.strip(), result.stderr.strip()] if part)
    return result.returncode, output


def _parse_key_value_output(output: str) -> dict[str, str]:
    """Parse `key=value` lines from `systemctl show` style output."""
    values: dict[str, str] = {}
    for line in output.splitlines():
        if "=" not in line:
            continue
        key, value = line.split("=", 1)
        values[key.strip()] = value.strip()
    return values


def _probe_endpoint(name: str, url: str) -> EndpointStatus:
    """Check that a local HTTP endpoint returns a successful response."""
    req = request.Request(url, method="GET")
    try:
        with request.urlopen(req, timeout=settings.MONITOR_REQUEST_TIMEOUT_SECONDS) as response:
            status_code = response.getcode()
            ok = 200 <= status_code < 400
            detail = f"HTTP {status_code}"
            return EndpointStatus(name=name, url=url, ok=ok, status_code=status_code, detail=detail)
    except error.HTTPError as http_error:
        return EndpointStatus(
            name=name,
            url=url,
            ok=False,
            status_code=http_error.code,
            detail=f"HTTP {http_error.code}: {http_error.reason}",
        )
    except Exception as exc:  # noqa: BLE001
        return EndpointStatus(name=name, url=url, ok=False, status_code=None, detail=str(exc))


def _service_show(service_name: str) -> ServiceStatus:
    """Inspect one systemd unit via `systemctl show`."""
    command = _privileged_prefix() + [
        "systemctl",
        "show",
        service_name,
        "--property",
        "ActiveState,SubState,NRestarts,ExecMainStatus,ExecMainCode",
    ]
    returncode, output = _run_command(command)
    if returncode != 0:
        return ServiceStatus(
            name=service_name,
            active_state="unknown",
            sub_state="unknown",
            restart_count=0,
            exec_main_status=returncode,
            exec_main_code=returncode,
            ok=False,
            detail=output or "systemctl show failed",
        )

    values = _parse_key_value_output(output)
    active_state = values.get("ActiveState", "unknown")
    sub_state = values.get("SubState", "unknown")
    restart_count = int(values.get("NRestarts", "0") or 0)
    exec_main_status = int(values.get("ExecMainStatus", "0") or 0)
    exec_main_code = int(values.get("ExecMainCode", "0") or 0)
    ok = active_state == "active"
    detail = f"active={active_state} sub={sub_state} restarts={restart_count}"
    return ServiceStatus(
        name=service_name,
        active_state=active_state,
        sub_state=sub_state,
        restart_count=restart_count,
        exec_main_status=exec_main_status,
        exec_main_code=exec_main_code,
        ok=ok,
        detail=detail,
    )


def _load_json_file(path: Path) -> dict[str, Any] | None:
    """Read a JSON document if it exists."""
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        logger.warning("Failed to parse JSON file path=%s", path)
        return None


def build_snapshot() -> HealthSnapshot:
    """Build the current combined service health snapshot."""
    endpoints = (
        _probe_endpoint("api", settings.MONITOR_API_HEALTH_URL),
        _probe_endpoint("dashboard", settings.MONITOR_DASHBOARD_URL),
    )
    services = tuple(_service_show(name) for name in settings.MONITOR_SERVICE_NAMES)
    collection_status = _load_json_file(settings.COLLECTION_STATUS_REPORT_PATH)
    return HealthSnapshot(
        checked_at=utc_now_iso(),
        hostname=socket.gethostname(),
        endpoints=endpoints,
        services=services,
        collection_status=collection_status,
    )


def _default_state() -> dict[str, Any]:
    """Return the empty monitor state payload."""
    return {
        "last_status": "unknown",
        "last_alert_at": None,
        "last_recovery_at": None,
        "last_reboot_at": None,
        "consecutive_failures": 0,
        "restart_counts": {},
    }


def load_state() -> dict[str, Any]:
    """Load the persisted watchdog state."""
    payload = _load_json_file(settings.MONITOR_STATE_PATH)
    if not payload:
        return _default_state()
    return {**_default_state(), **payload}


def save_state(state: dict[str, Any]) -> None:
    """Persist the watchdog state."""
    settings.MONITOR_STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
    settings.MONITOR_STATE_PATH.write_text(json.dumps(state, indent=2, sort_keys=True), encoding="utf-8")


def detect_service_restarts(
    services: tuple[ServiceStatus, ...],
    previous_counts: dict[str, Any],
) -> tuple[ServiceStatus, ...]:
    """Return services whose restart counter increased since the last check."""
    restarted: list[ServiceStatus] = []
    for service in services:
        previous = int(previous_counts.get(service.name, service.restart_count))
        if service.restart_count > previous:
            restarted.append(service)
    return tuple(restarted)


def _tail_file(path: Path, *, line_count: int) -> str:
    """Return the last `line_count` lines of a text file if it exists."""
    if not path.exists():
        return f"{path}: not found"
    try:
        lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError as error:
        return f"{path}: failed to read ({error})"
    excerpt = lines[-line_count:]
    return "\n".join(excerpt) if excerpt else f"{path}: empty"


def _service_status_text(service_name: str) -> str:
    """Return `systemctl status` output for one service."""
    command = _privileged_prefix() + [
        "systemctl",
        "status",
        service_name,
        "--no-pager",
        f"--lines={settings.MONITOR_LOG_TAIL_LINES}",
    ]
    _, output = _run_command(command)
    return output or f"{service_name}: no status output"


def _build_attachment_payloads(snapshot: HealthSnapshot) -> list[tuple[str, str]]:
    """Build the text attachments included with alert emails."""
    payloads = [
        ("app.log.tail.txt", _tail_file(settings.LOG_FILE_PATH, line_count=settings.MONITOR_LOG_TAIL_LINES)),
        ("cron.log.tail.txt", _tail_file(settings.CRON_LOG_PATH, line_count=settings.MONITOR_LOG_TAIL_LINES)),
        (
            "watchdog.log.tail.txt",
            _tail_file(settings.WATCHDOG_LOG_PATH, line_count=settings.MONITOR_LOG_TAIL_LINES),
        ),
    ]
    if settings.COLLECTION_STATUS_REPORT_PATH.exists():
        payloads.append(
            (
                "data_collection_status.json",
                settings.COLLECTION_STATUS_REPORT_PATH.read_text(encoding="utf-8", errors="replace"),
            )
        )
    for service in snapshot.services:
        payloads.append((f"{service.name}.status.txt", _service_status_text(service.name)))
    return payloads


def email_enabled() -> bool:
    """Return whether SMTP configuration is present."""
    return bool(settings.ALERT_EMAIL_TO and settings.SMTP_HOST)


def send_email(
    *,
    subject: str,
    body: str,
    html_body: str | None = None,
    attachments: list[tuple[str, str]] | None = None,
) -> bool:
    """Send a plaintext email with an optional HTML alternative and text attachments."""
    if not email_enabled():
        logger.warning("Email notification skipped because SMTP settings are incomplete.")
        return False

    message = EmailMessage()
    message["Subject"] = subject
    message["From"] = settings.ALERT_EMAIL_FROM or settings.SMTP_USERNAME or "market-intelligence@localhost"
    message["To"] = ", ".join(settings.ALERT_EMAIL_TO)
    message.set_content(body)
    if html_body:
        message.add_alternative(html_body, subtype="html")

    for filename, content in attachments or []:
        message.add_attachment(content, subtype="plain", filename=filename)

    try:
        with smtplib.SMTP(settings.SMTP_HOST, settings.SMTP_PORT, timeout=settings.SMTP_TIMEOUT_SECONDS) as smtp:
            smtp.ehlo()
            if settings.SMTP_USE_TLS:
                smtp.starttls()
                smtp.ehlo()
            if settings.SMTP_USERNAME:
                smtp.login(settings.SMTP_USERNAME, settings.SMTP_PASSWORD or "")
            smtp.send_message(message)
    except Exception:  # noqa: BLE001
        logger.exception("Failed to send health email subject=%s", subject)
        return False

    logger.info("Sent health email subject=%s to=%s", subject, ",".join(settings.ALERT_EMAIL_TO))
    return True


def _collection_summary_text(snapshot: HealthSnapshot) -> str:
    """Render a short collection summary from the saved status report."""
    report = snapshot.collection_status or {}
    if not report:
        return "collection_status: unavailable"
    return (
        "collection_status: "
        f"target={report.get('target_tweets_last_24_hours')} "
        f"collected={report.get('total_unique_tweets_last_24_hours')} "
        f"remaining={report.get('remaining_tweets_to_target')} "
        f"rate_per_hour={report.get('recent_tweets_per_hour')} "
        f"ready={report.get('assignment_data_collection_ready')}"
    )


def _status_label(ok: bool, *, healthy: str = "HEALTHY", unhealthy: str = "DEGRADED") -> str:
    """Return a human-readable status label."""
    return healthy if ok else unhealthy


def _stringify(value: Any) -> str:
    """Render arbitrary values into compact strings for alerts."""
    if value is None or value == "":
        return "n/a"
    if isinstance(value, bool):
        return "Yes" if value else "No"
    if isinstance(value, float):
        return f"{value:.3f}".rstrip("0").rstrip(".")
    if isinstance(value, (list, tuple)):
        return ", ".join(_stringify(item) for item in value) if value else "n/a"
    return str(value)


def _html_status_badge(label: str) -> str:
    """Render a compact HTML status badge."""
    palette = {
        "HEALTHY": ("#166534", "#dcfce7"),
        "RECOVERED": ("#166534", "#dcfce7"),
        "OK": ("#166534", "#dcfce7"),
        "DEGRADED": ("#b91c1c", "#fee2e2"),
        "CRITICAL": ("#991b1b", "#fecaca"),
        "RESTART DETECTED": ("#92400e", "#fef3c7"),
    }
    foreground, background = palette.get(label, ("#1f2937", "#e5e7eb"))
    return (
        "<span style=\"display:inline-block;padding:4px 10px;border-radius:999px;"
        f"font-weight:700;color:{foreground};background:{background};\">{escape(label)}</span>"
    )


def _render_html_table(headers: list[str], rows: list[list[Any]]) -> str:
    """Render a basic HTML table suitable for email clients."""
    header_html = "".join(
        f"<th style=\"border:1px solid #d1d5db;padding:8px;text-align:left;background:#f3f4f6;\">"
        f"{escape(header)}</th>"
        for header in headers
    )
    row_html = []
    for row in rows:
        cells = "".join(
            (
                cell
                if isinstance(cell, str) and cell.startswith("<span ")
                else f"<td style=\"border:1px solid #d1d5db;padding:8px;vertical-align:top;\">"
                f"{escape(_stringify(cell))}</td>"
            )
            if isinstance(cell, str) and cell.startswith("<td ")
            else (
                f"<td style=\"border:1px solid #d1d5db;padding:8px;vertical-align:top;\">{cell}</td>"
                if isinstance(cell, str) and cell.startswith("<span ")
                else f"<td style=\"border:1px solid #d1d5db;padding:8px;vertical-align:top;\">"
                f"{escape(_stringify(cell))}</td>"
            )
            for cell in row
        )
        row_html.append(f"<tr>{cells}</tr>")
    return (
        "<table style=\"border-collapse:collapse;width:100%;margin:12px 0;font-family:Arial,sans-serif;"
        "font-size:14px;\">"
        f"<thead><tr>{header_html}</tr></thead>"
        f"<tbody>{''.join(row_html)}</tbody>"
        "</table>"
    )


def _summary_rows(snapshot: HealthSnapshot) -> list[list[Any]]:
    report = snapshot.collection_status or {}
    return [
        ["Host", snapshot.hostname],
        ["Checked At (UTC)", snapshot.checked_at],
        ["Overall Status", _html_status_badge(_status_label(snapshot.overall_ok()))],
        ["Collection Ready", _stringify(report.get("assignment_data_collection_ready"))],
        ["24h Target", report.get("target_tweets_last_24_hours")],
        ["24h Collected", report.get("total_unique_tweets_last_24_hours")],
        ["24h Remaining", report.get("remaining_tweets_to_target")],
    ]


def _endpoint_rows(snapshot: HealthSnapshot) -> list[list[Any]]:
    return [
        [
            endpoint.name.upper(),
            _html_status_badge(_status_label(endpoint.ok)),
            endpoint.url,
            endpoint.status_code if endpoint.status_code is not None else "n/a",
            endpoint.detail,
        ]
        for endpoint in snapshot.endpoints
    ]


def _service_rows(snapshot: HealthSnapshot) -> list[list[Any]]:
    return [
        [
            service.name,
            _html_status_badge(_status_label(service.ok)),
            service.active_state,
            service.sub_state,
            service.restart_count,
            service.exec_main_status,
            service.detail,
        ]
        for service in snapshot.services
    ]


def _collection_rows(snapshot: HealthSnapshot) -> list[list[Any]]:
    report = snapshot.collection_status or {}
    if not report:
        return [["Collection Status", "Unavailable"]]
    return [
        ["Target Tweets (24h)", report.get("target_tweets_last_24_hours")],
        ["Collected Tweets (24h)", report.get("total_unique_tweets_last_24_hours")],
        ["Remaining To Target", report.get("remaining_tweets_to_target")],
        ["Recent Tweets / Hour", report.get("recent_tweets_per_hour")],
        ["Required Tweets / Hour", report.get("required_tweets_per_hour_for_target")],
        ["Rate Ratio", report.get("recent_vs_required_rate_ratio")],
        ["Recent Rate Limits", report.get("recent_rate_limit_events")],
        ["Missing Keywords", report.get("missing_required_keywords") or []],
        ["Collection Ready", report.get("assignment_data_collection_ready")],
    ]


def _render_snapshot_section_html(snapshot: HealthSnapshot, *, title: str) -> str:
    """Render one snapshot as HTML sections with status tables."""
    return "".join(
        [
            f"<h3 style=\"font-family:Arial,sans-serif;color:#111827;margin:20px 0 8px;\">{escape(title)}</h3>",
            _render_html_table(["Field", "Value"], _summary_rows(snapshot)),
            _render_html_table(["Endpoint", "Status", "URL", "HTTP", "Detail"], _endpoint_rows(snapshot)),
            _render_html_table(
                ["Service", "Status", "Active", "Sub", "Restarts", "Exec Status", "Detail"],
                _service_rows(snapshot),
            ),
            _render_html_table(["Metric", "Value"], _collection_rows(snapshot)),
        ]
    )


def _render_email_html(
    *,
    title: str,
    snapshot: HealthSnapshot,
    intro: str | None = None,
    before_snapshot: HealthSnapshot | None = None,
    restart_results: dict[str, str] | None = None,
) -> str:
    """Render an HTML email with clear status tables."""
    sections = [
        "<html><body style=\"margin:0;padding:24px;background:#f9fafb;font-family:Arial,sans-serif;color:#111827;\">",
        "<div style=\"max-width:960px;margin:0 auto;background:#ffffff;border:1px solid #e5e7eb;"
        "border-radius:12px;padding:24px;\">",
        f"<h2 style=\"margin:0 0 12px;color:#111827;\">{escape(title)}</h2>",
    ]
    if intro:
        sections.append(
            f"<p style=\"margin:0 0 16px;line-height:1.5;color:#374151;\">{escape(intro)}</p>"
        )
    if before_snapshot is not None:
        sections.append(_render_snapshot_section_html(before_snapshot, title="Before Recovery Attempt"))
    if restart_results:
        restart_rows = [[name, result] for name, result in restart_results.items()]
        sections.append(
            "<h3 style=\"font-family:Arial,sans-serif;color:#111827;margin:20px 0 8px;\">Recovery Actions</h3>"
        )
        sections.append(_render_html_table(["Service", "Action Result"], restart_rows))
    current_title = "Current Snapshot" if before_snapshot is not None or restart_results else "Health Snapshot"
    sections.append(_render_snapshot_section_html(snapshot, title=current_title))
    sections.append("</div></body></html>")
    return "".join(sections)


def _render_snapshot_text(snapshot: HealthSnapshot) -> str:
    """Render a human-readable health summary."""
    endpoint_lines = [
        (
            f"- {endpoint.name.upper():<10} status={_status_label(endpoint.ok):<8} "
            f"http={endpoint.status_code if endpoint.status_code is not None else 'n/a':<4} "
            f"url={endpoint.url} detail={endpoint.detail}"
        )
        for endpoint in snapshot.endpoints
    ]
    service_lines = [
        (
            f"- {service.name:<40} status={_status_label(service.ok):<8} "
            f"active={service.active_state:<10} sub={service.sub_state:<10} "
            f"restarts={service.restart_count:<3} exec_status={service.exec_main_status}"
        )
        for service in snapshot.services
    ]
    return "\n".join(
        [
            "Market Intelligence Health Summary",
            f"Checked At (UTC): {snapshot.checked_at}",
            f"Hostname: {snapshot.hostname}",
            f"Overall Status: {_status_label(snapshot.overall_ok())}",
            "",
            "Endpoints",
            *endpoint_lines,
            "",
            "Services",
            *service_lines,
            "",
            _collection_summary_text(snapshot),
        ]
    )


def restart_services(service_names: tuple[str, ...]) -> dict[str, str]:
    """Restart the configured services and return textual outcomes."""
    results: dict[str, str] = {}
    for service_name in service_names:
        command = _privileged_prefix() + ["systemctl", "restart", service_name]
        returncode, output = _run_command(command)
        results[service_name] = output or ("restart ok" if returncode == 0 else f"restart failed rc={returncode}")
    return results


def reboot_host() -> tuple[int, str]:
    """Request a host reboot via sudo."""
    command = _privileged_prefix() + ["/sbin/reboot"]
    return _run_command(command)


def _subject(*, category: str, status: str, snapshot: HealthSnapshot) -> str:
    return f"Market Intelligence | {category} | {status} | {snapshot.hostname}"


def _should_send_alert(last_alert_at: str | None) -> bool:
    """Throttle repeated unhealthy-state emails."""
    if not last_alert_at:
        return True
    try:
        last = datetime.fromisoformat(last_alert_at)
    except ValueError:
        return True
    delta = datetime.now(timezone.utc) - last
    return delta.total_seconds() >= settings.MONITOR_ALERT_COOLDOWN_SECONDS


def run_watchdog() -> int:
    """Check services, alert on crashes, and attempt automatic recovery."""
    settings.ensure_directories()
    configure_logging()
    state = load_state()
    snapshot = build_snapshot()

    restart_events = detect_service_restarts(snapshot.services, state.get("restart_counts", {}))
    if restart_events:
        body = (
            "A managed service restarted since the previous watchdog check.\n\n"
            f"{_render_snapshot_text(snapshot)}"
        )
        attachments = _build_attachment_payloads(snapshot)
        send_email(
            subject=_subject(category="Watchdog", status="RESTART DETECTED", snapshot=snapshot),
            body=body,
            html_body=_render_email_html(
                title="Service Restart Detected",
                intro="A managed service restarted since the previous watchdog check.",
                snapshot=snapshot,
            ),
            attachments=attachments,
        )

    if snapshot.overall_ok():
        if state.get("last_status") == "unhealthy" and settings.MONITOR_SEND_RECOVERY_EMAIL:
            send_email(
                subject=_subject(category="Watchdog", status="RECOVERED", snapshot=snapshot),
                body=f"The deployed services are healthy again.\n\n{_render_snapshot_text(snapshot)}",
                html_body=_render_email_html(
                    title="Services Recovered",
                    intro="The deployed services are healthy again.",
                    snapshot=snapshot,
                ),
            )
            state["last_recovery_at"] = snapshot.checked_at
        state["last_status"] = "healthy"
        state["consecutive_failures"] = 0
        state["restart_counts"] = {service.name: service.restart_count for service in snapshot.services}
        save_state(state)
        logger.info("Watchdog healthy hostname=%s", snapshot.hostname)
        return 0

    state["last_status"] = "unhealthy"
    state["consecutive_failures"] = int(state.get("consecutive_failures", 0)) + 1

    restart_results: dict[str, str] = {}
    if settings.MONITOR_RESTART_SERVICES:
        restart_results = restart_services(settings.MONITOR_SERVICE_NAMES)
        if settings.MONITOR_POST_RESTART_WAIT_SECONDS > 0:
            time.sleep(settings.MONITOR_POST_RESTART_WAIT_SECONDS)
        post_restart_snapshot = build_snapshot()
    else:
        post_restart_snapshot = snapshot

    body_lines = [
        "The deployed services became unhealthy.",
        "",
        "Before restart attempt:",
        _render_snapshot_text(snapshot),
    ]
    if restart_results:
        body_lines.extend(
            [
                "",
                "Restart results:",
                *[f"- {name}: {result}" for name, result in restart_results.items()],
                "",
                "After restart attempt:",
                _render_snapshot_text(post_restart_snapshot),
            ]
        )
    attachments = _build_attachment_payloads(post_restart_snapshot)

    if _should_send_alert(state.get("last_alert_at")):
        send_email(
            subject=_subject(category="Watchdog", status="DEGRADED", snapshot=post_restart_snapshot),
            body="\n".join(body_lines),
            html_body=_render_email_html(
                title="Service Health Degraded",
                intro="The deployed services became unhealthy and the watchdog attempted automatic recovery.",
                before_snapshot=snapshot,
                restart_results=restart_results,
                snapshot=post_restart_snapshot,
            ),
            attachments=attachments,
        )
        state["last_alert_at"] = utc_now_iso()

    if (
        not post_restart_snapshot.overall_ok()
        and settings.MONITOR_REBOOT_ON_CRITICAL
        and state["consecutive_failures"] >= settings.MONITOR_FAILURES_BEFORE_REBOOT
    ):
        send_email(
            subject=_subject(category="Watchdog", status="CRITICAL", snapshot=post_restart_snapshot),
            body=(
                "Repeated watchdog failures exceeded the configured threshold. "
                "The host reboot command is being executed.\n\n"
                f"{_render_snapshot_text(post_restart_snapshot)}"
            ),
            html_body=_render_email_html(
                title="Host Reboot Requested",
                intro=(
                    "Repeated watchdog failures exceeded the configured threshold. "
                    "The host reboot command is being executed."
                ),
                snapshot=post_restart_snapshot,
            ),
            attachments=attachments,
        )
        reboot_host()
        state["last_reboot_at"] = utc_now_iso()

    state["restart_counts"] = {service.name: service.restart_count for service in post_restart_snapshot.services}
    save_state(state)
    logger.warning("Watchdog detected unhealthy services hostname=%s", snapshot.hostname)
    return 1


def run_hourly_health_report() -> int:
    """Send an hourly health summary email."""
    settings.ensure_directories()
    configure_logging()
    snapshot = build_snapshot()
    subject = _subject(
        category="Hourly Health",
        status="HEALTHY" if snapshot.overall_ok() else "DEGRADED",
        snapshot=snapshot,
    )
    send_email(
        subject=subject,
        body=_render_snapshot_text(snapshot),
        html_body=_render_email_html(
            title="Hourly Health Summary",
            intro="Scheduled monitoring summary for the Market Intelligence deployment.",
            snapshot=snapshot,
        ),
    )
    logger.info("Hourly health report generated hostname=%s", snapshot.hostname)
    return 0
