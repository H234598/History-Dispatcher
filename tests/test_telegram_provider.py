from __future__ import annotations

from dataclasses import FrozenInstanceError

import pytest

from history_dispatcher.telegram_provider import (
    MAX_NATIVE_RECIPIENT_REFS,
    TEEBOTUS_CAPABILITY_V2,
    TelegramDispatchProvider,
    TelegramProviderError,
    TelegramRecipientOutcome,
    TelegramTransportBinding,
    merge_recipient_outcomes,
)


def test_provider_values_are_stable_and_unknown_values_fail_closed() -> None:
    assert TelegramDispatchProvider.TEEBOTUS.value == "teebotus"
    assert TelegramDispatchProvider.HISTORY_DISPATCHER.value == "history_dispatcher"
    assert TelegramDispatchProvider.parse(" TeeBotus ") is TelegramDispatchProvider.TEEBOTUS
    with pytest.raises(TelegramProviderError, match="unsupported"):
        TelegramDispatchProvider.parse("automatic")


def test_teebotus_binding_contains_only_capability_metadata() -> None:
    binding = TelegramTransportBinding.teebotus()

    assert binding.as_route_plan_fragment() == {
        "schema_version": 1,
        "provider": "teebotus",
        "bridge_capability": TEEBOTUS_CAPABILITY_V2,
    }
    assert binding.status_view()["recipient_count"] == 0
    assert "credential_ref" not in binding.status_view()
    with pytest.raises(TelegramProviderError, match="must not contain native"):
        TelegramTransportBinding(
            provider="teebotus",
            credential_ref="telegram_primary",
        )


def test_native_binding_requires_opaque_credentials_and_recipient_routes() -> None:
    binding = TelegramTransportBinding.history_dispatcher(
        credential_ref="telegram_primary",
        recipient_refs=("status_admin_primary", "status_admin_primary", "ops_admin"),
    )

    assert binding.provider is TelegramDispatchProvider.HISTORY_DISPATCHER
    assert binding.recipient_refs == ("status_admin_primary", "ops_admin")
    assert binding.as_route_plan_fragment() == {
        "schema_version": 1,
        "provider": "history_dispatcher",
        "credential_ref": "telegram_primary",
        "recipient_refs": ["status_admin_primary", "ops_admin"],
    }
    assert binding.status_view() == {
        "schema_version": 1,
        "provider": "history_dispatcher",
        "configured": True,
        "recipient_count": 2,
        "bridge_capability": "",
    }


@pytest.mark.parametrize(
    "credential_ref,recipient_refs",
    [
        ("123456789:ABCDEFGHIJKLMNOPQRSTUVWXYZabcdef", ("admin",)),
        ("telegram_primary", ("-1001234567890",)),
        ("../telegram", ("admin",)),
        ("telegram_primary", ("admin/path",)),
        ("", ("admin",)),
        ("telegram_primary", ()),
    ],
)
def test_native_binding_rejects_tokens_chat_ids_paths_and_missing_values(
    credential_ref: str,
    recipient_refs: tuple[str, ...],
) -> None:
    with pytest.raises(TelegramProviderError):
        TelegramTransportBinding.history_dispatcher(
            credential_ref=credential_ref,
            recipient_refs=recipient_refs,
        )


def test_native_binding_limits_recipient_references() -> None:
    with pytest.raises(TelegramProviderError, match="too many"):
        TelegramTransportBinding.history_dispatcher(
            credential_ref="telegram_primary",
            recipient_refs=tuple(
                f"recipient_{index}"
                for index in range(MAX_NATIVE_RECIPIENT_REFS + 1)
            ),
        )


def test_provider_is_bound_into_plan_hash_and_never_falls_back() -> None:
    teebotus = TelegramTransportBinding.teebotus()
    native = TelegramTransportBinding.history_dispatcher(
        credential_ref="telegram_primary",
        recipient_refs=("status_admin",),
    )

    assert teebotus.plan_hash() == TelegramTransportBinding.teebotus().plan_hash()
    assert teebotus.plan_hash() != native.plan_hash()
    teebotus.require_worker_provider("teebotus")
    native.require_worker_provider("history_dispatcher")
    with pytest.raises(TelegramProviderError, match="fallback is forbidden"):
        teebotus.require_worker_provider("history_dispatcher")
    with pytest.raises(TelegramProviderError, match="fallback is forbidden"):
        native.require_worker_provider("teebotus")


def test_binding_is_immutable() -> None:
    binding = TelegramTransportBinding.teebotus()
    with pytest.raises(FrozenInstanceError):
        binding.provider = TelegramDispatchProvider.HISTORY_DISPATCHER  # type: ignore[misc]


def test_recipient_merge_never_downgrades_success() -> None:
    merged = merge_recipient_outcomes(
        (
            TelegramRecipientOutcome(
                recipient_ref="status_admin",
                status="delivered",
                message_ref_key="message_1",
            ),
        ),
        (
            TelegramRecipientOutcome(
                recipient_ref="status_admin",
                status="failed",
                reason_code="temporary_failure",
            ),
            TelegramRecipientOutcome(
                recipient_ref="status_admin",
                status="accepted",
            ),
        ),
    )

    assert len(merged) == 1
    assert merged[0].status == "delivered"
    assert merged[0].message_ref_key == "message_1"


def test_recipient_merge_promotes_success_and_preserves_reconciliation_hold() -> None:
    uncertain = merge_recipient_outcomes(
        ({"recipient_ref": "status_admin", "status": "failed"},),
        (
            {
                "recipient_ref": "status_admin",
                "status": "accepted",
                "possible_duplicate": True,
            },
        ),
    )
    assert uncertain[0].status == "possible_duplicate"
    assert uncertain[0].possible_duplicate is True

    resolved = merge_recipient_outcomes(
        uncertain,
        ({"recipient_ref": "status_admin", "status": "acknowledged"},),
    )
    assert resolved[0].status == "acknowledged"
    assert resolved[0].successful is True


def test_skipped_recipient_is_terminal_until_a_real_success_receipt_arrives() -> None:
    skipped = merge_recipient_outcomes(
        ({"recipient_ref": "retired_admin", "status": "failed"},),
        ({"recipient_ref": "retired_admin", "status": "skipped"},),
    )
    assert skipped[0].status == "skipped"

    unchanged = merge_recipient_outcomes(
        skipped,
        ({"recipient_ref": "retired_admin", "status": "failed"},),
    )
    assert unchanged[0].status == "skipped"

    acknowledged = merge_recipient_outcomes(
        skipped,
        ({"recipient_ref": "retired_admin", "status": "acknowledged"},),
    )
    assert acknowledged[0].status == "acknowledged"
