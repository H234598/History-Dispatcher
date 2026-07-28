from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from history_dispatcher.crypto import StaticKeyProvider
from history_dispatcher.migrations.v2 import DatabaseV2Migrator
from history_dispatcher.store import DispatcherStore


def _migrated_database(tmp_path: Path) -> Path:
    store = DispatcherStore(
        tmp_path / "history.sqlite3",
        StaticKeyProvider(b"k" * 32),
    )
    store.append(
        {
            "id": "legacy-attempt-item",
            "dedupe_key": "legacy-attempt-item",
            "status": "delivered",
            "payload": {
                "history_kind": "task_completion",
                "classification_confidence": "compatible",
                "codex": {
                    "session_id": "session-attempt",
                    "turn_id": "turn-attempt",
                },
                "summary": {"text": "attempt fixture"},
            },
            "recipient_results": [
                {
                    "recipient_id": "recipient-attempt",
                    "status": "accepted",
                    "channel": "telegram",
                }
            ],
        }
    )
    DatabaseV2Migrator(
        store.database_path,
        store.key_provider,
        backup_dir=tmp_path / "backups",
        minimum_free_bytes=0,
    ).migrate()
    return store.database_path


def test_target_level_attempt_number_is_unique_even_with_null_recipient(
    tmp_path: Path,
) -> None:
    database = _migrated_database(tmp_path)
    with sqlite3.connect(database) as db:
        target_id = db.execute(
            "SELECT id FROM target_deliveries LIMIT 1"
        ).fetchone()[0]
        db.execute(
            "INSERT INTO delivery_attempts("
            "id,target_delivery_id,recipient_delivery_id,worker_id,attempt_no,"
            "started_at"
            ") VALUES ('attempt-target-1', ?, NULL, 'worker', 1, '2026-07-28T00:00:00Z')",
            (target_id,),
        )
        with pytest.raises(sqlite3.IntegrityError, match="UNIQUE"):
            db.execute(
                "INSERT INTO delivery_attempts("
                "id,target_delivery_id,recipient_delivery_id,worker_id,attempt_no,"
                "started_at"
                ") VALUES ('attempt-target-2', ?, NULL, 'worker', 1, "
                "'2026-07-28T00:00:01Z')",
                (target_id,),
            )


def test_recipient_level_attempt_number_is_unique_per_recipient(
    tmp_path: Path,
) -> None:
    database = _migrated_database(tmp_path)
    with sqlite3.connect(database) as db:
        target_id, recipient_id = db.execute(
            "SELECT rd.target_delivery_id, rd.id FROM recipient_deliveries rd "
            "LIMIT 1"
        ).fetchone()
        db.execute(
            "INSERT INTO delivery_attempts("
            "id,target_delivery_id,recipient_delivery_id,worker_id,attempt_no,"
            "started_at"
            ") VALUES ('attempt-recipient-1', ?, ?, 'worker', 1, "
            "'2026-07-28T00:00:00Z')",
            (target_id, recipient_id),
        )
        with pytest.raises(sqlite3.IntegrityError, match="UNIQUE"):
            db.execute(
                "INSERT INTO delivery_attempts("
                "id,target_delivery_id,recipient_delivery_id,worker_id,attempt_no,"
                "started_at"
                ") VALUES ('attempt-recipient-2', ?, ?, 'worker', 1, "
                "'2026-07-28T00:00:01Z')",
                (target_id, recipient_id),
            )
