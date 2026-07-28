from __future__ import annotations

from enum import Enum


class InvalidDeliveryTransition(ValueError):
    pass


class TargetDeliveryState(str, Enum):
    PENDING = "pending"
    CLAIMED = "claimed"
    DELIVERED = "delivered"
    PARTIAL = "partial"
    FAILED_RETRYABLE = "failed_retryable"
    FAILED_TERMINAL = "failed_terminal"
    QUARANTINED = "quarantined"
    SKIPPED_DISABLED = "skipped_disabled"
    SKIPPED_FILTERED = "skipped_filtered"
    SKIPPED_UNKNOWN = "skipped_unknown"
    LEGACY_HOLD = "legacy_hold"


class RecipientDeliveryState(str, Enum):
    PENDING = "pending"
    CLAIMED = "claimed"
    ACCEPTED = "accepted"
    DELIVERED = "delivered"
    ACKNOWLEDGED = "acknowledged"
    FAILED_RETRYABLE = "failed_retryable"
    FAILED_TERMINAL = "failed_terminal"
    QUARANTINED = "quarantined"
    SKIPPED = "skipped"
    POSSIBLE_DUPLICATE = "possible_duplicate"
    LEGACY_HOLD = "legacy_hold"


_SUCCESS_RECIPIENT_STATES = frozenset(
    {
        RecipientDeliveryState.ACCEPTED,
        RecipientDeliveryState.DELIVERED,
        RecipientDeliveryState.ACKNOWLEDGED,
    }
)


_TARGET_TRANSITIONS: dict[TargetDeliveryState, frozenset[TargetDeliveryState]] = {
    TargetDeliveryState.PENDING: frozenset(
        {
            TargetDeliveryState.CLAIMED,
            TargetDeliveryState.SKIPPED_DISABLED,
            TargetDeliveryState.SKIPPED_FILTERED,
            TargetDeliveryState.SKIPPED_UNKNOWN,
            TargetDeliveryState.FAILED_TERMINAL,
            TargetDeliveryState.QUARANTINED,
            TargetDeliveryState.LEGACY_HOLD,
        }
    ),
    TargetDeliveryState.CLAIMED: frozenset(
        {
            TargetDeliveryState.PENDING,
            TargetDeliveryState.DELIVERED,
            TargetDeliveryState.PARTIAL,
            TargetDeliveryState.FAILED_RETRYABLE,
            TargetDeliveryState.FAILED_TERMINAL,
            TargetDeliveryState.QUARANTINED,
            TargetDeliveryState.SKIPPED_DISABLED,
            TargetDeliveryState.SKIPPED_FILTERED,
            TargetDeliveryState.SKIPPED_UNKNOWN,
        }
    ),
    TargetDeliveryState.PARTIAL: frozenset(
        {
            TargetDeliveryState.CLAIMED,
            TargetDeliveryState.DELIVERED,
            TargetDeliveryState.FAILED_RETRYABLE,
            TargetDeliveryState.FAILED_TERMINAL,
            TargetDeliveryState.QUARANTINED,
        }
    ),
    TargetDeliveryState.FAILED_RETRYABLE: frozenset(
        {
            TargetDeliveryState.PENDING,
            TargetDeliveryState.CLAIMED,
            TargetDeliveryState.FAILED_TERMINAL,
            TargetDeliveryState.QUARANTINED,
        }
    ),
    TargetDeliveryState.DELIVERED: frozenset(),
    TargetDeliveryState.FAILED_TERMINAL: frozenset(),
    TargetDeliveryState.QUARANTINED: frozenset(),
    TargetDeliveryState.SKIPPED_DISABLED: frozenset(),
    TargetDeliveryState.SKIPPED_FILTERED: frozenset(),
    TargetDeliveryState.SKIPPED_UNKNOWN: frozenset(),
    TargetDeliveryState.LEGACY_HOLD: frozenset(),
}


_RECIPIENT_TRANSITIONS: dict[
    RecipientDeliveryState,
    frozenset[RecipientDeliveryState],
] = {
    RecipientDeliveryState.PENDING: frozenset(
        {
            RecipientDeliveryState.CLAIMED,
            RecipientDeliveryState.ACCEPTED,
            RecipientDeliveryState.DELIVERED,
            RecipientDeliveryState.ACKNOWLEDGED,
            RecipientDeliveryState.FAILED_RETRYABLE,
            RecipientDeliveryState.FAILED_TERMINAL,
            RecipientDeliveryState.QUARANTINED,
            RecipientDeliveryState.SKIPPED,
            RecipientDeliveryState.POSSIBLE_DUPLICATE,
            RecipientDeliveryState.LEGACY_HOLD,
        }
    ),
    RecipientDeliveryState.CLAIMED: frozenset(
        {
            RecipientDeliveryState.PENDING,
            RecipientDeliveryState.ACCEPTED,
            RecipientDeliveryState.DELIVERED,
            RecipientDeliveryState.ACKNOWLEDGED,
            RecipientDeliveryState.FAILED_RETRYABLE,
            RecipientDeliveryState.FAILED_TERMINAL,
            RecipientDeliveryState.QUARANTINED,
            RecipientDeliveryState.SKIPPED,
            RecipientDeliveryState.POSSIBLE_DUPLICATE,
        }
    ),
    RecipientDeliveryState.FAILED_RETRYABLE: frozenset(
        {
            RecipientDeliveryState.PENDING,
            RecipientDeliveryState.CLAIMED,
            RecipientDeliveryState.ACCEPTED,
            RecipientDeliveryState.DELIVERED,
            RecipientDeliveryState.ACKNOWLEDGED,
            RecipientDeliveryState.FAILED_TERMINAL,
            RecipientDeliveryState.QUARANTINED,
            RecipientDeliveryState.SKIPPED,
            RecipientDeliveryState.POSSIBLE_DUPLICATE,
        }
    ),
    RecipientDeliveryState.POSSIBLE_DUPLICATE: frozenset(
        {
            RecipientDeliveryState.ACCEPTED,
            RecipientDeliveryState.DELIVERED,
            RecipientDeliveryState.ACKNOWLEDGED,
            RecipientDeliveryState.FAILED_TERMINAL,
            RecipientDeliveryState.QUARANTINED,
        }
    ),
    RecipientDeliveryState.ACCEPTED: frozenset(
        {
            RecipientDeliveryState.DELIVERED,
            RecipientDeliveryState.ACKNOWLEDGED,
        }
    ),
    RecipientDeliveryState.DELIVERED: frozenset(
        {RecipientDeliveryState.ACKNOWLEDGED}
    ),
    RecipientDeliveryState.ACKNOWLEDGED: frozenset(),
    RecipientDeliveryState.FAILED_TERMINAL: _SUCCESS_RECIPIENT_STATES,
    RecipientDeliveryState.QUARANTINED: _SUCCESS_RECIPIENT_STATES,
    RecipientDeliveryState.SKIPPED: _SUCCESS_RECIPIENT_STATES,
    RecipientDeliveryState.LEGACY_HOLD: _SUCCESS_RECIPIENT_STATES,
}


def ensure_target_transition(
    current: TargetDeliveryState | str,
    new: TargetDeliveryState | str,
) -> TargetDeliveryState:
    current_state = TargetDeliveryState(current)
    new_state = TargetDeliveryState(new)
    if current_state == new_state:
        return new_state
    if new_state not in _TARGET_TRANSITIONS[current_state]:
        raise InvalidDeliveryTransition(
            f"target delivery transition {current_state.value!r} -> "
            f"{new_state.value!r} is not allowed"
        )
    return new_state


def ensure_recipient_transition(
    current: RecipientDeliveryState | str,
    new: RecipientDeliveryState | str,
) -> RecipientDeliveryState:
    current_state = RecipientDeliveryState(current)
    new_state = RecipientDeliveryState(new)
    if current_state == new_state:
        return new_state
    if new_state not in _RECIPIENT_TRANSITIONS[current_state]:
        raise InvalidDeliveryTransition(
            f"recipient delivery transition {current_state.value!r} -> "
            f"{new_state.value!r} is not allowed"
        )
    return new_state


def target_state_is_terminal(value: TargetDeliveryState | str) -> bool:
    state = TargetDeliveryState(value)
    return state in {
        TargetDeliveryState.DELIVERED,
        TargetDeliveryState.FAILED_TERMINAL,
        TargetDeliveryState.QUARANTINED,
        TargetDeliveryState.SKIPPED_DISABLED,
        TargetDeliveryState.SKIPPED_FILTERED,
        TargetDeliveryState.SKIPPED_UNKNOWN,
        TargetDeliveryState.LEGACY_HOLD,
    }


def recipient_state_is_successful(value: RecipientDeliveryState | str) -> bool:
    return RecipientDeliveryState(value) in _SUCCESS_RECIPIENT_STATES


def recipient_state_is_terminal(value: RecipientDeliveryState | str) -> bool:
    """Return whether the recipient must be excluded from automatic retries.

    Accepted and delivered outcomes may still advance monotonically when a later
    receipt arrives, but they are already terminal for resend decisions. A later
    externally proven success may also reconcile a skipped or failed terminal
    row without reopening it for automatic retries.
    """

    state = RecipientDeliveryState(value)
    return recipient_state_is_successful(state) or state in {
        RecipientDeliveryState.FAILED_TERMINAL,
        RecipientDeliveryState.QUARANTINED,
        RecipientDeliveryState.SKIPPED,
        RecipientDeliveryState.LEGACY_HOLD,
    }
