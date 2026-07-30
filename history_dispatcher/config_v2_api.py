from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from enum import Enum
from typing import Any, Mapping


class ConfigV2Error(ValueError):
    pass


class TelegramDispatchProvider(str, Enum):
    TEEBOTUS = "teebotus"
    HISTORY_DISPATCHER = "history_dispatcher"

    @classmethod
    def parse(cls, value: object) -> "TelegramDispatchProvider":
        try:
            return cls(str(value).strip().casefold())
        except ValueError as exc:
            raise ConfigV2Error("unsupported telegram provider") from exc


@dataclass(frozen=True)
class TelegramRoutingConfigV2:
    provider: TelegramDispatchProvider = TelegramDispatchProvider.TEEBOTUS

    @classmethod
    def from_mapping(cls, value: Mapping[str, Any] | None) -> "TelegramRoutingConfigV2":
        raw = dict(value or {})
        unknown = set(raw) - {"provider"}
        if unknown:
            raise ConfigV2Error(", ".join(sorted(unknown)))
        return cls(provider=TelegramDispatchProvider.parse(raw.get("provider", cls().provider.value)))

    def redacted(self) -> dict[str, str]:
        return {"provider": self.provider.value}


@dataclass(frozen=True)
class ConfigApplyPreviewV2:
    expected_revision: str
    requested_provider: TelegramDispatchProvider
    fingerprint: str


def apply_fingerprint(*, expected_revision: str, provider: TelegramDispatchProvider) -> str:
    payload = json.dumps(
        {
            "expected_revision": expected_revision,
            "provider": provider.value,
        },
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def preview_provider_change(
    *,
    expected_revision: str,
    provider: str,
) -> ConfigApplyPreviewV2:
    selected = TelegramDispatchProvider.parse(provider)
    return ConfigApplyPreviewV2(
        expected_revision=expected_revision,
        requested_provider=selected,
        fingerprint=apply_fingerprint(
            expected_revision=expected_revision,
            provider=selected,
        ),
    )


def redacted_config_status(provider: TelegramRoutingConfigV2) -> dict[str, Any]:
    return {
        "routing": {
            "telegram": provider.redacted(),
        }
    }
