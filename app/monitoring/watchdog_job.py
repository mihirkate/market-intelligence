"""Cron entrypoint for service watchdog checks."""

from __future__ import annotations

from app.monitoring.health import run_watchdog


def main() -> int:
    """Run one watchdog cycle."""
    return run_watchdog()


if __name__ == "__main__":
    raise SystemExit(main())
