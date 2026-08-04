"""Structured debug artifact capture for scraper failures."""

from __future__ import annotations

import json
import traceback
from pathlib import Path
from typing import Any
from uuid import uuid4

from app.core.config import settings
from app.scraper.models import utc_now_iso


class DebugArtifactStore:
    """Write structured JSON artifacts to help diagnose live-run failures."""

    def __init__(self, *, output_dir: Path | None = None) -> None:
        self.output_dir = output_dir or settings.DEBUG_ARTIFACTS_PATH
        self.output_dir.mkdir(parents=True, exist_ok=True)

    def write_event(
        self,
        kind: str,
        *,
        payload: dict[str, Any],
        run_id: str | None = None,
        error: Exception | None = None,
    ) -> Path:
        """Persist a debug event as a standalone JSON document."""
        event = {
            "kind": kind,
            "captured_at": utc_now_iso(),
            "run_id": run_id,
            "payload": _json_safe(payload),
        }
        if error is not None:
            event["error"] = {
                "type": type(error).__name__,
                "message": str(error),
                "traceback": traceback.format_exc(),
            }

        file_name = f"{event['captured_at'][:19].replace(':', '-')}-{kind}-{uuid4().hex[:8]}.json"
        target = self.output_dir / file_name
        target.write_text(json.dumps(event, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")
        return target


def _json_safe(value: Any) -> Any:
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, dict):
        return {str(key): _json_safe(item) for key, item in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [_json_safe(item) for item in value]
    if hasattr(value, "isoformat"):
        try:
            return value.isoformat()
        except Exception:  # noqa: BLE001
            return str(value)
    if hasattr(value, "__dict__"):
        return {key: _json_safe(item) for key, item in vars(value).items() if not key.startswith("_")}
    return str(value)
