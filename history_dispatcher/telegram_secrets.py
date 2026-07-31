from __future__ import annotations

import re
import subprocess
from collections.abc import Callable
from enum import Enum
from typing import Protocol

from .config import _opaque_profile


_BOT_TOKEN_RE = re.compile(r"^[1-9][0-9]{5,11}:[A-Za-z0-9_-]{20,256}$")
_CHAT_ID_RE = re.compile(r"^-?[0-9]{5,20}$")
_SECRET_TOOL_TIMEOUT_SECONDS = 5


class TelegramSecretError(RuntimeError):
    pass


class TelegramSecretKind(str, Enum):
    BOT_TOKEN = "bot_token"
    CHAT_ID = "chat_id"

    @classmethod
    def parse(cls, value: TelegramSecretKind | str) -> TelegramSecretKind:
        if isinstance(value, cls):
            return value
        try:
            return cls(str(value or "").strip().casefold())
        except ValueError as exc:
            raise TelegramSecretError("unsupported Telegram secret kind") from exc


class TelegramSecretBackend(Protocol):
    def lookup(
        self,
        kind: TelegramSecretKind,
        profile_ref: str,
    ) -> str | None: ...

    def store(
        self,
        kind: TelegramSecretKind,
        profile_ref: str,
        value: str,
    ) -> None: ...

    def clear(
        self,
        kind: TelegramSecretKind,
        profile_ref: str,
    ) -> bool: ...


class SecretToolTelegramBackend:
    def __init__(
        self,
        *,
        runner: Callable[..., subprocess.CompletedProcess[bytes]] | None = None,
    ) -> None:
        self._runner = runner or subprocess.run

    @staticmethod
    def _purpose(kind: TelegramSecretKind) -> str:
        if kind is TelegramSecretKind.BOT_TOKEN:
            return "telegram-bot-token"
        if kind is TelegramSecretKind.CHAT_ID:
            return "telegram-chat-id"
        raise TelegramSecretError("unsupported Telegram secret kind")

    @staticmethod
    def _label(kind: TelegramSecretKind) -> str:
        if kind is TelegramSecretKind.BOT_TOKEN:
            return "History-Dispatcher Telegram bot token"
        return "History-Dispatcher Telegram recipient chat ID"

    @classmethod
    def _attributes(
        cls,
        kind: TelegramSecretKind,
        profile_ref: str,
    ) -> list[str]:
        return [
            "application",
            "history-dispatcher",
            "purpose",
            cls._purpose(kind),
            "profile",
            profile_ref,
        ]

    def _run(
        self,
        argv: list[str],
        *,
        input_value: bytes | None = None,
    ) -> subprocess.CompletedProcess[bytes]:
        try:
            return self._runner(
                argv,
                check=False,
                capture_output=True,
                timeout=_SECRET_TOOL_TIMEOUT_SECONDS,
                **({"input": input_value} if input_value is not None else {}),
            )
        except (OSError, subprocess.TimeoutExpired) as exc:
            raise TelegramSecretError("Secret Service operation failed") from exc

    def lookup(
        self,
        kind: TelegramSecretKind,
        profile_ref: str,
    ) -> str | None:
        completed = self._run(
            ["secret-tool", "lookup", *self._attributes(kind, profile_ref)]
        )
        if completed.returncode != 0:
            if completed.stderr:
                raise TelegramSecretError("Secret Service lookup failed")
            return None
        try:
            value = completed.stdout.decode("utf-8").strip()
        except UnicodeDecodeError as exc:
            raise TelegramSecretError(
                "Secret Service lookup returned invalid data"
            ) from exc
        return value or None

    def store(
        self,
        kind: TelegramSecretKind,
        profile_ref: str,
        value: str,
    ) -> None:
        completed = self._run(
            [
                "secret-tool",
                "store",
                f"--label={self._label(kind)}",
                *self._attributes(kind, profile_ref),
            ],
            input_value=value.encode("utf-8"),
        )
        if completed.returncode != 0:
            raise TelegramSecretError("Secret Service store failed")

    def clear(
        self,
        kind: TelegramSecretKind,
        profile_ref: str,
    ) -> bool:
        completed = self._run(
            ["secret-tool", "clear", *self._attributes(kind, profile_ref)]
        )
        if completed.returncode != 0 and completed.stderr:
            raise TelegramSecretError("Secret Service clear failed")
        return completed.returncode == 0


class NativeTelegramSecretStore:
    def __init__(self, *, backend: TelegramSecretBackend | None = None) -> None:
        self.backend = backend or SecretToolTelegramBackend()

    @staticmethod
    def normalize_profile(profile_ref: object) -> str:
        try:
            return _opaque_profile(
                profile_ref,
                "Telegram secret profile",
                allow_empty=False,
            )
        except ValueError as exc:
            raise TelegramSecretError(str(exc)) from exc

    @staticmethod
    def validate_bot_token(value: object) -> str:
        if not isinstance(value, str) or not _BOT_TOKEN_RE.fullmatch(value):
            raise TelegramSecretError("Telegram bot token is invalid")
        return value

    @staticmethod
    def validate_chat_id(value: object) -> str:
        if not isinstance(value, str) or not _CHAT_ID_RE.fullmatch(value):
            raise TelegramSecretError("Telegram chat ID is invalid")
        return value

    def validate_value(
        self,
        kind: TelegramSecretKind | str,
        value: object,
    ) -> str:
        parsed = TelegramSecretKind.parse(kind)
        if parsed is TelegramSecretKind.BOT_TOKEN:
            return self.validate_bot_token(value)
        return self.validate_chat_id(value)

    def lookup_optional(
        self,
        kind: TelegramSecretKind | str,
        profile_ref: object,
    ) -> str | None:
        parsed = TelegramSecretKind.parse(kind)
        profile = self.normalize_profile(profile_ref)
        value = self.backend.lookup(parsed, profile)
        if value is None:
            return None
        return self.validate_value(parsed, value)

    def store_value(
        self,
        kind: TelegramSecretKind | str,
        profile_ref: object,
        value: object,
    ) -> None:
        parsed = TelegramSecretKind.parse(kind)
        profile = self.normalize_profile(profile_ref)
        validated = self.validate_value(parsed, value)
        self.backend.store(parsed, profile, validated)

    def clear_value(
        self,
        kind: TelegramSecretKind | str,
        profile_ref: object,
    ) -> bool:
        parsed = TelegramSecretKind.parse(kind)
        profile = self.normalize_profile(profile_ref)
        return self.backend.clear(parsed, profile)

    def lookup_bot_token(self, profile_ref: object) -> str:
        value = self.lookup_optional(TelegramSecretKind.BOT_TOKEN, profile_ref)
        if value is None:
            raise TelegramSecretError("Telegram bot token is unavailable")
        return value

    def lookup_chat_id(self, profile_ref: object) -> str:
        value = self.lookup_optional(TelegramSecretKind.CHAT_ID, profile_ref)
        if value is None:
            raise TelegramSecretError("Telegram chat ID is unavailable")
        return value

    def store_bot_token(self, profile_ref: object, token: object) -> None:
        self.store_value(TelegramSecretKind.BOT_TOKEN, profile_ref, token)

    def store_chat_id(self, profile_ref: object, chat_id: object) -> None:
        self.store_value(TelegramSecretKind.CHAT_ID, profile_ref, chat_id)

    def clear_bot_token(self, profile_ref: object) -> bool:
        return self.clear_value(TelegramSecretKind.BOT_TOKEN, profile_ref)

    def clear_chat_id(self, profile_ref: object) -> bool:
        return self.clear_value(TelegramSecretKind.CHAT_ID, profile_ref)
