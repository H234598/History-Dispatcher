from __future__ import annotations

import hashlib
import sqlite3
from dataclasses import dataclass, replace
from pathlib import Path

import pytest

from history_dispatcher.config import (
    config_revision,
    default_config,
    load_config,
    write_config,
)
from history_dispatcher.config_manager_v2 import (
    ConfigManagerV2,
    ConfigV2ApplyError,
)
from history_dispatcher.crypto import StaticKeyProvider
from history_dispatcher.migrations import DatabaseV2Migrator, DatabaseV3Migrator
from history_dispatcher.store import DispatcherStore
from history_dispatcher.telegram_provider import TelegramDispatchProvider


@dataclass
class MutableClock:
    value: float = 1000.0

    def __call__(self) -> float:
        return self.value

    def advance(self, seconds: float) -> None:
        self.value += seconds


def _native_patch() -> dict[str, object]:
    return {
        "routing": {
            "telegram": {
                "provider": "history_dispatcher",
                "credential_ref": "telegram_primary",
                "recipient_refs": ["status_admin_primary", "ops_admin"],
            }
        }
    }


def _manager(
    tmp_path: Path,
    *,
    clock: MutableClock | None = None,
    migrated: bool = True,
) -> tuple[ConfigManagerV2, Path, StaticKeyProvider]:
    provider = StaticKeyProvider(b"k" * 32)
    state_dir = tmp_path / "state"
    runtime_dir = tmp_path / "runtime"
    database = state_dir / "history.sqlite3"
    config_path = tmp_path / "config.toml"
    config = replace(
        default_config(config_path),
        state_dir=state_dir,
        runtime_dir=runtime_dir,
        database_path=database,
        socket_path=runtime_dir / "control.sock",
    )
    write_config(config)
    config = load_config(config_path)
    DispatcherStore(database, provider)
    if migrated:
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
    token_counter = iter(
        f"preview_{index:04d}_" + "a" * 32 for index in range(100)
    )
    manager = ConfigManagerV2(
        config,
        database_path=database,
        key_provider=provider,
        clock=clock or MutableClock(),
        token_factory=lambda: next(token_counter),
    )
    return manager, config_path, provider


def _preview(manager: ConfigManagerV2):
    revision = config_revision(manager.config)
    return manager.preview_apply(
        expected_revision=revision,
        patch=_native_patch(),
    )


def test_apply_preview_writes_config_and_bounded_audit(tmp_path: Path) -> None:
    manager, config_path, _provider = _manager(tmp_path)
    before = config_revision(manager.config)
    preview = _preview(manager)

    result = manager.apply_preview(
        expected_revision=before,
        preview_token=preview.preview_token,
        fingerprint=preview.fingerprint,
        confirmation=preview.confirmation,
        actor="uid:1000",
    )

    reloaded = load_config(config_path)
    assert reloaded.telegram_provider is TelegramDispatchProvider.HISTORY_DISPATCHER
    assert reloaded.telegram_credential_ref == "telegram_primary"
    assert reloaded.telegram_recipient_refs == (
        "status_admin_primary",
        "ops_admin",
    )
    assert result == {
        "ok": True,
        "schema_version": 2,
        "config_revision": config_revision(reloaded),
        "restart_required": False,
        "effect": "new_route_plans_only",
        "routing": {
            "telegram": {
                "provider": "history_dispatcher",
                "credential_ref": "telegram_primary",
                "recipient_refs": ["status_admin_primary", "ops_admin"],
            }
        },
    }

    with sqlite3.connect(reloaded.database_path) as db:
        row = db.execute(
            "SELECT actor_key,operation,revision_before,revision_after,"
            "preview_token_hash,result,affected_count,reason_code "
            "FROM config_audit"
        ).fetchone()
    assert row is not None
    assert row[0].startswith("actor_")
    assert row[1] == "config.apply_v2"
    assert row[2] == before
    assert row[3] == config_revision(reloaded)
    assert row[4] == hashlib.sha256(
        preview.preview_token.encode("utf-8")
    ).hexdigest()
    assert row[5:] == ("applied", 3, "applied")
    database_bytes = reloaded.database_path.read_bytes()
    assert preview.preview_token.encode("utf-8") not in database_bytes
    assert b"status_admin_primary" not in database_bytes


def test_apply_preview_consumes_token_and_rejects_replay(tmp_path: Path) -> None:
    manager, _path, _provider = _manager(tmp_path)
    preview = _preview(manager)
    revision = config_revision(manager.config)
    manager.apply_preview(
        expected_revision=revision,
        preview_token=preview.preview_token,
        fingerprint=preview.fingerprint,
        confirmation=preview.confirmation,
        actor="uid:1000",
    )

    with pytest.raises(ConfigV2ApplyError, match="preview token"):
        manager.apply_preview(
            expected_revision=revision,
            preview_token=preview.preview_token,
            fingerprint=preview.fingerprint,
            confirmation=preview.confirmation,
            actor="uid:1000",
        )


def test_apply_preview_rejects_expired_token_without_mutation(tmp_path: Path) -> None:
    clock = MutableClock()
    manager, config_path, _provider = _manager(tmp_path, clock=clock)
    preview = _preview(manager)
    before = config_path.read_bytes()
    clock.advance(61)

    with pytest.raises(ConfigV2ApplyError, match="expired"):
        manager.apply_preview(
            expected_revision=preview.expected_revision,
            preview_token=preview.preview_token,
            fingerprint=preview.fingerprint,
            confirmation=preview.confirmation,
            actor="uid:1000",
        )

    assert config_path.read_bytes() == before


@pytest.mark.parametrize(
    ("field", "value", "match"),
    (
        ("fingerprint", "0" * 64, "fingerprint"),
        ("confirmation", "APPLY wrong", "confirmation"),
        ("preview_token", "unknown_" + "x" * 32, "preview token"),
    ),
)
def test_apply_preview_rejects_mismatched_authorization(
    tmp_path: Path,
    field: str,
    value: str,
    match: str,
) -> None:
    manager, config_path, _provider = _manager(tmp_path)
    preview = _preview(manager)
    before = config_path.read_bytes()
    arguments = {
        "expected_revision": preview.expected_revision,
        "preview_token": preview.preview_token,
        "fingerprint": preview.fingerprint,
        "confirmation": preview.confirmation,
        "actor": "uid:1000",
    }
    arguments[field] = value

    with pytest.raises(ConfigV2ApplyError, match=match):
        manager.apply_preview(**arguments)

    assert config_path.read_bytes() == before


def test_apply_preview_rejects_revision_change_and_audits_rejection(
    tmp_path: Path,
) -> None:
    manager, config_path, _provider = _manager(tmp_path)
    preview = _preview(manager)
    externally_changed = replace(manager.config, log_level="WARNING")
    write_config(externally_changed)
    changed_bytes = config_path.read_bytes()

    with pytest.raises(ConfigV2ApplyError, match="revision"):
        manager.apply_preview(
            expected_revision=preview.expected_revision,
            preview_token=preview.preview_token,
            fingerprint=preview.fingerprint,
            confirmation=preview.confirmation,
            actor="uid:1000",
        )

    assert config_path.read_bytes() == changed_bytes
    with sqlite3.connect(manager.database_path) as db:
        row = db.execute(
            "SELECT result,reason_code FROM config_audit ORDER BY created_at DESC"
        ).fetchone()
    assert row == ("rejected", "revision_changed")


def test_apply_preview_requires_existing_audit_schema_before_write(
    tmp_path: Path,
) -> None:
    manager, config_path, _provider = _manager(tmp_path, migrated=False)
    preview = _preview(manager)
    before = config_path.read_bytes()

    with pytest.raises(ConfigV2ApplyError, match="config_audit"):
        manager.apply_preview(
            expected_revision=preview.expected_revision,
            preview_token=preview.preview_token,
            fingerprint=preview.fingerprint,
            confirmation=preview.confirmation,
            actor="uid:1000",
        )

    assert config_path.read_bytes() == before


def test_apply_preview_restores_backup_when_post_write_audit_fails(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    manager, config_path, _provider = _manager(tmp_path)
    preview = _preview(manager)
    before = config_path.read_bytes()
    original_audit = manager._audit_apply

    calls = 0

    def failing_audit(**kwargs):
        nonlocal calls
        calls += 1
        if kwargs["result"] == "applied":
            raise sqlite3.OperationalError("injected audit failure")
        return original_audit(**kwargs)

    monkeypatch.setattr(manager, "_audit_apply", failing_audit)

    with pytest.raises(ConfigV2ApplyError, match="rolled back"):
        manager.apply_preview(
            expected_revision=preview.expected_revision,
            preview_token=preview.preview_token,
            fingerprint=preview.fingerprint,
            confirmation=preview.confirmation,
            actor="uid:1000",
        )

    assert calls >= 1
    assert config_path.read_bytes() == before
    assert load_config(config_path).telegram_provider is TelegramDispatchProvider.TEEBOTUS
