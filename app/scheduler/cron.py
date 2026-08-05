"""Render and manage the recurring cron jobs."""

from __future__ import annotations

import argparse
from dataclasses import dataclass
import os
from pathlib import Path
import shlex
import subprocess
import sys

from app.core.config import settings

CRON_MARKER = "market-intelligence-jobs"
CRON_START = f"# BEGIN {CRON_MARKER}"
CRON_END = f"# END {CRON_MARKER}"
LEGACY_CRON_MARKER = "market-intelligence-scraper"
LEGACY_CRON_START = f"# BEGIN {LEGACY_CRON_MARKER}"
LEGACY_CRON_END = f"# END {LEGACY_CRON_MARKER}"


@dataclass(frozen=True, slots=True)
class CronJobSpec:
    """Cron job definition for one scheduled background task."""

    schedule: str
    project_dir: Path
    python_executable: Path
    log_path: Path
    module_name: str = "app.scheduler.job"
    env_file: Path | None = None

    def command(self) -> str:
        """Return the shell command executed by cron."""
        env_prefix = ""
        if self.env_file is not None:
            env_prefix = f"ENV_FILE={shlex.quote(str(self.env_file))} "
        return (
            f"cd {shlex.quote(str(self.project_dir))} && "
            f"{env_prefix}{shlex.quote(str(self.python_executable))} -m {self.module_name} "
            f">> {shlex.quote(str(self.log_path))} 2>&1"
        )

    def render(self) -> str:
        """Render one cron line."""
        return f"{self.schedule} {self.command()}"


def build_default_specs(*, python_executable: str | None = None) -> tuple[CronJobSpec, ...]:
    """Build the default recurring job specs from application settings."""
    python_path = Path(python_executable) if python_executable else Path(sys.executable)
    env_file_raw = os.getenv("ENV_FILE")
    env_file = None
    if env_file_raw:
        env_file = Path(env_file_raw).expanduser()
        if not env_file.is_absolute():
            env_file = (settings.BASE_DIR / env_file).resolve()
    return (
        CronJobSpec(
            schedule=settings.CRON_SCHEDULE,
            project_dir=settings.BASE_DIR,
            python_executable=python_path,
            log_path=settings.CRON_LOG_PATH,
            module_name="app.scheduler.job",
            env_file=env_file,
        ),
        CronJobSpec(
            schedule=settings.WATCHDOG_SCHEDULE,
            project_dir=settings.BASE_DIR,
            python_executable=python_path,
            log_path=settings.WATCHDOG_LOG_PATH,
            module_name="app.monitoring.watchdog_job",
            env_file=env_file,
        ),
        CronJobSpec(
            schedule=settings.HEALTH_REPORT_SCHEDULE,
            project_dir=settings.BASE_DIR,
            python_executable=python_path,
            log_path=settings.HEALTH_REPORT_LOG_PATH,
            module_name="app.monitoring.hourly_report_job",
            env_file=env_file,
        ),
    )


def render_managed_block(specs: tuple[CronJobSpec, ...]) -> str:
    """Render the full managed cron block."""
    lines = "\n".join(spec.render() for spec in specs)
    return f"{CRON_START}\n{lines}\n{CRON_END}\n"


def strip_managed_block(crontab_text: str) -> str:
    """Remove the managed cron blocks from an existing crontab."""
    lines = crontab_text.splitlines()
    result: list[str] = []
    in_block = False
    for line in lines:
        stripped = line.strip()
        if stripped in {CRON_START, LEGACY_CRON_START}:
            in_block = True
            continue
        if stripped in {CRON_END, LEGACY_CRON_END}:
            in_block = False
            continue
        if not in_block:
            result.append(line)

    cleaned = "\n".join(line for line in result if line.strip())
    return f"{cleaned}\n" if cleaned else ""


def merge_managed_block(crontab_text: str, specs: tuple[CronJobSpec, ...]) -> str:
    """Add or replace the managed cron block inside the provided crontab text."""
    base = strip_managed_block(crontab_text)
    return f"{base}{render_managed_block(specs)}"


def read_crontab() -> str:
    """Read the current user's crontab, returning an empty string if none exists."""
    try:
        result = subprocess.run(
            ["crontab", "-l"],
            capture_output=True,
            text=True,
            check=False,
        )
    except FileNotFoundError as error:
        raise RuntimeError("The `crontab` command is not installed on this host.") from error
    if result.returncode == 0:
        return result.stdout

    stderr = (result.stderr or "").lower()
    stdout = (result.stdout or "").lower()
    if "no crontab" in stderr or "no crontab" in stdout:
        return ""

    raise RuntimeError(result.stderr.strip() or result.stdout.strip() or "Failed to read crontab.")


def write_crontab(crontab_text: str) -> None:
    """Write a complete crontab for the current user."""
    try:
        subprocess.run(
            ["crontab", "-"],
            input=crontab_text,
            text=True,
            check=True,
        )
    except FileNotFoundError as error:
        raise RuntimeError("The `crontab` command is not installed on this host.") from error


def install_cron(specs: tuple[CronJobSpec, ...]) -> str:
    """Install or replace the managed cron block."""
    updated = merge_managed_block(read_crontab(), specs)
    write_crontab(updated)
    return updated


def remove_cron() -> str:
    """Remove the managed scraper cron block."""
    updated = strip_managed_block(read_crontab())
    write_crontab(updated)
    return updated


def cron_installed(crontab_text: str) -> bool:
    """Return whether the managed cron block is present."""
    return CRON_START in crontab_text and CRON_END in crontab_text


def build_parser() -> argparse.ArgumentParser:
    """Build the CLI parser."""
    parser = argparse.ArgumentParser(description="Manage the recurring cron entries.")
    subparsers = parser.add_subparsers(dest="command", required=True)

    subparsers.add_parser("render", help="Print the managed cron block.")
    subparsers.add_parser("install", help="Install or update the managed cron block.")
    subparsers.add_parser("status", help="Show whether the managed cron block is installed.")
    subparsers.add_parser("remove", help="Remove the managed cron block.")
    return parser


def main(argv: list[str] | None = None) -> int:
    """CLI entrypoint for cron management."""
    parser = build_parser()
    args = parser.parse_args(argv)
    specs = build_default_specs()

    try:
        if args.command == "render":
            print(render_managed_block(specs), end="")
            return 0

        if args.command == "install":
            print(install_cron(specs), end="")
            return 0

        if args.command == "status":
            current = read_crontab()
            print("installed" if cron_installed(current) else "not-installed")
            return 0

        if args.command == "remove":
            print(remove_cron(), end="")
            return 0
    except RuntimeError as error:
        parser.exit(1, f"{error}\n")

    parser.error(f"Unsupported command: {args.command}")
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
