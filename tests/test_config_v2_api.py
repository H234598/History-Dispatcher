from __future__ import annotations

import pytest

from history_dispatcher.config_v2_api import (
    ConfigV2Error,
    TelegramDispatchProvider,
    TelegramRoutingConfigV2,
    preview_provider_change,
    redacted_config_status,
)


def test_default_provider_is_teebotus() -> None:
    assert TelegramRoutingConfigV2().provider is TelegramDispatchProvider.TEEBOTUS


def test_native_provider_preview_is_deterministic() -> None:
    first = preview_provider_change(
        expected_revision="revision-a",
        provider="history_dispatcher",
    )
    second = preview_provider_change(
        expected_revision="revision-a",
        provider="history_dispatcher",
    )
    assert first == second
    assert first.requested_provider is TelegramDispatchProvider.HISTORY_DISPATCHER


def test_unknown_provider_and_keys_fail_closed() -> None:
    with pytest.raises(ConfigV2Error):
        TelegramDispatchProvider.parse("other")
    with pytest.raises(ConfigV2Error):
        TelegramRoutingConfigV2.from_mapping({"token": "secret"})


def test_redacted_status_has_no_secret_surface() -> None:
    status = redacted_config_status(TelegramRoutingConfigV2())
    assert status == {"routing": {"telegram": {"provider": "teebotus"}}}
