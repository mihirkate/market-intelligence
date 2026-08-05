from __future__ import annotations

from pathlib import Path

from app.scheduler.cron import (
    CRON_END,
    CRON_START,
    CronJobSpec,
    cron_installed,
    merge_managed_block,
    render_managed_block,
)
from app.scheduler.job import run_scheduled_scrape
from app.scraper.models import ScrapeSummary


class FakeLock:
    def __init__(self, acquired: bool) -> None:
        self.acquired = acquired
        self.released = False

    def acquire(self) -> bool:
        return self.acquired

    def release(self) -> None:
        self.released = True


class FakeManager:
    def __init__(self, summary: ScrapeSummary) -> None:
        self.summary = summary
        self.run_called = False
        self.closed = False

    def run(self) -> ScrapeSummary:
        self.run_called = True
        return self.summary

    def close(self) -> None:
        self.closed = True


def test_cron_spec_renders_managed_block_with_absolute_command() -> None:
    specs = (
        CronJobSpec(
            schedule="*/10 * * * *",
            project_dir=Path("/srv/market-intelligence"),
            python_executable=Path("/srv/market-intelligence/.venv/bin/python"),
            log_path=Path("/srv/market-intelligence/logs/cron.log"),
        ),
        CronJobSpec(
            schedule="*/2 * * * *",
            project_dir=Path("/srv/market-intelligence"),
            python_executable=Path("/srv/market-intelligence/.venv/bin/python"),
            log_path=Path("/srv/market-intelligence/logs/watchdog.log"),
            module_name="app.monitoring.watchdog_job",
        ),
        CronJobSpec(
            schedule="0 * * * *",
            project_dir=Path("/srv/market-intelligence"),
            python_executable=Path("/srv/market-intelligence/.venv/bin/python"),
            log_path=Path("/srv/market-intelligence/logs/health-report.log"),
            module_name="app.monitoring.hourly_report_job",
        ),
    )

    rendered = render_managed_block(specs)

    assert rendered.startswith(f"{CRON_START}\n")
    assert "*/10 * * * * cd /srv/market-intelligence && /srv/market-intelligence/.venv/bin/python -m app.scheduler.job >> /srv/market-intelligence/logs/cron.log 2>&1" in rendered
    assert "*/2 * * * * cd /srv/market-intelligence && /srv/market-intelligence/.venv/bin/python -m app.monitoring.watchdog_job >> /srv/market-intelligence/logs/watchdog.log 2>&1" in rendered
    assert "0 * * * * cd /srv/market-intelligence && /srv/market-intelligence/.venv/bin/python -m app.monitoring.hourly_report_job >> /srv/market-intelligence/logs/health-report.log 2>&1" in rendered
    assert rendered.endswith(f"{CRON_END}\n")


def test_merge_managed_block_replaces_existing_scheduler_block() -> None:
    existing = (
        "MAILTO=ops@example.com\n"
        f"{CRON_START}\n"
        "* * * * * old command\n"
        f"{CRON_END}\n"
    )
    specs = (
        CronJobSpec(
            schedule="*/15 * * * *",
            project_dir=Path("/srv/market-intelligence"),
            python_executable=Path("/srv/market-intelligence/.venv/bin/python"),
            log_path=Path("/srv/market-intelligence/logs/cron.log"),
        ),
    )

    merged = merge_managed_block(existing, specs)

    assert merged.count(CRON_START) == 1
    assert merged.count(CRON_END) == 1
    assert "old command" not in merged
    assert "MAILTO=ops@example.com" in merged
    assert cron_installed(merged) is True


def test_run_scheduled_scrape_skips_when_lock_is_active() -> None:
    lock = FakeLock(acquired=False)
    manager_created = False

    def manager_factory() -> FakeManager:
        nonlocal manager_created
        manager_created = True
        return FakeManager(ScrapeSummary(status="completed"))

    summary = run_scheduled_scrape(
        manager_factory=manager_factory,
        lock_factory=lambda path: lock,
    )

    assert summary is None
    assert manager_created is False
    assert lock.released is False


def test_run_scheduled_scrape_runs_manager_and_releases_lock() -> None:
    lock = FakeLock(acquired=True)
    manager = FakeManager(ScrapeSummary(status="completed", tweets_collected=3))

    summary = run_scheduled_scrape(
        manager_factory=lambda: manager,
        lock_factory=lambda path: lock,
    )

    assert summary is not None
    assert summary.status == "completed"
    assert manager.run_called is True
    assert manager.closed is True
    assert lock.released is True
