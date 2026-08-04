from __future__ import annotations

import json

from app.scraper.checkpoint import CheckpointStore, ScrapeCheckpoint


def test_checkpoint_save_and_restore_ignores_legacy_unknown_fields(tmp_path) -> None:
    store = CheckpointStore(path=tmp_path / "checkpoint.json")
    payload = {
        "run_id": "run-1",
        "last_keyword": "#nifty50",
        "last_url": "https://x.com/alice/status/1",
        "tweets_collected": 42,
        "urls_discovered": 75,
        "legacy_field": "ignore-me",
    }
    (tmp_path / "checkpoint.json").write_text(json.dumps(payload), encoding="utf-8")

    restored = store.load()
    restored.tweets_updated = 4
    store.save(restored)

    assert restored.run_id == "run-1"
    assert restored.last_keyword == "#nifty50"
    assert restored.last_url == "https://x.com/alice/status/1"
    assert restored.tweets_collected == 42
    assert restored.urls_discovered == 75


def test_checkpoint_round_trip_preserves_new_run_fields(tmp_path) -> None:
    store = CheckpointStore(path=tmp_path / "checkpoint.json")
    checkpoint = ScrapeCheckpoint(
        run_id="run-2",
        last_started_at="2026-08-04T10:00:00+00:00",
        last_completed_at="2026-08-04T10:01:00+00:00",
        last_keyword="#sensex",
        last_url="https://x.com/alice/status/2",
        tweets_collected=5,
        urls_discovered=9,
        tweets_updated=3,
        duplicate_tweets=3,
        parquet_rows_written=5,
        signal_rows_written=2,
    )

    store.save(checkpoint)
    restored = store.load()

    assert restored.run_id == "run-2"
    assert restored.last_started_at == "2026-08-04T10:00:00+00:00"
    assert restored.last_completed_at == "2026-08-04T10:01:00+00:00"
    assert restored.tweets_updated == 3
    assert restored.parquet_rows_written == 5
    assert restored.signal_rows_written == 2
