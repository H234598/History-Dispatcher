from __future__ import annotations

"""Config-v2 contract primitives.

This module freezes the provider-selection boundary before wiring it into the
mutable config loader. It intentionally contains no credential handling and no
Secret Service access.
"""

from dataclasses import dataclass
from enum import Enum
import hashlib
import json
from typing import Any


class TelegramDispatchProvider(str, Enum):
    TEEBOTUS = "teebotus"
    HISTORY_DISPATCHER = "history_dispatcher"


@dataclass(frozen=True)
class TelegramRoutingConfigV2:
    provider: TelegramDispatchProvider = TelegramDispatchProvider.TEEBOTUS

    @classmethod
    def from_mapping(cls, value: object) -> "TelegramRoutingConfigV2":
        if not isinstance(value, dict):
            raise ValueError("routing.telegram must be a table")
        unknown = set(value) - {"provider"}
        if unknown:
            raise ValueError(
                "unknown routing.telegram keys: " + ", ".join(sorted(unknown))
            )
        raw = str(value.get("provider", TelegramDispatchProvider.TEEBOTUS.value)).strip()
        try:
            provider = TelegramDispatchProvider(raw)
        except ValueError as exc:
            raise ValueError("unsupported Telegram dispatch provider") from exc
        return cls(provider=provider)

    def as_redacted_dict(self) -> dict[str, str]:
        return {"provider": self.provider.value}

    def revision_fragment(self) -> dict[str, str]:
        return self.as_redacted_dict()


@dataclass(frozen=True)
class ConfigApplyRequestV2:
    expected_revision: str
    preview_token: str
    changes: dict[str, Any]

    def fingerprint(self) -> str:
        payload = {
            "expected_revision": self.expected_revision,
            "changes": self.changes,
        }
        encoded = json.dumps(
            payload,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        ).encode("utf-8")
        return hashlib.sha256(encoded).hexdigest()


def validate_provider_transition(
    current: TelegramRoutingConfigV2,
    requested: TelegramRoutingConfigV2,
) -> dict[str, str]:
    if current.provider == requested.provider:
        return {"status": "unchanged"}
    return {
        "status": "staged",
        "from": current.provider.value,
        "to": requested.provider.value,
        "effect": "new_route_plans_only",
    }
