from __future__ import annotations

import hashlib
import hmac
import json
import secrets
import sqlite3
import threading
import time
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Any, Callable

from .config import DispatcherConfig, config_revision, load_config
from .crypto import SecretServiceKeyProvider
from .identifiers import persistent_opaque_id
from .migrations import verify_database_v4
from .telegram_provider import TelegramDispatchProvider
from .telegram_secrets import (
    NativeTelegramSecretStore,
    TelegramSecretError,
    TelegramSecretKind,
)


CREDENTIAL_SCHEMA_VERSION = 1
CREDENTIAL_PREVIEW_TTL_SECONDS = 60
MAX_CREDENTIAL_PREVIEWS = 128


class CredentialValidationError(ValueError):
    pass


class CredentialApplyError(RuntimeError):
    pass


class CredentialAction(str, Enum):
    SET = "set"
    REPLACE = "replace"
    DELETE = "delete"

    @classmethod
    def parse(cls, value: CredentialAction | str) -> CredentialAction:
        if isinstance(value, cls):
            return value
        try:
            return cls(str(value or "").strip().casefold())
        except ValueError as exc:
            raise CredentialValidationError("unsupported credential action") from exc


@dataclass(frozen=True)
class CredentialPreview:
    action: str
    secret_kind: str
    profile_ref: str
    fingerprint: str
    confirmation: str
    preview_token: str
    expires_in_seconds: int = CREDENTIAL_PREVIEW_TTL_SECONDS
    schema_version: int = CREDENTIAL_SCHEMA_VERSION

    def as_dict(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "action": self.action,
            "secret_kind": self.secret_kind,
            "profile_ref": self.profile_ref,
            "fingerprint": self.fingerprint,
            "confirmation": self.confirmation,
            "preview_token": self.preview_token,
            "expires_in_seconds": self.expires_in_seconds,
        }


@dataclass(frozen=True)
class _CredentialPreviewEntry:
    token_hash: str
    action: CredentialAction
    secret_kind: TelegramSecretKind
    profile_ref: str
    profile_key: str
    secret_value: str | None
    fingerprint: str
    config_revision: str
    expires_at: float


class CredentialManager:
    def __init__(
        self,
        config: DispatcherConfig,
        *,
        database_path: Path,
        key_provider: SecretServiceKeyProvider,
        secret_store: NativeTelegramSecretStore,
        clock: Callable[[], float] | None = None,
        token_factory: Callable[[], str] | None = None,
    ) -> None:
        self._config = config
        self.database_path = Path(database_path).expanduser().absolute()
        self.key_provider = key_provider
        self.secret_store = secret_store
        self._clock = clock or time.monotonic
        self._token_factory = token_factory or (
            lambda: secrets.token_urlsafe(32)
        )
        self._previews: dict[str, _CredentialPreviewEntry] = {}
        self._lock = threading.RLock()
        verification = verify_database_v4(self.database_path)
        if not verification["ok"]:
            raise CredentialApplyError(
                "database must pass schema-v4 verification"
            )

    @property
    def config(self) -> DispatcherConfig:
        return self._config

    def replace_config(self, config: DispatcherConfig) -> None:
        with self._lock:
            self._config = config
            self._prune_previews_locked()

    def preview_apply(
        self,
        *,
        action: CredentialAction | str,
        secret_kind: TelegramSecretKind | str,
        profile_ref: object,
        secret_value: object | None,
    ) -> CredentialPreview:
        with self._lock:
            parsed_action = CredentialAction.parse(action)
            try:
                parsed_kind = TelegramSecretKind.parse(secret_kind)
                profile = self.secret_store.normalize_profile(profile_ref)
            except TelegramSecretError as exc:
                raise CredentialValidationError(str(exc)) from exc
            self._authorize_profile(self._config, parsed_kind, profile)
            if parsed_action in {CredentialAction.SET, CredentialAction.REPLACE}:
                if secret_value is None:
                    raise CredentialValidationError(
                        f"credential {parsed_action.value} requires a secret value"
                    )
                try:
                    validated_value = self.secret_store.validate_value(
                        parsed_kind,
                        secret_value,
                    )
                except TelegramSecretError as exc:
                    raise CredentialValidationError(str(exc)) from exc
            else:
                if secret_value is not None:
                    raise CredentialValidationError(
                        "credential delete forbids a secret value"
                    )
                validated_value = None

            revision = config_revision(self._config)
            profile_key = self._profile_key(parsed_kind, profile)
            value_key = (
                persistent_opaque_id(
                    self.key_provider,
                    "telegram-secret-value",
                    f"{parsed_kind.value}|{profile}|{validated_value}",
                    prefix="secretvalue",
                    length=48,
                )
                if validated_value is not None
                else ""
            )
            canonical = json.dumps(
                {
                    "schema_version": CREDENTIAL_SCHEMA_VERSION,
                    "config_revision": revision,
                    "action": parsed_action.value,
                    "secret_kind": parsed_kind.value,
                    "profile_key": profile_key,
                    "value_key": value_key,
                },
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
                allow_nan=False,
            ).encode("utf-8")
            fingerprint = hashlib.sha256(canonical).hexdigest()
            token = self._token_factory()
            if (
                not isinstance(token, str)
                or len(token) < 32
                or len(token) > 512
                or any(ord(character) < 0x20 for character in token)
            ):
                raise CredentialValidationError(
                    "preview token factory returned an unsafe token"
                )
            self._prune_previews_locked()
            if len(self._previews) >= MAX_CREDENTIAL_PREVIEWS:
                oldest = min(
                    self._previews,
                    key=lambda key: self._previews[key].expires_at,
                )
                self._previews.pop(oldest, None)
            token_hash = self._token_hash(token)
            self._previews[token_hash] = _CredentialPreviewEntry(
                token_hash=token_hash,
                action=parsed_action,
                secret_kind=parsed_kind,
                profile_ref=profile,
                profile_key=profile_key,
                secret_value=validated_value,
                fingerprint=fingerprint,
                config_revision=revision,
                expires_at=self._clock() + CREDENTIAL_PREVIEW_TTL_SECONDS,
            )
            return CredentialPreview(
                action=parsed_action.value,
                secret_kind=parsed_kind.value,
                profile_ref=profile,
                fingerprint=fingerprint,
                confirmation=(
                    f"CREDENTIAL {parsed_action.value.upper()} "
                    f"{fingerprint[:12]}"
                ),
                preview_token=token,
            )

    def apply_preview(
        self,
        *,
        preview_token: str,
        fingerprint: str,
        confirmation: str,
        actor: str,
    ) -> dict[str, object]:
        if not isinstance(preview_token, str) or not preview_token:
            raise CredentialApplyError("preview token is invalid")
        token_hash = self._token_hash(preview_token)
        with self._lock:
            entry = self._previews.pop(token_hash, None)
            if entry is None:
                raise CredentialApplyError("preview token is unknown or consumed")
            if entry.expires_at <= self._clock():
                raise CredentialApplyError("preview token expired")
            normalized_fingerprint = str(fingerprint or "").strip().lower()
            if not hmac.compare_digest(normalized_fingerprint, entry.fingerprint):
                raise CredentialApplyError("preview fingerprint mismatch")
            expected_confirmation = (
                f"CREDENTIAL {entry.action.value.upper()} "
                f"{entry.fingerprint[:12]}"
            )
            if not hmac.compare_digest(
                str(confirmation or ""),
                expected_confirmation,
            ):
                raise CredentialApplyError("preview confirmation mismatch")
            normalized_actor = self._validate_actor(actor)
            current = load_config(self._config.config_path)
            if config_revision(current) != entry.config_revision:
                raise CredentialApplyError("config revision changed after preview")
            try:
                self._authorize_profile(
                    current,
                    entry.secret_kind,
                    entry.profile_ref,
                )
            except CredentialValidationError as exc:
                raise CredentialApplyError(str(exc)) from exc

            try:
                previous = self.secret_store.lookup_optional(
                    entry.secret_kind,
                    entry.profile_ref,
                )
            except TelegramSecretError as exc:
                raise CredentialApplyError("credential lookup failed") from exc
            if entry.action is CredentialAction.SET and previous is not None:
                raise CredentialApplyError("credential is already configured")
            if entry.action in {CredentialAction.REPLACE, CredentialAction.DELETE} and previous is None:
                raise CredentialApplyError("credential is not configured")

            mutation_started = False
            try:
                if entry.action in {CredentialAction.SET, CredentialAction.REPLACE}:
                    assert entry.secret_value is not None
                    self.secret_store.store_value(
                        entry.secret_kind,
                        entry.profile_ref,
                        entry.secret_value,
                    )
                    mutation_started = True
                    verified = self.secret_store.lookup_optional(
                        entry.secret_kind,
                        entry.profile_ref,
                    )
                    if verified is None or not hmac.compare_digest(
                        verified,
                        entry.secret_value,
                    ):
                        raise CredentialApplyError(
                            "Secret Service post-write verification failed"
                        )
                    configured = True
                else:
                    self.secret_store.clear_value(
                        entry.secret_kind,
                        entry.profile_ref,
                    )
                    mutation_started = True
                    if self.secret_store.lookup_optional(
                        entry.secret_kind,
                        entry.profile_ref,
                    ) is not None:
                        raise CredentialApplyError(
                            "Secret Service post-delete verification failed"
                        )
                    configured = False

                changed_at = datetime.now(timezone.utc).isoformat(
                    timespec="seconds"
                )
                self._commit_metadata_and_audit(
                    secret_kind=entry.secret_kind,
                    profile_key=entry.profile_key,
                    configured=configured,
                    last_changed=changed_at,
                    action=entry.action,
                    actor_key=self._actor_key(normalized_actor),
                    result="applied",
                    reason_code="applied",
                )
            except Exception as exc:
                if mutation_started:
                    try:
                        self._restore_previous(
                            entry.secret_kind,
                            entry.profile_ref,
                            previous,
                        )
                    except Exception as rollback_exc:
                        raise CredentialApplyError(
                            "credential_rollback_failed"
                        ) from rollback_exc
                    self._audit_best_effort(
                        entry=entry,
                        actor=normalized_actor,
                        result="rolled_back",
                        reason_code="apply_failed_rolled_back",
                    )
                    raise CredentialApplyError(
                        "credential apply failed and was rolled back"
                    ) from exc
                if isinstance(exc, CredentialApplyError):
                    raise
                raise CredentialApplyError("credential apply failed") from exc

            self._config = current
            return {
                "ok": True,
                "schema_version": CREDENTIAL_SCHEMA_VERSION,
                "action": entry.action.value,
                "secret_kind": entry.secret_kind.value,
                "profile_ref": entry.profile_ref,
                "configured": configured,
                "last_changed": changed_at,
            }

    def get_status(self) -> dict[str, object]:
        with self._lock:
            current = load_config(self._config.config_path)
            self._config = current
            bot = self._status_row(
                TelegramSecretKind.BOT_TOKEN,
                current.telegram_credential_ref,
            )
            recipients = [
                self._status_row(TelegramSecretKind.CHAT_ID, profile)
                for profile in current.telegram_recipient_refs
            ]
            return {
                "schema_version": CREDENTIAL_SCHEMA_VERSION,
                "bot": bot,
                "recipients": recipients,
            }

    def _status_row(
        self,
        kind: TelegramSecretKind,
        profile_ref: str,
    ) -> dict[str, object]:
        if not profile_ref:
            return {
                "profile_ref": "",
                "configured": False,
                "last_changed": None,
            }
        profile_key = self._profile_key(kind, profile_ref)
        with sqlite3.connect(self.database_path) as db:
            row = db.execute(
                "SELECT configured,last_changed FROM telegram_secret_metadata "
                "WHERE secret_kind=? AND profile_key=?",
                (kind.value, profile_key),
            ).fetchone()
        return {
            "profile_ref": profile_ref,
            "configured": bool(row[0]) if row is not None else False,
            "last_changed": str(row[1]) if row is not None else None,
        }

    def _commit_metadata_and_audit(
        self,
        *,
        secret_kind: TelegramSecretKind,
        profile_key: str,
        configured: bool,
        last_changed: str,
        action: CredentialAction,
        actor_key: str,
        result: str,
        reason_code: str,
    ) -> None:
        with sqlite3.connect(self.database_path) as db:
            db.execute("PRAGMA foreign_keys=ON")
            db.execute("BEGIN IMMEDIATE")
            db.execute(
                "INSERT INTO telegram_secret_metadata("
                "secret_kind,profile_key,configured,last_changed,last_operation"
                ") VALUES (?,?,?,?,?) "
                "ON CONFLICT(secret_kind,profile_key) DO UPDATE SET "
                "configured=excluded.configured,"
                "last_changed=excluded.last_changed,"
                "last_operation=excluded.last_operation",
                (
                    secret_kind.value,
                    profile_key,
                    int(configured),
                    last_changed,
                    action.value,
                ),
            )
            db.execute(
                "INSERT INTO credential_audit("
                "id,actor_key,profile_key,operation,secret_kind,result,reason_code,"
                "created_at"
                ") VALUES (?,?,?,?,?,?,?,?)",
                (
                    str(uuid.uuid4()),
                    actor_key,
                    profile_key,
                    f"credential.{action.value}",
                    secret_kind.value,
                    result,
                    reason_code,
                    last_changed,
                ),
            )
            db.commit()

    def _restore_previous(
        self,
        kind: TelegramSecretKind,
        profile_ref: str,
        previous: str | None,
    ) -> None:
        if previous is None:
            self.secret_store.clear_value(kind, profile_ref)
            if self.secret_store.lookup_optional(kind, profile_ref) is not None:
                raise CredentialApplyError("rollback clear verification failed")
            return
        self.secret_store.store_value(kind, profile_ref, previous)
        restored = self.secret_store.lookup_optional(kind, profile_ref)
        if restored is None or not hmac.compare_digest(restored, previous):
            raise CredentialApplyError("rollback restore verification failed")

    def _audit_best_effort(
        self,
        *,
        entry: _CredentialPreviewEntry,
        actor: str,
        result: str,
        reason_code: str,
    ) -> None:
        try:
            with sqlite3.connect(self.database_path) as db:
                db.execute(
                    "INSERT INTO credential_audit("
                    "id,actor_key,profile_key,operation,secret_kind,result,"
                    "reason_code,created_at"
                    ") VALUES (?,?,?,?,?,?,?,?)",
                    (
                        str(uuid.uuid4()),
                        self._actor_key(actor),
                        entry.profile_key,
                        f"credential.{entry.action.value}",
                        entry.secret_kind.value,
                        result,
                        reason_code,
                        datetime.now(timezone.utc).isoformat(timespec="seconds"),
                    ),
                )
                db.commit()
        except sqlite3.Error:
            pass

    @staticmethod
    def _authorize_profile(
        config: DispatcherConfig,
        kind: TelegramSecretKind,
        profile_ref: str,
    ) -> None:
        if config.telegram_provider is not TelegramDispatchProvider.HISTORY_DISPATCHER:
            raise CredentialValidationError(
                "native Telegram provider is not configured"
            )
        if kind is TelegramSecretKind.BOT_TOKEN:
            authorized = bool(config.telegram_credential_ref) and hmac.compare_digest(
                config.telegram_credential_ref,
                profile_ref,
            )
        else:
            authorized = profile_ref in config.telegram_recipient_refs
        if not authorized:
            raise CredentialValidationError(
                "Telegram secret profile is not configured"
            )

    def _profile_key(
        self,
        kind: TelegramSecretKind,
        profile_ref: str,
    ) -> str:
        return persistent_opaque_id(
            self.key_provider,
            "telegram-secret-profile",
            f"{kind.value}|{profile_ref}",
            prefix="secretprofile",
        )

    def _actor_key(self, actor: str) -> str:
        return persistent_opaque_id(
            self.key_provider,
            "credential-actor",
            actor,
            prefix="actor",
        )

    @staticmethod
    def _validate_actor(actor: object) -> str:
        if not isinstance(actor, str):
            raise CredentialApplyError("credential actor must be a string")
        normalized = actor.strip()
        if (
            not normalized
            or len(normalized) > 160
            or any(
                ord(character) < 0x20 or ord(character) == 0x7F
                for character in normalized
            )
        ):
            raise CredentialApplyError("credential actor is invalid")
        return normalized

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
