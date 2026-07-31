from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path

import pytest

from history_dispatcher.config import default_config, write_config
from history_dispatcher.credential_manager import (
    CredentialManager,
    CredentialValidationError,
)
from history_dispatcher.crypto import StaticKeyProvider
from history_dispatcher.migrations import (
    DatabaseV2Migrator,
    DatabaseV3Migrator,
    DatabaseV4Migrator,
)
from history_dispatcher.store import DispatcherStore
from history_dispatcher.telegram_provider import TelegramDispatchProvider
from history_dispatcher.telegram_secrets import NativeTelegramSecretStore


class MemoryBackend:
    def __init__(self) -> None:
        self.values: dict[tuple[str, str], str] = {}

    def lookup(self, kind, profile_ref):
        return self.values.get((kind.value, profile_ref))

    def store(self, kind, profile_ref, value):
        self.values[(kind.value, profile_ref)] = value

    def clear(self, kind, profile_ref):
        return self.values.pop((kind.value, profile_ref), None) is not None


def _manager(tmp_path: Path, *, clock=None) -> CredentialManager:
    provider = StaticKeyProvider(b"k" * 32)
    config_path = tmp_path / "config.toml"
    database = tmp_path / "state" / "history.sqlite3"
    config = replace(
        default_config(config_path),
        state_dir=tmp_path / "state",
        runtime_dir=tmp_path / "runtime",
        database_path=database,
        telegram_provider=TelegramDispatchProvider.HISTORY_DISPATCHER,
        telegram_credential_ref="telegram_primary",
        telegram_recipient_refs=("status_admin_primary", "ops_admin"),
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
    return CredentialManager(
        config,
        database_path=database,
        key_provider=provider,
        secret_store=NativeTelegramSecretStore(backend=MemoryBackend()),
        clock=clock,
        token_factory=lambda: "preview_" + "p" * 40,
    )


def test_credential_preview_is_secret_free_and_bound_to_config(tmp_path: Path) -> None:
    manager = _manager(tmp_path)
    secret = "123456789:ABCDEFGHIJKLMNOPQRSTUVWXYZabcdef"

    preview = manager.preview_apply(
        action="set",
        secret_kind="bot_token",
        profile_ref="telegram_primary",
        secret_value=secret,
    )
    payload = preview.as_dict()

    assert payload["schema_version"] == 1
    assert payload["action"] == "set"
    assert payload["secret_kind"] == "bot_token"
    assert payload["profile_ref"] == "telegram_primary"
    assert payload["confirmation"] == (
        f"CREDENTIAL SET {payload['fingerprint'][:12]}"
    )
    assert payload["expires_in_seconds"] == 60
    assert payload["preview_token"].startswith("preview_")
    serialized = json.dumps(payload, sort_keys=True)
    assert secret not in serialized
    assert "ABCDEFGHIJKLMNOPQRSTUVWXYZ" not in serialized
    assert secret.encode("utf-8") not in manager.database_path.read_bytes()


def test_credential_preview_authorizes_current_bot_and_recipient_profiles(
    tmp_path: Path,
) -> None:
    manager = _manager(tmp_path)

    bot = manager.preview_apply(
        action="set",
        secret_kind="bot_token",
        profile_ref="telegram_primary",
        secret_value="123456789:ABCDEFGHIJKLMNOPQRSTUVWXYZabcdef",
    )
    recipient = manager.preview_apply(
        action="set",
        secret_kind="chat_id",
        profile_ref="status_admin_primary",
        secret_value="-1001234567890",
    )

    assert bot.profile_ref == "telegram_primary"
    assert recipient.profile_ref == "status_admin_primary"
    with pytest.raises(CredentialValidationError, match="not configured"):
        manager.preview_apply(
            action="set",
            secret_kind="chat_id",
            profile_ref="unconfigured_admin",
            secret_value="-1001234567890",
        )


@pytest.mark.parametrize(
    "action,kind,value,match",
    [
        ("automatic", "bot_token", "x", "action"),
        ("set", "password", "x", "secret kind"),
        ("set", "bot_token", None, "requires"),
        ("replace", "chat_id", None, "requires"),
        ("delete", "bot_token", "unexpected", "forbids"),
        ("set", "bot_token", "invalid", "bot token"),
        ("set", "chat_id", "chat", "chat ID"),
    ],
)
def test_credential_preview_rejects_invalid_operations(
    tmp_path: Path,
    action: str,
    kind: str,
    value: str | None,
    match: str,
) -> None:
    manager = _manager(tmp_path)
    profile = "telegram_primary" if kind != "chat_id" else "status_admin_primary"

    with pytest.raises(CredentialValidationError, match=match):
        manager.preview_apply(
            action=action,
            secret_kind=kind,
            profile_ref=profile,
            secret_value=value,
        )


def test_credential_preview_expires_and_registry_is_bounded(tmp_path: Path) -> None:
    now = [100.0]
    manager = _manager(tmp_path, clock=lambda: now[0])
    manager._token_factory = iter(
        f"preview_{index:03d}_" + "x" * 32 for index in range(140)
    ).__next__

    first = manager.preview_apply(
        action="set",
        secret_kind="bot_token",
        profile_ref="telegram_primary",
        secret_value="123456789:ABCDEFGHIJKLMNOPQRSTUVWXYZabcdef",
    )
    for _ in range(130):
        manager.preview_apply(
            action="set",
            secret_kind="chat_id",
            profile_ref="status_admin_primary",
            secret_value="-1001234567890",
        )

    assert len(manager._previews) == 128
    now[0] += 61
    with pytest.raises(Exception, match="expired|unknown|consumed"):
        manager.apply_preview(
            preview_token=first.preview_token,
            fingerprint=first.fingerprint,
            confirmation=first.confirmation,
            actor="uid:1000",
        )
