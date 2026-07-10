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
from .config import DispatcherConfig, apply_safe_values, load_config, public_config, write_config
from .crypto import SecretServiceKeyProvider
from .protocol import ProtocolError, encode_message, read_message
from .store import DispatcherStore


OPERATIONS = (
    "protocol.describe", "health.get", "status.get", "report.get",
    "history.append", "history.query",
    "dispatch.claim", "dispatch.complete", "dispatch.retry",
   "delivery.record", "config.get", "config.validate", "config.apply",
    "collector.collect", "admin.preview", "admin.execute", "audit.query",
)


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
        self._tokens: dict[str, tuple[list[str], int, float]] = {}
        self._write_snapshot()

    def _status(self) -> dict[str, Any]:
        status = self.store.status()
        status.update({
            "schema_version": 1,
            "service": "history-dispatcher",
            "version": __version__,
            "ok": True,
            "generated_at": _timestamp(),
            "started_at": self._started_at,
            "last_operation": self._last_operation,
            "last_error": self._last_error,
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
        body = request.get("body") if isinstance(request.get("body"), dict) else {}
        if int(request.get("protocol_version", 0) or 0) != 1:
            return {"ok": False, "error": {"code": "unsupported_protocol", "message": "protocol_version must be 1"}}
        if operation not in OPERATIONS:
            return {"ok": False, "error": {"code": "unknown_operation", "message": "unknown operation"}}
        try:
            result = self._dispatch(operation, body)
            with self._lock:
                self._last_operation = operation
                self._last_error = ""
                self._write_snapshot()
            return {"ok": True, "data": result}
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
            new_config = apply_safe_values(self.config, values)
            write_config(new_config)
            self.config = load_config(new_config.config_path)
            return {"ok": True, "config": public_config(self.config), "restart_required": False}
        if operation == "history.append":
            return self.store.append(body, idempotency_key=str(body.get("idempotency_key") or ""))
        if operation == "history.query":
            return {"items": self.store.query(status=str(body.get("status") or ""), limit=int(body.get("limit", 20)), include_payload=bool(body.get("include_payload", False)))}
        if operation == "dispatch.claim":
            return {"items": self.store.claim(worker_id=str(body.get("worker_id") or ""), limit=int(body.get("limit", self.config.dispatch_batch_size)), claim_ttl_seconds=self.config.claim_ttl_seconds)}
        if operation == "dispatch.complete":
            return self.store.complete(item_id=str(body.get("item_id") or ""), worker_id=str(body.get("worker_id") or ""), recipient_results=body.get("recipient_results", []), reason=str(body.get("reason") or ""))
        if operation == "dispatch.retry":
            return self.store.retry(str(body.get("item_id") or ""), reason=str(body.get("reason") or ""))
        if operation == "delivery.record":
            return self.store.record_delivery(body)
        if operation == "collector.collect":
            from .collector import Collector
            return Collector(self.config, self.store).collect_once().as_dict()
        if operation == "admin.preview":
            preview = self.store.preview_delete(status=str(body.get("status") or ""), limit=int(body.get("limit", 100)))
            token = secrets.token_urlsafe(24)
            self._tokens[token] = (preview["ids"], int(preview["revision"]), time.monotonic() + 30)
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
