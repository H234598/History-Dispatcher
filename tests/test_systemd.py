from pathlib import Path

from history_dispatcher.systemd import render_units


def test_systemd_units_are_oneshot_and_local_only(tmp_path: Path) -> None:
    units = render_units(python="/tmp/History-Dispatcher/.venv/bin/python", config=tmp_path / "config.toml")
    assert "Type=simple" in units["history-dispatcher.service"]
    assert "Type=oneshot" in units["history-dispatcher-collector.service"]
    assert "OnUnitActiveSec=300s" in units["history-dispatcher-collector.timer"]
    for name in ("history-dispatcher.service", "history-dispatcher-collector.service"):
        text = units[name]
        assert "RestrictAddressFamilies=AF_UNIX AF_FILE" in text
        assert "NoNewPrivileges=yes" in text
        assert "PrivateTmp=yes" in text
        assert "MemoryDenyWriteExecute=yes" in text
        assert "ProtectSystem=strict" in text
    collector = units["history-dispatcher-collector.service"]
    assert "RuntimeDirectory=history-dispatcher" not in collector
    assert "StateDirectory=history-dispatcher" not in collector
    assert "ConfigurationDirectory=history-dispatcher" not in collector
