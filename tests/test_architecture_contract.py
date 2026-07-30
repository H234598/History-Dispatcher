from __future__ import annotations

import base64
import json
import os
import socket
import socketserver
import stat
import struct
import threading
import time
from pathlib import Path
from types import SimpleNamespace

import pytest

from history_dispatcher.cli import _parser
from history_dispatcher.config import load_config
from history_dispatcher.crypto import (
    KeyUnavailable,
    SecretServiceKeyProvider,
    StaticKeyProvider,
    decrypt_json,
    encrypt_json,
)
from history_dispatcher.protocol import ProtocolError, encode_message, read_message
from history_dispatcher.service import (
    OPERATIONS,
    ControlServer,
    DispatcherService,
    _ThreadingUnixServer,
    _same_user,
    call_socket,
)
from history_dispatcher.systemd import render_units


ROOT = Path(__file__).resolve().parents[1]
ARCHITECTURE = ROOT / "docs" / "architecture.md"
SECURITY_INVARIANTS = ROOT / "docs" / "contracts" / "security-invariants.md"
CONTROL_PROTOCOL = ROOT / "docs" / "contracts" / "control-protocol-v1.md"
STATUS_SNAPSHOT = ROOT / "docs" / "contracts" / "status-snapshot-v1.md"


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


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


class _PeerCredentialSocket:
    def __init__(self, *, uid: int | None = None, error: Exception | None = None) -> None:
        self.uid = os.getuid() if uid is None else uid
        self.error = error

    def getsockopt(self, level: int, option: int, size: int) -> bytes:
        assert level == socket.SOL_SOCKET
        assert option == socket.SO_PEERCRED
        assert size == struct.calcsize("3i")
        if self.error is not None:
            raise self.error
        return struct.pack("3i", os.getpid(), self.uid, os.getgid())


def test_control_service_is_local_unix_socket_with_peer_credentials(tmp_path: Path) -> None:
    assert issubclass(_ThreadingUnixServer, socketserver.UnixStreamServer)
    assert _ThreadingUnixServer.address_family == socket.AF_UNIX
    assert _ThreadingUnixServer.socket_type == socket.SOCK_STREAM
    assert _same_user(_PeerCredentialSocket()) is True  # type: ignore[arg-type]
    assert _same_user(_PeerCredentialSocket(uid=os.getuid() + 1)) is False  # type: ignore[arg-type]
    assert _same_user(_PeerCredentialSocket(error=OSError("denied"))) is False  # type: ignore[arg-type]

    service = _service(tmp_path)
    control = ControlServer(service)
    thread = threading.Thread(target=control.start, daemon=True)
    thread.start()
    try:
        mode = 0
        for _ in range(200):
            try:
                candidate = service.config.socket_path.stat().st_mode
            except FileNotFoundError:
                time.sleep(0.01)
                continue
            if stat.S_ISSOCK(candidate) and stat.S_IMODE(candidate) == 0o600:
                mode = candidate
                break
            time.sleep(0.01)
        assert stat.S_ISSOCK(mode)
        assert stat.S_IMODE(mode) == 0o600
        response = call_socket(
            service.config.socket_path,
            {
                "protocol_version": 1,
                "request_id": "architecture-contract",
                "operation": "protocol.describe",
                "body": {},
            },
        )
        assert response["ok"] is True
        assert response["data"]["protocol_version"] == 1
    finally:
        control.shutdown()
        thread.join(timeout=2)


def test_control_protocol_is_versioned_bounded_and_allowlisted() -> None:
    left, right = socket.socketpair(socket.AF_UNIX, socket.SOCK_STREAM)
    try:
        encoded = encode_message({"hello": "world"}, max_bytes=128)
        left.sendall(encoded)
        assert read_message(right, max_bytes=128) == {"hello": "world"}

        with pytest.raises(ProtocolError, match="exceeds"):
            encode_message({"too": "x" * 200}, max_bytes=32)

        left.sendall(struct.pack("!I", 129))
        with pytest.raises(ProtocolError, match="frame size"):
            read_message(right, max_bytes=128)
    finally:
        left.close()
        right.close()

    assert OPERATIONS == (
        "protocol.describe",
        "health.get",
        "status.get",
        "status.get_redacted",
        "report.get",
        "history.append",
        "history.query",
        "dispatch.claim",
        "dispatch.complete",
        "dispatch.retry",
        "delivery.record",
        "config.get",
        "config.validate",
        "config.apply",
        "collector.collect",
        "admin.preview",
        "admin.execute",
        "audit.query",
        "migration.import_legacy",
        "maintenance.prune",
    )


def test_payload_crypto_is_aes_gcm_with_secret_service_and_no_plaintext_fallback(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    payload = b'{"marker":"never-store-me-in-plaintext"}'
    aad = b"event-id"
    blob = encrypt_json(payload, StaticKeyProvider(b"k" * 32), aad=aad)

    assert payload not in blob
    assert decrypt_json(blob, StaticKeyProvider(b"k" * 32), aad=aad) == payload
    with pytest.raises(Exception):
        decrypt_json(blob, StaticKeyProvider(b"z" * 32), aad=aad)
    tampered = blob[:-1] + bytes([blob[-1] ^ 0x01])
    with pytest.raises(Exception):
        decrypt_json(tampered, StaticKeyProvider(b"k" * 32), aad=aad)

    calls: list[list[str]] = []

    def fake_run(argv: list[str], **kwargs: object) -> SimpleNamespace:
        calls.append(list(argv))
        assert kwargs["check"] is False
        assert kwargs["capture_output"] is True
        assert kwargs["timeout"] == 5
        return SimpleNamespace(returncode=0, stdout=base64.b64encode(b"s" * 32))

    monkeypatch.setattr("history_dispatcher.crypto.subprocess.run", fake_run)
    provider = SecretServiceKeyProvider()
    assert provider.get_key() == b"s" * 32
    assert calls == [[
        "secret-tool",
        "lookup",
        "application",
        "history-dispatcher",
        "purpose",
        "payload-key",
    ]]

    with pytest.raises(KeyUnavailable, match="exactly 32 bytes"):
        SecretServiceKeyProvider(lookup=lambda: b"short").get_key()


def test_status_snapshot_is_private_atomic_and_hard_bounded(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    service = _service(tmp_path)
    marker = "PRIVATE-PAYLOAD-MARKER"
    result = service.handle(
        {
            "protocol_version": 1,
            "request_id": "snapshot-append",
            "operation": "history.append",
            "body": {"dedupe_key": "snapshot", "payload": {"secret": marker}},
        }
    )
    assert result["ok"] is True

    snapshot = service.config.snapshot_path
    raw = snapshot.read_bytes()
    assert len(raw) <= 64 * 1024
    assert marker.encode("utf-8") not in raw
    assert stat.S_IMODE(snapshot.stat().st_mode) == 0o600
    parsed = json.loads(raw.decode("utf-8"))
    assert parsed["schema_version"] == 1
    assert "payload" not in raw.decode("utf-8")

    replacements: list[tuple[Path, Path]] = []
    real_replace = os.replace

    def recording_replace(source: str | os.PathLike[str], target: str | os.PathLike[str]) -> None:
        replacements.append((Path(source), Path(target)))
        real_replace(source, target)

    monkeypatch.setattr("history_dispatcher.service.os.replace", recording_replace)
    service._write_snapshot()
    assert replacements
    temporary, target = replacements[-1]
    assert target == snapshot
    assert temporary.parent == snapshot.parent
    assert not temporary.exists()

    monkeypatch.setattr(service, "_status", lambda: {"schema_version": 1, "huge": "x" * (65 * 1024)})
    with pytest.raises(RuntimeError, match="64 KiB"):
        service._write_snapshot()


def test_cli_applet_action_allowlist_is_enforced_by_argparse() -> None:
    parser = _parser()
    parsed = parser.parse_args(["applet-action", "--action", "collect"])
    assert parsed.action == "collect"
    parsed = parser.parse_args(["applet-action", "--action", "service-restart"])
    assert parsed.action == "service-restart"
    with pytest.raises(SystemExit):
        parser.parse_args(["applet-action", "--action", "arbitrary-command"])


def test_systemd_units_keep_local_only_hardening_baseline(tmp_path: Path) -> None:
    units = render_units(
        python="/usr/bin/python3",
        config=tmp_path / "config.toml",
        interval="300s",
    )
    service = units["history-dispatcher.service"]
    collector = units["history-dispatcher-collector.service"]
    timer = units["history-dispatcher-collector.timer"]

    for rendered in (service, collector):
        for directive in (
            "NoNewPrivileges=yes",
            "PrivateTmp=yes",
            "PrivateDevices=yes",
            "ProtectSystem=strict",
            "ProtectHome=read-only",
            "RestrictAddressFamilies=AF_UNIX AF_FILE",
            "RestrictNamespaces=yes",
            "LockPersonality=yes",
            "MemoryDenyWriteExecute=yes",
            "UMask=0077",
        ):
            assert directive in rendered
        assert "/bin/sh" not in rendered
        assert "bash -c" not in rendered

    assert "ExecStart=/usr/bin/python3 -m history_dispatcher" in service
    assert " serve" in service
    assert " collect" in collector
    assert "Persistent=true" in timer


def test_architecture_and_contract_documents_cover_the_frozen_v1_boundary() -> None:
    architecture = _read(ARCHITECTURE)
    security = _read(SECURITY_INVARIANTS)
    protocol = _read(CONTROL_PROTOCOL)
    snapshot = _read(STATUS_SNAPSHOT)

    for component in (
        "Collector",
        "DispatcherService",
        "DispatcherStore",
        "Cinnamon-Applet",
        "TeeBotus",
    ):
        assert component in architecture

    for invariant in (
        "SI-001",
        "SI-002",
        "SI-003",
        "SI-004",
        "SI-005",
        "SI-006",
        "SI-007",
        "SI-008",
        "SI-009",
        "SI-010",
    ):
        assert invariant in security

    assert "protocol_version = 1" in protocol
    assert "4-Byte" in protocol
    assert "SO_PEERCRED" in protocol
    assert "idempotency_conflict" in protocol
    assert "idempotency_in_progress" in protocol
    assert "schema_version = 1" in snapshot
    assert "65.536 Byte" in snapshot


def test_required_architecture_decisions_are_recorded() -> None:
    adr_files = sorted((ROOT / "docs" / "adr").glob("ADR-*.md"))
    adr_ids = {path.name[:7] for path in adr_files}
    required_ids = {f"ADR-{number:03d}" for number in range(1, 17)}

    assert required_ids <= adr_ids
    for path in adr_files:
        text = _read(path)
        assert "Status: Akzeptiert" in text
        assert "## Entscheidung" in text
        assert "## Konsequenzen" in text
        assert "## Verifikation" in text
