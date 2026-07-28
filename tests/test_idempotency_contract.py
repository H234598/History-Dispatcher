from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path

from history_dispatcher.config import load_config
from history_dispatcher.crypto import StaticKeyProvider
from history_dispatcher.service import DispatcherService, _request_fingerprint


def _service(tmp_path: Path) -> DispatcherService:
    tmp_path.mkdir(parents=True, exist_ok=True)
    config_file = tmp_path / "config.toml"
    config_file.write_text("", encoding="utf-8")
    config = load_config(config_file)
    config = config.__class__(
        **{
            **config.__dict__,
            "state_dir": tmp_path / "state",
            "runtime_dir": tmp_path / "runtime",
            "database_path": tmp_path / "state" / "history.sqlite3",
            "socket_path": tmp_path / "runtime" / "control.sock",
        }
    )
    return DispatcherService(config, key_provider=StaticKeyProvider(b"k" * 32))


def _request(operation: str, body: object, request_id: str = "stable-id") -> dict[str, object]:
    return {
        "protocol_version": 1,
        "request_id": request_id,
        "operation": operation,
        "body": body,
    }


def test_non_object_request_bodies_are_rejected_without_mutation(tmp_path: Path) -> None:
    service = _service(tmp_path)

    for invalid_body in (None, [], "text", 1, True):
        response = service.handle(
            _request(
                "history.append",
                invalid_body,
                f"invalid-{type(invalid_body).__name__}",
            )
        )
        assert response == {
            "ok": False,
            "error": {"code": "invalid_request", "message": "body must be an object"},
        }

    assert service.store.status()["total"] == 0


def test_same_request_id_and_fingerprint_replays_the_durable_response(tmp_path: Path) -> None:
    service = _service(tmp_path)
    message = _request(
        "history.append",
        {"dedupe_key": "same", "payload": {"value": 1}},
    )

    first = service.handle(message)
    second = service.handle(message)

    assert first == second
    assert first["ok"] is True
    assert service.store.status()["total"] == 1


def test_same_request_id_with_different_body_is_a_conflict(tmp_path: Path) -> None:
    service = _service(tmp_path)
    first = service.handle(
        _request("history.append", {"dedupe_key": "first", "payload": {"value": 1}})
    )
    conflict = service.handle(
        _request("history.append", {"dedupe_key": "second", "payload": {"value": 2}})
    )

    assert first["ok"] is True
    assert conflict["ok"] is False
    assert conflict["error"]["code"] == "idempotency_conflict"
    assert service.store.status()["total"] == 1


def test_same_request_id_with_different_operation_is_a_conflict(tmp_path: Path) -> None:
    service = _service(tmp_path)
    first = service.handle(
        _request("history.append", {"dedupe_key": "first", "payload": {"value": 1}})
    )
    conflict = service.handle(
        _request("dispatch.retry", {"item_id": first["data"]["id"]})
    )

    assert conflict["ok"] is False
    assert conflict["error"]["code"] == "idempotency_conflict"


def test_reserved_request_without_response_is_not_blindly_reexecuted(tmp_path: Path) -> None:
    service = _service(tmp_path)
    body = {"dedupe_key": "pending", "payload": {"value": 1}}
    fingerprint = _request_fingerprint("history.append", body)
    assert service.idempotency.begin("pending-id", "history.append", fingerprint) is None

    response = service.handle(_request("history.append", body, "pending-id"))

    assert response["ok"] is False
    assert response["error"]["code"] == "idempotency_in_progress"
    assert service.store.status()["total"] == 0


def test_idempotency_records_follow_audit_retention(tmp_path: Path) -> None:
    service = _service(tmp_path)
    response = service.handle(
        _request(
            "history.append",
            {"dedupe_key": "retention", "payload": {"value": 1}},
            "retention-id",
        )
    )
    assert response["ok"] is True

    old = (
        datetime.now(timezone.utc)
        - timedelta(days=service.config.audit_retention_days + 1)
    ).isoformat(timespec="seconds")
    with service.store._connect() as db:
        db.execute(
            "UPDATE idempotency_results SET created_at=? WHERE request_id=?",
            (old, "retention-id"),
        )

    pruned = service.handle(
        {
            "protocol_version": 1,
            "operation": "maintenance.prune",
            "body": {},
        }
    )
    assert pruned["ok"] is True
    assert pruned["data"]["idempotency_deleted"] == 1


def test_legacy_unfingerprinted_cache_rows_are_discarded_without_touching_queue(
    tmp_path: Path,
) -> None:
    import sqlite3

    from history_dispatcher.idempotency import IdempotencyStore

    database = tmp_path / "legacy.sqlite3"
    with sqlite3.connect(database) as db:
        db.execute(
            "CREATE TABLE idempotency_results("
            "request_id TEXT PRIMARY KEY, operation TEXT NOT NULL, "
            "response_json TEXT NOT NULL, created_at TEXT NOT NULL)"
        )
        db.execute("CREATE TABLE queue_marker(id TEXT PRIMARY KEY)")
        db.execute("INSERT INTO queue_marker(id) VALUES ('preserve-me')")
        db.execute(
            "INSERT INTO idempotency_results(request_id, operation, response_json, created_at) "
            "VALUES ('legacy', 'history.append', '{\"ok\":true}', '2026-07-28T00:00:00+00:00')"
        )

    IdempotencyStore(database, client_scope="uid:test")

    with sqlite3.connect(database) as db:
        assert db.execute("SELECT COUNT(*) FROM idempotency_results").fetchone()[0] == 0
        assert db.execute("SELECT id FROM queue_marker").fetchone()[0] == "preserve-me"
        columns = {
            row[1] for row in db.execute("PRAGMA table_info(idempotency_results)")
        }
    assert {"request_fingerprint", "client_scope"} <= columns


def test_request_id_is_scoped_to_the_authenticated_local_user(tmp_path: Path) -> None:
    from history_dispatcher.idempotency import IdempotencyConflict, IdempotencyStore

    database = tmp_path / "scope.sqlite3"
    first = IdempotencyStore(database, client_scope="uid:1000")
    second = IdempotencyStore(database, client_scope="uid:1001")
    fingerprint = _request_fingerprint(
        "history.append",
        {"payload": {"value": 1}},
    )
    assert first.begin("same-id", "history.append", fingerprint) is None
    first.complete("same-id", "history.append", fingerprint, {"ok": True})

    try:
        second.begin("same-id", "history.append", fingerprint)
    except IdempotencyConflict:
        pass
    else:
        raise AssertionError(
            "request_id was replayed across authenticated client scopes"
        )
