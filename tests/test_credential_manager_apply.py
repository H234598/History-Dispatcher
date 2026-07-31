from __future__ import annotations

import json
import sqlite3
from dataclasses import replace
from pathlib import Path

import pytest

from history_dispatcher.config import default_config, write_config
from history_dispatcher.credential_manager import (
    CredentialApplyError,
    CredentialManager,
)
from history_dispatcher.crypto import StaticKeyProvider
from history_dispatcher.migrations import (
    DatabaseV2Migrator,
    DatabaseV3Migrator,
    DatabaseV4Migrator,
)
from history_dispatcher.store import DispatcherStore
from history_dispatcher.telegram_provider import TelegramDispatchProvider
from history_dispatcher.telegram_secrets import (
    NativeTelegramSecretStore,
    TelegramSecretError,
)


class MemoryBackend:
    def __init__(self) -> None:
        self.values: dict[tuple[str, str], str] = {}
        self.fail_store = False
        self.fail_clear = False
        self.fail_lookup = False

    def lookup(self, kind, profile_ref):
        if self.fail_lookup:
            raise TelegramSecretError("lookup failed")
        return self.values.get((kind.value, profile_ref))

    def store(self, kind, profile_ref, value):
        if self.fail_store:
            raise TelegramSecretError("store failed")
        self.values[(kind.value, profile_ref)] = value

    def clear(self, kind, profile_ref):
        if self.fail_clear:
            raise TelegramSecretError("clear failed")
        return self.values.pop((kind.value, profile_ref), None) is not None


def _manager(tmp_path: Path) -> tuple[CredentialManager, MemoryBackend]:
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
    manager = CredentialManager(
        config,
        database_path=database,
        key_provider=provider,
        secret_store=NativeTelegramSecretStore(backend=backend),
        token_factory=lambda: "preview_" + "z" * 40,
    )
    return manager, backend


def _apply(manager: CredentialManager, **preview_kwargs):
    preview = manager.preview_apply(**preview_kwargs)
    return manager.apply_preview(
        preview_token=preview.preview_token,
        fingerprint=preview.fingerprint,
        confirmation=preview.confirmation,
        actor="uid:1000",
    )


def test_set_bot_token_writes_secret_free_metadata_and_audit(tmp_path: Path) -> None:
    manager, backend = _manager(tmp_path)
    secret = "123456789:ABCDEFGHIJKLMNOPQRSTUVWXYZabcdef"

    result = _apply(
        manager,
        action="set",
        secret_kind="bot_token",
        profile_ref="telegram_primary",
        secret_value=secret,
    )

    assert result == {
        "ok": True,
        "schema_version": 1,
        "action": "set",
        "secret_kind": "bot_token",
        "profile_ref": "telegram_primary",
        "configured": True,
        "last_changed": result["last_changed"],
    }
    assert backend.values[("bot_token", "telegram_primary")] == secret
    with sqlite3.connect(manager.database_path) as db:
        metadata = db.execute(
            "SELECT secret_kind,profile_key,configured,last_changed,last_operation "
            "FROM telegram_secret_metadata"
        ).fetchone()
        audit = db.execute(
            "SELECT actor_key,profile_key,operation,secret_kind,result,reason_code "
            "FROM credential_audit"
        ).fetchone()
    assert metadata[0] == "bot_token"
    assert metadata[2:] == (1, result["last_changed"], "set")
    assert metadata[1].startswith("secretprofile_")
    assert audit[0].startswith("actor_")
    assert audit[1] == metadata[1]
    assert audit[2:] == (
        "credential.set",
        "bot_token",
        "applied",
        "applied",
    )
    database_bytes = manager.database_path.read_bytes()
    for forbidden in (
        secret,
        "telegram_primary",
        "ABCDEFGHIJKLMNOPQRSTUVWXYZ",
        "preview_" + "z" * 40,
    ):
        assert forbidden.encode("utf-8") not in database_bytes


def test_replace_and_delete_chat_id_preserve_secret_free_status(tmp_path: Path) -> None:
    manager, backend = _manager(tmp_path)
    backend.values[("chat_id", "status_admin_primary")] = "-1001234567890"

    replaced = _apply(
        manager,
        action="replace",
        secret_kind="chat_id",
        profile_ref="status_admin_primary",
        secret_value="-1009876543210",
    )
    deleted = _apply(
        manager,
        action="delete",
        secret_kind="chat_id",
        profile_ref="status_admin_primary",
        secret_value=None,
    )
    status = manager.get_status()

    assert replaced["configured"] is True
    assert deleted["configured"] is False
    assert ("chat_id", "status_admin_primary") not in backend.values
    assert status["bot"] == {
        "profile_ref": "telegram_primary",
        "configured": False,
        "last_changed": None,
    }
    assert status["recipients"] == [
        {
            "profile_ref": "status_admin_primary",
            "configured": False,
            "last_changed": deleted["last_changed"],
        }
    ]
    rendered = json.dumps(status, sort_keys=True)
    assert "-100" not in rendered


def test_set_requires_absence_replace_and_delete_require_existing_value(
    tmp_path: Path,
) -> None:
    manager, backend = _manager(tmp_path)
    backend.values[("bot_token", "telegram_primary")] = (
        "123456789:ABCDEFGHIJKLMNOPQRSTUVWXYZabcdef"
    )

    with pytest.raises(CredentialApplyError, match="already configured"):
        _apply(
            manager,
            action="set",
            secret_kind="bot_token",
            profile_ref="telegram_primary",
            secret_value="123456789:abcdefghijklmnopqrstuvwxyzABCDEFG",
        )
    backend.values.clear()
    for action in ("replace", "delete"):
        with pytest.raises(CredentialApplyError, match="not configured"):
            _apply(
                manager,
                action=action,
                secret_kind="bot_token",
                profile_ref="telegram_primary",
                secret_value=(
                    "123456789:abcdefghijklmnopqrstuvwxyzABCDEFG"
                    if action == "replace"
                    else None
                ),
            )


def test_metadata_failure_restores_previous_secret(tmp_path: Path, monkeypatch) -> None:
    manager, backend = _manager(tmp_path)
    old = "123456789:ABCDEFGHIJKLMNOPQRSTUVWXYZabcdef"
    new = "123456789:abcdefghijklmnopqrstuvwxyzABCDEFG"
    backend.values[("bot_token", "telegram_primary")] = old

    def fail_commit(**_kwargs):
        raise sqlite3.OperationalError("injected metadata failure")

    monkeypatch.setattr(manager, "_commit_metadata_and_audit", fail_commit)

    with pytest.raises(CredentialApplyError, match="rolled back"):
        _apply(
            manager,
            action="replace",
            secret_kind="bot_token",
            profile_ref="telegram_primary",
            secret_value=new,
        )

    assert backend.values[("bot_token", "telegram_primary")] == old
    with sqlite3.connect(manager.database_path) as db:
        assert db.execute(
            "SELECT COUNT(*) FROM telegram_secret_metadata"
        ).fetchone()[0] == 0


def test_rollback_failure_is_terminal(tmp_path: Path, monkeypatch) -> None:
    manager, backend = _manager(tmp_path)
    old = "123456789:ABCDEFGHIJKLMNOPQRSTUVWXYZabcdef"
    new = "123456789:abcdefghijklmnopqrstuvwxyzABCDEFG"
    backend.values[("bot_token", "telegram_primary")] = old

    def fail_commit(**_kwargs):
        backend.fail_store = True
        raise sqlite3.OperationalError("injected metadata failure")

    monkeypatch.setattr(manager, "_commit_metadata_and_audit", fail_commit)

    with pytest.raises(CredentialApplyError, match="credential_rollback_failed"):
        _apply(
            manager,
            action="replace",
            secret_kind="bot_token",
            profile_ref="telegram_primary",
            secret_value=new,
        )


def test_preview_is_one_use_and_fingerprint_confirmation_are_checked(
    tmp_path: Path,
) -> None:
    manager, _backend = _manager(tmp_path)
    preview = manager.preview_apply(
        action="set",
        secret_kind="bot_token",
        profile_ref="telegram_primary",
        secret_value="123456789:ABCDEFGHIJKLMNOPQRSTUVWXYZabcdef",
    )

    with pytest.raises(CredentialApplyError, match="fingerprint"):
        manager.apply_preview(
            preview_token=preview.preview_token,
            fingerprint="0" * 64,
            confirmation=preview.confirmation,
            actor="uid:1000",
        )
    with pytest.raises(CredentialApplyError, match="unknown|consumed"):
        manager.apply_preview(
            preview_token=preview.preview_token,
            fingerprint=preview.fingerprint,
            confirmation=preview.confirmation,
            actor="uid:1000",
        )
