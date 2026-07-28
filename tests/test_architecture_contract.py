from __future__ import annotations

import ast
import re
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SERVICE = ROOT / "history_dispatcher" / "service.py"
PROTOCOL = ROOT / "history_dispatcher" / "protocol.py"
CRYPTO = ROOT / "history_dispatcher" / "crypto.py"
SYSTEMD = ROOT / "history_dispatcher" / "systemd.py"
APPLET = ROOT / "files" / "history-dispatcher@H234598" / "applet.js"
ARCHITECTURE = ROOT / "docs" / "architecture.md"
SECURITY_INVARIANTS = ROOT / "docs" / "contracts" / "security-invariants.md"
CONTROL_PROTOCOL = ROOT / "docs" / "contracts" / "control-protocol-v1.md"
STATUS_SNAPSHOT = ROOT / "docs" / "contracts" / "status-snapshot-v1.md"


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def _literal_assignment(source: str, name: str) -> object:
    tree = ast.parse(source)
    for node in tree.body:
        if isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Name) and target.id == name:
                    return ast.literal_eval(node.value)
    raise AssertionError(f"assignment {name!r} not found")


def test_control_service_is_local_unix_socket_with_peer_credentials() -> None:
    source = _read(SERVICE)

    assert "socketserver.UnixStreamServer" in source
    assert "socketserver.TCPServer" not in source
    assert "socketserver.UDPServer" not in source
    assert "socket.SO_PEERCRED" in source
    assert "uid == os.getuid()" in source
    assert "os.chmod(self.path, 0o600)" in source


def test_control_protocol_is_versioned_bounded_and_allowlisted() -> None:
    protocol = _read(PROTOCOL)
    service = _read(SERVICE)

    assert 'struct.pack("!I", len(payload))' in protocol
    assert "size <= 0 or size > max_bytes" in protocol
    assert '"protocol_version": protocol_version' in protocol
    assert "protocol_version must be 1" in service

    operations = _literal_assignment(service, "OPERATIONS")
    assert operations == (
        "protocol.describe",
        "health.get",
        "status.get",
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


def test_payload_crypto_is_aes_gcm_with_secret_service_and_no_plaintext_fallback() -> None:
    source = _read(CRYPTO)

    assert "from cryptography.hazmat.primitives.ciphers.aead import AESGCM" in source
    assert '["secret-tool", "lookup", "application", "history-dispatcher", "purpose", "payload-key"]' in source
    assert "AESGCM(key_provider.get_key()).encrypt" in source
    assert "AESGCM(key_provider.get_key()).decrypt" in source
    assert "must be exactly 32 bytes" in source
    assert "plaintext" not in source.lower()


def test_status_snapshot_is_private_atomic_and_hard_bounded() -> None:
    source = _read(SERVICE)

    assert '"schema_version": 1' in source
    assert "64 * 1024" in source
    assert "status snapshot exceeds 64 KiB" in source
    assert "handle.flush()" in source
    assert "os.fsync(handle.fileno())" in source
    assert "os.chmod(temporary, 0o600)" in source
    assert "os.replace(temporary, path)" in source


def test_applet_is_snapshot_only_shell_free_and_uses_fixed_action_entrypoint() -> None:
    source = _read(APPLET)

    for forbidden in (
        "imports.gi.Soup",
        "Gio.SocketClient",
        "Gio.SocketConnection",
        "sqlite",
        "spawn_sync",
        "spawn_command_line_sync",
        "spawn_command_line_async",
        "/bin/sh",
        "bash -c",
    ):
        assert forbidden not in source

    assert "MAX_SNAPSHOT_BYTES = 64 * 1024" in source
    assert 'args.push("applet-action", "--action", action)' in source
    assert "ALLOWED_ACTIONS" in source
    assert "generation !== this.generation" in source


def test_applet_removal_only_cleans_local_resources() -> None:
    source = _read(APPLET)
    match = re.search(
        r"on_applet_removed_from_panel:\s*function\(\)\s*\{(?P<body>.*?)\n\s*\}\n\};",
        source,
        re.DOTALL,
    )
    assert match, "applet removal hook not found"
    body = match.group("body")

    assert "this.removed = true" in body
    assert "this.generation += 1" in body
    assert "cancellable.cancel()" in body
    assert "source_remove" in body
    assert "menu.destroy()" in body
    for forbidden in ("_runAction", "service-stop", "systemctl", "dispatch.claim", "collector.collect"):
        assert forbidden not in body


def test_systemd_units_keep_local_only_hardening_baseline() -> None:
    source = _read(SYSTEMD)

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
        assert directive in source


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

    for invariant in ("SI-001", "SI-002", "SI-003", "SI-004", "SI-005", "SI-006", "SI-007", "SI-008", "SI-009", "SI-010"):
        assert invariant in security

    assert "protocol_version = 1" in protocol
    assert "4-Byte" in protocol
    assert "SO_PEERCRED" in protocol
    assert "schema_version = 1" in snapshot
    assert "65.536 Byte" in snapshot


def test_all_sixteen_architecture_decisions_are_recorded() -> None:
    adr_files = sorted((ROOT / "docs" / "adr").glob("ADR-*.md"))

    assert len(adr_files) == 16
    assert adr_files[0].name.startswith("ADR-001-")
    assert adr_files[-1].name.startswith("ADR-016-")
    for path in adr_files:
        text = _read(path)
        assert "Status: Akzeptiert" in text
        assert "## Entscheidung" in text
        assert "## Konsequenzen" in text
        assert "## Verifikation" in text
