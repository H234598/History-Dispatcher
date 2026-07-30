from __future__ import annotations

from dataclasses import replace
from typing import Any, Mapping

from .config import DispatcherConfig
from .config_v2_api import (
    ConfigApplyPreviewV2,
    ConfigV2Error,
    TelegramDispatchProvider,
    TelegramRoutingConfigV2,
    apply_fingerprint,
    preview_provider_change,
)


class ConfigApplyConflict(ConfigV2Error):
    pass


def telegram_routing_from_raw(raw: Mapping[str, Any] | None) -> TelegramRoutingConfigV2:
    routing = dict(raw or {})
    telegram = routing.get("telegram", {})
    if not isinstance(telegram, Mapping):
        raise ConfigV2Error("routing.telegram must be a table")
    return TelegramRoutingConfigV2.from_mapping(telegram)


def public_routing_status(raw: Mapping[str, Any] | None) -> dict[str, Any]:
    return {
        "routing": {
            "telegram": telegram_routing_from_raw(raw).redacted(),
        }
    }


def preview_telegram_provider_change(
    *,
    current_revision: str,
    requested_provider: str,
) -> ConfigApplyPreviewV2:
    return preview_provider_change(
        expected_revision=current_revision,
        provider=requested_provider,
    )


def apply_telegram_provider_change(
    config: DispatcherConfig,
    *,
    expected_revision: str,
    requested_provider: str,
    current_revision: str,
) -> DispatcherConfig:
    if expected_revision != current_revision:
        raise ConfigApplyConflict("config revision changed before apply")
    provider = TelegramDispatchProvider.parse(requested_provider)
    # Provider selection is intentionally prepared as a revisioned boundary.
    # The persisted TOML mutation follows with the audited config writer.
    _ = apply_fingerprint(
        expected_revision=expected_revision,
        provider=provider,
    )
    return replace(config)
