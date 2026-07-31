from __future__ import annotations

import json
import sqlite3
import threading
import time
from dataclasses import replace
from pathlib import Path

from history_dispatcher.config import default_config, write_config
from history_dispatcher.crypto import StaticKeyProvider
from history_dispatcher.migrations import (
    DatabaseV2Migrator,
    DatabaseV3Migrator,
    DatabaseV4Migrator,
)
from history_dispatcher.service import ControlServer, DispatcherService, call_socket
from history_dispatcher.store import DispatcherStore
from history_dispatcher.telegram_provider import TelegramDispatchProvider
from history_dispatcher.telegram_secrets import NativeTelegramSecretStore


class MemoryBackend:
    def __init__(self) -> None:
        self.values: dict[tuple[str, str], str] = {}
        self.mutations = 0

    def lookup(self, kind, profile_ref):
        return self.values.get((kind.value, profile_ref))

    def store(self, kind, profile_ref, value):
        self.mutations += 1
        self.values[(kind.value, profile_ref)] = value

    def clear(self, kind, profile_ref):
        self.mutations += 1
        return self.values.pop((kind.value, profile_ref), None) is not None


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


def _service(tmp_path: Path) -> tuple[DispatcherService, MemoryBackend]:
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
        telegram_provider=TelegramDispatchProvider.HISTORY_DISPATCHER,
        telegram_credential_ref="telegram_primary",
        telegram_recipient_refs=("status_admin_primary",),
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
    DatabaseV4Migrator(
        database,
        provider,
        backup_dir=tmp_path / "backups-v4",
    ).migrate()
    backend = MemoryBackend()
    service = DispatcherService(
        config,
        key_provider=provider,
        telegram_secret_store=NativeTelegramSecretStore(backend=backend),
    )
    return service, backend


def test_credential_service_preview_apply_status_and_durable_replay(
    tmp_path: Path,
) -> None:
    service, backend = _service(tmp_path)
    secret = "123456789:ABCDEFGHIJKLMNOPQRSTUVWXYZabcdef"

    initial = service.handle(_request("credential.get_status", {}))
    assert initial["ok"] is True
    assert initial["data"]["bot"] == {
        "profile_ref": "telegram_primary",
        "configured": False,
        "last_changed": None,
    }

    preview_request = _request(
        "credential.preview_apply",
        {
            "action": "set",
            "secret_kind": "bot_token",
            "profile_ref": "telegram_primary",
            "secret_value": secret,
        },
        request_id="credential-preview-set-bot",
    )
    preview_response = service.handle(preview_request)
    preview_replay = service.handle(preview_request)
    assert preview_response["ok"] is True
    preview = preview_response["data"]
    assert secret not in json.dumps(preview_response, sort_keys=True)
    assert preview_replay["ok"] is False
    assert preview_replay["error"]["code"] == "idempotency_in_progress"

    apply_body = {
        "preview_token": preview["preview_token"],
        "fingerprint": preview["fingerprint"],
        "confirmation": preview["confirmation"],
    }
    apply_request = _request(
        "credential.apply",
        apply_body,
        request_id="credential-apply-set-bot",
    )
    applied = service.handle(apply_request)
    replayed = service.handle(apply_request)

    assert applied == replayed
    assert applied["ok"] is True
    assert applied["data"]["configured"] is True
    assert backend.mutations == 1
    assert backend.values[("bot_token", "telegram_primary")] == secret

    status = service.handle(_request("credential.get_status", {}))
    assert status["data"]["bot"]["configured"] is True
    public_status = service.handle(_request("status.get_redacted", {}))
    assert public_status["data"]["status"]["telegram"]["credential"] == {
        "configured": True,
        "last_changed": applied["data"]["last_changed"],
    }

    snapshot = (service.config.runtime_dir / "status-v2.json").read_bytes()
    database = service.config.database_path.read_bytes()
    config = service.config.config_path.read_bytes()
    for forbidden in (secret.encode(), b"123456789:", b"ABCDEFGHIJKLMNOPQRSTUVWXYZ"):
        assert forbidden not in snapshot
        assert forbidden not in database
        assert forbidden not in config


def test_credential_preview_validation_failure_releases_exact_reservation(
    tmp_path: Path,
) -> None:
    service, backend = _service(tmp_path)
    request_id = "credential-preview-validation-retry"

    invalid = service.handle(
        _request(
            "credential.preview_apply",
            {
                "action": "set",
                "secret_kind": "bot_token",
                "profile_ref": "telegram_primary",
                "secret_value": "invalid",
            },
            request_id=request_id,
        )
    )
    corrected = service.handle(
        _request(
            "credential.preview_apply",
            {
                "action": "set",
                "secret_kind": "bot_token",
                "profile_ref": "telegram_primary",
                "secret_value": "123456789:ABCDEFGHIJKLMNOPQRSTUVWXYZabcdef",
            },
            request_id=request_id,
        )
    )

    assert invalid["ok"] is False
    assert corrected["ok"] is True
    assert backend.mutations == 0


def test_credential_mutations_require_request_id_and_token_is_not_cached(
    tmp_path: Path,
) -> None:
    service, _backend = _service(tmp_path)
    secret = "123456789:ABCDEFGHIJKLMNOPQRSTUVWXYZabcdef"

    preview = service.handle(
        _request(
            "credential.preview_apply",
            {
                "action": "set",
                "secret_kind": "bot_token",
                "profile_ref": "telegram_primary",
                "secret_value": secret,
            },
        )
    )
    apply = service.handle(
        _request(
            "credential.apply",
            {
                "preview_token": "preview_" + "x" * 32,
                "fingerprint": "0" * 64,
                "confirmation": "CREDENTIAL SET 000000000000",
            },
        )
    )

    assert preview["error"]["code"] == "invalid_request_id"
    assert apply["error"]["code"] == "invalid_request_id"

    valid_preview = service.handle(
        _request(
            "credential.preview_apply",
            {
                "action": "set",
                "secret_kind": "bot_token",
                "profile_ref": "telegram_primary",
                "secret_value": secret,
            },
            request_id="credential-preview-not-cached",
        )
    )
    token = valid_preview["data"]["preview_token"]
    with sqlite3.connect(service.config.database_path) as db:
        response_json = db.execute(
            "SELECT response_json FROM idempotency_results WHERE request_id=?",
            ("credential-preview-not-cached",),
        ).fetchone()[0]
    assert response_json == ""
    assert token.encode("utf-8") not in service.config.database_path.read_bytes()


def test_credential_flow_is_available_through_same_user_unix_socket(
    tmp_path: Path,
) -> None:
    service, _backend = _service(tmp_path)
    control = ControlServer(service)
    thread = threading.Thread(target=control.start, daemon=True)
    thread.start()
    try:
        for _ in range(200):
            if service.config.socket_path.exists():
                break
            time.sleep(0.01)
        status = call_socket(
            service.config.socket_path,
            _request("credential.get_status", {}),
        )
        preview = call_socket(
            service.config.socket_path,
            _request(
                "credential.preview_apply",
                {
                    "action": "set",
                    "secret_kind": "chat_id",
                    "profile_ref": "status_admin_primary",
                    "secret_value": "-1001234567890",
                },
                request_id="socket-credential-preview",
            ),
        )["data"]
        applied = call_socket(
            service.config.socket_path,
            _request(
                "credential.apply",
                {
                    "preview_token": preview["preview_token"],
                    "fingerprint": preview["fingerprint"],
                    "confirmation": preview["confirmation"],
                },
                request_id="socket-credential-apply",
            ),
        )

        assert status["ok"] is True
        assert applied["ok"] is True
        assert applied["data"]["secret_kind"] == "chat_id"
        assert "-1001234567890" not in json.dumps(applied, sort_keys=True)
    finally:
        control.shutdown()
        thread.join(timeout=2)
