from __future__ import annotations

import math
from dataclasses import dataclass
from pathlib import Path

import pytest

from history_dispatcher.config import config_revision, load_config
from history_dispatcher.config_manager_v2 import (
    ConfigManagerV2,
    ConfigPatchV2,
    ConfigV2ValidationError,
)
from history_dispatcher.crypto import StaticKeyProvider
from history_dispatcher.telegram_provider import TelegramDispatchProvider


@dataclass
class MutableClock:
    value: float = 1000.0

    def __call__(self) -> float:
        return self.value

    def advance(self, seconds: float) -> None:
        self.value += seconds


def _manager(
    tmp_path: Path,
    *,
    clock: MutableClock | None = None,
) -> ConfigManagerV2:
    config_path = tmp_path / "config.toml"
    config_path.write_text("", encoding="utf-8")
    config = load_config(config_path)
    tokens = iter(f"preview_{index:04d}_" + "a" * 32 for index in range(200))
    return ConfigManagerV2(
        config,
        database_path=config.database_path,
        key_provider=StaticKeyProvider(b"k" * 32),
        clock=clock or MutableClock(),
        token_factory=lambda: next(tokens),
    )


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


def test_validate_patch_returns_canonical_typed_value(tmp_path: Path) -> None:
    manager = _manager(tmp_path)

    patch = manager.validate_patch(_native_patch())

    assert isinstance(patch, ConfigPatchV2)
    assert patch.telegram.provider is TelegramDispatchProvider.HISTORY_DISPATCHER
    assert patch.telegram.credential_ref == "telegram_primary"
    assert patch.telegram.recipient_refs == (
        "status_admin_primary",
        "ops_admin",
    )
    assert patch.canonical_dict() == _native_patch()


def test_get_redacted_exposes_only_routing_profiles(tmp_path: Path) -> None:
    manager = _manager(tmp_path)

    status = manager.get_redacted()

    assert status == {
        "schema_version": 2,
        "config_revision": config_revision(manager.config),
        "routing": {
            "telegram": {
                "provider": "teebotus",
                "credential_ref": "",
                "recipient_refs": [],
            }
        },
    }


def test_preview_is_deterministic_but_token_is_one_time_material(
    tmp_path: Path,
) -> None:
    manager = _manager(tmp_path)
    revision = config_revision(manager.config)

    first = manager.preview_apply(
        expected_revision=revision,
        patch=_native_patch(),
    )
    second = manager.preview_apply(
        expected_revision=revision,
        patch=_native_patch(),
    )

    assert first.fingerprint == second.fingerprint
    assert first.preview_token != second.preview_token
    assert first.expected_revision == revision
    assert first.confirmation == f"APPLY {first.fingerprint[:12]}"
    assert first.effect == "new_route_plans_only"
    assert first.expires_in_seconds == 60
    assert first.changes == {
        "routing.telegram.provider": {
            "from": "teebotus",
            "to": "history_dispatcher",
        },
        "routing.telegram.credential_ref": {
            "from": "",
            "to": "telegram_primary",
        },
        "routing.telegram.recipient_refs": {
            "from": [],
            "to": ["status_admin_primary", "ops_admin"],
        },
    }
    assert first.as_dict()["preview_token"] == first.preview_token


@pytest.mark.parametrize(
    "patch",
    (
        {"bot_token": "secret"},
        {"routing": {"telegram": {"bot_token": "secret"}}},
        {"routing": {"telegram": {"chat_id": "-1001234567890"}}},
        {"routing": {"telegram": {"secret": "value"}}},
        {"routing": {"telegram": {"provider": "automatic"}}},
        {
            "routing": {
                "telegram": {
                    "provider": "teebotus",
                    "credential_ref": "telegram_primary",
                }
            }
        },
        {
            "routing": {
                "telegram": {
                    "provider": "history_dispatcher",
                    "recipient_refs": ["-1001234567890"],
                }
            }
        },
        {"routing": {"unknown": {}}},
        {"routing": []},
    ),
)
def test_validate_patch_rejects_unsafe_or_unknown_values(
    tmp_path: Path,
    patch: dict[str, object],
) -> None:
    manager = _manager(tmp_path)

    with pytest.raises(ConfigV2ValidationError):
        manager.validate_patch(patch)


def test_validate_patch_rejects_too_many_recipient_profiles(
    tmp_path: Path,
) -> None:
    manager = _manager(tmp_path)
    patch = {
        "routing": {
            "telegram": {
                "provider": "history_dispatcher",
                "recipient_refs": [
                    f"recipient_{index}" for index in range(33)
                ],
            }
        }
    }

    with pytest.raises(ConfigV2ValidationError, match="recipient"):
        manager.validate_patch(patch)


def test_validate_patch_rejects_oversized_and_nonfinite_json(
    tmp_path: Path,
) -> None:
    manager = _manager(tmp_path)

    with pytest.raises(ConfigV2ValidationError, match="64 KiB"):
        manager.validate_patch(
            {
                "routing": {
                    "telegram": {
                        "provider": "history_dispatcher",
                        "credential_ref": "telegram_primary",
                        "recipient_refs": ["r" + "x" * (65 * 1024)],
                    }
                }
            }
        )

    with pytest.raises(ConfigV2ValidationError, match="finite JSON"):
        manager.validate_patch(
            {
                "routing": {
                    "telegram": {
                        "provider": "history_dispatcher",
                        "unknown": math.nan,
                    }
                }
            }
        )


def test_preview_rejects_wrong_revision_before_allocating_token(
    tmp_path: Path,
) -> None:
    manager = _manager(tmp_path)

    with pytest.raises(ConfigV2ValidationError, match="revision"):
        manager.preview_apply(
            expected_revision="0" * 64,
            patch=_native_patch(),
        )
