from __future__ import annotations

import pytest

from history_dispatcher.config_v2_api import ConfigV2Error
from history_dispatcher.config_v2_integration import (
    ConfigApplyConflict,
    preview_telegram_provider_change,
    public_routing_status,
    telegram_routing_from_raw,
)


def test_routing_loader_defaults_to_teebotus() -> None:
    assert telegram_routing_from_raw({}).provider.value == "teebotus"


def test_routing_loader_accepts_native_provider() -> None:
    assert telegram_routing_from_raw(
        {"telegram": {"provider": "history_dispatcher"}}
    ).provider.value == "history_dispatcher"


def test_routing_loader_rejects_secrets_and_unknown_keys() -> None:
    with pytest.raises(ConfigV2Error):
        telegram_routing_from_raw(
            {"telegram": {"provider": "teebotus", "token": "secret"}}
        )


def test_status_is_redacted() -> None:
    status = public_routing_status(
        {"telegram": {"provider": "history_dispatcher"}}
    )
    assert status == {
        "routing": {
            "telegram": {"provider": "history_dispatcher"}
        }
    }


def test_preview_fingerprint_is_revision_bound() -> None:
    first = preview_telegram_provider_change(
        current_revision="rev-a",
        requested_provider="history_dispatcher",
    )
    second = preview_telegram_provider_change(
        current_revision="rev-a",
        requested_provider="history_dispatcher",
    )
    third = preview_telegram_provider_change(
        current_revision="rev-b",
        requested_provider="history_dispatcher",
    )
    assert first.fingerprint == second.fingerprint
    assert first.fingerprint != third.fingerprint


def test_conflict_type_exists_for_future_apply_path() -> None:
    assert issubclass(ConfigApplyConflict, ConfigV2Error)
