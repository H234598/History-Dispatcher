from __future__ import annotations

import sqlite3
import stat
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from history_dispatcher.crypto import StaticKeyProvider
from history_dispatcher.migrations import (
    DatabaseV2Migrator,
    DatabaseV3Migrator,
    DatabaseV4Migrator,
    MigrationV4Error,
    verify_database_v4,
)
from history_dispatcher.store import DispatcherStore


def _v3_database(tmp_path: Path) -> tuple[Path, StaticKeyProvider]:
    provider = StaticKeyProvider(b"k" * 32)
    database = tmp_path / "state" / "history.sqlite3"
    DispatcherStore(database, provider)
    DatabaseV2Migrator(
        database,
        provider,
        backup_dir=tmp_path / "backups-v2",
        minimum_free_bytes=0,
    ).migrate()
    DatabaseV3Migrator(
        database,
        provider,
        backup_dir=tmp_path / "backups-v3",
    ).migrate()
    return database, provider


def _versions(database: Path) -> list[int]:
    with sqlite3.connect(database) as db:
        return [
            int(row[0])
            for row in db.execute(
                "SELECT version FROM schema_migrations ORDER BY version"
            )
        ]


def test_v4_dry_run_is_write_free(tmp_path: Path) -> None:
    database, provider = _v3_database(tmp_path)
    backup_dir = tmp_path / "backups-v4"

    report = DatabaseV4Migrator(
        database,
        provider,
        backup_dir=backup_dir,
    ).migrate(dry_run=True)

    assert report.ok is True
    assert report.dry_run is True
    assert report.source_schema_version == 3
    assert report.target_schema_version == 4
    assert report.metadata_rows == 0
    assert report.audit_rows == 0
    assert report.backup is None
    assert backup_dir.exists() is False
    assert _versions(database) == [1, 2, 3]
    with sqlite3.connect(database) as db:
        for table in ("telegram_secret_metadata", "credential_audit"):
            assert db.execute(
                "SELECT COUNT(*) FROM sqlite_master "
                "WHERE type='table' AND name=?",
                (table,),
            ).fetchone()[0] == 0


def test_v4_apply_creates_secret_free_tables_and_private_backup(
    tmp_path: Path,
) -> None:
    database, provider = _v3_database(tmp_path)
    backup_dir = tmp_path / "backups-v4"

    report = DatabaseV4Migrator(
        database,
        provider,
        backup_dir=backup_dir,
    ).migrate()

    assert report.ok is True
    assert report.idempotent is False
    assert report.target_schema_version == 4
    assert report.backup is not None
    backup = backup_dir / report.backup.name
    assert backup.is_file()
    assert stat.S_IMODE(backup.stat().st_mode) == 0o600
    assert stat.S_IMODE(backup_dir.stat().st_mode) == 0o700
    assert _versions(database) == [1, 2, 3, 4]
    verification = verify_database_v4(database)
    assert verification["ok"] is True
    assert verification["metadata_rows"] == 0
    assert verification["audit_rows"] == 0

    with sqlite3.connect(database) as db:
        metadata_columns = {
            row[1]
            for row in db.execute("PRAGMA table_info(telegram_secret_metadata)")
        }
        audit_columns = {
            row[1] for row in db.execute("PRAGMA table_info(credential_audit)")
        }
    for forbidden in ("token", "chat_id", "secret", "value", "profile_ref"):
        assert forbidden not in metadata_columns
        assert forbidden not in audit_columns


def test_v4_second_run_is_idempotent_without_second_backup(tmp_path: Path) -> None:
    database, provider = _v3_database(tmp_path)
    backup_dir = tmp_path / "backups-v4"
    migrator = DatabaseV4Migrator(database, provider, backup_dir=backup_dir)
    first = migrator.migrate()
    backups = sorted(backup_dir.iterdir())

    second = migrator.migrate()

    assert first.backup is not None
    assert second.idempotent is True
    assert second.backup is None
    assert sorted(backup_dir.iterdir()) == backups


def test_v4_constraints_reject_secret_kind_and_plain_profile_columns(
    tmp_path: Path,
) -> None:
    database, provider = _v3_database(tmp_path)
    DatabaseV4Migrator(
        database,
        provider,
        backup_dir=tmp_path / "backups-v4",
    ).migrate()

    with sqlite3.connect(database) as db:
        with pytest.raises(sqlite3.IntegrityError):
            db.execute(
                "INSERT INTO telegram_secret_metadata("
                "secret_kind,profile_key,configured,last_changed,last_operation"
                ") VALUES ('password','profile_key',1,'2026-07-31T00:00:00Z','set')"
            )
        with pytest.raises(sqlite3.IntegrityError):
            db.execute(
                "INSERT INTO credential_audit("
                "id,actor_key,profile_key,operation,secret_kind,result,reason_code,"
                "created_at"
                ") VALUES ('a','actor','profile','credential.set','token','applied','',"
                "'2026-07-31T00:00:00Z')"
            )


def test_v4_preflight_rejects_active_target_claim_before_backup(tmp_path: Path) -> None:
    database, provider = _v3_database(tmp_path)
    now = datetime.now(timezone.utc)
    expires = (now + timedelta(minutes=5)).isoformat(timespec="seconds")
    timestamp = now.isoformat(timespec="seconds")
    with sqlite3.connect(database) as db:
        db.execute(
            "INSERT INTO history_events("
            "id,source,dedupe_key,history_kind,classification_schema_version,"
            "classification_confidence,encrypted_payload,payload_hash,"
            "operational_state,created_at,collected_at"
            ") VALUES ('event','fixture','dedupe','task_completion',1,'compatible',"
            "X'00','hash','ready',?,?)",
            (timestamp, timestamp),
        )
        db.execute(
            "INSERT INTO route_plans("
            "id,event_id,config_revision,routing_schema_version,planner_version,"
            "plan_hash,plan_state,created_at"
            ") VALUES ('route','event','r',3,'fixture','plan','active',?)",
            (timestamp,),
        )
        db.execute(
            "INSERT INTO target_deliveries("
            "id,route_plan_id,target_id,state,claim_worker_id,claim_token_hash,"
            "claim_expires_at,idempotency_key,created_at,updated_at"
            ") VALUES ('target','route','telegram','claimed','worker',?,?,'idem',?,?)",
            ("a" * 64, expires, timestamp, timestamp),
        )
        db.execute(
            "INSERT INTO target_delivery_bindings("
            "target_delivery_id,provider_id,provider_schema_version,binding_json,"
            "binding_hash,created_at"
            ") VALUES ('target','history_dispatcher',1,'{}','hash',?)",
            (timestamp,),
        )
    backup_dir = tmp_path / "backups-v4"

    with pytest.raises(MigrationV4Error, match="claims must be inactive"):
        DatabaseV4Migrator(
            database,
            provider,
            backup_dir=backup_dir,
        ).migrate()

    assert backup_dir.exists() is False
    assert _versions(database) == [1, 2, 3]
