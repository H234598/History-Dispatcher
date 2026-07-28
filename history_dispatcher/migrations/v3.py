from __future__ import annotations

import hashlib
import json
import os
import sqlite3
import tempfile
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from ..crypto import SecretServiceKeyProvider
from ..schema_v3 import DB_SCHEMA_VERSION, V3_DDL, V3_TABLES
from .v2 import (
    BackupReport,
    _active_claim_count,
    _assert_no_symlink_chain,
    _assert_regular_owned_database,
    _connect,
    _foreign_key_violations,
    _fsync_directory,
    _iter_sql_statements,
    _now,
    _prepare_private_directory,
    _quick_check,
    _remove_sqlite_sidecars,
    _schema_versions,
    _sha256_file,
    _table_exists,
    verify_database_v2,
)


class MigrationV3Error(RuntimeError):
    pass


def _canonical_json(value: object) -> str:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    )


def _active_target_claim_count(db: sqlite3.Connection) -> int:
    if not _table_exists(db, "target_deliveries"):
        return 0
    return int(
        db.execute(
            "SELECT COUNT(*) FROM target_deliveries "
            "WHERE state='claimed' AND claim_expires_at > ?",
            (_now(),),
        ).fetchone()[0]
    )


def _binding_for_legacy_target(target_id: str) -> tuple[str, int, str, str]:
    normalized = str(target_id or "").strip().casefold()
    provider_id = normalized if normalized in {"local_archive", "vault"} else "legacy_unknown"
    fragment = {
        "schema_version": 0,
        "provider": provider_id,
        "legacy_migrated": True,
    }
    rendered = _canonical_json(fragment)
    return (
        provider_id,
        0,
        rendered,
        hashlib.sha256(rendered.encode("utf-8")).hexdigest(),
    )


def _binding_for_legacy_recipient(recipient_key: str) -> tuple[str, str]:
    normalized = str(recipient_key or "").strip().casefold()
    if not normalized:
        normalized = hashlib.sha256(b"legacy-unknown-recipient").hexdigest()[:32]
    recipient_ref = f"legacy_{normalized}"
    if len(recipient_ref) > 96:
        recipient_ref = (
            "legacy_" + hashlib.sha256(recipient_ref.encode("utf-8")).hexdigest()[:64]
        )
    return (
        recipient_ref,
        hashlib.sha256(recipient_ref.encode("utf-8")).hexdigest(),
    )


@dataclass(frozen=True)
class MigrationV3Report:
    ok: bool
    dry_run: bool
    idempotent: bool
    source_schema_version: int
    target_schema_version: int
    backup: BackupReport | None
    target_deliveries: int
    bindings: int
    recipient_deliveries: int
    recipient_bindings: int
    quick_check: str
    foreign_key_violations: tuple[str, ...]
    no_external_dispatch_created: bool

    def as_dict(self) -> dict[str, Any]:
        return {
            "ok": self.ok,
            "dry_run": self.dry_run,
            "idempotent": self.idempotent,
            "source_schema_version": self.source_schema_version,
            "target_schema_version": self.target_schema_version,
            "backup": self.backup.as_dict() if self.backup else None,
            "target_deliveries": self.target_deliveries,
            "bindings": self.bindings,
            "recipient_deliveries": self.recipient_deliveries,
            "recipient_bindings": self.recipient_bindings,
            "quick_check": self.quick_check,
            "foreign_key_violations": list(self.foreign_key_violations),
            "no_external_dispatch_created": self.no_external_dispatch_created,
        }


class DatabaseV3Migrator:
    def __init__(
        self,
        database_path: Path,
        key_provider: SecretServiceKeyProvider,
        *,
        backup_dir: Path | None = None,
    ) -> None:
        self.database_path = Path(database_path).expanduser().absolute()
        self.key_provider = key_provider
        self.backup_dir = (
            Path(backup_dir).expanduser().absolute()
            if backup_dir is not None
            else self.database_path.parent / "backups"
        )

    def preflight(self) -> dict[str, Any]:
        _assert_regular_owned_database(self.database_path)
        _assert_no_symlink_chain(self.backup_dir, allow_missing_leaf=True)
        self.key_provider.get_key()
        v2 = verify_database_v2(self.database_path)
        if not v2["ok"]:
            raise MigrationV3Error("database must pass the complete v2 verification first")
        with _connect(self.database_path) as db:
            versions = _schema_versions(db)
            if versions and max(versions) > DB_SCHEMA_VERSION:
                raise MigrationV3Error("database schema is newer than this migrator")
            active_v1_claims = _active_claim_count(db)
            active_target_claims = _active_target_claim_count(db)
            targets = int(
                db.execute("SELECT COUNT(*) FROM target_deliveries").fetchone()[0]
            )
            recipients = int(
                db.execute("SELECT COUNT(*) FROM recipient_deliveries").fetchone()[0]
            )
            bindings = (
                int(
                    db.execute(
                        "SELECT COUNT(*) FROM target_delivery_bindings"
                    ).fetchone()[0]
                )
                if _table_exists(db, "target_delivery_bindings")
                else 0
            )
            recipient_bindings = (
                int(
                    db.execute(
                        "SELECT COUNT(*) FROM recipient_delivery_bindings"
                    ).fetchone()[0]
                )
                if _table_exists(db, "recipient_delivery_bindings")
                else 0
            )
            quick = _quick_check(db)
            foreign_keys = _foreign_key_violations(db)
        if active_v1_claims or active_target_claims:
            raise MigrationV3Error("all v1 and target-specific claims must be inactive")
        if quick != "ok" or foreign_keys:
            raise MigrationV3Error("database integrity checks failed")
        return {
            "schema_versions": list(versions),
            "source_schema_version": max(versions or (0,)),
            "target_schema_version": DB_SCHEMA_VERSION,
            "migration_required": DB_SCHEMA_VERSION not in versions,
            "target_deliveries": targets,
            "bindings": bindings,
            "recipient_deliveries": recipients,
            "recipient_bindings": recipient_bindings,
            "quick_check": quick,
            "foreign_key_violations": list(foreign_keys),
        }

    def migrate(self, *, dry_run: bool = False) -> MigrationV3Report:
        preflight = self.preflight()
        source_version = int(preflight["source_schema_version"])
        if not bool(preflight["migration_required"]):
            verification = verify_database_v3(self.database_path)
            return MigrationV3Report(
                ok=verification["ok"],
                dry_run=dry_run,
                idempotent=True,
                source_schema_version=source_version,
                target_schema_version=DB_SCHEMA_VERSION,
                backup=None,
                target_deliveries=verification["target_deliveries"],
                bindings=verification["bindings"],
                recipient_deliveries=verification["recipient_deliveries"],
                recipient_bindings=verification["recipient_bindings"],
                quick_check=verification["quick_check"],
                foreign_key_violations=tuple(
                    verification["foreign_key_violations"]
                ),
                no_external_dispatch_created=True,
            )
        if dry_run:
            return MigrationV3Report(
                ok=True,
                dry_run=True,
                idempotent=False,
                source_schema_version=source_version,
                target_schema_version=DB_SCHEMA_VERSION,
                backup=None,
                target_deliveries=int(preflight["target_deliveries"]),
                bindings=int(preflight["target_deliveries"]),
                recipient_deliveries=int(preflight["recipient_deliveries"]),
                recipient_bindings=int(preflight["recipient_deliveries"]),
                quick_check=str(preflight["quick_check"]),
                foreign_key_violations=tuple(
                    str(value) for value in preflight["foreign_key_violations"]
                ),
                no_external_dispatch_created=True,
            )

        backup = self._create_backup()
        now = _now()
        with _connect(self.database_path) as db:
            try:
                db.execute("BEGIN IMMEDIATE")
                if _active_claim_count(db) or _active_target_claim_count(db):
                    raise MigrationV3Error(
                        "all v1 and target-specific claims must be inactive"
                    )
                for statement in _iter_sql_statements(V3_DDL):
                    db.execute(statement)
                target_rows = db.execute(
                    "SELECT id,target_id,created_at FROM target_deliveries "
                    "ORDER BY created_at,id"
                ).fetchall()
                for row in target_rows:
                    provider_id, schema_version, binding_json, binding_hash = (
                        _binding_for_legacy_target(str(row["target_id"]))
                    )
                    db.execute(
                        "INSERT INTO target_delivery_bindings("
                        "target_delivery_id,provider_id,provider_schema_version,"
                        "binding_json,binding_hash,created_at"
                        ") VALUES (?,?,?,?,?,?)",
                        (
                            str(row["id"]),
                            provider_id,
                            schema_version,
                            binding_json,
                            binding_hash,
                            str(row["created_at"] or now),
                        ),
                    )
                recipient_rows = db.execute(
                    "SELECT id,target_delivery_id,recipient_key,created_at "
                    "FROM recipient_deliveries ORDER BY created_at,id"
                ).fetchall()
                for row in recipient_rows:
                    recipient_ref, recipient_ref_hash = _binding_for_legacy_recipient(
                        str(row["recipient_key"])
                    )
                    db.execute(
                        "INSERT INTO recipient_delivery_bindings("
                        "recipient_delivery_id,target_delivery_id,recipient_ref,"
                        "recipient_ref_hash,created_at"
                        ") VALUES (?,?,?,?,?)",
                        (
                            str(row["id"]),
                            str(row["target_delivery_id"]),
                            recipient_ref,
                            recipient_ref_hash,
                            str(row["created_at"] or now),
                        ),
                    )
                counts = self._verify_transaction(db)
                report_json = _canonical_json(
                    {
                        **counts,
                        "no_external_dispatch_created": True,
                    }
                )
                db.execute(
                    "INSERT INTO migration_journal("
                    "id,migration_version,phase,source_schema_version,"
                    "target_schema_version,backup_name,backup_sha256,report_json,"
                    "created_at,completed_at"
                    ") VALUES (?,?,'verified',?,?,?,?,?,?,?)",
                    (
                        str(uuid.uuid4()),
                        DB_SCHEMA_VERSION,
                        source_version,
                        DB_SCHEMA_VERSION,
                        backup.name,
                        backup.sha256,
                        report_json,
                        now,
                        now,
                    ),
                )
                db.execute(
                    "INSERT INTO schema_migrations(version,applied_at) VALUES (?,?)",
                    (DB_SCHEMA_VERSION, now),
                )
                db.execute(f"PRAGMA user_version={DB_SCHEMA_VERSION}")
                db.commit()
            except MigrationV3Error:
                db.rollback()
                raise
            except Exception as exc:
                db.rollback()
                raise MigrationV3Error(
                    f"database v3 migration rolled back; backup {backup.name} is intact"
                ) from exc
        verification = verify_database_v3(self.database_path)
        if not verification["ok"]:
            raise MigrationV3Error(
                f"database v3 verification failed; backup {backup.name} is intact"
            )
        return MigrationV3Report(
            ok=True,
            dry_run=False,
            idempotent=False,
            source_schema_version=source_version,
            target_schema_version=DB_SCHEMA_VERSION,
            backup=backup,
            target_deliveries=verification["target_deliveries"],
            bindings=verification["bindings"],
            recipient_deliveries=verification["recipient_deliveries"],
            recipient_bindings=verification["recipient_bindings"],
            quick_check=verification["quick_check"],
            foreign_key_violations=tuple(
                verification["foreign_key_violations"]
            ),
            no_external_dispatch_created=True,
        )

    def _create_backup(self) -> BackupReport:
        _prepare_private_directory(self.backup_dir, label="backup directory")
        stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        name = (
            f"{self.database_path.stem}-v2-before-v3-{stamp}-"
            f"{uuid.uuid4().hex[:8]}.sqlite3"
        )
        target = self.backup_dir / name
        descriptor, temporary_name = tempfile.mkstemp(
            prefix=f".{name}.", suffix=".tmp", dir=self.backup_dir
        )
        os.close(descriptor)
        temporary = Path(temporary_name)
        try:
            with _connect(self.database_path) as source:
                destination = sqlite3.connect(temporary)
                try:
                    destination.execute("PRAGMA journal_mode=DELETE")
                    source.backup(destination)
                    destination.commit()
                    quick = _quick_check(destination)
                finally:
                    destination.close()
            _remove_sqlite_sidecars(temporary)
            if quick != "ok":
                raise MigrationV3Error("database backup quick_check failed")
            with temporary.open("rb+") as handle:
                os.fsync(handle.fileno())
            os.chmod(temporary, 0o600)
            os.replace(temporary, target)
            _fsync_directory(self.backup_dir)
            return BackupReport(
                name=name,
                sha256=_sha256_file(target),
                size_bytes=target.stat().st_size,
                quick_check=quick,
            )
        finally:
            _remove_sqlite_sidecars(temporary)
            try:
                temporary.unlink()
            except FileNotFoundError:
                pass

    @staticmethod
    def _verify_transaction(db: sqlite3.Connection) -> dict[str, int]:
        targets = int(
            db.execute("SELECT COUNT(*) FROM target_deliveries").fetchone()[0]
        )
        bindings = int(
            db.execute("SELECT COUNT(*) FROM target_delivery_bindings").fetchone()[0]
        )
        recipients = int(
            db.execute("SELECT COUNT(*) FROM recipient_deliveries").fetchone()[0]
        )
        recipient_bindings = int(
            db.execute(
                "SELECT COUNT(*) FROM recipient_delivery_bindings"
            ).fetchone()[0]
        )
        if targets != bindings:
            raise MigrationV3Error("every target delivery must have one binding")
        if recipients != recipient_bindings:
            raise MigrationV3Error("every recipient delivery must have one binding")
        unsafe = int(
            db.execute(
                "SELECT COUNT(*) FROM target_deliveries td "
                "JOIN route_plans rp ON rp.id=td.route_plan_id "
                "WHERE rp.plan_state='legacy_migrated' AND "
                "td.state IN ('pending','claimed','failed_retryable')"
            ).fetchone()[0]
        )
        if unsafe:
            raise MigrationV3Error("migration made legacy deliveries dispatchable")
        if _quick_check(db) != "ok" or _foreign_key_violations(db):
            raise MigrationV3Error("database integrity checks failed")
        return {
            "target_deliveries": targets,
            "bindings": bindings,
            "recipient_deliveries": recipients,
            "recipient_bindings": recipient_bindings,
        }


def verify_database_v3(database_path: Path) -> dict[str, Any]:
    path = Path(database_path).expanduser().absolute()
    _assert_regular_owned_database(path)
    v2 = verify_database_v2(path)
    with _connect(path) as db:
        versions = _schema_versions(db)
        missing = tuple(table for table in V3_TABLES if not _table_exists(db, table))
        quick = _quick_check(db)
        foreign_keys = _foreign_key_violations(db)
        targets = (
            int(db.execute("SELECT COUNT(*) FROM target_deliveries").fetchone()[0])
            if _table_exists(db, "target_deliveries")
            else 0
        )
        bindings = (
            int(
                db.execute(
                    "SELECT COUNT(*) FROM target_delivery_bindings"
                ).fetchone()[0]
            )
            if _table_exists(db, "target_delivery_bindings")
            else 0
        )
        recipients = (
            int(db.execute("SELECT COUNT(*) FROM recipient_deliveries").fetchone()[0])
            if _table_exists(db, "recipient_deliveries")
            else 0
        )
        recipient_bindings = (
            int(
                db.execute(
                    "SELECT COUNT(*) FROM recipient_delivery_bindings"
                ).fetchone()[0]
            )
            if _table_exists(db, "recipient_delivery_bindings")
            else 0
        )
    return {
        "ok": (
            v2["ok"]
            and DB_SCHEMA_VERSION in versions
            and not missing
            and quick == "ok"
            and not foreign_keys
            and targets == bindings
            and recipients == recipient_bindings
        ),
        "schema_versions": list(versions),
        "missing_tables": list(missing),
        "quick_check": quick,
        "foreign_key_violations": list(foreign_keys),
        "target_deliveries": targets,
        "bindings": bindings,
        "recipient_deliveries": recipients,
        "recipient_bindings": recipient_bindings,
        "no_external_dispatch_created": True,
    }
