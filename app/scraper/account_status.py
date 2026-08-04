"""Inspect the local twscrape account pool and current rate-limit locks."""

from __future__ import annotations

import asyncio
import json
from datetime import datetime, timezone

from twscrape import API

from app.core.config import settings
from app.core.logging import configure_logging, get_logger

logger = get_logger(__name__)


async def _collect_status() -> list[dict[str, object]]:
    api = API(
        str(settings.TWSCRAPE_ACCOUNTS_DB),
        raise_when_no_account=True,
        wait_timeout=settings.TWSCRAPE_WAIT_TIMEOUT,
        wait_interval=settings.TWSCRAPE_WAIT_INTERVAL,
    )
    accounts = await api.pool.get_all()
    now = datetime.now(timezone.utc)

    rows: list[dict[str, object]] = []
    for account in accounts:
        locks = {}
        for queue_name, locked_until in getattr(account, "locks", {}).items():
            remaining_seconds = max(0.0, (locked_until - now).total_seconds())
            locks[queue_name] = {
                "locked_until": locked_until.isoformat(),
                "remaining_seconds": round(remaining_seconds, 2),
            }

        rows.append(
            {
                "username": account.username,
                "active": getattr(account, "active", None),
                "error_msg": getattr(account, "error_msg", None),
                "last_used": getattr(getattr(account, "last_used", None), "isoformat", lambda: None)(),
                "locks": locks,
            }
        )
    return rows


def main() -> None:
    """Print the current account-pool status as JSON."""
    settings.ensure_directories()
    configure_logging()
    rows = asyncio.run(_collect_status())
    logger.info("Loaded twscrape account status count=%s", len(rows))
    print(json.dumps(rows, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
