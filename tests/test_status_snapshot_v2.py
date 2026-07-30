from __future__ import annotations

import json
import os
import stat
from pathlib import Path

import pytest

from history_dispatcher.status_snapshot_v2 import (
    STATUS_V2_SNAPSHOT_MAX_BYTES,
    write_status_v2_snapshot,
)


def _payload() -> dict[str, object]:
    return {
        "version": 2,
        "status": {
            "schema_version": 2,
            "generated_at": "2026-07-30T17:00:00Z",
            "telegram": {
                "provider": "teebotus",
                "credential": {"configured": False, "last_changed": None},
            },
            "workers": [],
            "queue": {"queued": 0},
            "deliveries": {},
        },
    }


def test_status_v2_snapshot_is_private_atomic_and_bounded(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    path = tmp_path / "runtime" / "status-v2.json"
    replacements: list[tuple[Path, Path]] = []
    real_replace = os.replace

    def recording_replace(
        source: str | os.PathLike[str],
        target: str | os.PathLike[str],
    ) -> None:
        replacements.append((Path(source), Path(target)))
        real_replace(source, target)

    monkeypatch.setattr(
        "history_dispatcher.status_snapshot_v2.os.replace",
        recording_replace,
    )

    write_status_v2_snapshot(path, _payload())

    raw = path.read_bytes()
    assert len(raw) <= STATUS_V2_SNAPSHOT_MAX_BYTES
    assert stat.S_IMODE(path.stat().st_mode) == 0o600
    assert json.loads(raw.decode("utf-8"))["version"] == 2
    assert replacements
    temporary, target = replacements[-1]
    assert target == path
    assert temporary.parent == path.parent
    assert not temporary.exists()


def test_status_v2_snapshot_rejects_oversize_without_replacing_previous_file(
    tmp_path: Path,
) -> None:
    path = tmp_path / "runtime" / "status-v2.json"
    path.parent.mkdir(mode=0o700, parents=True)
    path.write_text('{"previous":true}', encoding="utf-8")
    os.chmod(path, 0o600)

    oversized = _payload()
    oversized["status"] = {
        **dict(oversized["status"]),
        "workers": [{"state": "x" * (65 * 1024)}],
    }

    with pytest.raises((RuntimeError, ValueError), match="64 KiB"):
        write_status_v2_snapshot(path, oversized)

    assert path.read_text(encoding="utf-8") == '{"previous":true}'
    assert not list(path.parent.glob(".status-v2.json.*.tmp"))


def test_status_v2_snapshot_rejects_secret_fields_before_write(tmp_path: Path) -> None:
    path = tmp_path / "runtime" / "status-v2.json"
    unsafe = _payload()
    unsafe["status"] = {
        **dict(unsafe["status"]),
        "bot_token": "123456789:ABCDEFGHIJKLMNOPQRSTUVWXYZabcdef",
    }

    with pytest.raises(ValueError, match="forbidden|sensitive"):
        write_status_v2_snapshot(path, unsafe)

    assert path.exists() is False
