from __future__ import annotations

import hashlib
import hmac
import json
import os
import secrets
import sqlite3
import threading
import time
import uuid
from collections.abc import Callable, Mapping
from dataclasses import dataclass, replace
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .config import (
    DispatcherConfig,
    _opaque_profile,
    _recipient_profiles,
    config_revision,
    load_config,
    write_config,
)
from .crypto import SecretServiceKeyProvider
from .identifiers import persistent_opaque_id
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

    def apply_preview(
        self,
        *,
        expected_revision: str,
        preview_token: str,
        fingerprint: str,
        confirmation: str,
        actor: str,
    ) -> dict[str, object]:
        normalized_revision = str(expected_revision or "").strip().lower()
        normalized_fingerprint = str(fingerprint or "").strip().lower()
        normalized_actor = self._validate_actor(actor)
        if not isinstance(preview_token, str) or not preview_token:
            raise ConfigV2ApplyError("preview token is invalid")
        token_hash = self._token_hash(preview_token)
        with self._lock:
            entry = self._previews.pop(token_hash, None)
            if entry is None:
                raise ConfigV2ApplyError("preview token is unknown or consumed")
            if entry.expires_at <= self._clock():
                raise ConfigV2ApplyError("preview token expired")
            self._require_audit_schema()
            if normalized_revision != entry.expected_revision:
                self._audit_rejection(
                    actor=normalized_actor,
                    revision_before=entry.expected_revision,
                    preview_token_hash=token_hash,
                    reason_code="revision_mismatch",
                )
                raise ConfigV2ApplyError("config revision mismatch")
            if not hmac.compare_digest(
                normalized_fingerprint,
                entry.fingerprint,
            ):
                self._audit_rejection(
                    actor=normalized_actor,
                    revision_before=entry.expected_revision,
                    preview_token_hash=token_hash,
                    reason_code="fingerprint_mismatch",
                )
                raise ConfigV2ApplyError("preview fingerprint mismatch")
            expected_confirmation = f"APPLY {entry.fingerprint[:12]}"
            if not hmac.compare_digest(
                str(confirmation or ""),
                expected_confirmation,
            ):
                self._audit_rejection(
                    actor=normalized_actor,
                    revision_before=entry.expected_revision,
                    preview_token_hash=token_hash,
                    reason_code="confirmation_mismatch",
                )
                raise ConfigV2ApplyError("preview confirmation mismatch")

            current = load_config(self._config.config_path)
            current_revision = config_revision(current)
            if current_revision != entry.expected_revision:
                self._audit_rejection(
                    actor=normalized_actor,
                    revision_before=entry.expected_revision,
                    revision_after=current_revision,
                    preview_token_hash=token_hash,
                    reason_code="revision_changed",
                )
                raise ConfigV2ApplyError(
                    "config revision changed after preview"
                )

            desired = entry.patch.telegram
            candidate = replace(
                current,
                telegram_provider=desired.provider,
                telegram_credential_ref=desired.credential_ref,
                telegram_recipient_refs=desired.recipient_refs,
            )
            affected_count = len(self._changes_against(current, entry.patch))
            before_bytes = (
                current.config_path.read_bytes()
                if current.config_path.exists()
                else None
            )
            try:
                write_config(candidate)
                reloaded = load_config(candidate.config_path)
                candidate_revision = config_revision(candidate)
                reloaded_revision = config_revision(reloaded)
                if reloaded_revision != candidate_revision:
                    raise ConfigV2ApplyError(
                        "post-write config verification failed"
                    )
            except Exception as exc:
                self._restore_config_bytes(current.config_path, before_bytes)
                self._config = load_config(current.config_path)
                self._audit_rejection(
                    actor=normalized_actor,
                    revision_before=current_revision,
                    preview_token_hash=token_hash,
                    reason_code="write_failed_rolled_back",
                )
                if isinstance(exc, ConfigV2ApplyError):
                    raise
                raise ConfigV2ApplyError(
                    "config write failed and was rolled back"
                ) from exc

            try:
                self._audit_apply(
                    actor_key=self._actor_key(normalized_actor),
                    revision_before=current_revision,
                    revision_after=reloaded_revision,
                    preview_token_hash=token_hash,
                    result="applied",
                    affected_count=affected_count,
                    reason_code="applied",
                )
            except Exception as exc:
                self._restore_config_bytes(current.config_path, before_bytes)
                self._config = load_config(current.config_path)
                self._audit_rejection(
                    actor=normalized_actor,
                    revision_before=current_revision,
                    revision_after=reloaded_revision,
                    preview_token_hash=token_hash,
                    reason_code="audit_failed_rolled_back",
                )
                raise ConfigV2ApplyError(
                    "config apply audit failed and was rolled back"
                ) from exc

            self._config = reloaded
            return {
                "ok": True,
                "schema_version": CONFIG_V2_SCHEMA_VERSION,
                "config_revision": reloaded_revision,
                "restart_required": False,
                "effect": "new_route_plans_only",
                "routing": {
                    "telegram": {
                        "provider": reloaded.telegram_provider.value,
                        "credential_ref": reloaded.telegram_credential_ref,
                        "recipient_refs": list(
                            reloaded.telegram_recipient_refs
                        ),
                    }
                },
            }

    def _changes(
        self,
        patch: ConfigPatchV2,
    ) -> dict[str, dict[str, object]]:
        return self._changes_against(self._config, patch)

    @staticmethod
    def _changes_against(
        current: DispatcherConfig,
        patch: ConfigPatchV2,
    ) -> dict[str, dict[str, object]]:
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

    @staticmethod
    def _validate_actor(actor: object) -> str:
        if not isinstance(actor, str):
            raise ConfigV2ApplyError("config actor must be a string")
        normalized = actor.strip()
        if (
            not normalized
            or len(normalized) > 160
            or any(
                ord(character) < 0x20 or ord(character) == 0x7F
                for character in normalized
            )
        ):
            raise ConfigV2ApplyError("config actor is invalid")
        return normalized

    def _actor_key(self, actor: str) -> str:
        return persistent_opaque_id(
            self.key_provider,
            "config-actor",
            actor,
            prefix="actor",
        )

    def _require_audit_schema(self) -> None:
        try:
            with sqlite3.connect(self.database_path) as db:
                row = db.execute(
                    "SELECT 1 FROM sqlite_master "
                    "WHERE type='table' AND name='config_audit'"
                ).fetchone()
        except sqlite3.Error as exc:
            raise ConfigV2ApplyError(
                "config_audit schema is unavailable"
            ) from exc
        if row is None:
            raise ConfigV2ApplyError(
                "config_audit table is unavailable"
            )

    def _audit_rejection(
        self,
        *,
        actor: str,
        revision_before: str,
        preview_token_hash: str,
        reason_code: str,
        revision_after: str = "",
    ) -> None:
        try:
            self._audit_apply(
                actor_key=self._actor_key(actor),
                revision_before=revision_before,
                revision_after=revision_after,
                preview_token_hash=preview_token_hash,
                result="rejected",
                affected_count=0,
                reason_code=reason_code,
            )
        except Exception:
            # A rejection remains fail-closed even when its best-effort audit
            # cannot be recorded. Successful writes never use this path.
            pass

    def _audit_apply(
        self,
        *,
        actor_key: str,
        revision_before: str,
        revision_after: str,
        preview_token_hash: str,
        result: str,
        affected_count: int,
        reason_code: str,
    ) -> None:
        created_at = datetime.now(timezone.utc).isoformat(timespec="seconds")
        audit_id = persistent_opaque_id(
            self.key_provider,
            "config-audit",
            f"{created_at}|{uuid.uuid4().hex}",
            prefix="audit",
        )
        with sqlite3.connect(self.database_path, timeout=30) as db:
            db.execute("PRAGMA foreign_keys=ON")
            db.execute(
                "INSERT INTO config_audit("
                "id,actor_key,operation,revision_before,revision_after,"
                "preview_token_hash,result,affected_count,reason_code,created_at"
                ") VALUES (?,?,?,?,?,?,?,?,?,?)",
                (
                    audit_id,
                    actor_key,
                    "config.apply_v2",
                    revision_before,
                    revision_after,
                    preview_token_hash,
                    result,
                    max(0, int(affected_count)),
                    reason_code,
                    created_at,
                ),
            )

    @staticmethod
    def _restore_config_bytes(path: Path, before_bytes: bytes | None) -> None:
        if before_bytes is None:
            try:
                path.unlink()
            except FileNotFoundError:
                pass
            return
        temporary = path.with_name(
            f".{path.name}.{os.getpid()}.rollback.tmp"
        )
        try:
            with temporary.open("wb") as handle:
                handle.write(before_bytes)
                handle.flush()
                os.fsync(handle.fileno())
            os.chmod(temporary, 0o600)
            os.replace(temporary, path)
        finally:
            try:
                temporary.unlink()
            except FileNotFoundError:
                pass
