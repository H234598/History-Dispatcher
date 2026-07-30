from __future__ import annotations

import pytest

from history_dispatcher.config_v2_contract import (
    ConfigApplyRequestV2,
    TelegramDispatchProvider,
    TelegramRoutingConfigV2,
    validate_provider_transition,
)


def test_default_provider_is_teebotus_and_redacted_output_has_no_secret():
    config = TelegramRoutingConfigV2.from_mapping({})

    assert config.provider is TelegramDispatchProvider.TEEBOTUS
    assert config.as_redacted_dict() == {"provider": "teebotus"}
    assert "token" not in str(config.as_redacted_dict())


def test_native_provider_transition_is_staged_only():
    result = validate_provider_transition(
        TelegramRoutingConfigV2(TelegramDispatchProvider.TEEBOTUS),
        TelegramRoutingConfigV2(TelegramDispatchProvider.HISTORY_DISPATCHER),
    )

    assert result["status"] == "staged"
    assert result["effect"] == "new_route_plans_only"


def test_unknown_provider_and_keys_fail_closed():
    with pytest.raises(ValueError):
        TelegramRoutingConfigV2.from_mapping({"provider": "unknown"})
    with pytest.raises(ValueError):
        TelegramRoutingConfigV2.from_mapping({"provider": "teebotus", "token": "secret"})


def test_apply_request_fingerprint_is_stable():
    request = ConfigApplyRequestV2(
        expected_revision="revision",
        preview_token="preview",
        changes={"routing": {"telegram": {"provider": "history_dispatcher"}}},
    )

    assert request.fingerprint() == request.fingerprint()
