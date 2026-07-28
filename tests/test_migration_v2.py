from __future__ import annotations

import json
import sqlite3
import stat
from pathlib import Path

import pytest

from history_dispatcher.crypto import StaticKeyProvider, decrypt_json
from history_dispatcher.migrations.v2 import (
    DatabaseV2Migrator,
    MigrationV2Error,
    restore_database_backup,
    verify_database_v2,
)
from history_dispatcher.schema_v2 import DB_SCHEMA_VERSION, V2_TABLES
from history_dispatcher.store import DispatcherStore


def _store(tmp_path: Path, *, key: bytes = b"k" * 32) -> DispatcherStore:
    return DispatcherStore(
        tmp_path / "history.sqlite3",
        StaticKeyProvider(key),
    )


def _schema_versions(path: Path) -> list[int]:
    with sqlite3.connect(path) as db:
        return [
            int(row[0])
            for row in db.execute(
                "SELECT version FROM schema_migrations ORDER BY version"
            ).fetchall()
        ]


def _table_names(path: Path) -> set[str]:
    with sqlite3.connect(path) as db:
        return {
            str(row[0])
            for row in db.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            ).fetchall()
        }


def _seed_legacy_rows(store: DispatcherStore) -> None:
    store.append(
        {
            "id": "legacy-unknown",
            "source": "codex",
            "dedupe_key": "legacy-unknown",
            "kind": "codex_run_summary",
            "project": "/home/alice/UnknownProject",
            "status": "queued",
            "payload": {
                "codex": {
                    "session_id": "session-unknown",
                    "turn_id": "turn-unknown",
                },
                "summary": {"text": "legacy unknown"},
            },
        }
    )
    store.append(
        {
            "id": "legacy-explicit",
            "source": "codex",
            "dedupe_key": "legacy-explicit",
            "kind": "codex_run_summary",
            "project": "https://example.invalid/H234598/History-Dispatcher.git",
            "status": "delivered",
            "payload": {
                "history_kind": "task_completion",
                "classification_schema_version": 1,
                "classification_confidence": "compatible",
                "codex": {
                    "session_id": "session-explicit",
                    "turn_id": "turn-explicit",
                },
                "summary": {"text": "explicit completion"},
            },
            "recipient_results": [
                {
                    "recipient_id": "admin-account-1",
                    "status": "accepted",
                    "channel": "telegram",
                    "message_ref": "telegram-message-123",
                }
            ],
        }
    )
    store.append(
        {
            "id": "legacy-partial",
            "source": "teebotus-legacy",
            "dedupe_key": "legacy-partial",
            "kind": "codex_run_summary",
            "project": "/home/alice/PartialProject",
            "status": "delivered",
            "attempt_count": 2,
            "payload": {
                "codex": {
                    "session_id": "session-partial",
                    "turn_id": "turn-partial",
                },
                "summary": {"text": "partial delivery"},
            },
            "recipient_results": [
                {
                    "recipient_id": "admin-account-2",
                    "status": "delivered",
                    "channel": "telegram",
                    "message_ref": "telegram-message-456",
                },
                {
                    "recipient_id": "admin-account-3",
                    "status": "failed",
                    "channel": "telegram",
                    "reason": "temporary private error",
                },
            ],
        }
    )


def test_v2_dry_run_is_write_free_and_reports_conservative_mapping(
    tmp_path: Path,
) -> None:
    store = _store(tmp_path)
    _seed_legacy_rows(store)
    backup_dir = tmp_path / "backups"
    migrator = DatabaseV2Migrator(
        store.database_path,
        store.key_provider,
        backup_dir=backup_dir,
        minimum_free_bytes=0,
    )

    report = migrator.migrate(dry_run=True)

    assert report.ok is True
    assert report.dry_run is True
    assert report.backup is None
    assert report.history_events == 3
    assert report.mapping_counts["kind:task_completion"] == 1
    assert report.mapping_counts["kind:unknown"] == 2
    assert report.no_external_dispatch_created is True
    assert _schema_versions(store.database_path) == [1]
    assert "history_events" not in _table_names(store.database_path)
    assert backup_dir.exists() is False


def test_v2_migration_is_additive_encrypted_and_never_creates_retryable_targets(
    tmp_path: Path,
) -> None:
    store = _store(tmp_path)
    _seed_legacy_rows(store)
    backup_dir = tmp_path / "backups"
    migrator = DatabaseV2Migrator(
        store.database_path,
        store.key_provider,
        backup_dir=backup_dir,
        minimum_free_bytes=0,
    )

    report = migrator.migrate()

    assert report.ok is True
    assert report.dry_run is False
    assert report.idempotent is False
    assert report.source_schema_version == 1
    assert report.target_schema_version == DB_SCHEMA_VERSION
    assert report.history_events == 3
    assert report.route_plans == 2
    assert report.target_deliveries == 2
    assert report.recipient_deliveries == 3
    assert report.no_external_dispatch_created is True
    assert report.backup is not None
    backup_path = backup_dir / report.backup.name
    assert backup_path.is_file()
    assert stat.S_IMODE(backup_path.stat().st_mode) == 0o600
    assert stat.S_IMODE(store.database_path.stat().st_mode) == 0o600
    assert report.backup.sha256
    assert list(backup_dir.iterdir()) == [backup_path]

    verification = verify_database_v2(store.database_path)
    assert verification["ok"] is True
    assert verification["history_items"] == verification["history_events"] == 3
    assert verification["migrated_legacy_events"] == 3
    assert set(V2_TABLES) <= _table_names(store.database_path)
    assert _schema_versions(store.database_path) == [1, 2]

    with sqlite3.connect(store.database_path) as db:
        db.row_factory = sqlite3.Row
        events = db.execute(
            "SELECT * FROM history_events ORDER BY id"
        ).fetchall()
        assert {str(row["operational_state"]) for row in events} == {
            "legacy_hold"
        }
        assert {int(row["legacy_hold"]) for row in events} == {1}
        by_id = {str(row["id"]): row for row in events}
        assert by_id["legacy-explicit"]["history_kind"] == "task_completion"
        assert by_id["legacy-unknown"]["history_kind"] == "unknown"
        assert by_id["legacy-partial"]["history_kind"] == "unknown"
        assert by_id["legacy-explicit"]["classification_confidence"] == "compatible"
        assert by_id["legacy-unknown"]["classification_confidence"] == "ambiguous"
        serialized_metadata = "\n".join(
            "|".join(
                str(row[key])
                for key in (
                    "session_key",
                    "turn_key",
                    "parent_thread_key",
                    "project_id",
                    "project_label",
                )
            )
            for row in events
        )
        for forbidden in (
            "session-explicit",
            "turn-explicit",
            "/home/alice",
            "admin-account",
        ):
            assert forbidden not in serialized_metadata

        copied = by_id["legacy-explicit"]
        raw = decrypt_json(
            bytes(copied["encrypted_payload"]),
            store.key_provider,
            aad=b"legacy-explicit",
        )
        assert json.loads(raw)["summary"]["text"] == "explicit completion"

        target_rows = db.execute(
            "SELECT target_id,state,legacy_outcome FROM target_deliveries "
            "ORDER BY id"
        ).fetchall()
        assert {str(row["state"]) for row in target_rows} == {
            "delivered",
            "legacy_hold",
        }
        assert not db.execute(
            "SELECT 1 FROM target_deliveries "
            "WHERE state IN ('pending','claimed','failed_retryable')"
        ).fetchone()

        recipients = db.execute(
            "SELECT recipient_key,state,external_message_ref_key,last_error_class "
            "FROM recipient_deliveries ORDER BY id"
        ).fetchall()
        assert len(recipients) == 3
        rendered = json.dumps([dict(row) for row in recipients], sort_keys=True)
        for forbidden in (
            "admin-account-1",
            "admin-account-2",
            "admin-account-3",
            "telegram-message-123",
            "telegram-message-456",
            "temporary private error",
        ):
            assert forbidden not in rendered
        assert {str(row["state"]) for row in recipients} == {
            "accepted",
            "delivered",
            "legacy_hold",
        }

        journal = db.execute(
            "SELECT phase,backup_name,backup_sha256,report_json "
            "FROM migration_journal"
        ).fetchone()
        assert journal["phase"] == "verified"
        assert journal["backup_name"] == report.backup.name
        assert journal["backup_sha256"] == report.backup.sha256
        assert "/home/" not in str(journal["report_json"])


def test_v2_migration_is_idempotent_and_does_not_create_second_backup(
    tmp_path: Path,
) -> None:
    store = _store(tmp_path)
    _seed_legacy_rows(store)
    backup_dir = tmp_path / "backups"
    migrator = DatabaseV2Migrator(
        store.database_path,
        store.key_provider,
        backup_dir=backup_dir,
        minimum_free_bytes=0,
    )
    first = migrator.migrate()
    backups_before = sorted(backup_dir.iterdir())

    second = migrator.migrate()

    assert first.idempotent is False
    assert second.idempotent is True
    assert second.backup is None
    assert sorted(backup_dir.iterdir()) == backups_before
    assert verify_database_v2(store.database_path)["ok"] is True


def test_v2_database_triggers_block_route_mutation_and_success_downgrades(
    tmp_path: Path,
) -> None:
    store = _store(tmp_path)
    _seed_legacy_rows(store)
    DatabaseV2Migrator(
        store.database_path,
        store.key_provider,
        backup_dir=tmp_path / "backups",
        minimum_free_bytes=0,
    ).migrate()

    with sqlite3.connect(store.database_path) as db:
        route_id = db.execute("SELECT id FROM route_plans LIMIT 1").fetchone()[0]
        with pytest.raises(sqlite3.IntegrityError, match="immutable"):
            db.execute(
                "UPDATE route_plans SET config_revision='changed' WHERE id=?",
                (route_id,),
            )

        delivered_target = db.execute(
            "SELECT id FROM target_deliveries WHERE state='delivered' LIMIT 1"
        ).fetchone()[0]
        with pytest.raises(sqlite3.IntegrityError, match="invalid target"):
            db.execute(
                "UPDATE target_deliveries SET state='pending' WHERE id=?",
                (delivered_target,),
            )

        accepted_recipient = db.execute(
            "SELECT id FROM recipient_deliveries WHERE state='accepted' LIMIT 1"
        ).fetchone()[0]
        with pytest.raises(sqlite3.IntegrityError, match="invalid recipient"):
            db.execute(
                "UPDATE recipient_deliveries SET state='failed_retryable' WHERE id=?",
                (accepted_recipient,),
            )


def test_v2_migration_rolls_back_schema_and_rows_on_injected_failure(
    tmp_path: Path,
) -> None:
    store = _store(tmp_path)
    _seed_legacy_rows(store)
    backup_dir = tmp_path / "backups"

    def fail_after_rows(phase: str) -> None:
        if phase == "after_rows":
            raise RuntimeError("injected migration failure")

    migrator = DatabaseV2Migrator(
        store.database_path,
        store.key_provider,
        backup_dir=backup_dir,
        minimum_free_bytes=0,
        fault_hook=fail_after_rows,
    )

    with pytest.raises(MigrationV2Error, match="rolled back"):
        migrator.migrate()

    assert _schema_versions(store.database_path) == [1]
    assert "history_events" not in _table_names(store.database_path)
    backups = list(backup_dir.iterdir())
    assert len(backups) == 1
    assert backups[0].suffix == ".sqlite3"
    with sqlite3.connect(store.database_path) as db:
        assert db.execute("PRAGMA quick_check").fetchone()[0] == "ok"
        assert db.execute("SELECT COUNT(*) FROM history_items").fetchone()[0] == 3


def test_v2_migration_refuses_active_v1_claim_before_backup(tmp_path: Path) -> None:
    store = _store(tmp_path)
    store.append(
        {
            "id": "claimed-item",
            "dedupe_key": "claimed-item",
            "payload": {"summary": {"text": "claimed"}},
        }
    )
    assert store.claim(worker_id="legacy-worker", limit=1, claim_ttl_seconds=300)
    backup_dir = tmp_path / "backups"
    migrator = DatabaseV2Migrator(
        store.database_path,
        store.key_provider,
        backup_dir=backup_dir,
        minimum_free_bytes=0,
    )

    with pytest.raises(MigrationV2Error, match="active v1 dispatch claims"):
        migrator.migrate()

    assert backup_dir.exists() is False
    assert _schema_versions(store.database_path) == [1]


def test_wrong_key_fails_before_any_backup_or_schema_write(tmp_path: Path) -> None:
    store = _store(tmp_path, key=b"k" * 32)
    _seed_legacy_rows(store)
    backup_dir = tmp_path / "backups"
    migrator = DatabaseV2Migrator(
        store.database_path,
        StaticKeyProvider(b"z" * 32),
        backup_dir=backup_dir,
        minimum_free_bytes=0,
    )

    with pytest.raises(MigrationV2Error, match="cannot be verified"):
        migrator.migrate()

    assert _schema_versions(store.database_path) == [1]
    assert "history_events" not in _table_names(store.database_path)
    assert backup_dir.exists() is False


def test_preflight_backup_can_restore_original_v1_database(tmp_path: Path) -> None:
    store = _store(tmp_path)
    _seed_legacy_rows(store)
    backup_dir = tmp_path / "backups"
    report = DatabaseV2Migrator(
        store.database_path,
        store.key_provider,
        backup_dir=backup_dir,
        minimum_free_bytes=0,
    ).migrate()
    assert report.backup is not None
    backup_path = backup_dir / report.backup.name
    restored_path = tmp_path / "restored-v1.sqlite3"

    restored = restore_database_backup(
        backup_path,
        restored_path,
        expected_sha256=report.backup.sha256,
        confirmation=f"RESTORE {report.backup.sha256[:12]}",
    )

    assert restored["ok"] is True
    assert restored["quick_check"] == "ok"
    assert stat.S_IMODE(restored_path.stat().st_mode) == 0o600
    assert _schema_versions(restored_path) == [1]
    assert "history_events" not in _table_names(restored_path)
    assert not Path(f"{restored_path}-wal").exists()
    assert not Path(f"{restored_path}-shm").exists()
    with sqlite3.connect(restored_path) as db:
        assert db.execute("SELECT COUNT(*) FROM history_items").fetchone()[0] == 3
        assert db.execute("SELECT COUNT(*) FROM recipient_results").fetchone()[0] == 3


def test_restore_rejects_wrong_hash_and_confirmation(tmp_path: Path) -> None:
    store = _store(tmp_path)
    _seed_legacy_rows(store)
    report = DatabaseV2Migrator(
        store.database_path,
        store.key_provider,
        backup_dir=tmp_path / "backups",
        minimum_free_bytes=0,
    ).migrate()
    assert report.backup is not None
    backup = tmp_path / "backups" / report.backup.name

    with pytest.raises(MigrationV2Error, match="hash"):
        restore_database_backup(
            backup,
            tmp_path / "bad-hash.sqlite3",
            expected_sha256="0" * 64,
            confirmation="RESTORE 000000000000",
        )
    with pytest.raises(MigrationV2Error, match="confirmation"):
        restore_database_backup(
            backup,
            tmp_path / "bad-confirm.sqlite3",
            expected_sha256=report.backup.sha256,
            confirmation="RESTORE WRONG",
        )
