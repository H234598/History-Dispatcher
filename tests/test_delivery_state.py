from __future__ import annotations

import pytest

from history_dispatcher.delivery_state import (
    InvalidDeliveryTransition,
    RecipientDeliveryState,
    TargetDeliveryState,
    ensure_recipient_transition,
    ensure_target_transition,
    recipient_state_is_terminal,
    target_state_is_terminal,
)


def test_target_success_is_monotonic_and_retry_path_is_explicit() -> None:
    assert ensure_target_transition("pending", "claimed") is TargetDeliveryState.CLAIMED
    assert ensure_target_transition("claimed", "failed_retryable") is TargetDeliveryState.FAILED_RETRYABLE
    assert ensure_target_transition("failed_retryable", "pending") is TargetDeliveryState.PENDING
    assert ensure_target_transition("claimed", "delivered") is TargetDeliveryState.DELIVERED
    with pytest.raises(InvalidDeliveryTransition):
        ensure_target_transition("delivered", "pending")


def test_target_skip_and_legacy_hold_are_terminal() -> None:
    for state in (
        "delivered",
        "failed_terminal",
        "quarantined",
        "skipped_disabled",
        "skipped_filtered",
        "skipped_unknown",
        "legacy_hold",
    ):
        assert target_state_is_terminal(state) is True
        assert ensure_target_transition(state, state).value == state
        with pytest.raises(InvalidDeliveryTransition):
            ensure_target_transition(state, "pending")


def test_recipient_success_rank_cannot_be_downgraded() -> None:
    assert ensure_recipient_transition("pending", "accepted") is RecipientDeliveryState.ACCEPTED
    assert ensure_recipient_transition("accepted", "delivered") is RecipientDeliveryState.DELIVERED
    assert ensure_recipient_transition("delivered", "acknowledged") is RecipientDeliveryState.ACKNOWLEDGED
    with pytest.raises(InvalidDeliveryTransition):
        ensure_recipient_transition("accepted", "failed_retryable")
    with pytest.raises(InvalidDeliveryTransition):
        ensure_recipient_transition("acknowledged", "delivered")


def test_possible_duplicate_requires_reconciliation() -> None:
    assert ensure_recipient_transition("claimed", "possible_duplicate") is RecipientDeliveryState.POSSIBLE_DUPLICATE
    assert ensure_recipient_transition("possible_duplicate", "delivered") is RecipientDeliveryState.DELIVERED
    assert recipient_state_is_terminal("possible_duplicate") is False
    assert recipient_state_is_terminal("legacy_hold") is True
