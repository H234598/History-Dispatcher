from __future__ import annotations

import json
import socket
import struct
from typing import Any


class ProtocolError(ValueError):
    pass


def encode_message(value: Any, *, max_bytes: int) -> bytes:
    payload = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    if len(payload) > max_bytes:
        raise ProtocolError("message exceeds configured frame limit")
    return struct.pack("!I", len(payload)) + payload


def read_message(connection: socket.socket, *, max_bytes: int) -> Any:
    header = _read_exact(connection, 4)
    if not header:
        return None
    size = struct.unpack("!I", header)[0]
    if size <= 0 or size > max_bytes:
        raise ProtocolError("invalid frame size")
    raw = _read_exact(connection, size)
    try:
        return json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ProtocolError("invalid JSON frame") from exc


def _read_exact(connection: socket.socket, size: int) -> bytes:
    chunks: list[bytes] = []
    remaining = size
    while remaining:
        chunk = connection.recv(remaining)
        if not chunk:
            if chunks:
                raise ProtocolError("truncated frame")
            return b""
        chunks.append(chunk)
        remaining -= len(chunk)
    return b"".join(chunks)


def request(operation: str, body: dict[str, Any] | None = None, *, protocol_version: int = 1) -> dict[str, Any]:
    return {"protocol_version": protocol_version, "request_id": __import__("uuid").uuid4().hex, "operation": operation, "body": body or {}}
