from __future__ import annotations

import hashlib
import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

import history_dispatcher.migrations.v2 as migration_v2
from history_dispatcher.crypto import StaticKeyProvider
from history_dispatcher.migrations.v2 import (
    DatabaseV2Migrator,
    MigrationV2Error,
    restore_database_backup,
)
from history_dispatcher.store import DispatcherStore


def _store(tmp_path: Path) -> DispatcherStore:
    store = DispatcherStore(
        tmp_path / "history.sqlite3",
        StaticKeyProvider(b"k" * 32),
    )
    store.append(
        {
            "id": "review-item",
            "dedupe_key": "review-item",
            "status": "queued",
            "payload": {"summary": {"text": "review hardening"}},
        }
    )
    return store


def test_migration_connection_context_closes_the_connection(tmp_path: Path) -> None:
    store = _store(tmp_path)

    with migration_v2._connect(store.database_path) as connection:
        assert connection.execute("SELECT 1").fetchone()[0] == 1

    with pytest.raises(sqlite3.ProgrammingError, match="closed"):
        connection.execute("SELECT 1")


def test_active_claim_is_rechecked_inside_the_write_transaction(
    tmp_path: Path,
) -> None:
    store = _store(tmp_path)
    backup_dir = tmp_path / "backups"

    def insert_claim_after_backup(phase: str) -> None:
        if phase != "after_backup":
            return
        claimed_at = datetime.now(timezone.utc).isoformat(timespec="seconds")
        expires_at = (
            datetime.now(timezone.utc) + timedelta(minutes=10)
        ).isoformat(timespec="seconds")
        with sqlite3.connect(store.database_path) as db:
            db.execute(
                "INSERT INTO dispatch_claims(item_id,worker_id,claimed_at,expires_at) "
                "VALUES (?,?,?,?)",
                ("review-item", "late-v1-worker", claimed_at, expires_at),
            )

    migrator = DatabaseV2Migrator(
        store.database_path,
        store.key_provider,
        backup_dir=backup_dir,
        minimum_free_bytes=0,
        fault_hook=insert_claim_after_backup,
    )

    with pytest.raises(MigrationV2Error, match="active v1 dispatch claims"):
        migrator.migrate()

    with sqlite3.connect(store.database_path) as db:
        versions = [
            int(row[0])
            for row in db.execute(
                "SELECT version FROM schema_migrations ORDER BY version"
            )
        ]
        assert versions == [1]
        assert db.execute(
            "SELECT COUNT(*) FROM sqlite_master "
            "WHERE type='table' AND name='history_events'"
        ).fetchone()[0] == 0
    assert len(list(backup_dir.glob("*.sqlite3"))) == 1


def test_preflight_rejects_partial_v1_schema_before_backup(tmp_path: Path) -> None:
    store = _store(tmp_path)
    with sqlite3.connect(store.database_path) as db:
        db.execute("DROP TABLE recipient_results")
    backup_dir = tmp_path / "backups"

    with pytest.raises(MigrationV2Error, match="required v1 table"):
        DatabaseV2Migrator(
            store.database_path,
            store.key_provider,
            backup_dir=backup_dir,
            minimum_free_bytes=0,
        ).migrate()

    assert backup_dir.exists() is False


def test_backup_directory_file_is_rejected_as_migration_error(tmp_path: Path) -> None:
    store = _store(tmp_path)
    backup_dir = tmp_path / "backups"
    backup_dir.write_text("not a directory", encoding="utf-8")

    with pytest.raises(MigrationV2Error, match="backup directory"):
        DatabaseV2Migrator(
            store.database_path,
            store.key_provider,
            backup_dir=backup_dir,
            minimum_free_bytes=0,
        ).migrate()


def test_restore_uses_verified_staging_after_source_path_is_replaced(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store = _store(tmp_path)
    report = DatabaseV2Migrator(
        store.database_path,
        store.key_provider,
        backup_dir=tmp_path / "backups",
        minimum_free_bytes=0,
    ).migrate()
    assert report.backup is not None
    backup = tmp_path / "backups" / report.backup.name
    original_bytes = backup.read_bytes()
    expected_hash = hashlib.sha256(original_bytes).hexdigest()
    original_copy = migration_v2._copy_verified_backup_to_staging

    def copy_then_replace_source(
        backup_path: Path,
        destination_directory: Path,
    ) -> tuple[Path, str]:
        staging, digest = original_copy(backup_path, destination_directory)
        backup_path.write_bytes(b"replacement after validated copy")
        return staging, digest

    monkeypatch.setattr(
        migration_v2,
        "_copy_verified_backup_to_staging",
        copy_then_replace_source,
    )
    destination = tmp_path / "restored.sqlite3"

    result = restore_database_backup(
        backup,
        destination,
        expected_sha256=expected_hash,
        confirmation=f"RESTORE {expected_hash[:12]}",
    )

    assert result["ok"] is True
    assert result["restored_sha256"] == expected_hash
    assert destination.read_bytes() == original_bytes
    with sqlite3.connect(destination) as db:
        assert db.execute("PRAGMA quick_check").fetchone()[0] == "ok"
