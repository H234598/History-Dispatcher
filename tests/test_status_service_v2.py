from __future__ import annotations

import json
import os
import stat
import threading
import time
from pathlib import Path

from history_dispatcher.config import load_config
from history_dispatcher.crypto import StaticKeyProvider
from history_dispatcher.service import (
    OPERATIONS,
    ControlServer,
    DispatcherService,
    call_socket,
)


def _service(tmp_path: Path) -> DispatcherService:
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


def test_service_exposes_additive_redacted_status_without_changing_v1(
    tmp_path: Path,
) -> None:
    service = _service(tmp_path)

    v1 = service.handle(
        {
            "protocol_version": 1,
            "request_id": "status-v1",
            "operation": "status.get",
            "body": {},
        }
    )
    v2 = service.handle(
        {
            "protocol_version": 1,
            "request_id": "status-v2",
            "operation": "status.get_redacted",
            "body": {},
        }
    )

    assert "status.get_redacted" in OPERATIONS
    assert v1["ok"] is True
    assert v1["data"]["schema_version"] == 1
    assert v2["ok"] is True
    assert v2["data"]["version"] == 2
    assert v2["data"]["status"]["schema_version"] == 2
    assert v2["data"]["status"]["telegram"] == {
        "provider": "teebotus",
        "credential": {"configured": False, "last_changed": None},
    }


def test_redacted_status_is_available_through_the_same_user_unix_socket(
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
        response = call_socket(
            service.config.socket_path,
            {
                "protocol_version": 1,
                "request_id": "status-v2-socket",
                "operation": "status.get_redacted",
                "body": {},
            },
        )
        assert response["ok"] is True
        assert response["data"]["version"] == 2
        assert response["data"]["status"]["telegram"]["provider"] == "teebotus"
    finally:
        control.shutdown()
        thread.join(timeout=2)


def test_service_writes_separate_private_v1_and_v2_snapshots(tmp_path: Path) -> None:
    service = _service(tmp_path)
    v1_path = service.config.snapshot_path
    v2_path = service.config.runtime_dir / "status-v2.json"

    assert v1_path.is_file()
    assert v2_path.is_file()
    v1_raw = v1_path.read_bytes()
    v2_raw = v2_path.read_bytes()
    assert len(v1_raw) <= 64 * 1024
    assert len(v2_raw) <= 64 * 1024
    assert stat.S_IMODE(v1_path.stat().st_mode) == 0o600
    assert stat.S_IMODE(v2_path.stat().st_mode) == 0o600
    assert json.loads(v1_raw.decode("utf-8"))["schema_version"] == 1
    assert json.loads(v2_raw.decode("utf-8"))["version"] == 2
    assert b"encrypted_payload" not in v2_raw
    assert b"recipient_ref" not in v2_raw
    assert b"bot_token" not in v2_raw


def test_v1_snapshot_remains_the_last_service_replace_for_compatibility(
    tmp_path: Path,
    monkeypatch,
) -> None:
    service = _service(tmp_path)
    replacements: list[Path] = []
    real_replace = os.replace

    def service_replace(source, target) -> None:
        replacements.append(Path(target))
        real_replace(source, target)

    def v2_replace(source, target) -> None:
        replacements.append(Path(target))
        real_replace(source, target)

    monkeypatch.setattr("history_dispatcher.service.os.replace", service_replace)
    monkeypatch.setattr(
        "history_dispatcher.status_snapshot_v2.os.replace",
        v2_replace,
    )

    service._write_snapshot()

    assert replacements == [
        service.config.runtime_dir / "status-v2.json",
        service.config.snapshot_path,
    ]
