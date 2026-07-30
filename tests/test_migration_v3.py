from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from history_dispatcher.crypto import StaticKeyProvider
from history_dispatcher.migrations import (
    DatabaseV2Migrator,
    DatabaseV3Migrator,
    MigrationV3Error,
    verify_database_v3,
)
from history_dispatcher.store import DispatcherStore


def _v2_store(tmp_path: Path) -> DispatcherStore:
    store = DispatcherStore(
        tmp_path / "history.sqlite3",
        StaticKeyProvider(b"k" * 32),
    )
    store.append(
        {
            "id": "legacy-v3-item",
            "dedupe_key": "legacy-v3-item",
            "status": "delivered",
            "payload": {
                "history_kind": "task_completion",
                "classification_confidence": "compatible",
                "summary": {"text": "v3 migration fixture"},
            },
            "recipient_results": [
                {
                    "recipient_id": "legacy-admin",
                    "status": "accepted",
                    "channel": "telegram",
                }
            ],
        }
    )
    DatabaseV2Migrator(
        store.database_path,
        store.key_provider,
        backup_dir=tmp_path / "backups-v2",
        minimum_free_bytes=0,
    ).migrate()
    return store


def _versions(path: Path) -> list[int]:
    with sqlite3.connect(path) as db:
        return [
            int(row[0])
            for row in db.execute(
                "SELECT version FROM schema_migrations ORDER BY version"
            )
        ]


def test_v3_dry_run_is_write_free(tmp_path: Path) -> None:
    store = _v2_store(tmp_path)
    backup_dir = tmp_path / "backups-v3"
    migrator = DatabaseV3Migrator(
        store.database_path,
        store.key_provider,
        backup_dir=backup_dir,
    )

    report = migrator.migrate(dry_run=True)

    assert report.ok is True
    assert report.dry_run is True
    assert report.target_deliveries == 1
    assert report.bindings == 1
    assert report.recipient_deliveries == 1
    assert report.recipient_bindings == 1
    assert backup_dir.exists() is False
    assert _versions(store.database_path) == [1, 2]
    with sqlite3.connect(store.database_path) as db:
        for table in (
            "target_delivery_bindings",
            "recipient_delivery_bindings",
        ):
            assert db.execute(
                "SELECT COUNT(*) FROM sqlite_master "
                "WHERE type='table' AND name=?",
                (table,),
            ).fetchone()[0] == 0


def test_v3_migration_binds_legacy_targets_without_redispatch(tmp_path: Path) -> None:
    store = _v2_store(tmp_path)
    backup_dir = tmp_path / "backups-v3"

    report = DatabaseV3Migrator(
        store.database_path,
        store.key_provider,
        backup_dir=backup_dir,
    ).migrate()

    assert report.ok is True
    assert report.idempotent is False
    assert report.source_schema_version == 2
    assert report.target_schema_version == 3
    assert report.target_deliveries == report.bindings == 1
    assert report.recipient_deliveries == report.recipient_bindings == 1
    assert report.no_external_dispatch_created is True
    assert report.backup is not None
    assert _versions(store.database_path) == [1, 2, 3]
    verification = verify_database_v3(store.database_path)
    assert verification["ok"] is True
    assert verification["target_deliveries"] == verification["bindings"] == 1
    assert verification["recipient_deliveries"] == verification["recipient_bindings"] == 1

    with sqlite3.connect(store.database_path) as db:
        db.row_factory = sqlite3.Row
        binding = db.execute(
            "SELECT provider_id,provider_schema_version,binding_json "
            "FROM target_delivery_bindings"
        ).fetchone()
        assert binding["provider_id"] == "legacy_unknown"
        assert binding["provider_schema_version"] == 0
        assert json.loads(binding["binding_json"]) == {
            "legacy_migrated": True,
            "provider": "legacy_unknown",
            "schema_version": 0,
        }
        recipient_binding = db.execute(
            "SELECT recipient_ref,recipient_ref_hash "
            "FROM recipient_delivery_bindings"
        ).fetchone()
        assert recipient_binding["recipient_ref"].startswith("legacy_recipient_")
        assert len(recipient_binding["recipient_ref_hash"]) == 64
        target = db.execute(
            "SELECT state,claim_worker_id,claim_token_hash,claim_expires_at "
            "FROM target_deliveries"
        ).fetchone()
        assert target["state"] == "delivered"
        assert target["claim_worker_id"] == ""
        assert target["claim_token_hash"] == ""
        assert target["claim_expires_at"] == ""


def test_v3_second_run_is_idempotent_and_creates_no_backup(tmp_path: Path) -> None:
    store = _v2_store(tmp_path)
    backup_dir = tmp_path / "backups-v3"
    migrator = DatabaseV3Migrator(
        store.database_path,
        store.key_provider,
        backup_dir=backup_dir,
    )
    first = migrator.migrate()
    backups = sorted(backup_dir.iterdir())

    second = migrator.migrate()

    assert first.backup is not None
    assert second.idempotent is True
    assert second.backup is None
    assert sorted(backup_dir.iterdir()) == backups


def test_v3_migration_rechecks_active_target_claims(tmp_path: Path) -> None:
    store = _v2_store(tmp_path)
    now = datetime.now(timezone.utc)
    expires = (now + timedelta(minutes=10)).isoformat(timespec="seconds")
    timestamp = now.isoformat(timespec="seconds")
    with sqlite3.connect(store.database_path) as db:
        db.execute(
            "INSERT INTO route_plans("
            "id,event_id,config_revision,routing_schema_version,planner_version,"
            "plan_hash,plan_state,created_at"
            ") VALUES ('active-route','legacy-v3-item','r1',2,'fixture',"
            "'active-route-hash','active',?)",
            (timestamp,),
        )
        db.execute(
            "INSERT INTO target_deliveries("
            "id,route_plan_id,target_id,state,idempotency_key,created_at,updated_at"
            ") VALUES ('active-target','active-route','telegram','pending',"
            "'active-target-idem',?,?)",
            (timestamp, timestamp),
        )
        db.execute(
            "UPDATE target_deliveries SET state='claimed',claim_worker_id='worker',"
            "claim_token_hash=?,claim_expires_at=? WHERE id='active-target'",
            ("a" * 64, expires),
        )

    backup_dir = tmp_path / "backups-v3"
    with pytest.raises(MigrationV3Error, match="claims must be inactive"):
        DatabaseV3Migrator(
            store.database_path,
            store.key_provider,
            backup_dir=backup_dir,
        ).migrate()

    assert backup_dir.exists() is False
    assert _versions(store.database_path) == [1, 2]


def test_v3_constraints_make_bindings_immutable_and_claim_fields_consistent(
    tmp_path: Path,
) -> None:
    store = _v2_store(tmp_path)
    DatabaseV3Migrator(
        store.database_path,
        store.key_provider,
        backup_dir=tmp_path / "backups-v3",
    ).migrate()

    with sqlite3.connect(store.database_path) as db:
        target_id = db.execute(
            "SELECT target_delivery_id FROM target_delivery_bindings LIMIT 1"
        ).fetchone()[0]
        recipient_id = db.execute(
            "SELECT recipient_delivery_id FROM recipient_delivery_bindings LIMIT 1"
        ).fetchone()[0]
        with pytest.raises(sqlite3.IntegrityError, match="immutable"):
            db.execute(
                "UPDATE target_delivery_bindings SET provider_id='teebotus' "
                "WHERE target_delivery_id=?",
                (target_id,),
            )
        with pytest.raises(sqlite3.IntegrityError, match="immutable"):
            db.execute(
                "UPDATE recipient_delivery_bindings SET recipient_ref='changed' "
                "WHERE recipient_delivery_id=?",
                (recipient_id,),
            )
        with pytest.raises(sqlite3.IntegrityError, match="claim fields"):
            db.execute(
                "UPDATE target_deliveries SET claim_worker_id='orphan' WHERE id=?",
                (target_id,),
            )
