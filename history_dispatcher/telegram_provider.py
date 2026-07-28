from __future__ import annotations

import hashlib
import json
import re
import unicodedata
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from enum import Enum
from typing import Any


TELEGRAM_PROVIDER_SCHEMA_VERSION = 1
MAX_NATIVE_RECIPIENT_REFS = 32
MAX_OPAQUE_REF_LENGTH = 96
TEEBOTUS_CAPABILITY_V2 = "history-dispatcher-telegram-v2"

_OPAQUE_REF_RE = re.compile(r"^[a-z][a-z0-9_.-]{0,95}$")
_REASON_CODE_RE = re.compile(r"^[a-z][a-z0-9_]{0,95}$")
_TELEGRAM_TOKEN_RE = re.compile(r"^(?:bot)?\d{6,12}:[A-Za-z0-9_-]{20,}$", re.IGNORECASE)
_RAW_CHAT_ID_RE = re.compile(r"^-?\d{5,20}$")
_ALLOWED_RECIPIENT_STATUSES = frozenset(
    {
        "accepted",
        "delivered",
        "acknowledged",
        "failed",
        "skipped",
        "possible_duplicate",
    }
)
_SUCCESS_RANK = {
    "accepted": 1,
    "delivered": 2,
    "acknowledged": 3,
}


class TelegramProviderError(ValueError):
    """Raised when a Telegram provider contract is unsafe or ambiguous."""


class TelegramDispatchProvider(str, Enum):
    TEEBOTUS = "teebotus"
    HISTORY_DISPATCHER = "history_dispatcher"

    @classmethod
    def parse(cls, value: TelegramDispatchProvider | str) -> TelegramDispatchProvider:
        if isinstance(value, cls):
            return value
        normalized = unicodedata.normalize("NFC", str(value or "").strip()).casefold()
        try:
            return cls(normalized)
        except ValueError as exc:
            raise TelegramProviderError("unsupported Telegram dispatch provider") from exc


def _normalize_opaque_ref(value: Any, *, field: str) -> str:
    if not isinstance(value, str):
        raise TelegramProviderError(f"{field} must be an opaque string reference")
    normalized = unicodedata.normalize("NFC", value.strip()).casefold()
    if not normalized:
        raise TelegramProviderError(f"{field} must not be empty")
    if len(normalized) > MAX_OPAQUE_REF_LENGTH:
        raise TelegramProviderError(f"{field} exceeds the maximum length")
    if any(ord(char) < 0x20 or ord(char) == 0x7F for char in normalized):
        raise TelegramProviderError(f"{field} contains control characters")
    if _TELEGRAM_TOKEN_RE.fullmatch(normalized):
        raise TelegramProviderError(f"{field} must not contain a Telegram token")
    if _RAW_CHAT_ID_RE.fullmatch(normalized):
        raise TelegramProviderError(f"{field} must not contain a raw Telegram chat id")
    if not _OPAQUE_REF_RE.fullmatch(normalized):
        raise TelegramProviderError(f"{field} is not a valid opaque reference")
    return normalized


def _normalize_recipient_refs(values: Iterable[str]) -> tuple[str, ...]:
    if isinstance(values, (str, bytes, bytearray)):
        raise TelegramProviderError("recipient_refs must be a sequence of opaque references")
    normalized: list[str] = []
    seen: set[str] = set()
    for value in values:
        recipient_ref = _normalize_opaque_ref(value, field="recipient_ref")
        if recipient_ref in seen:
            continue
        seen.add(recipient_ref)
        normalized.append(recipient_ref)
        if len(normalized) > MAX_NATIVE_RECIPIENT_REFS:
            raise TelegramProviderError("too many native Telegram recipient references")
    return tuple(normalized)


@dataclass(frozen=True)
class TelegramTransportBinding:
    """Immutable provider decision embedded in one route plan.

    No automatic provider fallback is permitted after this binding is created.
    Native credential and recipient values are opaque references only; actual bot
    tokens and chat IDs remain in Secret Service or another approved credential
    store and never enter route plans, snapshots, dconf, or logs.
    """

    provider: TelegramDispatchProvider | str
    credential_ref: str = ""
    recipient_refs: tuple[str, ...] = ()
    bridge_capability: str = ""
    provider_schema_version: int = TELEGRAM_PROVIDER_SCHEMA_VERSION

    def __post_init__(self) -> None:
        provider = TelegramDispatchProvider.parse(self.provider)
        if int(self.provider_schema_version) != TELEGRAM_PROVIDER_SCHEMA_VERSION:
            raise TelegramProviderError("unsupported Telegram provider schema version")

        credential_ref = ""
        recipient_refs: tuple[str, ...] = ()
        bridge_capability = ""
        if provider is TelegramDispatchProvider.TEEBOTUS:
            if self.credential_ref or self.recipient_refs:
                raise TelegramProviderError(
                    "TeeBotus bindings must not contain native credential or recipient references"
                )
            bridge_capability = _normalize_opaque_ref(
                self.bridge_capability or TEEBOTUS_CAPABILITY_V2,
                field="bridge_capability",
            )
        else:
            if self.bridge_capability:
                raise TelegramProviderError(
                    "native History-Dispatcher bindings must not contain a TeeBotus capability"
                )
            credential_ref = _normalize_opaque_ref(
                self.credential_ref,
                field="credential_ref",
            )
            recipient_refs = _normalize_recipient_refs(self.recipient_refs)
            if not recipient_refs:
                raise TelegramProviderError(
                    "native History-Dispatcher Telegram requires at least one recipient reference"
                )

        object.__setattr__(self, "provider", provider)
        object.__setattr__(self, "credential_ref", credential_ref)
        object.__setattr__(self, "recipient_refs", recipient_refs)
        object.__setattr__(self, "bridge_capability", bridge_capability)
        object.__setattr__(
            self,
            "provider_schema_version",
            TELEGRAM_PROVIDER_SCHEMA_VERSION,
        )

    @classmethod
    def teebotus(
        cls,
        *,
        capability: str = TEEBOTUS_CAPABILITY_V2,
    ) -> TelegramTransportBinding:
        return cls(
            provider=TelegramDispatchProvider.TEEBOTUS,
            bridge_capability=capability,
        )

    @classmethod
    def history_dispatcher(
        cls,
        *,
        credential_ref: str,
        recipient_refs: Iterable[str],
    ) -> TelegramTransportBinding:
        return cls(
            provider=TelegramDispatchProvider.HISTORY_DISPATCHER,
            credential_ref=credential_ref,
            recipient_refs=tuple(recipient_refs),
        )

    def as_route_plan_fragment(self) -> dict[str, Any]:
        fragment: dict[str, Any] = {
            "schema_version": self.provider_schema_version,
            "provider": self.provider.value,
        }
        if self.provider is TelegramDispatchProvider.TEEBOTUS:
            fragment["bridge_capability"] = self.bridge_capability
        else:
            fragment["credential_ref"] = self.credential_ref
            fragment["recipient_refs"] = list(self.recipient_refs)
        return fragment

    def plan_hash(self) -> str:
        encoded = json.dumps(
            self.as_route_plan_fragment(),
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        ).encode("utf-8")
        return hashlib.sha256(encoded).hexdigest()

    def status_view(self) -> dict[str, Any]:
        """Return a redacted view safe for status and settings summaries."""

        return {
            "schema_version": self.provider_schema_version,
            "provider": self.provider.value,
            "configured": True,
            "recipient_count": len(self.recipient_refs),
            "bridge_capability": (
                self.bridge_capability
                if self.provider is TelegramDispatchProvider.TEEBOTUS
                else ""
            ),
        }

    def require_worker_provider(
        self,
        worker_provider: TelegramDispatchProvider | str,
    ) -> None:
        actual = TelegramDispatchProvider.parse(worker_provider)
        if actual is not self.provider:
            raise TelegramProviderError(
                "Telegram worker provider does not match the immutable route plan; "
                "automatic cross-provider fallback is forbidden"
            )


@dataclass(frozen=True)
class TelegramRecipientOutcome:
    """Transport-neutral recipient result adapted from TeeBotus monotone merging."""

    recipient_ref: str
    status: str
    possible_duplicate: bool = False
    message_ref_key: str = ""
    reason_code: str = ""

    def __post_init__(self) -> None:
        recipient_ref = _normalize_opaque_ref(
            self.recipient_ref,
            field="recipient_ref",
        )
        status = unicodedata.normalize("NFC", str(self.status or "").strip()).casefold()
        if status not in _ALLOWED_RECIPIENT_STATUSES:
            raise TelegramProviderError("unsupported Telegram recipient status")
        possible_duplicate = bool(self.possible_duplicate or status == "possible_duplicate")
        if possible_duplicate and status in _SUCCESS_RANK:
            status = "possible_duplicate"
        message_ref_key = ""
        if self.message_ref_key:
            message_ref_key = _normalize_opaque_ref(
                self.message_ref_key,
                field="message_ref_key",
            )
        reason_code = ""
        if self.reason_code:
            reason_code = unicodedata.normalize(
                "NFC",
                str(self.reason_code).strip(),
            ).casefold()
            if not _REASON_CODE_RE.fullmatch(reason_code):
                raise TelegramProviderError("invalid Telegram recipient reason code")
        object.__setattr__(self, "recipient_ref", recipient_ref)
        object.__setattr__(self, "status", status)
        object.__setattr__(self, "possible_duplicate", possible_duplicate)
        object.__setattr__(self, "message_ref_key", message_ref_key)
        object.__setattr__(self, "reason_code", reason_code)

    @property
    def successful(self) -> bool:
        return self.status in _SUCCESS_RANK and not self.possible_duplicate


def _prefer_recipient_outcome(
    previous: TelegramRecipientOutcome,
    current: TelegramRecipientOutcome,
) -> TelegramRecipientOutcome:
    if previous.recipient_ref != current.recipient_ref:
        raise TelegramProviderError("cannot merge different Telegram recipients")
    previous_rank = _SUCCESS_RANK.get(previous.status, -1)
    current_rank = _SUCCESS_RANK.get(current.status, -1)
    if previous_rank >= 0:
        if current_rank > previous_rank:
            return current
        return previous
    if current_rank >= 0:
        return current
    if previous.status == "skipped":
        return previous
    if previous.status == "possible_duplicate":
        return previous
    if current.status in {"skipped", "possible_duplicate"}:
        return current
    return current


def merge_recipient_outcomes(
    existing: Iterable[TelegramRecipientOutcome | Mapping[str, Any]],
    current: Iterable[TelegramRecipientOutcome | Mapping[str, Any]],
) -> tuple[TelegramRecipientOutcome, ...]:
    """Merge outcomes without downgrading accepted/delivered/acknowledged states.

    The behavior is adapted from TeeBotus recipient-result ranking and inactive
    recipient reconciliation. It is kept transport-neutral so both TeeBotus and
    the native History-Dispatcher Telegram worker use the same store contract.
    """

    merged: dict[str, TelegramRecipientOutcome] = {}
    order: list[str] = []
    for raw in (*tuple(existing), *tuple(current)):
        outcome = (
            raw
            if isinstance(raw, TelegramRecipientOutcome)
            else TelegramRecipientOutcome(**dict(raw))
        )
        previous = merged.get(outcome.recipient_ref)
        if previous is None:
            merged[outcome.recipient_ref] = outcome
            order.append(outcome.recipient_ref)
        else:
            merged[outcome.recipient_ref] = _prefer_recipient_outcome(
                previous,
                outcome,
            )
    return tuple(merged[recipient_ref] for recipient_ref in order)
