from __future__ import annotations

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
from ..schema_v4 import DB_SCHEMA_VERSION, V4_DDL, V4_TABLES
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
)
from .v3 import _active_target_claim_count, verify_database_v3


class MigrationV4Error(RuntimeError):
    pass


def _canonical_json(value: object) -> str:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    )


@dataclass(frozen=True)
class MigrationV4Report:
    ok: bool
    dry_run: bool
    idempotent: bool
    source_schema_version: int
    target_schema_version: int
    backup: BackupReport | None
    metadata_rows: int
    audit_rows: int
    quick_check: str
    foreign_key_violations: tuple[str, ...]

    def as_dict(self) -> dict[str, Any]:
        return {
            "ok": self.ok,
            "dry_run": self.dry_run,
            "idempotent": self.idempotent,
            "source_schema_version": self.source_schema_version,
            "target_schema_version": self.target_schema_version,
            "backup": self.backup.as_dict() if self.backup else None,
            "metadata_rows": self.metadata_rows,
            "audit_rows": self.audit_rows,
            "quick_check": self.quick_check,
            "foreign_key_violations": list(self.foreign_key_violations),
        }


class DatabaseV4Migrator:
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
        v3 = verify_database_v3(self.database_path)
        if not v3["ok"]:
            raise MigrationV4Error(
                "database must pass the complete v3 verification first"
            )
        with _connect(self.database_path) as db:
            versions = _schema_versions(db)
            if versions and max(versions) > DB_SCHEMA_VERSION:
                raise MigrationV4Error("database schema is newer than this migrator")
            active_v1_claims = _active_claim_count(db)
            active_target_claims = _active_target_claim_count(db)
            metadata_rows = (
                int(
                    db.execute(
                        "SELECT COUNT(*) FROM telegram_secret_metadata"
                    ).fetchone()[0]
                )
                if _table_exists(db, "telegram_secret_metadata")
                else 0
            )
            audit_rows = (
                int(
                    db.execute("SELECT COUNT(*) FROM credential_audit").fetchone()[0]
                )
                if _table_exists(db, "credential_audit")
                else 0
            )
            quick = _quick_check(db)
            foreign_keys = _foreign_key_violations(db)
        if active_v1_claims or active_target_claims:
            raise MigrationV4Error("all v1 and target-specific claims must be inactive")
        if quick != "ok" or foreign_keys:
            raise MigrationV4Error("database integrity checks failed")
        return {
            "schema_versions": list(versions),
            "source_schema_version": max(versions or (0,)),
            "target_schema_version": DB_SCHEMA_VERSION,
            "migration_required": DB_SCHEMA_VERSION not in versions,
            "metadata_rows": metadata_rows,
            "audit_rows": audit_rows,
            "quick_check": quick,
            "foreign_key_violations": list(foreign_keys),
        }

    def migrate(self, *, dry_run: bool = False) -> MigrationV4Report:
        preflight = self.preflight()
        source_version = int(preflight["source_schema_version"])
        if not bool(preflight["migration_required"]):
            verification = verify_database_v4(self.database_path)
            return MigrationV4Report(
                ok=verification["ok"],
                dry_run=dry_run,
                idempotent=True,
                source_schema_version=source_version,
                target_schema_version=DB_SCHEMA_VERSION,
                backup=None,
                metadata_rows=verification["metadata_rows"],
                audit_rows=verification["audit_rows"],
                quick_check=verification["quick_check"],
                foreign_key_violations=tuple(
                    verification["foreign_key_violations"]
                ),
            )
        if dry_run:
            return MigrationV4Report(
                ok=True,
                dry_run=True,
                idempotent=False,
                source_schema_version=source_version,
                target_schema_version=DB_SCHEMA_VERSION,
                backup=None,
                metadata_rows=int(preflight["metadata_rows"]),
                audit_rows=int(preflight["audit_rows"]),
                quick_check=str(preflight["quick_check"]),
                foreign_key_violations=tuple(
                    str(value) for value in preflight["foreign_key_violations"]
                ),
            )

        backup = self._create_backup()
        now = _now()
        with _connect(self.database_path) as db:
            try:
                db.execute("BEGIN IMMEDIATE")
                if _active_claim_count(db) or _active_target_claim_count(db):
                    raise MigrationV4Error(
                        "all v1 and target-specific claims must be inactive"
                    )
                for statement in _iter_sql_statements(V4_DDL):
                    db.execute(statement)
                counts = self._verify_transaction(db)
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
                        _canonical_json(counts),
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
            except MigrationV4Error:
                db.rollback()
                raise
            except Exception as exc:
                db.rollback()
                raise MigrationV4Error(
                    f"database v4 migration rolled back; backup {backup.name} is intact"
                ) from exc
        verification = verify_database_v4(self.database_path)
        if not verification["ok"]:
            raise MigrationV4Error(
                f"database v4 verification failed; backup {backup.name} is intact"
            )
        return MigrationV4Report(
            ok=True,
            dry_run=False,
            idempotent=False,
            source_schema_version=source_version,
            target_schema_version=DB_SCHEMA_VERSION,
            backup=backup,
            metadata_rows=verification["metadata_rows"],
            audit_rows=verification["audit_rows"],
            quick_check=verification["quick_check"],
            foreign_key_violations=tuple(
                verification["foreign_key_violations"]
            ),
        )

    def _create_backup(self) -> BackupReport:
        _prepare_private_directory(self.backup_dir, label="backup directory")
        stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        name = (
            f"{self.database_path.stem}-v3-before-v4-{stamp}-"
            f"{uuid.uuid4().hex[:8]}.sqlite3"
        )
        target = self.backup_dir / name
        descriptor, temporary_name = tempfile.mkstemp(
            prefix=f".{name}.",
            suffix=".tmp",
            dir=self.backup_dir,
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
                raise MigrationV4Error("database backup quick_check failed")
            with temporary.open("rb+") as handle:
                os.fsync(handle.fileno())
            os.chmod(temporary, 0o600)
            os.replace(temporary, target)
            _remove_sqlite_sidecars(target)
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
        missing = tuple(table for table in V4_TABLES if not _table_exists(db, table))
        if missing:
            raise MigrationV4Error(
                "credential metadata schema is incomplete: " + ", ".join(missing)
            )
        if _quick_check(db) != "ok" or _foreign_key_violations(db):
            raise MigrationV4Error("database integrity checks failed")
        return {
            "metadata_rows": int(
                db.execute(
                    "SELECT COUNT(*) FROM telegram_secret_metadata"
                ).fetchone()[0]
            ),
            "audit_rows": int(
                db.execute("SELECT COUNT(*) FROM credential_audit").fetchone()[0]
            ),
        }


def verify_database_v4(database_path: Path) -> dict[str, Any]:
    path = Path(database_path).expanduser().absolute()
    _assert_regular_owned_database(path)
    v3 = verify_database_v3(path)
    with _connect(path) as db:
        versions = _schema_versions(db)
        missing = tuple(table for table in V4_TABLES if not _table_exists(db, table))
        quick = _quick_check(db)
        foreign_keys = _foreign_key_violations(db)
        metadata_rows = (
            int(
                db.execute(
                    "SELECT COUNT(*) FROM telegram_secret_metadata"
                ).fetchone()[0]
            )
            if _table_exists(db, "telegram_secret_metadata")
            else 0
        )
        audit_rows = (
            int(db.execute("SELECT COUNT(*) FROM credential_audit").fetchone()[0])
            if _table_exists(db, "credential_audit")
            else 0
        )
    return {
        "ok": (
            v3["ok"]
            and DB_SCHEMA_VERSION in versions
            and not missing
            and quick == "ok"
            and not foreign_keys
        ),
        "schema_versions": list(versions),
        "missing_tables": list(missing),
        "quick_check": quick,
        "foreign_key_violations": list(foreign_keys),
        "metadata_rows": metadata_rows,
        "audit_rows": audit_rows,
    }
