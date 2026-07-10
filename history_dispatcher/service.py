from __future__ import annotations

import json
import os
import secrets
import socket
import socketserver
import struct
import threading
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from . import __version__
from .config import DispatcherConfig, apply_safe_values, config_revision, load_config, public_config, write_config
from .crypto import SecretServiceKeyProvider
from .protocol import ProtocolError, encode_message, read_message
from .store import DispatcherStore


OPERATIONS = (
    "protocol.describe", "health.get", "status.get", "report.get",
    "history.append", "history.query",
    "dispatch.claim", "dispatch.complete", "dispatch.retry",
   "delivery.record", "config.get", "config.validate", "config.apply",
    "collector.collect", "admin.preview", "admin.execute", "audit.query",
    "migration.import_legacy",
    "maintenance.prune",
)
IDEMPOTENT_OPERATIONS = frozenset({
    "history.append", "dispatch.claim", "dispatch.complete", "dispatch.retry", "delivery.record",
    "config.apply", "collector.collect", "admin.execute", "migration.import_legacy",
    "maintenance.prune",
})


def _timestamp() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


class DispatcherService:
    def __init__(self, config: DispatcherConfig, *, key_provider: SecretServiceKeyProvider | None = None) -> None:
        self.config = config
        self.key_provider = key_provider or SecretServiceKeyProvider()
        self.store = DispatcherStore(config.database_path, self.key_provider)
        self._lock = threading.RLock()
        self._started_at = _timestamp()
        self._last_operation = ""
        self._last_error = ""
        self._last_collection: dict[str, Any] = {}
        self._last_delivery: dict[str, Any] = {}
        self._tokens: dict[str, tuple[list[str], str, float]] = {}
        self._write_snapshot()

    def _status(self) -> dict[str, Any]:
        status = self.store.status()
        preview_rows = self.store.query(limit=20, include_payload=False)
        status.update({
            "schema_version": 1,
            "service": "history-dispatcher",
            "version": __version__,
            "ok": True,
            "generated_at": _timestamp(),
            "started_at": self._started_at,
            "last_operation": self._last_operation,
            "last_error": self._last_error,
            "last_collection": dict(self._last_collection),
            "last_delivery": dict(self._last_delivery),
            "queue_preview": [
                {
                    "id": str(item.get("id") or ""),
                    "status": str(item.get("status") or ""),
                    "kind": str(item.get("kind") or ""),
                    "created_at": str(item.get("created_at") or ""),
                    "last_error": str(item.get("last_error") or "")[:160],
                }
                for item in preview_rows
            ],
            "collector": {
                "enabled": self.config.collector_enabled,
                "interval_seconds": self.config.collector_interval_seconds,
                "sources": len([source for source in self.config.sources if source.enabled]),
            },
            "dispatch": {
                "enabled": self.config.dispatch_enabled,
                "paused": self.config.dispatch_paused,
                "batch_size": self.config.dispatch_batch_size,
            },
            "capabilities": {
                "admin": True,
                "destructive_admin": True,
                "config_apply": True,
            },
        })
        return status

    def _write_snapshot(self) -> None:
        path = self.config.snapshot_path
        path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
        data = json.dumps(self._status(), ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        if len(data.encode("utf-8")) > 64 * 1024:
            raise RuntimeError("status snapshot exceeds 64 KiB")
        with temporary.open("w", encoding="utf-8") as handle:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        os.chmod(temporary, 0o600)
        os.replace(temporary, path)

    def handle(self, request: object) -> dict[str, Any]:
        if not isinstance(request, dict):
            return {"ok": False, "error": {"code": "invalid_request", "message": "request must be an object"}}
        operation = str(request.get("operation") or "").strip()
        request_id = str(request.get("request_id") or "").strip()
        body = request.get("body") if isinstance(request.get("body"), dict) else {}
        if int(request.get("protocol_version", 0) or 0) != 1:
            return {"ok": False, "error": {"code": "unsupported_protocol", "message": "protocol_version must be 1"}}
        if operation not in OPERATIONS:
            return {"ok": False, "error": {"code": "unknown_operation", "message": "unknown operation"}}
        if operation in IDEMPOTENT_OPERATIONS and request_id:
            if len(request_id) > 128 or any(ord(char) < 0x20 for char in request_id):
                return {"ok": False, "error": {"code": "invalid_request_id", "message": "request_id is invalid"}}
            cached = self.store.get_idempotent_response(request_id, operation)
            if cached is not None:
                return cached
        try:
            result = self._dispatch(operation, body)
            with self._lock:
                self._last_operation = operation
                self._last_error = ""
                self._write_snapshot()
            response = {"ok": True, "data": result}
            if operation in IDEMPOTENT_OPERATIONS and request_id:
                self.store.save_idempotent_response(request_id, operation, response)
            return response
        except Exception as exc:  # API boundary: never expose internal traceback.
            with self._lock:
                self._last_operation = operation
                self._last_error = f"{type(exc).__name__}: {str(exc)[:240]}"
                self._write_snapshot()
            return {"ok": False, "error": {"code": "operation_failed", "message": str(exc)[:500]}}

    def _dispatch(self, operation: str, body: dict[str, Any]) -> dict[str, Any]:
        if operation == "protocol.describe":
            return {"protocol_version": 1, "operations": list(OPERATIONS), "max_frame_bytes": self.config.frame_limit_bytes}
        if operation in {"health.get", "status.get", "report.get"}:
            return self._status()
        if operation == "config.get":
            return public_config(self.config)
        if operation == "config.validate":
            candidate = Path(str(body.get("path") or self.config.config_path)).expanduser()
            checked = load_config(candidate)
            return {"ok": True, "config": public_config(checked)}
        if operation == "config.apply":
            values = body.get("values")
            if not isinstance(values, dict):
                return {"ok": False, "error": "values_must_be_object"}
            expected_revision = str(body.get("expected_revision") or "").strip()
            if expected_revision and expected_revision != config_revision(self.config):
                return {"ok": False, "error": "config_revision_changed", "config_revision": config_revision(self.config)}
            new_config = apply_safe_values(self.config, values)
            write_config(new_config)
            self.config = load_config(new_config.config_path)
            return {"ok": True, "config": public_config(self.config), "restart_required": False}
        if operation == "history.append":
            return self.store.append(body, idempotency_key=str(body.get("idempotency_key") or ""))
        if operation == "history.query":
            return {"items": self.store.query(status=str(body.get("status") or ""), limit=int(body.get("limit", 20)), include_payload=bool(body.get("include_payload", False)))}
        if operation == "dispatch.claim":
            if not self.config.dispatch_enabled:
                return {"items": [], "blocked": True, "reason": "dispatch_disabled"}
            if self.config.dispatch_paused:
                return {"items": [], "blocked": True, "reason": "dispatch_paused"}
            return {"items": self.store.claim(worker_id=str(body.get("worker_id") or ""), limit=int(body.get("limit", self.config.dispatch_batch_size)), claim_ttl_seconds=self.config.claim_ttl_seconds)}
        if operation == "dispatch.complete":
            attempt_count = self.store.attempt_count(str(body.get("item_id") or ""))
            retry_index = min(attempt_count, len(self.config.retry_delays_seconds) - 1)
            recipient_results = body.get("recipient_results", [])
            if not isinstance(recipient_results, list):
                return {"ok": False, "error": "recipient_results_must_be_array"}
            return self.store.complete(
                item_id=str(body.get("item_id") or ""),
                worker_id=str(body.get("worker_id") or ""),
                recipient_results=recipient_results,
                reason=str(body.get("reason") or ""),
                retry_delay_seconds=self.config.retry_delays_seconds[retry_index],
                max_attempts=self.config.max_attempts,
            )
        if operation == "dispatch.retry":
            return self.store.retry(str(body.get("item_id") or ""), reason=str(body.get("reason") or ""))
        if operation == "delivery.record":
            result = self.store.record_delivery(body)
            self._last_delivery = {"at": _timestamp(), "ok": bool(result.get("ok")), "event_id": str(result.get("event_id") or "")}
            return result
        if operation == "collector.collect":
            from .collector import Collector
            result = Collector(self.config, self.store).collect_once().as_dict()
            self._last_collection = {"at": _timestamp(), **result}
            return result
        if operation == "migration.import_legacy":
            from .migration import migrate_legacy_jsonl
            path = Path(str(body.get("path") or "")).expanduser()
            return migrate_legacy_jsonl(path, self.store, dry_run=bool(body.get("dry_run")))
        if operation == "maintenance.prune":
            return self.store.prune(completed_days=self.config.completed_retention_days, audit_days=self.config.audit_retention_days)
        if operation == "admin.preview":
            ids = body.get("ids", [])
            if not isinstance(ids, list):
                ids = []
            preview = self.store.preview_delete(
                status=str(body.get("status") or ""),
                limit=int(body.get("limit", 100)),
                ids=[str(item) for item in ids],
            )
            token = secrets.token_urlsafe(24)
            self._tokens[token] = (preview["ids"], str(preview["revision"]), time.monotonic() + 30)
            preview["confirmation_token"] = token
            preview["expires_in_seconds"] = 30
            return preview
        if operation == "admin.execute":
            token = str(body.get("confirmation_token") or "")
            entry = self._tokens.pop(token, None)
            if entry is None or entry[2] < time.monotonic():
                return {"ok": False, "error": "confirmation_token_invalid_or_expired"}
            ids, revision, _ = entry
            return self.store.execute_delete(ids=ids, confirmation=str(body.get("confirmation") or ""), revision=revision, reason=str(body.get("reason") or ""))
        if operation == "audit.query":
            return {"items": self._audit_query(limit=int(body.get("limit", 50)))}
        raise AssertionError(operation)

    def _audit_query(self, *, limit: int) -> list[dict[str, Any]]:
        with self.store._lock, self.store._connect() as db:
            rows = db.execute("SELECT event_id, operation, item_id, details_json, created_at FROM admin_audit_events ORDER BY created_at DESC LIMIT ?", (max(1, min(limit, 100)),)).fetchall()
        return [dict(row) for row in rows]


class _ThreadingUnixServer(socketserver.ThreadingMixIn, socketserver.UnixStreamServer):
    daemon_threads = True
    allow_reuse_address = True


class _Handler(socketserver.StreamRequestHandler):
    def handle(self) -> None:
        server = self.server
        assert isinstance(server, _ThreadingUnixServer)
        service: DispatcherService = server.dispatcher_service  # type: ignore[attr-defined]
        if not _same_user(self.connection):
            return
        self.connection.settimeout(30)
        while True:
            try:
                request = __import__("history_dispatcher.protocol", fromlist=["read_message"]).read_message(self.connection, max_bytes=service.config.frame_limit_bytes)
                if request is None:
                    return
                response = service.handle(request)
                self.connection.sendall(encode_message(response, max_bytes=service.config.frame_limit_bytes))
            except (OSError, ProtocolError):
                return


def _same_user(connection: socket.socket) -> bool:
    try:
        raw = connection.getsockopt(socket.SOL_SOCKET, socket.SO_PEERCRED, struct.calcsize("3i"))
        _pid, uid, _gid = struct.unpack("3i", raw)
        return uid == os.getuid()
    except (OSError, struct.error):
        return False


class ControlServer:
    def __init__(self, service: DispatcherService) -> None:
        self.service = service
        self.path = service.config.socket_path
        self.server: _ThreadingUnixServer | None = None

    def start(self) -> None:
        self.path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        if self.path.exists():
            if not self.path.is_socket():
                raise RuntimeError(f"refusing to replace non-socket path: {self.path}")
            self.path.unlink()
        self.server = _ThreadingUnixServer(str(self.path), _Handler)
        self.server.dispatcher_service = self.service  # type: ignore[attr-defined]
        os.chmod(self.path, 0o600)
        self.server.serve_forever(poll_interval=0.25)

    def shutdown(self) -> None:
        if self.server is not None:
            self.server.shutdown()
            self.server.server_close()
            self.server = None
        try:
            self.path.unlink()
        except FileNotFoundError:
            pass


def serve(config: DispatcherConfig) -> None:
    service = DispatcherService(config)
    control = ControlServer(service)
    try:
        control.start()
    finally:
        control.shutdown()


def call_socket(path: Path, request: dict[str, Any], *, max_bytes: int = 8 * 1024 * 1024) -> dict[str, Any]:
    from .protocol import encode_message, read_message
    with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as connection:
        connection.settimeout(10)
        connection.connect(str(path))
        connection.sendall(encode_message(request, max_bytes=max_bytes))
        response = read_message(connection, max_bytes=max_bytes)
    if not isinstance(response, dict):
        raise ProtocolError("missing response")
    return response
