from __future__ import annotations

import json
import math
import re
from collections.abc import Mapping, Sequence
from dataclasses import asdict
from typing import Any

from .delivery_store import (
    MAX_CLAIM_BATCH,
    DeliveryStore,
    RecipientDeliverySnapshot,
    TargetDeliveryClaim,
)
from .telegram_provider import MAX_NATIVE_RECIPIENT_REFS, TelegramRecipientOutcome


PROVIDER_API_SCHEMA_VERSION = 2
PROVIDER_API_OPERATIONS = (
    "provider.v2.claim",
    "provider.v2.renew",
    "provider.v2.register_recipients",
    "provider.v2.record_recipients",
    "provider.v2.complete",
    "provider.v2.heartbeat",
)

_IDENTIFIER_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}$")
_CLAIM_TOKEN_RE = re.compile(r"^[A-Za-z0-9_-]{32,512}$")
_REASON_RE = re.compile(r"^[a-z][a-z0-9_]{0,95}$")
_MAX_BODY_BYTES = 256 * 1024
_MAX_HEARTBEAT_DETAILS = 16


class ProviderApiValidationError(ValueError):
    pass


def _body(value: Mapping[str, Any] | object) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        raise ProviderApiValidationError("provider body must be an object")
    body = dict(value)
    try:
        encoded = json.dumps(
            body,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        ).encode("utf-8")
    except (TypeError, ValueError) as exc:
        raise ProviderApiValidationError("provider body must contain finite JSON") from exc
    if len(encoded) > _MAX_BODY_BYTES:
        raise ProviderApiValidationError("provider body exceeds the byte limit")
    return body


def _only(body: Mapping[str, Any], allowed: frozenset[str]) -> None:
    unknown = sorted(str(key) for key in body if str(key) not in allowed)
    if unknown:
        raise ProviderApiValidationError(
            "unknown field(s): " + ", ".join(unknown[:8])
        )


def _identifier(body: Mapping[str, Any], key: str) -> str:
    value = body.get(key)
    if not isinstance(value, str):
        raise ProviderApiValidationError(f"{key} must be a string")
    normalized = value.strip()
    if not _IDENTIFIER_RE.fullmatch(normalized):
        raise ProviderApiValidationError(f"{key} is invalid")
    return normalized


def _claim_token(body: Mapping[str, Any]) -> str:
    value = body.get("claim_token")
    if not isinstance(value, str) or not _CLAIM_TOKEN_RE.fullmatch(value):
        raise ProviderApiValidationError("claim_token is invalid")
    return value


def _integer(
    body: Mapping[str, Any],
    key: str,
    *,
    default: int,
    minimum: int,
    maximum: int,
) -> int:
    value = body.get(key, default)
    if isinstance(value, bool):
        raise ProviderApiValidationError(f"{key} must be an integer")
    try:
        result = int(value)
    except (TypeError, ValueError) as exc:
        raise ProviderApiValidationError(f"{key} must be an integer") from exc
    if result < minimum or result > maximum:
        raise ProviderApiValidationError(f"{key} is out of range")
    return result


def _ratio(body: Mapping[str, Any], key: str, *, default: float) -> float:
    value = body.get(key, default)
    if isinstance(value, bool):
        raise ProviderApiValidationError(f"{key} must be a number")
    try:
        result = float(value)
    except (TypeError, ValueError) as exc:
        raise ProviderApiValidationError(f"{key} must be a number") from exc
    if not math.isfinite(result) or result < 0.0 or result > 0.5:
        raise ProviderApiValidationError(f"{key} is out of range")
    return result


def _optional_reason(body: Mapping[str, Any], key: str) -> str:
    value = body.get(key, "")
    if value in (None, ""):
        return ""
    if not isinstance(value, str):
        raise ProviderApiValidationError(f"{key} must be a string")
    normalized = value.strip().casefold()
    if not _REASON_RE.fullmatch(normalized):
        raise ProviderApiValidationError(f"{key} is invalid")
    return normalized


def _recipient_refs(body: Mapping[str, Any]) -> tuple[str, ...]:
    raw = body.get("recipient_refs")
    if not isinstance(raw, Sequence) or isinstance(raw, (str, bytes, bytearray)):
        raise ProviderApiValidationError("recipient_refs must be an array")
    if not raw or len(raw) > MAX_NATIVE_RECIPIENT_REFS:
        raise ProviderApiValidationError("recipient_refs count is invalid")
    refs: list[str] = []
    seen: set[str] = set()
    for value in raw:
        outcome = TelegramRecipientOutcome(
            recipient_ref=value if isinstance(value, str) else "",
            status="failed",
        )
        if outcome.recipient_ref not in seen:
            seen.add(outcome.recipient_ref)
            refs.append(outcome.recipient_ref)
    return tuple(refs)


def _outcomes(body: Mapping[str, Any]) -> tuple[TelegramRecipientOutcome, ...]:
    raw = body.get("outcomes")
    if not isinstance(raw, Sequence) or isinstance(raw, (str, bytes, bytearray)):
        raise ProviderApiValidationError("outcomes must be an array")
    if not raw or len(raw) > MAX_NATIVE_RECIPIENT_REFS:
        raise ProviderApiValidationError("outcomes count is invalid")
    result: list[TelegramRecipientOutcome] = []
    allowed = frozenset(
        {
            "recipient_ref",
            "status",
            "possible_duplicate",
            "message_ref_key",
            "reason_code",
        }
    )
    seen: set[str] = set()
    for value in raw:
        if not isinstance(value, Mapping):
            raise ProviderApiValidationError("outcome must be an object")
        item = dict(value)
        _only(item, allowed)
        try:
            outcome = TelegramRecipientOutcome(**item)
        except (TypeError, ValueError) as exc:
            raise ProviderApiValidationError(str(exc)) from exc
        if outcome.recipient_ref in seen:
            raise ProviderApiValidationError("duplicate recipient outcome")
        seen.add(outcome.recipient_ref)
        result.append(outcome)
    return tuple(result)


def _heartbeat_details(body: Mapping[str, Any]) -> dict[str, Any]:
    raw = body.get("details", {})
    if not isinstance(raw, Mapping):
        raise ProviderApiValidationError("details must be an object")
    if len(raw) > _MAX_HEARTBEAT_DETAILS:
        raise ProviderApiValidationError("details contains too many fields")
    result: dict[str, Any] = {}
    for key, value in raw.items():
        if not isinstance(key, str) or not _REASON_RE.fullmatch(key.strip().casefold()):
            raise ProviderApiValidationError("details contains an invalid key")
        normalized_key = key.strip().casefold()
        if isinstance(value, bool) or isinstance(value, int):
            result[normalized_key] = value
        elif isinstance(value, str):
            if len(value) > 500:
                raise ProviderApiValidationError("details string is too long")
            result[normalized_key] = value
        else:
            raise ProviderApiValidationError("details contains an unsupported value")
    return result


def _claim_dict(claim: TargetDeliveryClaim) -> dict[str, Any]:
    value = asdict(claim)
    value["binding"] = dict(claim.binding)
    value["payload"] = dict(claim.payload)
    value["successful_recipient_refs"] = list(claim.successful_recipient_refs)
    value["open_recipient_refs"] = list(claim.open_recipient_refs)
    return value


def _recipient_dict(snapshot: RecipientDeliverySnapshot) -> dict[str, Any]:
    return asdict(snapshot)


class ProviderApiV2:
    def __init__(self, store: DeliveryStore) -> None:
        self.store = store

    def dispatch(self, operation: str, raw_body: Mapping[str, Any] | object) -> dict[str, Any]:
        if operation not in PROVIDER_API_OPERATIONS:
            raise ProviderApiValidationError("unknown provider operation")
        body = _body(raw_body)
        if operation == "provider.v2.claim":
            return self._claim(body)
        if operation == "provider.v2.renew":
            return self._renew(body)
        if operation == "provider.v2.register_recipients":
            return self._register_recipients(body)
        if operation == "provider.v2.record_recipients":
            return self._record_recipients(body)
        if operation == "provider.v2.complete":
            return self._complete(body)
        if operation == "provider.v2.heartbeat":
            return self._heartbeat(body)
        raise AssertionError(operation)

    def _claim(self, body: Mapping[str, Any]) -> dict[str, Any]:
        _only(
            body,
            frozenset(
                {
                    "target_id",
                    "provider_id",
                    "worker_id",
                    "capability_version",
                    "limit",
                    "lease_seconds",
                    "max_attempts",
                    "base_backoff_seconds",
                    "max_backoff_seconds",
                    "jitter_ratio",
                }
            ),
        )
        claims = self.store.claim_target_deliveries(
            target_id=_identifier(body, "target_id"),
            provider_id=_identifier(body, "provider_id"),
            worker_id=_identifier(body, "worker_id"),
            capability_version=_identifier(body, "capability_version"),
            limit=_integer(body, "limit", default=20, minimum=1, maximum=MAX_CLAIM_BATCH),
            lease_seconds=_integer(
                body,
                "lease_seconds",
                default=120,
                minimum=10,
                maximum=1800,
            ),
            max_attempts=_integer(
                body,
                "max_attempts",
                default=8,
                minimum=1,
                maximum=100,
            ),
            base_backoff_seconds=_integer(
                body,
                "base_backoff_seconds",
                default=5,
                minimum=1,
                maximum=86400,
            ),
            max_backoff_seconds=_integer(
                body,
                "max_backoff_seconds",
                default=3600,
                minimum=1,
                maximum=604800,
            ),
            jitter_ratio=_ratio(body, "jitter_ratio", default=0.20),
        )
        return {
            "ok": True,
            "schema_version": PROVIDER_API_SCHEMA_VERSION,
            "claims": [_claim_dict(claim) for claim in claims],
        }

    def _renew(self, body: Mapping[str, Any]) -> dict[str, Any]:
        _only(
            body,
            frozenset(
                {
                    "target_delivery_id",
                    "worker_id",
                    "claim_token",
                    "lease_seconds",
                    "max_claim_lifetime_seconds",
                }
            ),
        )
        expires = self.store.renew_claim(
            target_delivery_id=_identifier(body, "target_delivery_id"),
            worker_id=_identifier(body, "worker_id"),
            claim_token=_claim_token(body),
            lease_seconds=_integer(
                body,
                "lease_seconds",
                default=120,
                minimum=10,
                maximum=1800,
            ),
            max_claim_lifetime_seconds=_integer(
                body,
                "max_claim_lifetime_seconds",
                default=1800,
                minimum=30,
                maximum=86400,
            ),
        )
        return {"ok": True, "claim_expires_at": expires}

    def _register_recipients(self, body: Mapping[str, Any]) -> dict[str, Any]:
        _only(
            body,
            frozenset(
                {
                    "target_delivery_id",
                    "worker_id",
                    "claim_token",
                    "recipient_refs",
                }
            ),
        )
        snapshots = self.store.register_recipients(
            target_delivery_id=_identifier(body, "target_delivery_id"),
            worker_id=_identifier(body, "worker_id"),
            claim_token=_claim_token(body),
            recipient_refs=_recipient_refs(body),
        )
        return {"ok": True, "recipients": [_recipient_dict(row) for row in snapshots]}

    def _record_recipients(self, body: Mapping[str, Any]) -> dict[str, Any]:
        _only(
            body,
            frozenset(
                {
                    "target_delivery_id",
                    "worker_id",
                    "claim_token",
                    "outcomes",
                }
            ),
        )
        snapshots = self.store.record_recipient_outcomes(
            target_delivery_id=_identifier(body, "target_delivery_id"),
            worker_id=_identifier(body, "worker_id"),
            claim_token=_claim_token(body),
            outcomes=_outcomes(body),
        )
        return {"ok": True, "recipients": [_recipient_dict(row) for row in snapshots]}

    def _complete(self, body: Mapping[str, Any]) -> dict[str, Any]:
        _only(
            body,
            frozenset(
                {
                    "target_delivery_id",
                    "worker_id",
                    "claim_token",
                    "outcome",
                    "error_class",
                    "retry_after_seconds",
                    "max_attempts",
                    "base_backoff_seconds",
                    "max_backoff_seconds",
                    "jitter_ratio",
                }
            ),
        )
        outcome = body.get("outcome")
        if outcome is not None and not isinstance(outcome, str):
            raise ProviderApiValidationError("outcome must be a string or null")
        state = self.store.complete_target(
            target_delivery_id=_identifier(body, "target_delivery_id"),
            worker_id=_identifier(body, "worker_id"),
            claim_token=_claim_token(body),
            outcome=outcome,
            error_class=_optional_reason(body, "error_class"),
            retry_after_seconds=_integer(
                body,
                "retry_after_seconds",
                default=0,
                minimum=0,
                maximum=604800,
            ),
            max_attempts=_integer(
                body,
                "max_attempts",
                default=8,
                minimum=1,
                maximum=100,
            ),
            base_backoff_seconds=_integer(
                body,
                "base_backoff_seconds",
                default=5,
                minimum=1,
                maximum=86400,
            ),
            max_backoff_seconds=_integer(
                body,
                "max_backoff_seconds",
                default=3600,
                minimum=1,
                maximum=604800,
            ),
            jitter_ratio=_ratio(body, "jitter_ratio", default=0.20),
        )
        return {"ok": True, "state": state}

    def _heartbeat(self, body: Mapping[str, Any]) -> dict[str, Any]:
        _only(
            body,
            frozenset(
                {
                    "worker_id",
                    "target_id",
                    "provider_id",
                    "capability_version",
                    "state",
                    "details",
                }
            ),
        )
        self.store.heartbeat(
            worker_id=_identifier(body, "worker_id"),
            target_id=_identifier(body, "target_id"),
            provider_id=_identifier(body, "provider_id"),
            capability_version=_identifier(body, "capability_version"),
            state=_identifier(body, "state"),
            details=_heartbeat_details(body),
        )
        return {"ok": True}
