from __future__ import annotations

import hashlib
import json
import os
import shutil
import sqlite3
import stat
import tempfile
import uuid
from collections import defaultdict
from collections.abc import Callable, Iterator, Mapping, Sequence
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath
from typing import Any
from urllib.parse import urlsplit

from cryptography.exceptions import InvalidTag

from ..crypto import KeyUnavailable, SecretServiceKeyProvider, decrypt_json
from ..identifiers import persistent_opaque_id
from ..redaction import safe_project_label
from ..schema_v2 import (
    CLASSIFICATION_CONFIDENCES,
    DB_SCHEMA_VERSION,
    HISTORY_KINDS,
    ROUTING_SCHEMA_VERSION,
    V2_DDL,
    V2_TABLES,
)


MINIMUM_FREE_BYTES = 256 * 1024 * 1024
_SUCCESS_RECIPIENT_STATES = frozenset({"accepted", "delivered", "acknowledged"})
_SQLITE_SIDECAR_SUFFIXES = ("-wal", "-shm", "-journal")
_REQUIRED_V1_TABLES = (
    "schema_migrations",
    "history_items",
    "recipient_results",
    "dispatch_claims",
)


class MigrationV2Error(RuntimeError):
    pass


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _canonical_json(value: object) -> str:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    )


@contextmanager
def _connect(path: Path) -> Iterator[sqlite3.Connection]:
    connection = sqlite3.connect(
        path,
        timeout=30,
        isolation_level=None,
        check_same_thread=False,
    )
    try:
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys=ON")
        connection.execute("PRAGMA busy_timeout=30000")
        yield connection
    finally:
        connection.close()


def _iter_sql_statements(script: str) -> Iterator[str]:
    statement = ""
    for line in script.splitlines(keepends=True):
        statement += line
        if sqlite3.complete_statement(statement):
            rendered = statement.strip()
            if rendered:
                yield rendered
            statement = ""
    if statement.strip():
        raise MigrationV2Error("incomplete v2 schema statement")


def _table_exists(db: sqlite3.Connection, table: str) -> bool:
    return (
        db.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?",
            (table,),
        ).fetchone()
        is not None
    )


def _schema_versions(db: sqlite3.Connection) -> tuple[int, ...]:
    if not _table_exists(db, "schema_migrations"):
        return ()
    return tuple(
        int(row["version"])
        for row in db.execute(
            "SELECT version FROM schema_migrations ORDER BY version"
        ).fetchall()
    )


def _quick_check(db: sqlite3.Connection) -> str:
    return "\n".join(str(row[0]) for row in db.execute("PRAGMA quick_check"))


def _foreign_key_violations(db: sqlite3.Connection) -> tuple[str, ...]:
    return tuple(
        "|".join(str(value) for value in row)
        for row in db.execute("PRAGMA foreign_key_check")
    )


def _assert_no_symlink_chain(path: Path, *, allow_missing_leaf: bool = False) -> None:
    current = path.expanduser().absolute()
    if allow_missing_leaf and not os.path.lexists(current):
        current = current.parent
    while True:
        if os.path.islink(current):
            raise MigrationV2Error(
                f"symlink path component is not allowed: {current}"
            )
        if current.parent == current:
            break
        current = current.parent


def _assert_regular_owned_database(path: Path) -> os.stat_result:
    _assert_no_symlink_chain(path)
    try:
        info = path.stat()
    except OSError as exc:
        raise MigrationV2Error("database is unavailable") from exc
    if not stat.S_ISREG(info.st_mode):
        raise MigrationV2Error("database must be a regular file")
    if hasattr(os, "getuid") and info.st_uid != os.getuid():
        raise MigrationV2Error("database must be owned by the current user")
    return info


def _prepare_private_directory(path: Path, *, label: str) -> None:
    _assert_no_symlink_chain(path, allow_missing_leaf=True)
    if os.path.islink(path):
        raise MigrationV2Error(f"{label} must not be a symlink")
    try:
        path.mkdir(mode=0o700, parents=True, exist_ok=True)
    except OSError as exc:
        raise MigrationV2Error(f"{label} is not usable") from exc
    _assert_no_symlink_chain(path)
    try:
        info = os.lstat(path)
    except OSError as exc:
        raise MigrationV2Error(f"{label} is unavailable") from exc
    if not stat.S_ISDIR(info.st_mode):
        raise MigrationV2Error(f"{label} must be a directory")
    if hasattr(os, "getuid") and info.st_uid != os.getuid():
        raise MigrationV2Error(f"{label} must be owned by the current user")
    try:
        descriptor = os.open(
            path,
            os.O_RDONLY
            | getattr(os, "O_DIRECTORY", 0)
            | getattr(os, "O_NOFOLLOW", 0),
        )
    except OSError as exc:
        raise MigrationV2Error(f"{label} cannot be opened safely") from exc
    try:
        opened = os.fstat(descriptor)
        if not stat.S_ISDIR(opened.st_mode):
            raise MigrationV2Error(f"{label} must be a directory")
        if (opened.st_dev, opened.st_ino) != (info.st_dev, info.st_ino):
            raise MigrationV2Error(f"{label} changed during validation")
        os.fchmod(descriptor, 0o700)
    finally:
        os.close(descriptor)


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _fsync_directory(path: Path) -> None:
    descriptor = os.open(
        path,
        os.O_RDONLY
        | getattr(os, "O_DIRECTORY", 0)
        | getattr(os, "O_NOFOLLOW", 0),
    )
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def _remove_sqlite_sidecars(path: Path) -> None:
    for suffix in _SQLITE_SIDECAR_SUFFIXES:
        try:
            Path(f"{path}{suffix}").unlink()
        except FileNotFoundError:
            pass


def _active_claim_count(db: sqlite3.Connection) -> int:
    if not _table_exists(db, "dispatch_claims"):
        return 0
    return int(
        db.execute(
            "SELECT COUNT(*) FROM dispatch_claims WHERE expires_at > ?",
            (_now(),),
        ).fetchone()[0]
    )


def _require_v1_tables(db: sqlite3.Connection) -> None:
    missing = tuple(table for table in _REQUIRED_V1_TABLES if not _table_exists(db, table))
    if missing:
        raise MigrationV2Error(
            "database is missing required v1 table(s): " + ", ".join(missing)
        )


@dataclass(frozen=True)
class PreflightReport:
    schema_versions: tuple[int, ...]
    database_bytes: int
    database_mode: int
    free_bytes: int
    required_free_bytes: int
    active_claims: int
    history_items: int
    recipient_results: int
    quick_check: str
    foreign_key_violations: tuple[str, ...]
    migration_required: bool

    def as_dict(self) -> dict[str, Any]:
        return {
            "schema_versions": list(self.schema_versions),
            "database_bytes": self.database_bytes,
            "database_mode": oct(self.database_mode),
            "free_bytes": self.free_bytes,
            "required_free_bytes": self.required_free_bytes,
            "active_claims": self.active_claims,
            "history_items": self.history_items,
            "recipient_results": self.recipient_results,
            "quick_check": self.quick_check,
            "foreign_key_violations": list(self.foreign_key_violations),
            "migration_required": self.migration_required,
        }


@dataclass(frozen=True)
class BackupReport:
    name: str
    sha256: str
    size_bytes: int
    quick_check: str

    def as_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "sha256": self.sha256,
            "size_bytes": self.size_bytes,
            "quick_check": self.quick_check,
        }


@dataclass(frozen=True)
class MigrationV2Report:
    ok: bool
    dry_run: bool
    idempotent: bool
    source_schema_version: int
    target_schema_version: int
    preflight: PreflightReport
    backup: BackupReport | None
    history_events: int
    route_plans: int
    target_deliveries: int
    recipient_deliveries: int
    mapping_counts: Mapping[str, int]
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
            "preflight": self.preflight.as_dict(),
            "backup": self.backup.as_dict() if self.backup else None,
            "history_events": self.history_events,
            "route_plans": self.route_plans,
            "target_deliveries": self.target_deliveries,
            "recipient_deliveries": self.recipient_deliveries,
            "mapping_counts": dict(sorted(self.mapping_counts.items())),
            "quick_check": self.quick_check,
            "foreign_key_violations": list(self.foreign_key_violations),
            "no_external_dispatch_created": self.no_external_dispatch_created,
        }


@dataclass(frozen=True)
class _LegacyMapping:
    history_kind: str
    confidence: str
    reason_code: str
    classification_schema_version: int
    session_key: str
    turn_key: str
    parent_thread_key: str
    project_id: str
    project_label: str


@dataclass(frozen=True)
class _MigrationCounts:
    history_events: int = 0
    route_plans: int = 0
    target_deliveries: int = 0
    recipient_deliveries: int = 0


class DatabaseV2Migrator:
    def __init__(
        self,
        database_path: Path,
        key_provider: SecretServiceKeyProvider,
        *,
        backup_dir: Path | None = None,
        minimum_free_bytes: int = MINIMUM_FREE_BYTES,
        fault_hook: Callable[[str], None] | None = None,
    ) -> None:
        self.database_path = Path(database_path).expanduser().absolute()
        self.key_provider = key_provider
        self.backup_dir = (
            Path(backup_dir).expanduser().absolute()
            if backup_dir is not None
            else self.database_path.parent / "backups"
        )
        self.minimum_free_bytes = max(0, int(minimum_free_bytes))
        self._fault_hook = fault_hook

    def _fault(self, phase: str) -> None:
        if self._fault_hook is not None:
            self._fault_hook(phase)

    def preflight(self) -> PreflightReport:
        info = _assert_regular_owned_database(self.database_path)
        _assert_no_symlink_chain(self.database_path.parent)
        _assert_no_symlink_chain(self.backup_dir, allow_missing_leaf=True)
        self.key_provider.get_key()
        disk = shutil.disk_usage(self.database_path.parent)
        required_free = max(self.minimum_free_bytes, int(info.st_size) * 2)
        with _connect(self.database_path) as db:
            _require_v1_tables(db)
            versions = _schema_versions(db)
            if not versions:
                raise MigrationV2Error("database has no recorded schema version")
            if max(versions) > DB_SCHEMA_VERSION:
                raise MigrationV2Error("database schema is newer than this migrator")
            quick = _quick_check(db)
            foreign_keys = _foreign_key_violations(db)
            active_claims = _active_claim_count(db)
            history_items = int(
                db.execute("SELECT COUNT(*) FROM history_items").fetchone()[0]
            )
            recipient_results = int(
                db.execute("SELECT COUNT(*) FROM recipient_results").fetchone()[0]
            )
        if quick != "ok":
            raise MigrationV2Error("database quick_check failed")
        if foreign_keys:
            raise MigrationV2Error("database foreign_key_check failed")
        if disk.free < required_free:
            raise MigrationV2Error("insufficient free space for safe migration")
        return PreflightReport(
            schema_versions=versions,
            database_bytes=int(info.st_size),
            database_mode=stat.S_IMODE(info.st_mode),
            free_bytes=int(disk.free),
            required_free_bytes=required_free,
            active_claims=active_claims,
            history_items=history_items,
            recipient_results=recipient_results,
            quick_check=quick,
            foreign_key_violations=foreign_keys,
            migration_required=DB_SCHEMA_VERSION not in versions,
        )

    def migrate(self, *, dry_run: bool = False) -> MigrationV2Report:
        preflight = self.preflight()
        source_version = max(preflight.schema_versions)
        if not preflight.migration_required:
            verification = verify_database_v2(self.database_path)
            return MigrationV2Report(
                ok=verification["ok"],
                dry_run=dry_run,
                idempotent=True,
                source_schema_version=source_version,
                target_schema_version=DB_SCHEMA_VERSION,
                preflight=preflight,
                backup=None,
                history_events=verification["history_events"],
                route_plans=verification["route_plans"],
                target_deliveries=verification["target_deliveries"],
                recipient_deliveries=verification["recipient_deliveries"],
                mapping_counts={},
                quick_check=verification["quick_check"],
                foreign_key_violations=tuple(
                    verification["foreign_key_violations"]
                ),
                no_external_dispatch_created=verification[
                    "no_external_dispatch_created"
                ],
            )
        if preflight.active_claims:
            raise MigrationV2Error(
                "active v1 dispatch claims must expire or be released"
            )

        planned_mapping = self._plan_mapping_counts()
        if dry_run:
            return MigrationV2Report(
                ok=True,
                dry_run=True,
                idempotent=False,
                source_schema_version=source_version,
                target_schema_version=DB_SCHEMA_VERSION,
                preflight=preflight,
                backup=None,
                history_events=preflight.history_items,
                route_plans=0,
                target_deliveries=0,
                recipient_deliveries=preflight.recipient_results,
                mapping_counts=planned_mapping,
                quick_check=preflight.quick_check,
                foreign_key_violations=preflight.foreign_key_violations,
                no_external_dispatch_created=True,
            )

        os.chmod(self.database_path, 0o600)
        backup = self._create_backup()
        self._fault("after_backup")
        journal_id = str(uuid.uuid4())
        counts = _MigrationCounts()
        mapping_counts: dict[str, int] = defaultdict(int)
        with _connect(self.database_path) as db:
            try:
                db.execute("BEGIN IMMEDIATE")
                if _active_claim_count(db):
                    raise MigrationV2Error(
                        "active v1 dispatch claims must expire or be released"
                    )
                for statement in _iter_sql_statements(V2_DDL):
                    db.execute(statement)
                self._fault("after_schema")
                counts = self._migrate_legacy_rows(db, mapping_counts)
                self._fault("after_rows")
                self._verify_transaction(
                    db,
                    expected_history_items=preflight.history_items,
                )
                report_payload = {
                    "history_events": counts.history_events,
                    "route_plans": counts.route_plans,
                    "target_deliveries": counts.target_deliveries,
                    "recipient_deliveries": counts.recipient_deliveries,
                    "mapping_counts": dict(sorted(mapping_counts.items())),
                    "no_external_dispatch_created": True,
                }
                now = _now()
                db.execute(
                    "INSERT INTO migration_journal("
                    "id,migration_version,phase,source_schema_version,"
                    "target_schema_version,backup_name,backup_sha256,report_json,"
                    "created_at,completed_at"
                    ") VALUES (?, ?, 'verified', ?, ?, ?, ?, ?, ?, ?)",
                    (
                        journal_id,
                        DB_SCHEMA_VERSION,
                        source_version,
                        DB_SCHEMA_VERSION,
                        backup.name,
                        backup.sha256,
                        _canonical_json(report_payload),
                        now,
                        now,
                    ),
                )
                db.execute(
                    "INSERT INTO schema_migrations(version, applied_at) VALUES (?, ?)",
                    (DB_SCHEMA_VERSION, now),
                )
                db.execute(f"PRAGMA user_version={DB_SCHEMA_VERSION}")
                self._fault("before_commit")
                db.commit()
            except MigrationV2Error:
                db.rollback()
                raise
            except Exception as exc:
                db.rollback()
                raise MigrationV2Error(
                    f"database v2 migration rolled back; backup {backup.name} "
                    "is intact"
                ) from exc
        os.chmod(self.database_path, 0o600)
        verification = verify_database_v2(self.database_path)
        if not verification["ok"]:
            raise MigrationV2Error(
                f"database v2 post-commit verification failed; backup "
                f"{backup.name} is intact"
            )
        return MigrationV2Report(
            ok=True,
            dry_run=False,
            idempotent=False,
            source_schema_version=source_version,
            target_schema_version=DB_SCHEMA_VERSION,
            preflight=preflight,
            backup=backup,
            history_events=counts.history_events,
            route_plans=counts.route_plans,
            target_deliveries=counts.target_deliveries,
            recipient_deliveries=counts.recipient_deliveries,
            mapping_counts=mapping_counts,
            quick_check=verification["quick_check"],
            foreign_key_violations=tuple(
                verification["foreign_key_violations"]
            ),
            no_external_dispatch_created=verification[
                "no_external_dispatch_created"
            ],
        )

    def _plan_mapping_counts(self) -> dict[str, int]:
        counts: dict[str, int] = defaultdict(int)
        with _connect(self.database_path) as db:
            _require_v1_tables(db)
            for row in db.execute(
                "SELECT * FROM history_items ORDER BY created_at, id"
            ):
                payload = self._decode_payload(row)
                mapping = self._map_legacy_row(row, payload)
                counts[f"kind:{mapping.history_kind}"] += 1
                counts[f"confidence:{mapping.confidence}"] += 1
                counts[f"legacy_status:{row['status']!s}"] += 1
        return counts

    def _create_backup(self) -> BackupReport:
        _prepare_private_directory(self.backup_dir, label="backup directory")
        stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        name = (
            f"{self.database_path.stem}-v1-before-v2-{stamp}-"
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
                raise MigrationV2Error("database backup quick_check failed")
            with temporary.open("rb+") as handle:
                os.fsync(handle.fileno())
            os.chmod(temporary, 0o600)
            _assert_no_symlink_chain(self.backup_dir)
            os.replace(temporary, target)
            _remove_sqlite_sidecars(temporary)
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

    def _decode_payload(self, row: sqlite3.Row) -> Mapping[str, Any]:
        item_id = str(row["id"])
        try:
            raw = decrypt_json(
                bytes(row["payload"]),
                self.key_provider,
                aad=item_id.encode("utf-8"),
            )
            payload = json.loads(raw.decode("utf-8"))
        except (
            InvalidTag,
            KeyUnavailable,
            UnicodeDecodeError,
            json.JSONDecodeError,
            TypeError,
            ValueError,
        ) as exc:
            raise MigrationV2Error(
                f"legacy payload {item_id} cannot be verified"
            ) from exc
        if not isinstance(payload, dict):
            raise MigrationV2Error(f"legacy payload {item_id} is not an object")
        if hashlib.sha256(raw).hexdigest() != str(row["payload_hash"]):
            raise MigrationV2Error(f"legacy payload {item_id} hash mismatch")
        return payload

    def _map_legacy_row(
        self,
        row: sqlite3.Row,
        payload: Mapping[str, Any],
    ) -> _LegacyMapping:
        classification = payload.get("classification")
        classification_map = (
            classification if isinstance(classification, Mapping) else {}
        )
        explicit_kind = str(
            payload.get("history_kind")
            or classification_map.get("history_kind")
            or ""
        ).strip()
        if explicit_kind in HISTORY_KINDS:
            history_kind = explicit_kind
            confidence = str(
                payload.get("classification_confidence")
                or classification_map.get("confidence")
                or "legacy"
            ).strip()
            if confidence not in CLASSIFICATION_CONFIDENCES:
                confidence = "legacy"
            reason = "legacy_explicit_classification"
        else:
            history_kind = "unknown"
            confidence = "ambiguous"
            reason = "legacy_v1_unclassified"
        try:
            classification_version = max(
                0,
                min(
                    int(
                        payload.get("classification_schema_version")
                        or classification_map.get("schema_version")
                        or 0
                    ),
                    1_000_000,
                ),
            )
        except (TypeError, ValueError):
            classification_version = 0

        codex = payload.get("codex")
        codex_map = codex if isinstance(codex, Mapping) else {}
        session_value = (
            codex_map.get("session_id")
            or payload.get("session_id")
            or ""
        )
        turn_value = codex_map.get("turn_id") or payload.get("turn_id") or ""
        parent_value = (
            codex_map.get("parent_thread_id")
            or payload.get("parent_thread_id")
            or ""
        )
        project_value = str(row["project"] or "")
        return _LegacyMapping(
            history_kind=history_kind,
            confidence=confidence,
            reason_code=reason,
            classification_schema_version=classification_version,
            session_key=persistent_opaque_id(
                self.key_provider,
                "session",
                session_value,
                prefix="sess",
            ),
            turn_key=persistent_opaque_id(
                self.key_provider,
                "turn",
                turn_value,
                prefix="turn",
            ),
            parent_thread_key=persistent_opaque_id(
                self.key_provider,
                "parent-thread",
                parent_value,
                prefix="parent",
            ),
            project_id=persistent_opaque_id(
                self.key_provider,
                "project",
                project_value,
                prefix="proj",
            ),
            project_label=_legacy_project_label(project_value),
        )

    def _migrate_legacy_rows(
        self,
        db: sqlite3.Connection,
        mapping_counts: dict[str, int],
    ) -> _MigrationCounts:
        _require_v1_tables(db)
        counts = _MigrationCounts()
        rows = db.execute(
            "SELECT * FROM history_items ORDER BY created_at, id"
        ).fetchall()
        for row in rows:
            payload = self._decode_payload(row)
            mapping = self._map_legacy_row(row, payload)
            created = str(row["created_at"])
            collected = str(row["updated_at"] or created)
            db.execute(
                "INSERT INTO history_events("
                "id,legacy_item_id,source,source_instance,dedupe_key,history_kind,"
                "classification_schema_version,classification_confidence,"
                "classification_reason_code,session_key,turn_key,parent_thread_key,"
                "project_id,project_label,encrypted_payload,payload_hash,"
                "operational_state,legacy_status,legacy_hold,created_at,collected_at,"
                "terminal_at"
                ") VALUES (?, ?, ?, 'legacy-v1', ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, "
                "'legacy_hold', ?, 1, ?, ?, '')",
                (
                    str(row["id"]),
                    str(row["id"]),
                    str(row["source"]),
                    str(row["dedupe_key"]),
                    mapping.history_kind,
                    mapping.classification_schema_version,
                    mapping.confidence,
                    mapping.reason_code,
                    mapping.session_key,
                    mapping.turn_key,
                    mapping.parent_thread_key,
                    mapping.project_id,
                    mapping.project_label,
                    bytes(row["payload"]),
                    str(row["payload_hash"]),
                    str(row["status"]),
                    created,
                    collected,
                ),
            )
            counts = _MigrationCounts(
                history_events=counts.history_events + 1,
                route_plans=counts.route_plans,
                target_deliveries=counts.target_deliveries,
                recipient_deliveries=counts.recipient_deliveries,
            )
            mapping_counts[f"kind:{mapping.history_kind}"] += 1
            mapping_counts[f"confidence:{mapping.confidence}"] += 1
            mapping_counts[f"legacy_status:{row['status']!s}"] += 1
            recipient_rows = db.execute(
                "SELECT * FROM recipient_results WHERE item_id=? "
                "ORDER BY recipient_id",
                (str(row["id"]),),
            ).fetchall()
            if recipient_rows:
                added = self._migrate_recipient_results(db, row, recipient_rows)
                counts = _MigrationCounts(
                    history_events=counts.history_events,
                    route_plans=counts.route_plans + added.route_plans,
                    target_deliveries=(
                        counts.target_deliveries + added.target_deliveries
                    ),
                    recipient_deliveries=(
                        counts.recipient_deliveries + added.recipient_deliveries
                    ),
                )
        return counts

    def _migrate_recipient_results(
        self,
        db: sqlite3.Connection,
        history_row: sqlite3.Row,
        recipient_rows: Sequence[sqlite3.Row],
    ) -> _MigrationCounts:
        event_id = str(history_row["id"])
        grouped: dict[str, list[sqlite3.Row]] = defaultdict(list)
        for recipient in recipient_rows:
            channel = str(recipient["channel"] or "").strip().casefold()
            target_id = "telegram" if channel == "telegram" else "legacy_unknown"
            grouped[target_id].append(recipient)

        route_id = persistent_opaque_id(
            self.key_provider,
            "route-plan",
            f"{event_id}|legacy-v1",
            prefix="route",
        )
        plan_description: list[dict[str, Any]] = []
        normalized_groups: dict[str, list[dict[str, Any]]] = {}
        for target_id, rows in sorted(grouped.items()):
            rendered: list[dict[str, Any]] = []
            for row in rows:
                recipient_key = persistent_opaque_id(
                    self.key_provider,
                    "recipient",
                    str(row["recipient_id"]),
                    prefix="recipient",
                )
                rendered.append(
                    {
                        "recipient_key": recipient_key,
                        "status": str(row["status"] or "").strip().casefold(),
                        "possible_duplicate": bool(row["possible_duplicate"]),
                    }
                )
            normalized_groups[target_id] = rendered
            plan_description.append(
                {"target_id": target_id, "recipients": rendered}
            )
        plan_hash = hashlib.sha256(
            _canonical_json(
                {
                    "event_id": event_id,
                    "migration": DB_SCHEMA_VERSION,
                    "targets": plan_description,
                }
            ).encode("utf-8")
        ).hexdigest()
        created = str(history_row["created_at"])
        db.execute(
            "INSERT INTO route_plans("
            "id,event_id,config_revision,routing_schema_version,planner_version,"
            "plan_hash,plan_state,created_at"
            ") VALUES (?, ?, 'legacy-v1', ?, 'migration-v2', ?, "
            "'legacy_migrated', ?)",
            (route_id, event_id, ROUTING_SCHEMA_VERSION, plan_hash, created),
        )
        target_count = 0
        recipient_count = 0
        for target_id, rows in sorted(grouped.items()):
            normalized = normalized_groups[target_id]
            statuses = {entry["status"] for entry in normalized}
            possible_duplicate = any(
                bool(entry["possible_duplicate"]) for entry in normalized
            )
            successes = sum(
                1
                for entry in normalized
                if entry["status"] in _SUCCESS_RECIPIENT_STATES
                and not entry["possible_duplicate"]
            )
            if possible_duplicate:
                target_state = "legacy_hold"
                legacy_outcome = "possible_duplicate"
                terminal_at = ""
            elif successes == len(normalized):
                target_state = "delivered"
                legacy_outcome = "delivered"
                terminal_at = str(history_row["updated_at"] or created)
            elif successes:
                target_state = "legacy_hold"
                legacy_outcome = "partial"
                terminal_at = ""
            else:
                target_state = "legacy_hold"
                legacy_outcome = "failed" if statuses else "unknown"
                terminal_at = ""
            target_delivery_id = persistent_opaque_id(
                self.key_provider,
                "target-delivery",
                f"{route_id}|{target_id}",
                prefix="target",
            )
            target_idempotency_key = persistent_opaque_id(
                self.key_provider,
                "target-idempotency",
                f"{event_id}|{target_id}|legacy-v1",
                prefix="idem",
                length=48,
            )
            db.execute(
                "INSERT INTO target_deliveries("
                "id,route_plan_id,target_id,state,legacy_outcome,attempt_count,"
                "last_error_class,idempotency_key,created_at,updated_at,terminal_at"
                ") VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    target_delivery_id,
                    route_id,
                    target_id,
                    target_state,
                    legacy_outcome,
                    int(history_row["attempt_count"] or 0),
                    "" if target_state == "delivered" else "legacy_hold",
                    target_idempotency_key,
                    created,
                    str(history_row["updated_at"] or created),
                    terminal_at,
                ),
            )
            target_count += 1
            for row, normalized_recipient in zip(rows, normalized, strict=True):
                raw_status = normalized_recipient["status"]
                is_possible_duplicate = bool(
                    normalized_recipient["possible_duplicate"]
                )
                if is_possible_duplicate:
                    recipient_state = "possible_duplicate"
                    recipient_terminal = ""
                    error_class = "possible_duplicate"
                elif raw_status in _SUCCESS_RECIPIENT_STATES:
                    recipient_state = raw_status
                    recipient_terminal = str(row["updated_at"] or created)
                    error_class = ""
                elif raw_status in {"skipped", "discarded"}:
                    recipient_state = "skipped"
                    recipient_terminal = str(row["updated_at"] or created)
                    error_class = ""
                else:
                    recipient_state = "legacy_hold"
                    recipient_terminal = ""
                    error_class = "legacy_failure"
                recipient_key = normalized_recipient["recipient_key"]
                recipient_delivery_id = persistent_opaque_id(
                    self.key_provider,
                    "recipient-delivery",
                    f"{target_delivery_id}|{recipient_key}",
                    prefix="delivery",
                )
                recipient_idempotency_key = persistent_opaque_id(
                    self.key_provider,
                    "recipient-idempotency",
                    f"{event_id}|{target_id}|{recipient_key}",
                    prefix="idem",
                    length=48,
                )
                message_ref_key = persistent_opaque_id(
                    self.key_provider,
                    "external-message-ref",
                    str(row["message_ref"] or ""),
                    prefix="msgref",
                )
                db.execute(
                    "INSERT INTO recipient_deliveries("
                    "id,target_delivery_id,recipient_key,state,legacy_outcome,"
                    "external_message_ref_key,idempotency_key,attempt_count,"
                    "possible_duplicate,last_error_class,created_at,updated_at,"
                    "terminal_at"
                    ") VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    (
                        recipient_delivery_id,
                        target_delivery_id,
                        recipient_key,
                        recipient_state,
                        raw_status or "unknown",
                        message_ref_key,
                        recipient_idempotency_key,
                        int(history_row["attempt_count"] or 0),
                        int(is_possible_duplicate),
                        error_class,
                        created,
                        str(row["updated_at"] or created),
                        recipient_terminal,
                    ),
                )
                recipient_count += 1
        return _MigrationCounts(
            route_plans=1,
            target_deliveries=target_count,
            recipient_deliveries=recipient_count,
        )

    @staticmethod
    def _verify_transaction(
        db: sqlite3.Connection,
        *,
        expected_history_items: int,
    ) -> None:
        migrated = int(
            db.execute(
                "SELECT COUNT(*) FROM history_events "
                "WHERE legacy_item_id IS NOT NULL"
            ).fetchone()[0]
        )
        if migrated != expected_history_items:
            raise MigrationV2Error(
                "v1 history count does not match migrated events"
            )
        unsafe_targets = int(
            db.execute(
                "SELECT COUNT(*) FROM target_deliveries td "
                "JOIN route_plans rp ON rp.id=td.route_plan_id "
                "WHERE rp.plan_state='legacy_migrated' "
                "AND td.state IN ('pending','claimed','failed_retryable')"
            ).fetchone()[0]
        )
        if unsafe_targets:
            raise MigrationV2Error(
                "migration created externally retryable deliveries"
            )
        foreign_keys = _foreign_key_violations(db)
        if foreign_keys:
            raise MigrationV2Error("v2 foreign_key_check failed")
        if _quick_check(db) != "ok":
            raise MigrationV2Error("v2 quick_check failed")


def _legacy_project_label(value: str) -> str:
    normalized = str(value or "").replace("\\", "/").rstrip("/")
    try:
        parsed = urlsplit(normalized)
    except ValueError:
        parsed = None
    path = parsed.path if parsed and parsed.scheme else normalized
    label = PurePosixPath(path).name if path else ""
    if label.endswith(".git"):
        label = label[:-4]
    return safe_project_label(label or "Unbekanntes Projekt")


def verify_database_v2(database_path: Path) -> dict[str, Any]:
    path = Path(database_path).expanduser().absolute()
    _assert_regular_owned_database(path)
    with _connect(path) as db:
        versions = _schema_versions(db)
        missing = tuple(
            table for table in V2_TABLES if not _table_exists(db, table)
        )
        quick = _quick_check(db)
        foreign_keys = _foreign_key_violations(db)
        history_items = (
            int(db.execute("SELECT COUNT(*) FROM history_items").fetchone()[0])
            if _table_exists(db, "history_items")
            else 0
        )
        history_events = (
            int(db.execute("SELECT COUNT(*) FROM history_events").fetchone()[0])
            if _table_exists(db, "history_events")
            else 0
        )
        migrated_legacy_events = (
            int(
                db.execute(
                    "SELECT COUNT(*) FROM history_events "
                    "WHERE legacy_item_id IS NOT NULL"
                ).fetchone()[0]
            )
            if _table_exists(db, "history_events")
            else 0
        )
        route_plans = (
            int(db.execute("SELECT COUNT(*) FROM route_plans").fetchone()[0])
            if _table_exists(db, "route_plans")
            else 0
        )
        target_deliveries = (
            int(
                db.execute("SELECT COUNT(*) FROM target_deliveries").fetchone()[0]
            )
            if _table_exists(db, "target_deliveries")
            else 0
        )
        recipient_deliveries = (
            int(
                db.execute(
                    "SELECT COUNT(*) FROM recipient_deliveries"
                ).fetchone()[0]
            )
            if _table_exists(db, "recipient_deliveries")
            else 0
        )
        unsafe_targets = (
            int(
                db.execute(
                    "SELECT COUNT(*) FROM target_deliveries td "
                    "JOIN route_plans rp ON rp.id=td.route_plan_id "
                    "WHERE rp.plan_state='legacy_migrated' "
                    "AND td.state IN ('pending','claimed','failed_retryable')"
                ).fetchone()[0]
            )
            if _table_exists(db, "target_deliveries")
            and _table_exists(db, "route_plans")
            else 0
        )
    ok = (
        DB_SCHEMA_VERSION in versions
        and not missing
        and quick == "ok"
        and not foreign_keys
        and migrated_legacy_events >= history_items
        and history_events >= migrated_legacy_events
        and unsafe_targets == 0
    )
    return {
        "ok": ok,
        "schema_versions": list(versions),
        "missing_tables": list(missing),
        "quick_check": quick,
        "foreign_key_violations": list(foreign_keys),
        "history_items": history_items,
        "history_events": history_events,
        "migrated_legacy_events": migrated_legacy_events,
        "route_plans": route_plans,
        "target_deliveries": target_deliveries,
        "recipient_deliveries": recipient_deliveries,
        "no_external_dispatch_created": unsafe_targets == 0,
    }


def _copy_verified_backup_to_staging(
    backup: Path,
    destination_directory: Path,
) -> tuple[Path, str]:
    flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)
    try:
        source_descriptor = os.open(backup, flags)
    except OSError as exc:
        raise MigrationV2Error("backup cannot be opened safely") from exc
    staging: Path | None = None
    try:
        source_info = os.fstat(source_descriptor)
        if not stat.S_ISREG(source_info.st_mode):
            raise MigrationV2Error("backup must be a regular file")
        if hasattr(os, "getuid") and source_info.st_uid != os.getuid():
            raise MigrationV2Error("backup must be owned by the current user")
        descriptor, temporary_name = tempfile.mkstemp(
            prefix=".history-dispatcher-backup-",
            suffix=".verified.sqlite3",
            dir=destination_directory,
        )
        staging = Path(temporary_name)
        digest = hashlib.sha256()
        with os.fdopen(descriptor, "wb") as target, os.fdopen(
            os.dup(source_descriptor),
            "rb",
        ) as source:
            for block in iter(lambda: source.read(1024 * 1024), b""):
                digest.update(block)
                target.write(block)
            target.flush()
            os.fsync(target.fileno())
        os.chmod(staging, 0o600)
        return staging, digest.hexdigest()
    except Exception:
        if staging is not None:
            try:
                staging.unlink()
            except FileNotFoundError:
                pass
        raise
    finally:
        os.close(source_descriptor)


def restore_database_backup(
    backup_path: Path,
    destination_path: Path,
    *,
    expected_sha256: str,
    confirmation: str,
) -> dict[str, Any]:
    backup = Path(backup_path).expanduser().absolute()
    destination = Path(destination_path).expanduser().absolute()
    _assert_no_symlink_chain(backup)
    _assert_no_symlink_chain(destination, allow_missing_leaf=True)
    _prepare_private_directory(destination.parent, label="restore destination directory")

    staging, actual_hash = _copy_verified_backup_to_staging(
        backup,
        destination.parent,
    )
    normalized_expected = str(expected_sha256).strip().lower()
    try:
        if actual_hash != normalized_expected:
            raise MigrationV2Error("backup hash does not match expected SHA-256")
        if confirmation != f"RESTORE {actual_hash[:12]}":
            raise MigrationV2Error("restore confirmation mismatch")
        with _connect(staging) as source:
            if _quick_check(source) != "ok":
                raise MigrationV2Error("backup quick_check failed")
            if _foreign_key_violations(source):
                raise MigrationV2Error("backup foreign_key_check failed")

        if destination.exists():
            _assert_regular_owned_database(destination)
            with _connect(destination) as current:
                current.execute("PRAGMA wal_checkpoint(TRUNCATE)")
        _assert_no_symlink_chain(destination, allow_missing_leaf=True)
        os.replace(staging, destination)
        _remove_sqlite_sidecars(destination)
        _fsync_directory(destination.parent)
        return {
            "ok": True,
            "restored_sha256": _sha256_file(destination),
            "source_backup_sha256": actual_hash,
            "quick_check": "ok",
        }
    finally:
        _remove_sqlite_sidecars(staging)
        try:
            staging.unlink()
        except FileNotFoundError:
            pass
