from __future__ import annotations

import hashlib
import json
import secrets
import threading
import time
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .config import (
    DispatcherConfig,
    _opaque_profile,
    _recipient_profiles,
    config_revision,
)
from .crypto import SecretServiceKeyProvider
from .telegram_provider import TelegramDispatchProvider


CONFIG_V2_SCHEMA_VERSION = 2
MAX_CONFIG_PATCH_BYTES = 64 * 1024
MAX_CONFIG_PREVIEWS = 128
CONFIG_PREVIEW_TTL_SECONDS = 60


class ConfigV2ValidationError(ValueError):
    pass


class ConfigV2ApplyError(RuntimeError):
    pass


@dataclass(frozen=True)
class TelegramPatchV2:
    provider: TelegramDispatchProvider
    credential_ref: str
    recipient_refs: tuple[str, ...]

    def canonical_dict(self) -> dict[str, object]:
        return {
            "provider": self.provider.value,
            "credential_ref": self.credential_ref,
            "recipient_refs": list(self.recipient_refs),
        }


@dataclass(frozen=True)
class ConfigPatchV2:
    telegram: TelegramPatchV2

    def canonical_dict(self) -> dict[str, object]:
        return {"routing": {"telegram": self.telegram.canonical_dict()}}

    def fingerprint(self, *, expected_revision: str) -> str:
        encoded = json.dumps(
            {
                "schema_version": CONFIG_V2_SCHEMA_VERSION,
                "expected_revision": expected_revision,
                "patch": self.canonical_dict(),
            },
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        ).encode("utf-8")
        return hashlib.sha256(encoded).hexdigest()


@dataclass(frozen=True)
class ConfigPreviewV2:
    expected_revision: str
    fingerprint: str
    confirmation: str
    effect: str
    changes: Mapping[str, Mapping[str, object]]
    preview_token: str
    expires_in_seconds: int

    def as_dict(self) -> dict[str, object]:
        return {
            "schema_version": CONFIG_V2_SCHEMA_VERSION,
            "expected_revision": self.expected_revision,
            "fingerprint": self.fingerprint,
            "confirmation": self.confirmation,
            "effect": self.effect,
            "changes": {
                key: dict(value) for key, value in self.changes.items()
            },
            "preview_token": self.preview_token,
            "expires_in_seconds": self.expires_in_seconds,
        }


@dataclass(frozen=True)
class _PreviewEntry:
    token_hash: str
    fingerprint: str
    expected_revision: str
    expires_at: float
    patch: ConfigPatchV2


class ConfigManagerV2:
    def __init__(
        self,
        config: DispatcherConfig,
        *,
        database_path: Path,
        key_provider: SecretServiceKeyProvider,
        clock: Callable[[], float] | None = None,
        token_factory: Callable[[], str] | None = None,
    ) -> None:
        self._config = config
        self.database_path = Path(database_path)
        self.key_provider = key_provider
        self._clock = clock or time.monotonic
        self._token_factory = token_factory or (
            lambda: secrets.token_urlsafe(32)
        )
        self._previews: dict[str, _PreviewEntry] = {}
        self._lock = threading.RLock()

    @property
    def config(self) -> DispatcherConfig:
        return self._config

    def replace_config(self, config: DispatcherConfig) -> None:
        with self._lock:
            self._config = config
            self._prune_previews_locked()

    def get_redacted(self) -> dict[str, object]:
        config = self._config
        return {
            "schema_version": CONFIG_V2_SCHEMA_VERSION,
            "config_revision": config_revision(config),
            "routing": {
                "telegram": {
                    "provider": config.telegram_provider.value,
                    "credential_ref": config.telegram_credential_ref,
                    "recipient_refs": list(config.telegram_recipient_refs),
                }
            },
        }

    def validate_patch(self, raw_patch: object) -> ConfigPatchV2:
        patch = self._bounded_mapping(raw_patch)
        unknown_root = set(patch) - {"routing"}
        if unknown_root:
            raise ConfigV2ValidationError(
                "unknown Config v2 field(s): "
                + ", ".join(sorted(str(key) for key in unknown_root))
            )
        routing = patch.get("routing")
        if not isinstance(routing, Mapping):
            raise ConfigV2ValidationError("routing must be an object")
        routing_map = dict(routing)
        unknown_routing = set(routing_map) - {"telegram"}
        if unknown_routing:
            raise ConfigV2ValidationError(
                "unknown routing field(s): "
                + ", ".join(sorted(str(key) for key in unknown_routing))
            )
        telegram = routing_map.get("telegram")
        if not isinstance(telegram, Mapping):
            raise ConfigV2ValidationError(
                "routing.telegram must be an object"
            )
        telegram_map = dict(telegram)
        unknown_telegram = set(telegram_map) - {
            "provider",
            "credential_ref",
            "recipient_refs",
        }
        if unknown_telegram:
            raise ConfigV2ValidationError(
                "unknown routing.telegram field(s): "
                + ", ".join(
                    sorted(str(key) for key in unknown_telegram)
                )
            )
        current = self._config
        try:
            provider = TelegramDispatchProvider.parse(
                telegram_map.get(
                    "provider",
                    current.telegram_provider.value,
                )
            )
            credential_ref = _opaque_profile(
                telegram_map.get(
                    "credential_ref",
                    current.telegram_credential_ref,
                ),
                "routing.telegram.credential_ref",
                allow_empty=True,
            )
            recipient_refs = _recipient_profiles(
                telegram_map.get(
                    "recipient_refs",
                    list(current.telegram_recipient_refs),
                )
            )
        except ValueError as exc:
            raise ConfigV2ValidationError(str(exc)) from exc
        if provider is TelegramDispatchProvider.TEEBOTUS and (
            credential_ref or recipient_refs
        ):
            raise ConfigV2ValidationError(
                "native Telegram profiles require provider history_dispatcher"
            )
        return ConfigPatchV2(
            telegram=TelegramPatchV2(
                provider=provider,
                credential_ref=credential_ref,
                recipient_refs=recipient_refs,
            )
        )

    def preview_apply(
        self,
        *,
        expected_revision: str,
        patch: object,
    ) -> ConfigPreviewV2:
        normalized_revision = str(expected_revision or "").strip().lower()
        with self._lock:
            current_revision = config_revision(self._config)
            if normalized_revision != current_revision:
                raise ConfigV2ValidationError(
                    "config revision changed before preview"
                )
            typed_patch = self.validate_patch(patch)
            fingerprint = typed_patch.fingerprint(
                expected_revision=normalized_revision
            )
            token = self._token_factory()
            if (
                not isinstance(token, str)
                or len(token) < 32
                or len(token) > 512
                or any(ord(character) < 0x20 for character in token)
            ):
                raise ConfigV2ValidationError(
                    "preview token factory returned an unsafe token"
                )
            self._prune_previews_locked()
            if len(self._previews) >= MAX_CONFIG_PREVIEWS:
                oldest_key = min(
                    self._previews,
                    key=lambda key: self._previews[key].expires_at,
                )
                self._previews.pop(oldest_key, None)
            token_hash = self._token_hash(token)
            self._previews[token_hash] = _PreviewEntry(
                token_hash=token_hash,
                fingerprint=fingerprint,
                expected_revision=normalized_revision,
                expires_at=self._clock() + CONFIG_PREVIEW_TTL_SECONDS,
                patch=typed_patch,
            )
            return ConfigPreviewV2(
                expected_revision=normalized_revision,
                fingerprint=fingerprint,
                confirmation=f"APPLY {fingerprint[:12]}",
                effect="new_route_plans_only",
                changes=self._changes(typed_patch),
                preview_token=token,
                expires_in_seconds=CONFIG_PREVIEW_TTL_SECONDS,
            )

    def _changes(
        self,
        patch: ConfigPatchV2,
    ) -> dict[str, dict[str, object]]:
        current = self._config
        desired = patch.telegram
        fields: tuple[tuple[str, object, object], ...] = (
            (
                "routing.telegram.provider",
                current.telegram_provider.value,
                desired.provider.value,
            ),
            (
                "routing.telegram.credential_ref",
                current.telegram_credential_ref,
                desired.credential_ref,
            ),
            (
                "routing.telegram.recipient_refs",
                list(current.telegram_recipient_refs),
                list(desired.recipient_refs),
            ),
        )
        return {
            name: {"from": before, "to": after}
            for name, before, after in fields
            if before != after
        }

    def _bounded_mapping(self, value: object) -> dict[str, Any]:
        if not isinstance(value, Mapping):
            raise ConfigV2ValidationError("Config v2 patch must be an object")
        patch = dict(value)
        try:
            encoded = json.dumps(
                patch,
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
                allow_nan=False,
            ).encode("utf-8")
        except (TypeError, ValueError) as exc:
            raise ConfigV2ValidationError(
                "Config v2 patch must contain finite JSON"
            ) from exc
        if len(encoded) > MAX_CONFIG_PATCH_BYTES:
            raise ConfigV2ValidationError(
                "Config v2 patch exceeds 64 KiB"
            )
        return patch

    @staticmethod
    def _token_hash(token: str) -> str:
        return hashlib.sha256(token.encode("utf-8")).hexdigest()

    def _prune_previews_locked(self) -> None:
        now = self._clock()
        expired = [
            key
            for key, entry in self._previews.items()
            if entry.expires_at <= now
        ]
        for key in expired:
            self._previews.pop(key, None)
