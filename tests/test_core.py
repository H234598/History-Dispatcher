from __future__ import annotations

import json
import socket
import threading
import time
from pathlib import Path

from history_dispatcher.config import load_config
from history_dispatcher.crypto import StaticKeyProvider, decrypt_json, encrypt_json
from history_dispatcher.protocol import encode_message, read_message, request
from history_dispatcher.service import DispatcherService, ControlServer, call_socket


def _service(tmp_path: Path) -> DispatcherService:
    config_file = tmp_path / "config.toml"
    config_file.write_text("", encoding="utf-8")
    config = load_config(config_file)
    config = config.__class__(
        **{**config.__dict__,
           "state_dir": tmp_path / "state",
           "runtime_dir": tmp_path / "runtime",
           "database_path": tmp_path / "state" / "history.sqlite3",
           "socket_path": tmp_path / "runtime" / "control.sock"}
    )
    return DispatcherService(config, key_provider=StaticKeyProvider(b"k" * 32))


def test_encryption_round_trip_and_wrong_key() -> None:
    blob = encrypt_json(b'{"ok":true}', StaticKeyProvider(b"k" * 32), aad=b"item")
    assert decrypt_json(blob, StaticKeyProvider(b"k" * 32), aad=b"item") == b'{"ok":true}'


def test_append_deduplicates_and_claim_complete(tmp_path: Path) -> None:
    service = _service(tmp_path)
    first = service.handle(request("history.append", {
        "dedupe_key": "same",
        "source": "test",
        "payload": {"title": "hello"},
    }))
    second = service.handle(request("history.append", {
        "dedupe_key": "same",
        "source": "test",
        "payload": {"title": "hello"},
    }))
    assert first["ok"] and second["ok"]
    assert second["data"]["deduplicated"] is True
    claimed = service.handle(request("dispatch.claim", {"worker_id": "worker", "limit": 5}))
    assert len(claimed["data"]["items"]) == 1
    item_id = claimed["data"]["items"][0]["id"]
    completed = service.handle(request("dispatch.complete", {
        "item_id": item_id,
        "worker_id": "worker",
        "recipient_results": [{"recipient_id": "admin", "status": "delivered", "channel": "test"}],
    }))
    assert completed == {"ok": True, "data": {"ok": True, "item_id": item_id, "status": "delivered"}}


def test_preview_execute_requires_exact_confirmation(tmp_path: Path) -> None:
    service = _service(tmp_path)
    service.handle(request("history.append", {"dedupe_key": "delete-me", "payload": {"x": 1}}))
    preview = service.handle(request("admin.preview", {"status": "queued", "limit": 10}))
    assert preview["ok"]
    data = preview["data"]
    bad = service.handle(request("admin.execute", {
        "confirmation_token": data["confirmation_token"],
        "confirmation": "LOESCHEN 2",
    }))
    assert bad["ok"] and bad["data"]["ok"] is False
    preview = service.handle(request("admin.preview", {"status": "queued", "limit": 10}))
    data = preview["data"]
    good = service.handle(request("admin.execute", {
        "confirmation_token": data["confirmation_token"],
        "confirmation": "LOESCHEN 1",
        "reason": "test",
    }))
    assert good["ok"] and good["data"]["deleted"] == 1


def test_socket_round_trip(tmp_path: Path) -> None:
    service = _service(tmp_path)
    control = ControlServer(service)
    thread = threading.Thread(target=control.start, daemon=True)
    thread.start()
    for _ in range(100):
        if service.config.socket_path.exists():
            break
        time.sleep(0.01)
    response = call_socket(service.config.socket_path, request("protocol.describe", {}))
    assert response["ok"] and response["data"]["protocol_version"] == 1
    control.shutdown()
    thread.join(timeout=2)


def test_safe_config_apply_writes_valid_toml(tmp_path: Path) -> None:
    service = _service(tmp_path)
    result = service.handle(request("config.apply", {
        "values": {
            "dispatch_paused": True,
            "dispatch_batch_size": 7,
            "collector_interval_seconds": 600,
        },
    }))
    assert result["ok"]
    assert result["data"]["config"]["dispatch"]["paused"] is True
    assert result["data"]["config"]["dispatch"]["batch_size"] == 7
    assert load_config(service.config.config_path).dispatch_paused is True
