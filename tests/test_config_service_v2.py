from __future__ import annotations

import json
import sqlite3
import threading
import time
from dataclasses import replace
from pathlib import Path

from history_dispatcher.config import (
    config_revision,
    default_config,
    load_config,
    write_config,
)
from history_dispatcher.crypto import StaticKeyProvider
from history_dispatcher.migrations import DatabaseV2Migrator, DatabaseV3Migrator
from history_dispatcher.service import ControlServer, DispatcherService, call_socket
from history_dispatcher.store import DispatcherStore


def _native_patch() -> dict[str, object]:
    return {
        "routing": {
            "telegram": {
                "provider": "history_dispatcher",
                "credential_ref": "telegram_primary",
                "recipient_refs": ["status_admin_primary", "ops_admin"],
            }
        }
    }


def _request(
    operation: str,
    body: dict[str, object],
    *,
    request_id: str = "",
) -> dict[str, object]:
    return {
        "protocol_version": 1,
        "request_id": request_id,
        "operation": operation,
        "body": body,
    }


def _service(tmp_path: Path) -> DispatcherService:
    provider = StaticKeyProvider(b"k" * 32)
    config_path = tmp_path / "config.toml"
    state_dir = tmp_path / "state"
    runtime_dir = tmp_path / "runtime"
    database = state_dir / "history.sqlite3"
    config = replace(
        default_config(config_path),
        state_dir=state_dir,
        runtime_dir=runtime_dir,
        database_path=database,
        socket_path=runtime_dir / "control.sock",
    )
    write_config(config)
    DispatcherStore(database, provider)
    DatabaseV2Migrator(
        database,
        provider,
        backup_dir=tmp_path / "backups-v2",
        minimum_free_bytes=0,
    ).migrate()
    DatabaseV3Migrator(
        database,
        provider,
        backup_dir=tmp_path / "backups-v3",
    ).migrate()
    return DispatcherService(load_config(config_path), key_provider=provider)


def test_config_v2_service_validate_preview_apply_and_idempotent_replay(
    tmp_path: Path,
) -> None:
    service = _service(tmp_path)
    patch = _native_patch()

    redacted = service.handle(_request("config.get_redacted", {}))
    assert redacted["ok"] is True
    revision = redacted["data"]["config_revision"]
    assert redacted["data"]["routing"]["telegram"] == {
        "provider": "teebotus",
        "credential_ref": "",
        "recipient_refs": [],
    }

    validated = service.handle(
        _request(
            "config.validate_patch",
            {"patch": patch},
            request_id="config-v2-validate",
        )
    )
    assert validated == {
        "ok": True,
        "data": {
            "schema_version": 2,
            "patch": patch,
        },
    }

    preview_response = service.handle(
        _request(
            "config.preview_apply",
            {"expected_revision": revision, "patch": patch},
            request_id="config-v2-preview",
        )
    )
    assert preview_response["ok"] is True
    preview = preview_response["data"]
    assert preview["schema_version"] == 2
    assert preview["effect"] == "new_route_plans_only"
    assert preview["confirmation"] == f"APPLY {preview['fingerprint'][:12]}"
    assert len(preview["preview_token"]) >= 32

    apply_body = {
        "expected_revision": revision,
        "preview_token": preview["preview_token"],
        "fingerprint": preview["fingerprint"],
        "confirmation": preview["confirmation"],
    }
    apply_request = _request(
        "config.apply",
        apply_body,
        request_id="config-v2-apply",
    )
    applied = service.handle(apply_request)
    replayed = service.handle(apply_request)

    assert applied == replayed
    assert applied["ok"] is True
    assert applied["data"]["effect"] == "new_route_plans_only"
    assert applied["data"]["routing"]["telegram"] == {
        "provider": "history_dispatcher",
        "credential_ref": "telegram_primary",
        "recipient_refs": ["status_admin_primary", "ops_admin"],
    }
    reloaded = load_config(service.config.config_path)
    assert config_revision(reloaded) == applied["data"]["config_revision"]
    assert reloaded.telegram_provider.value == "history_dispatcher"

    replay_with_new_request_id = service.handle(
        _request(
            "config.apply",
            apply_body,
            request_id="config-v2-apply-replay-new-id",
        )
    )
    assert replay_with_new_request_id["ok"] is False
    assert replay_with_new_request_id["error"]["code"] == "operation_failed"
    assert "preview token" in replay_with_new_request_id["error"]["message"]

    status = service.handle(_request("status.get_redacted", {}))
    assert status["data"]["status"]["telegram"]["provider"] == "history_dispatcher"
    snapshot = (service.config.runtime_dir / "status-v2.json").read_text(
        encoding="utf-8"
    )
    for forbidden in (
        "preview_token",
        "bot_token",
        "chat_id",
        "123456789:",
    ):
        assert forbidden not in snapshot


def test_config_v2_mutations_require_request_id_and_preview_token_is_not_cached(
    tmp_path: Path,
) -> None:
    service = _service(tmp_path)
    patch = _native_patch()
    revision = config_revision(service.config)

    for operation, body in (
        ("config.validate_patch", {"patch": patch}),
        (
            "config.preview_apply",
            {"expected_revision": revision, "patch": patch},
        ),
        (
            "config.apply",
            {
                "expected_revision": revision,
                "preview_token": "preview_" + "x" * 32,
                "fingerprint": "0" * 64,
                "confirmation": "APPLY 000000000000",
            },
        ),
    ):
        response = service.handle(_request(operation, body))
        assert response["ok"] is False
        assert response["error"]["code"] == "invalid_request_id"

    preview_request = _request(
        "config.preview_apply",
        {"expected_revision": revision, "patch": patch},
        request_id="config-v2-preview-one-shot",
    )
    first = service.handle(preview_request)
    second = service.handle(preview_request)

    assert first["ok"] is True
    assert second["ok"] is False
    assert second["error"]["code"] == "idempotency_in_progress"
    token = first["data"]["preview_token"]
    with sqlite3.connect(service.config.database_path) as db:
        response_json = db.execute(
            "SELECT response_json FROM idempotency_results WHERE request_id=?",
            ("config-v2-preview-one-shot",),
        ).fetchone()[0]
    assert response_json == ""
    assert token.encode("utf-8") not in service.config.database_path.read_bytes()


def test_config_v2_flow_is_available_through_same_user_unix_socket(
    tmp_path: Path,
) -> None:
    service = _service(tmp_path)
    control = ControlServer(service)
    thread = threading.Thread(target=control.start, daemon=True)
    thread.start()
    try:
        for _ in range(200):
            if service.config.socket_path.exists():
                break
            time.sleep(0.01)
        redacted = call_socket(
            service.config.socket_path,
            _request("config.get_redacted", {}),
        )
        revision = redacted["data"]["config_revision"]
        preview = call_socket(
            service.config.socket_path,
            _request(
                "config.preview_apply",
                {"expected_revision": revision, "patch": _native_patch()},
                request_id="socket-config-v2-preview",
            ),
        )["data"]
        applied = call_socket(
            service.config.socket_path,
            _request(
                "config.apply",
                {
                    "expected_revision": revision,
                    "preview_token": preview["preview_token"],
                    "fingerprint": preview["fingerprint"],
                    "confirmation": preview["confirmation"],
                },
                request_id="socket-config-v2-apply",
            ),
        )
        assert applied["ok"] is True
        assert applied["data"]["routing"]["telegram"]["provider"] == (
            "history_dispatcher"
        )
    finally:
        control.shutdown()
        thread.join(timeout=2)


def test_legacy_config_operations_remain_backward_compatible(tmp_path: Path) -> None:
    service = _service(tmp_path)

    legacy_get = service.handle(_request("config.get", {}))
    legacy_validate = service.handle(
        _request(
            "config.validate",
            {"path": str(service.config.config_path)},
        )
    )
    legacy_apply = service.handle(
        _request(
            "config.apply",
            {
                "expected_revision": config_revision(service.config),
                "values": {"log_level": "WARNING"},
            },
            request_id="legacy-config-apply",
        )
    )

    assert legacy_get["ok"] is True
    assert legacy_validate["ok"] is True
    assert legacy_apply["ok"] is True
    assert legacy_apply["data"]["config"]["log_level"] == "WARNING"
    assert load_config(service.config.config_path).log_level == "WARNING"
