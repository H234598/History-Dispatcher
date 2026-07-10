from __future__ import annotations

import hashlib
import json
import sqlite3
import threading
import uuid
from collections.abc import Iterable, Mapping, Sequence
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from .crypto import SecretServiceKeyProvider, decrypt_json, encrypt_json


SCHEMA_VERSION = 1


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _canonical(value: object) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")


class DispatcherStore:
    def __init__(self, database_path: Path, key_provider: SecretServiceKeyProvider) -> None:
        self.database_path = database_path
        self.key_provider = key_provider
        self._lock = threading.RLock()
        self.database_path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        self._initialize()

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.database_path, timeout=30, isolation_level=None, check_same_thread=False)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA journal_mode=WAL")
        connection.execute("PRAGMA foreign_keys=ON")
        connection.execute("PRAGMA busy_timeout=30000")
        return connection

    def _initialize(self) -> None:
        with self._lock, self._connect() as db:
            db.executescript(
                """
                CREATE TABLE IF NOT EXISTS schema_migrations (
                    version INTEGER PRIMARY KEY,
                    applied_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS history_items (
                    id TEXT PRIMARY KEY,
                    source TEXT NOT NULL,
                    dedupe_key TEXT NOT NULL UNIQUE,
                    kind TEXT NOT NULL,
                    target_group TEXT NOT NULL,
                    project TEXT NOT NULL DEFAULT '',
                    payload BLOB NOT NULL,
                    payload_hash TEXT NOT NULL,
                    status TEXT NOT NULL,
                    attempt_count INTEGER NOT NULL DEFAULT 0,
                    available_at TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    last_error TEXT NOT NULL DEFAULT '',
                    possible_duplicate INTEGER NOT NULL DEFAULT 0
                );
                CREATE INDEX IF NOT EXISTS idx_history_dispatch
                    ON history_items(status, available_at, created_at);
                CREATE TABLE IF NOT EXISTS dispatch_claims (
                    item_id TEXT PRIMARY KEY REFERENCES history_items(id) ON DELETE CASCADE,
                    worker_id TEXT NOT NULL,
                    claimed_at TEXT NOT NULL,
                    expires_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS recipient_results (
                    item_id TEXT NOT NULL REFERENCES history_items(id) ON DELETE CASCADE,
                    recipient_id TEXT NOT NULL,
                    status TEXT NOT NULL,
                    channel TEXT NOT NULL DEFAULT '',
                    message_ref TEXT NOT NULL DEFAULT '',
                    reason TEXT NOT NULL DEFAULT '',
                    possible_duplicate INTEGER NOT NULL DEFAULT 0,
                    updated_at TEXT NOT NULL,
                    PRIMARY KEY(item_id, recipient_id)
                );
                CREATE TABLE IF NOT EXISTS delivery_events (
                    event_id TEXT PRIMARY KEY,
                    item_id TEXT NOT NULL REFERENCES history_items(id) ON DELETE CASCADE,
                    recipient_id TEXT NOT NULL,
                    event_type TEXT NOT NULL,
                    message_ref TEXT NOT NULL DEFAULT '',
                    occurred_at TEXT NOT NULL,
                    UNIQUE(item_id, recipient_id, event_type, message_ref)
                );
                CREATE TABLE IF NOT EXISTS admin_audit_events (
                    event_id TEXT PRIMARY KEY,
                    operation TEXT NOT NULL,
                    item_id TEXT NOT NULL DEFAULT '',
                    details_json TEXT NOT NULL,
                    created_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS deletion_tombstones (
                    item_id TEXT PRIMARY KEY,
                    payload_hash TEXT NOT NULL,
                    operation TEXT NOT NULL,
                    deleted_at TEXT NOT NULL,
                    reason TEXT NOT NULL
                );
                """
            )
            db.execute(
                "INSERT OR IGNORE INTO schema_migrations(version, applied_at) VALUES (?, ?)",
                (SCHEMA_VERSION, _now()),
            )

    def append(self, item: Mapping[str, Any], *, idempotency_key: str = "") -> dict[str, Any]:
        payload = dict(item.get("payload") if isinstance(item.get("payload"), Mapping) else item)
        item_id = str(item.get("id") or uuid.uuid4())
        source = str(item.get("source") or "unknown").strip()[:96] or "unknown"
        dedupe = str(item.get("dedupe_key") or idempotency_key or item_id).strip()[:512]
        kind = str(item.get("kind") or "history").strip()[:96] or "history"
        target_group = str(item.get("target_group") or "status_admins").strip()[:96] or "status_admins"
        project = str(item.get("project") or "").strip()[:512]
        created = str(item.get("created_at") or _now())
        raw = _canonical(payload)
        encrypted = encrypt_json(raw, self.key_provider, aad=item_id.encode("utf-8"))
        payload_hash = hashlib.sha256(raw).hexdigest()
        with self._lock, self._connect() as db:
            existing = db.execute("SELECT id, payload_hash, status FROM history_items WHERE dedupe_key=?", (dedupe,)).fetchone()
            if existing is not None:
                return {"ok": True, "id": existing["id"], "deduplicated": True, "status": existing["status"], "payload_hash": existing["payload_hash"]}
            db.execute(
                """
                INSERT INTO history_items(
                    id, source, dedupe_key, kind, target_group, project, payload,
                    payload_hash, status, available_at, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'queued', ?, ?, ?)
                """,
                (item_id, source, dedupe, kind, target_group, project, encrypted, payload_hash, created, created, created),
            )
        return {"ok": True, "id": item_id, "deduplicated": False, "status": "queued", "payload_hash": payload_hash}

    def _decode_row(self, row: sqlite3.Row) -> dict[str, Any]:
        payload = json.loads(decrypt_json(bytes(row["payload"]), self.key_provider, aad=str(row["id"]).encode("utf-8")))
        result = {key: row[key] for key in row.keys() if key != "payload"}
        result["payload"] = payload
        result["possible_duplicate"] = bool(result["possible_duplicate"])
        return result

    def query(self, *, status: str = "", limit: int = 20, include_payload: bool = False) -> list[dict[str, Any]]:
        limit = max(1, min(int(limit), 100))
        sql = "SELECT * FROM history_items"
        params: list[Any] = []
        if status:
            sql += " WHERE status=?"
            params.append(status)
        sql += " ORDER BY created_at DESC LIMIT ?"
        params.append(limit)
        with self._lock, self._connect() as db:
            rows = db.execute(sql, params).fetchall()
        result: list[dict[str, Any]] = []
        for row in rows:
            if include_payload:
                result.append(self._decode_row(row))
            else:
                result.append({key: row[key] for key in row.keys() if key != "payload"})
        return result

    def claim(self, *, worker_id: str, limit: int, claim_ttl_seconds: int) -> list[dict[str, Any]]:
        now = datetime.now(timezone.utc)
        now_text = now.isoformat(timespec="seconds")
        expires = (now + timedelta(seconds=claim_ttl_seconds)).isoformat(timespec="seconds")
        worker = str(worker_id).strip()[:128]
        if not worker:
            raise ValueError("worker_id must not be empty")
        with self._lock, self._connect() as db:
            db.execute("BEGIN IMMEDIATE")
            db.execute("DELETE FROM dispatch_claims WHERE expires_at <= ?", (now_text,))
            rows = db.execute(
                """
                SELECT h.* FROM history_items h
                LEFT JOIN dispatch_claims c ON c.item_id=h.id
                WHERE h.status='queued' AND h.available_at <= ? AND c.item_id IS NULL
                ORDER BY h.created_at DESC LIMIT ?
                """,
                (now_text, max(1, min(int(limit), 1000))),
            ).fetchall()
            result: list[dict[str, Any]] = []
            for row in rows:
                db.execute(
                    "INSERT INTO dispatch_claims(item_id, worker_id, claimed_at, expires_at) VALUES (?, ?, ?, ?)",
                    (row["id"], worker, now_text, expires),
                )
                result.append(self._decode_row(row))
            db.commit()
        return result

    def complete(self, *, item_id: str, worker_id: str, recipient_results: Sequence[Mapping[str, Any]], reason: str = "") -> dict[str, Any]:
        item_id = str(item_id).strip()
        worker_id = str(worker_id).strip()
        now = _now()
        results = [dict(item) for item in recipient_results]
        statuses = {str(item.get("status") or "").strip() for item in results}
        final_status = "delivered" if results and statuses <= {"delivered", "accepted", "acknowledged"} else "failed"
        if not results:
            final_status = "skipped"
        with self._lock, self._connect() as db:
            db.execute("BEGIN IMMEDIATE")
            claim = db.execute("SELECT worker_id FROM dispatch_claims WHERE item_id=?", (item_id,)).fetchone()
            if claim is None or claim["worker_id"] != worker_id:
                db.rollback()
                return {"ok": False, "error": "claim_not_owned", "item_id": item_id}
            for item in results:
                recipient = str(item.get("recipient_id") or "").strip()
                if not recipient:
                    continue
                db.execute(
                    """
                    INSERT INTO recipient_results(item_id, recipient_id, status, channel, message_ref, reason, possible_duplicate, updated_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(item_id, recipient_id) DO UPDATE SET
                        status=excluded.status, channel=excluded.channel, message_ref=excluded.message_ref,
                        reason=excluded.reason, possible_duplicate=excluded.possible_duplicate, updated_at=excluded.updated_at
                    """,
                    (item_id, recipient, str(item.get("status") or "failed"), str(item.get("channel") or ""), str(item.get("message_ref") or ""), str(item.get("reason") or reason), int(bool(item.get("possible_duplicate"))), now),
                )
            db.execute(
                "UPDATE history_items SET status=?, updated_at=?, last_error=?, possible_duplicate=? WHERE id=?",
                (final_status, now, reason if final_status == "failed" else "", int(any(item.get("possible_duplicate") for item in results)), item_id),
            )
            db.execute("DELETE FROM dispatch_claims WHERE item_id=?", (item_id,))
            db.commit()
        return {"ok": True, "item_id": item_id, "status": final_status}

    def retry(self, item_id: str, *, reason: str = "") -> dict[str, Any]:
        now = _now()
        with self._lock, self._connect() as db:
            changed = db.execute(
                "UPDATE history_items SET status='queued', available_at=?, updated_at=?, last_error=? WHERE id=? AND status IN ('failed','skipped','discarded')",
                (now, now, reason, str(item_id).strip()),
            ).rowcount
        return {"ok": bool(changed), "item_id": str(item_id).strip(), "status": "queued" if changed else "not_retryable"}

    def record_delivery(self, event: Mapping[str, Any]) -> dict[str, Any]:
        event_id = str(event.get("event_id") or uuid.uuid4())
        item_id = str(event.get("item_id") or "").strip()
        recipient_id = str(event.get("recipient_id") or "").strip()
        event_type = str(event.get("event_type") or "").strip()
        if not item_id or not recipient_id or not event_type:
            return {"ok": False, "error": "missing_delivery_identity"}
        with self._lock, self._connect() as db:
            db.execute(
                "INSERT OR IGNORE INTO delivery_events(event_id,item_id,recipient_id,event_type,message_ref,occurred_at) VALUES (?, ?, ?, ?, ?, ?)",
                (event_id, item_id, recipient_id, event_type, str(event.get("message_ref") or ""), str(event.get("occurred_at") or _now())),
            )
        return {"ok": True, "event_id": event_id, "deduplicated": False}

    def status(self) -> dict[str, Any]:
        with self._lock, self._connect() as db:
            counts = {row["status"]: int(row["count"]) for row in db.execute("SELECT status, COUNT(*) AS count FROM history_items GROUP BY status")}
            total = int(db.execute("SELECT COUNT(*) FROM history_items").fetchone()[0])
            oldest = db.execute("SELECT created_at FROM history_items WHERE status='queued' ORDER BY created_at ASC LIMIT 1").fetchone()
        return {"total": total, "status_counts": counts, "queued": counts.get("queued", 0), "oldest_queued_at": oldest["created_at"] if oldest else ""}

    def preview_delete(self, *, status: str = "", limit: int = 100) -> dict[str, Any]:
        rows = self.query(status=status, limit=min(max(int(limit), 1), 100), include_payload=False)
        return {"ok": True, "count": len(rows), "ids": [str(row["id"]) for row in rows], "status": status, "revision": self.status()["total"]}

    def execute_delete(self, *, ids: Iterable[str], confirmation: str, revision: int, reason: str = "") -> dict[str, Any]:
        normalized = [str(item).strip() for item in ids if str(item).strip()]
        if not normalized or confirmation != f"LOESCHEN {len(normalized)}":
            return {"ok": False, "error": "confirmation_mismatch"}
        if self.status()["total"] != int(revision):
            return {"ok": False, "error": "revision_changed"}
        now = _now()
        deleted = 0
        with self._lock, self._connect() as db:
            db.execute("BEGIN IMMEDIATE")
            for item_id in normalized:
                row = db.execute("SELECT payload_hash FROM history_items WHERE id=?", (item_id,)).fetchone()
                if row is None:
                    continue
                db.execute(
                    "INSERT OR REPLACE INTO deletion_tombstones(item_id,payload_hash,operation,deleted_at,reason) VALUES (?, ?, 'admin_delete', ?, ?)",
                    (item_id, row["payload_hash"], now, reason[:500]),
                )
                db.execute(
                    "INSERT INTO admin_audit_events(event_id,operation,item_id,details_json,created_at) VALUES (?, 'admin_delete', ?, ?, ?)",
                    (str(uuid.uuid4()), item_id, json.dumps({"reason": reason[:500]}, sort_keys=True), now),
                )
                db.execute("DELETE FROM history_items WHERE id=?", (item_id,))
                deleted += 1
            db.commit()
        return {"ok": True, "deleted": deleted}

