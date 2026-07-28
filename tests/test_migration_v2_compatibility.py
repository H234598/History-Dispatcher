from __future__ import annotations

import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from history_dispatcher.crypto import StaticKeyProvider, decrypt_json
from history_dispatcher.migrations.v2 import DatabaseV2Migrator, MigrationV2Error
from history_dispatcher.store import DispatcherStore


def _store(tmp_path: Path) -> DispatcherStore:
    return DispatcherStore(
        tmp_path / "history.sqlite3",
        StaticKeyProvider(b"k" * 32),
    )


def test_v1_retention_can_prune_legacy_rows_without_deleting_v2_copy(
    tmp_path: Path,
) -> None:
    store = _store(tmp_path)
    store.append(
        {
            "id": "legacy-prunable",
            "dedupe_key": "legacy-prunable",
            "status": "delivered",
            "payload": {
                "history_kind": "task_completion",
                "classification_confidence": "compatible",
                "summary": {"text": "preserve encrypted v2 copy"},
            },
            "recipient_results": [
                {
                    "recipient_id": "recipient-prunable",
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
    old = (datetime.now(timezone.utc) - timedelta(days=10)).isoformat(
        timespec="seconds"
    )
    with sqlite3.connect(store.database_path) as db:
        db.execute(
            "UPDATE history_items SET status='delivered', updated_at=? WHERE id=?",
            (old, "legacy-prunable"),
        )

    result = store.prune(completed_days=1, audit_days=1)

    assert result["history_items"] == 1
    assert result["recipient_results"] == 1
    with sqlite3.connect(store.database_path) as db:
        db.row_factory = sqlite3.Row
        assert db.execute(
            "SELECT COUNT(*) FROM history_items WHERE id='legacy-prunable'"
        ).fetchone()[0] == 0
        event = db.execute(
            "SELECT encrypted_payload,legacy_item_id FROM history_events "
            "WHERE id='legacy-prunable'"
        ).fetchone()
        assert event is not None
        assert event["legacy_item_id"] == "legacy-prunable"
        assert db.execute(
            "SELECT COUNT(*) FROM recipient_deliveries"
        ).fetchone()[0] == 1
    payload = decrypt_json(
        bytes(event["encrypted_payload"]),
        store.key_provider,
        aad=b"legacy-prunable",
    )
    assert b"preserve encrypted v2 copy" in payload


def test_possible_duplicate_success_is_migrated_to_reconciliation_hold(
    tmp_path: Path,
) -> None:
    store = _store(tmp_path)
    store.append(
        {
            "id": "legacy-possible-duplicate",
            "dedupe_key": "legacy-possible-duplicate",
            "status": "delivered",
            "payload": {
                "history_kind": "task_completion",
                "classification_confidence": "compatible",
                "summary": {"text": "uncertain accept"},
            },
            "recipient_results": [
                {
                    "recipient_id": "recipient-uncertain",
                    "status": "accepted",
                    "channel": "telegram",
                    "possible_duplicate": True,
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

    with sqlite3.connect(store.database_path) as db:
        target_state, target_outcome = db.execute(
            "SELECT state,legacy_outcome FROM target_deliveries"
        ).fetchone()
        recipient_state, possible_duplicate = db.execute(
            "SELECT state,possible_duplicate FROM recipient_deliveries"
        ).fetchone()
    assert (target_state, target_outcome) == (
        "legacy_hold",
        "possible_duplicate",
    )
    assert (recipient_state, possible_duplicate) == (
        "possible_duplicate",
        1,
    )


def test_preflight_rejects_database_symlink_and_broken_backup_symlink(
    tmp_path: Path,
) -> None:
    store = _store(tmp_path)
    store.append(
        {
            "id": "legacy-symlink",
            "dedupe_key": "legacy-symlink",
            "payload": {"summary": {"text": "symlink"}},
        }
    )
    database_link = tmp_path / "database-link.sqlite3"
    database_link.symlink_to(store.database_path)

    with pytest.raises(MigrationV2Error, match="symlink"):
        DatabaseV2Migrator(
            database_link,
            store.key_provider,
            backup_dir=tmp_path / "backups",
            minimum_free_bytes=0,
        ).preflight()

    broken_backup = tmp_path / "broken-backups"
    broken_backup.symlink_to(tmp_path / "missing-target", target_is_directory=True)
    with pytest.raises(MigrationV2Error, match="symlink"):
        DatabaseV2Migrator(
            store.database_path,
            store.key_provider,
            backup_dir=broken_backup,
            minimum_free_bytes=0,
        ).migrate()
