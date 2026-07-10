from __future__ import annotations

import json
import socket
import threading
import time
from pathlib import Path

from history_dispatcher.config import config_revision, load_config
from history_dispatcher.crypto import StaticKeyProvider, decrypt_json, encrypt_json
from history_dispatcher.migration import migrate_legacy_jsonl
from history_dispatcher.protocol import encode_message, read_message, request
from history_dispatcher.service import DispatcherService, ControlServer, call_socket


def _service(tmp_path: Path) -> DispatcherService:
    tmp_path.mkdir(parents=True, exist_ok=True)
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


def test_mutating_request_id_is_replayed_idempotently(tmp_path: Path) -> None:
    service = _service(tmp_path)
    message = request("history.append", {"dedupe_key": "request-1", "payload": {"x": 1}})
    message["request_id"] = "stable-request"
    first = service.handle(message)
    second = service.handle(message)
    assert first == second
    assert service.store.status()["total"] == 1


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


def test_failed_completion_is_requeued_for_automatic_retry(tmp_path: Path) -> None:
    service = _service(tmp_path)
    created = service.handle(request("history.append", {"dedupe_key": "retry-me", "payload": {"x": 1}}))
    item_id = created["data"]["id"]
    claimed = service.handle(request("dispatch.claim", {"worker_id": "worker", "limit": 1}))
    assert claimed["data"]["items"][0]["id"] == item_id
    completed = service.handle(request("dispatch.complete", {
        "item_id": item_id,
        "worker_id": "worker",
        "reason": "temporary",
        "recipient_results": [{"recipient_id": "admin", "status": "failed", "reason": "temporary"}],
    }))
    assert completed["data"]["status"] == "queued"
    assert service.store.status()["queued"] == 1


def test_config_rejects_unknown_keys_and_uses_optimistic_revision(tmp_path: Path) -> None:
    config_file = tmp_path / "config.toml"
    config_file.write_text("[dispatch]\nnot_allowed = true\n", encoding="utf-8")
    try:
        load_config(config_file)
    except ValueError as exc:
        assert "unknown config keys" in str(exc)
    else:
        raise AssertionError("unknown config key was accepted")
    service = _service(tmp_path / "revision")
    revision = config_revision(service.config)
    changed = service.handle(request("config.apply", {"expected_revision": "stale", "values": {"dispatch_paused": True}}))
    assert changed["ok"] and changed["data"]["error"] == "config_revision_changed"
    applied = service.handle(request("config.apply", {"expected_revision": revision, "values": {"dispatch_paused": True}}))
    assert applied["ok"] and applied["data"]["config"]["dispatch"]["paused"] is True
    assert service.config.config_path.with_name("config.toml.bak").is_file()


def test_legacy_jsonl_migration_streams_encrypted_rows_and_digest(tmp_path: Path) -> None:
    legacy = tmp_path / "legacy.jsonl"
    legacy.write_text(
        "\n".join([
            json.dumps({"id": "legacy-1", "kind": "codex_run_summary", "status": "queued", "summary": {"text": "one"}}),
            json.dumps({"id": "legacy-2", "kind": "codex_run_summary", "status": "accepted", "summary": {"text": "two"}}),
        ]) + "\n",
        encoding="utf-8",
    )
    service = _service(tmp_path / "migration")
    report = migrate_legacy_jsonl(legacy, service.store)
    assert report["imported"] == 2
    assert report["source_digest"]
    rows = service.store.query(limit=10, include_payload=True)
    assert {row["id"] for row in rows} == {"legacy-1", "legacy-2"}
    assert {row["status"] for row in rows} == {"queued", "delivered"}


def test_append_preserves_migrated_recipient_results(tmp_path: Path) -> None:
    service = _service(tmp_path)
    result = service.store.append({
        "id": "with-recipient",
        "payload": {"x": 1},
        "status": "delivered",
        "recipient_results": [{"recipient_id": "admin", "status": "accepted", "channel": "telegram"}],
    })
    assert result["ok"] is True
    assert service.store.recipient_results_for("with-recipient")[0]["recipient_id"] == "admin"
    assert service.store.query(limit=1, include_payload=False)[0]["status"] == "delivered"
