"""Cron entrypoint for hourly service health emails."""

from __future__ import annotations

from app.monitoring.health import run_hourly_health_report


def main() -> int:
    """Send the hourly health summary email."""
    return run_hourly_health_report()


if __name__ == "__main__":
    raise SystemExit(main())
