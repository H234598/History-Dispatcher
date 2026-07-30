from __future__ import annotations

import json
import os
import stat
import tempfile
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from .status_v2 import MAX_STATUS_BYTES, STATUS_SCHEMA_VERSION, validate_redacted_status


STATUS_V2_SNAPSHOT_MAX_BYTES = MAX_STATUS_BYTES


def _fsync_directory(path: Path) -> None:
    descriptor = os.open(
        path,
        os.O_RDONLY | getattr(os, "O_DIRECTORY", 0) | getattr(os, "O_NOFOLLOW", 0),
    )
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def _validated_bytes(payload: Mapping[str, Any]) -> bytes:
    if set(payload) != {"version", "status"}:
        raise ValueError("status-v2 snapshot must contain version and status")
    if int(payload.get("version", 0) or 0) != STATUS_SCHEMA_VERSION:
        raise ValueError("status-v2 snapshot version mismatch")
    status = payload.get("status")
    if not isinstance(status, Mapping):
        raise ValueError("status-v2 snapshot status must be an object")
    validate_redacted_status(status)
    encoded = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")
    if len(encoded) > STATUS_V2_SNAPSHOT_MAX_BYTES:
        raise RuntimeError("status-v2 snapshot exceeds 64 KiB")
    return encoded


def write_status_v2_snapshot(path: Path, payload: Mapping[str, Any]) -> None:
    destination = Path(path)
    encoded = _validated_bytes(payload)
    destination.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    if destination.parent.is_symlink():
        raise RuntimeError("status-v2 snapshot directory must not be a symlink")
    os.chmod(destination.parent, 0o700)
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{destination.name}.",
        suffix=".tmp",
        dir=destination.parent,
    )
    temporary = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(encoded)
            handle.flush()
            os.fsync(handle.fileno())
        os.chmod(temporary, 0o600)
        if not stat.S_ISREG(temporary.stat().st_mode):
            raise RuntimeError("status-v2 temporary snapshot is not a regular file")
        os.replace(temporary, destination)
        _fsync_directory(destination.parent)
    finally:
        try:
            temporary.unlink()
        except FileNotFoundError:
            pass
