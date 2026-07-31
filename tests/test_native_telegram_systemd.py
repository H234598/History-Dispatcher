from __future__ import annotations

from pathlib import Path

import pytest

from history_dispatcher import systemd
from history_dispatcher.systemd import render_units


def test_only_native_worker_unit_gains_internet_address_families(
    tmp_path: Path,
) -> None:
    units = render_units(
        python="/tmp/History-Dispatcher/.venv/bin/python",
        config=tmp_path / "config.toml",
    )

    worker = units["history-dispatcher-telegram-worker.service"]
    assert "Type=simple" in worker
    assert "telegram-worker" in worker
    assert "After=history-dispatcher.service" in worker
    assert "Requires=history-dispatcher.service" in worker
    assert "Restart=on-failure" in worker
    assert "RestrictAddressFamilies=AF_UNIX AF_FILE AF_INET AF_INET6" in worker
    for directive in (
        "NoNewPrivileges=yes",
        "PrivateTmp=yes",
        "PrivateDevices=yes",
        "ProtectSystem=strict",
        "ProtectHome=read-only",
        "RestrictNamespaces=yes",
        "LockPersonality=yes",
        "MemoryDenyWriteExecute=yes",
        "UMask=0077",
    ):
        assert directive in worker

    assert "RestrictAddressFamilies=AF_UNIX AF_FILE\n" in units[
        "history-dispatcher.service"
    ]
    assert "RestrictAddressFamilies=AF_UNIX AF_FILE\n" in units[
        "history-dispatcher-collector.service"
    ]
    assert "AF_INET" not in units["history-dispatcher.service"]
    assert "AF_INET" not in units["history-dispatcher-collector.service"]

    rendered = "\n".join(units.values()).casefold()
    assert "bot_token" not in rendered
    assert "chat_id" not in rendered
    assert "123456789:" not in rendered
    assert "-1001234567890" not in rendered
    assert "environment=" not in worker.casefold()


def test_installer_enables_worker_only_with_explicit_flag(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[list[str]] = []

    def fake_run(argv: list[str], *, check: bool):
        assert check is True
        calls.append(list(argv))
        return None

    monkeypatch.setattr(systemd.subprocess, "run", fake_run)
    common = [
        "--python",
        "/tmp/History-Dispatcher/.venv/bin/python",
        "--config",
        str(tmp_path / "config.toml"),
        "--unit-dir",
        str(tmp_path / "units"),
        "--enable",
    ]

    assert systemd.main(common) == 0
    assert not any(
        "history-dispatcher-telegram-worker.service" in call for call in calls
    )

    calls.clear()
    assert systemd.main([*common, "--enable-telegram-worker"]) == 0
    assert [
        "systemctl",
        "--user",
        "enable",
        "--now",
        "history-dispatcher-telegram-worker.service",
    ] in calls
