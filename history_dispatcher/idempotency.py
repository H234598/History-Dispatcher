from __future__ import annotations

import json
import os
import sqlite3
import threading
from collections.abc import Mapping
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any


class IdempotencyConflict(RuntimeError):
    """The request ID is already bound to a different request fingerprint."""


class IdempotencyInProgress(RuntimeError):
    """The request ID is reserved but no durable response is available yet."""


def _timestamp() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _canonical_response(response: Mapping[str, Any]) -> str:
    return json.dumps(
        dict(response),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    )


class IdempotencyStore:
    """Durable request-ID reservations stored beside the dispatcher queue.

    The control socket accepts only the current operating-system user, so the
    authenticated client scope is the effective UID. A request ID is bound to
    that scope, the operation, and a canonical operation/body fingerprint.
    """

    def __init__(self, database_path: Path, *, client_scope: str | None = None) -> None:
        self.database_path = Path(database_path)
        self.client_scope = str(client_scope or f"uid:{os.getuid()}")
        self._lock = threading.RLock()
        self.database_path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        self._initialize()

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(
            self.database_path,
            timeout=30,
            isolation_level=None,
            check_same_thread=False,
        )
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA journal_mode=WAL")
        connection.execute("PRAGMA busy_timeout=30000")
        return connection

    def _initialize(self) -> None:
        with self._lock, self._connect() as db:
            db.execute(
                """
                CREATE TABLE IF NOT EXISTS idempotency_results (
                    request_id TEXT PRIMARY KEY,
                    operation TEXT NOT NULL,
                    request_fingerprint TEXT NOT NULL DEFAULT '',
                    client_scope TEXT NOT NULL DEFAULT '',
                    response_json TEXT NOT NULL DEFAULT '',
                    created_at TEXT NOT NULL
                )
                """
            )
            columns = {
                str(row["name"])
                for row in db.execute("PRAGMA table_info(idempotency_results)").fetchall()
            }
            if "request_fingerprint" not in columns:
                db.execute(
                    "ALTER TABLE idempotency_results "
                    "ADD COLUMN request_fingerprint TEXT NOT NULL DEFAULT ''"
                )
            if "client_scope" not in columns:
                db.execute(
                    "ALTER TABLE idempotency_results "
                    "ADD COLUMN client_scope TEXT NOT NULL DEFAULT ''"
                )
            # Old v1 cache rows did not retain an operation/body fingerprint and
            # therefore cannot be replayed safely. They are cache-only metadata;
            # deleting them does not alter queue or delivery state.
            db.execute(
                "DELETE FROM idempotency_results "
                "WHERE request_fingerprint='' OR client_scope=''"
            )

    @staticmethod
    def _validate_identity(request_id: str, operation: str, fingerprint: str) -> tuple[str, str, str]:
        normalized_id = str(request_id).strip()
        normalized_operation = str(operation).strip()
        normalized_fingerprint = str(fingerprint).strip().lower()
        if (
            not normalized_id
            or len(normalized_id) > 128
            or any(ord(char) < 0x20 for char in normalized_id)
        ):
            raise ValueError("request_id is invalid")
        if not normalized_operation or len(normalized_operation) > 96:
            raise ValueError("operation is invalid")
        if len(normalized_fingerprint) != 64 or any(
            char not in "0123456789abcdef" for char in normalized_fingerprint
        ):
            raise ValueError("request fingerprint is invalid")
        return normalized_id, normalized_operation, normalized_fingerprint

    def begin(
        self,
        request_id: str,
        operation: str,
        fingerprint: str,
    ) -> dict[str, Any] | None:
        normalized_id, normalized_operation, normalized_fingerprint = self._validate_identity(
            request_id, operation, fingerprint
        )
        with self._lock, self._connect() as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute(
                "SELECT operation, request_fingerprint, client_scope, response_json "
                "FROM idempotency_results WHERE request_id=?",
                (normalized_id,),
            ).fetchone()
            if row is None:
                db.execute(
                    "INSERT INTO idempotency_results("
                    "request_id, operation, request_fingerprint, client_scope, response_json, created_at"
                    ") VALUES (?, ?, ?, ?, '', ?)",
                    (
                        normalized_id,
                        normalized_operation,
                        normalized_fingerprint,
                        self.client_scope,
                        _timestamp(),
                    ),
                )
                db.commit()
                return None

            if (
                str(row["operation"]) != normalized_operation
                or str(row["request_fingerprint"]) != normalized_fingerprint
                or str(row["client_scope"]) != self.client_scope
            ):
                db.rollback()
                raise IdempotencyConflict(normalized_id)

            encoded = str(row["response_json"] or "")
            if not encoded:
                db.rollback()
                raise IdempotencyInProgress(normalized_id)
            try:
                cached = json.loads(encoded)
            except json.JSONDecodeError as exc:
                db.rollback()
                raise IdempotencyInProgress(normalized_id) from exc
            if not isinstance(cached, dict):
                db.rollback()
                raise IdempotencyInProgress(normalized_id)
            db.commit()
            return cached

    def complete(
        self,
        request_id: str,
        operation: str,
        fingerprint: str,
        response: Mapping[str, Any],
    ) -> dict[str, Any]:
        normalized_id, normalized_operation, normalized_fingerprint = self._validate_identity(
            request_id, operation, fingerprint
        )
        encoded = _canonical_response(response)
        with self._lock, self._connect() as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute(
                "SELECT operation, request_fingerprint, client_scope, response_json "
                "FROM idempotency_results WHERE request_id=?",
                (normalized_id,),
            ).fetchone()
            if row is None:
                db.rollback()
                raise IdempotencyInProgress(normalized_id)
            if (
                str(row["operation"]) != normalized_operation
                or str(row["request_fingerprint"]) != normalized_fingerprint
                or str(row["client_scope"]) != self.client_scope
            ):
                db.rollback()
                raise IdempotencyConflict(normalized_id)

            existing = str(row["response_json"] or "")
            if existing:
                try:
                    cached = json.loads(existing)
                except json.JSONDecodeError as exc:
                    db.rollback()
                    raise IdempotencyInProgress(normalized_id) from exc
                if not isinstance(cached, dict):
                    db.rollback()
                    raise IdempotencyInProgress(normalized_id)
                db.commit()
                return cached

            db.execute(
                "UPDATE idempotency_results SET response_json=? WHERE request_id=?",
                (encoded, normalized_id),
            )
            db.commit()
        return dict(response)

    def prune(self, *, retention_days: int) -> int:
        cutoff = (
            datetime.now(timezone.utc) - timedelta(days=max(1, int(retention_days)))
        ).isoformat(timespec="seconds")
        with self._lock, self._connect() as db:
            deleted = db.execute(
                "DELETE FROM idempotency_results WHERE created_at < ?",
                (cutoff,),
            ).rowcount
        return int(deleted)
