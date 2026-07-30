from __future__ import annotations

import json
import sqlite3
from pathlib import Path

from history_dispatcher.status_runtime_v2 import build_runtime_health_status
from history_dispatcher.status_v2 import CredentialStatus


def _runtime_tables(database: Path) -> None:
    with sqlite3.connect(database) as db:
        db.executescript(
            """
            CREATE TABLE worker_heartbeats (
                worker_id TEXT PRIMARY KEY,
                target_id TEXT NOT NULL DEFAULT '',
                capability_version TEXT NOT NULL DEFAULT '',
                state TEXT NOT NULL,
                last_heartbeat_at TEXT NOT NULL,
                details_json TEXT NOT NULL DEFAULT '{}'
            );
            CREATE TABLE target_deliveries (
                id TEXT PRIMARY KEY,
                state TEXT NOT NULL
            );
            """
        )


def test_runtime_status_reads_bounded_worker_and_delivery_health(tmp_path: Path) -> None:
    database = tmp_path / "history.sqlite3"
    _runtime_tables(database)
    with sqlite3.connect(database) as db:
        db.execute(
            "INSERT INTO worker_heartbeats("
            "worker_id,target_id,capability_version,state,last_heartbeat_at,details_json"
            ") VALUES (?,?,?,?,?,?)",
            (
                "native-worker",
                "telegram",
                "history-dispatcher-telegram-native-v1",
                "healthy",
                "2026-07-30T17:00:00Z",
                json.dumps(
                    {
                        "provider_id": "history_dispatcher",
                        "message": "token=supersecret /home/alice/private",
                    }
                ),
            ),
        )
        db.executemany(
            "INSERT INTO target_deliveries(id,state) VALUES (?,?)",
            (("one", "pending"), ("two", "delivered"), ("three", "delivered")),
        )

    status = build_runtime_health_status(
        database_path=database,
        telegram_provider="history_dispatcher",
        credential=CredentialStatus(
            configured=True,
            last_changed="2026-07-30T16:00:00Z",
        ),
        queue_counts={"queued": 2},
        generated_at="2026-07-30T17:00:01Z",
    ).as_dict()

    assert status["telegram"]["provider"] == "history_dispatcher"
    assert status["telegram"]["credential"]["configured"] is True
    assert status["queue"] == {"queued": 2}
    assert status["deliveries"] == {"delivered": 2, "pending": 1}
    assert status["workers"] == [
        {
            "worker_id": "native-worker",
            "target": "telegram",
            "provider": "history_dispatcher",
            "capability": "history-dispatcher-telegram-native-v1",
            "state": "healthy",
            "heartbeat": "2026-07-30T17:00:00Z",
        }
    ]
    rendered = json.dumps(status, ensure_ascii=False)
    assert "supersecret" not in rendered
    assert "/home/alice" not in rendered


def test_runtime_status_is_safe_before_delivery_schema_migration(tmp_path: Path) -> None:
    database = tmp_path / "history.sqlite3"
    with sqlite3.connect(database) as db:
        db.execute("CREATE TABLE history_items(id TEXT PRIMARY KEY)")

    status = build_runtime_health_status(
        database_path=database,
        telegram_provider="teebotus",
        credential=CredentialStatus(configured=False),
        queue_counts={},
        generated_at="2026-07-30T17:00:00Z",
    ).as_dict()

    assert status["workers"] == []
    assert status["deliveries"] == {}
    assert status["telegram"]["provider"] == "teebotus"


def test_runtime_status_caps_worker_rows_and_fails_closed_on_bad_details(
    tmp_path: Path,
) -> None:
    database = tmp_path / "history.sqlite3"
    _runtime_tables(database)
    with sqlite3.connect(database) as db:
        db.executemany(
            "INSERT INTO worker_heartbeats("
            "worker_id,target_id,capability_version,state,last_heartbeat_at,details_json"
            ") VALUES (?,?,?,?,?,?)",
            (
                (
                    f"worker-{index:03d}",
                    "telegram",
                    "history-dispatcher-telegram-native-v1",
                    "idle",
                    f"2026-07-30T17:{index % 60:02d}:00Z",
                    "{broken-json" if index == 0 else '{"provider_id":"history_dispatcher"}',
                )
                for index in range(70)
            ),
        )

    status = build_runtime_health_status(
        database_path=database,
        telegram_provider="history_dispatcher",
        credential=CredentialStatus(configured=False),
        queue_counts={},
        generated_at="2026-07-30T18:00:00Z",
    ).as_dict()

    assert len(status["workers"]) == 64
    malformed = next(
        worker for worker in status["workers"] if worker["worker_id"] == "worker-000"
    )
    assert malformed["provider"] == "unknown"
