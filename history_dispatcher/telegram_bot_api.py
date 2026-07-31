from __future__ import annotations

import http.client
import json
import re
import secrets
import socket
import ssl
from dataclasses import dataclass
from typing import Callable, TypeAlias

from .telegram_secrets import NativeTelegramSecretStore, TelegramSecretError


TELEGRAM_API_HOST = "api.telegram.org"
TELEGRAM_API_PORT = 443
TELEGRAM_API_TIMEOUT_SECONDS = 10
MAX_JSON_REQUEST_BYTES = 64 * 1024
MAX_MULTIPART_REQUEST_BYTES = 2 * 1024 * 1024
MAX_RESPONSE_BYTES = 256 * 1024
MAX_DOCUMENT_BYTES = 1 * 1024 * 1024
MAX_RETRY_AFTER_SECONDS = 7 * 24 * 3600
MAX_MESSAGE_CHARACTERS = 4096
MAX_DOCUMENT_CAPTION_CHARACTERS = 900

_FILENAME_RE = re.compile(r"^history-[a-z0-9][a-z0-9_.-]{0,120}\.txt$")
_BOUNDARY_RE = re.compile(r"^[A-Za-z0-9]{16,70}$")


@dataclass(frozen=True)
class TelegramApiSuccess:
    message_id: int


@dataclass(frozen=True)
class TelegramApiRateLimited:
    retry_after_seconds: int


@dataclass(frozen=True)
class TelegramApiRejected:
    reason_code: str
    retryable: bool


@dataclass(frozen=True)
class TelegramApiPossibleDuplicate:
    reason_code: str


TelegramApiResult: TypeAlias = (
    TelegramApiSuccess
    | TelegramApiRateLimited
    | TelegramApiRejected
    | TelegramApiPossibleDuplicate
)

ConnectionFactory: TypeAlias = Callable[..., http.client.HTTPSConnection]
BoundaryFactory: TypeAlias = Callable[[], str]


class TelegramBotApiClient:
    def __init__(
        self,
        *,
        connection_factory: ConnectionFactory | None = None,
        ssl_context_factory: Callable[[], ssl.SSLContext] | None = None,
        boundary_factory: BoundaryFactory | None = None,
    ) -> None:
        self._connection_factory = connection_factory or http.client.HTTPSConnection
        self._ssl_context_factory = ssl_context_factory or ssl.create_default_context
        self._boundary_factory = boundary_factory or (
            lambda: "historydispatcher" + secrets.token_hex(12)
        )

    def get_me(self, token: str) -> TelegramApiResult:
        validated_token = self._validate_token(token)
        return self._json_request(validated_token, "getMe", {})

    def send_message(
        self,
        token: str,
        chat_id: str,
        text: str,
    ) -> TelegramApiResult:
        validated_token = self._validate_token(token)
        validated_chat_id = self._validate_chat_id(chat_id)
        if not isinstance(text, str) or not 1 <= len(text) <= MAX_MESSAGE_CHARACTERS:
            raise ValueError("Telegram message text is out of range")
        if "\x00" in text:
            raise ValueError("Telegram message text contains NUL")
        return self._json_request(
            validated_token,
            "sendMessage",
            {"chat_id": validated_chat_id, "text": text},
        )

    def send_document(
        self,
        token: str,
        chat_id: str,
        filename: str,
        document: bytes,
        caption: str,
    ) -> TelegramApiResult:
        validated_token = self._validate_token(token)
        validated_chat_id = self._validate_chat_id(chat_id)
        if not isinstance(filename, str) or not _FILENAME_RE.fullmatch(filename):
            raise ValueError("Telegram document filename is invalid")
        if not isinstance(document, bytes) or not 1 <= len(document) <= MAX_DOCUMENT_BYTES:
            raise ValueError("Telegram document is out of range")
        if not isinstance(caption, str) or len(caption) > MAX_DOCUMENT_CAPTION_CHARACTERS:
            raise ValueError("Telegram document caption is out of range")
        if "\x00" in caption:
            raise ValueError("Telegram document caption contains NUL")

        boundary = self._boundary_factory()
        if not isinstance(boundary, str) or not _BOUNDARY_RE.fullmatch(boundary):
            raise ValueError("Telegram multipart boundary is invalid")
        body = self._multipart_body(
            boundary=boundary,
            chat_id=validated_chat_id,
            filename=filename,
            document=document,
            caption=caption,
        )
        if len(body) > MAX_MULTIPART_REQUEST_BYTES:
            raise ValueError("Telegram multipart request exceeds the byte limit")
        return self._request(
            validated_token,
            "sendDocument",
            body,
            f"multipart/form-data; boundary={boundary}",
        )

    @staticmethod
    def _validate_token(token: object) -> str:
        try:
            return NativeTelegramSecretStore.validate_bot_token(token)
        except TelegramSecretError as exc:
            raise ValueError("Telegram bot token is invalid") from exc

    @staticmethod
    def _validate_chat_id(chat_id: object) -> str:
        try:
            return NativeTelegramSecretStore.validate_chat_id(chat_id)
        except TelegramSecretError as exc:
            raise ValueError("Telegram chat ID is invalid") from exc

    def _json_request(
        self,
        token: str,
        method: str,
        payload: dict[str, object],
    ) -> TelegramApiResult:
        body = json.dumps(
            payload,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        ).encode("utf-8")
        if len(body) > MAX_JSON_REQUEST_BYTES:
            raise ValueError("Telegram JSON request exceeds the byte limit")
        return self._request(token, method, body, "application/json")

    def _request(
        self,
        token: str,
        method: str,
        body: bytes,
        content_type: str,
    ) -> TelegramApiResult:
        if method not in {"getMe", "sendMessage", "sendDocument"}:
            raise ValueError("Telegram Bot API method is not allowlisted")
        context = self._ssl_context_factory()
        if not isinstance(context, ssl.SSLContext):
            raise ValueError("Telegram TLS context is invalid")
        connection = self._connection_factory(
            TELEGRAM_API_HOST,
            TELEGRAM_API_PORT,
            timeout=TELEGRAM_API_TIMEOUT_SECONDS,
            context=context,
        )
        try:
            try:
                connection.connect()
            except (OSError, socket.timeout, ssl.SSLError, http.client.HTTPException):
                return TelegramApiRejected(
                    "telegram_connect_failed",
                    retryable=True,
                )

            try:
                connection.request(
                    "POST",
                    f"/bot{token}/{method}",
                    body,
                    {
                        "Content-Type": content_type,
                        "Content-Length": str(len(body)),
                        "Connection": "close",
                        "Accept": "application/json",
                    },
                )
                response = connection.getresponse()
                status = int(response.status)
                raw = response.read(MAX_RESPONSE_BYTES + 1)
            except Exception:
                return TelegramApiPossibleDuplicate("telegram_accept_unknown")

            if len(raw) > MAX_RESPONSE_BYTES:
                if status == 200:
                    return TelegramApiPossibleDuplicate(
                        "telegram_response_too_large"
                    )
                return TelegramApiRejected(
                    "telegram_protocol_error",
                    retryable=True,
                )
            try:
                decoded = raw.decode("utf-8")
                envelope = json.loads(decoded)
            except (UnicodeDecodeError, json.JSONDecodeError):
                if status == 200:
                    return TelegramApiPossibleDuplicate("telegram_protocol_unknown")
                return TelegramApiRejected(
                    "telegram_protocol_error",
                    retryable=True,
                )
            return self._interpret_response(status, envelope)
        finally:
            try:
                connection.close()
            except Exception:
                pass

    @staticmethod
    def _interpret_response(status: int, envelope: object) -> TelegramApiResult:
        if not isinstance(envelope, dict) or not isinstance(envelope.get("ok"), bool):
            if status == 200:
                return TelegramApiPossibleDuplicate("telegram_protocol_unknown")
            return TelegramApiRejected("telegram_protocol_error", retryable=True)

        ok = bool(envelope["ok"])
        if status == 200 and ok:
            result = envelope.get("result")
            if not isinstance(result, dict):
                return TelegramApiPossibleDuplicate("telegram_protocol_unknown")
            raw_message_id = result.get("message_id", result.get("id"))
            if (
                isinstance(raw_message_id, bool)
                or not isinstance(raw_message_id, int)
                or raw_message_id <= 0
            ):
                return TelegramApiPossibleDuplicate("telegram_protocol_unknown")
            return TelegramApiSuccess(message_id=raw_message_id)

        error_code = envelope.get("error_code", status)
        if isinstance(error_code, bool) or not isinstance(error_code, int):
            error_code = status
        if status == 429 or error_code == 429:
            parameters = envelope.get("parameters")
            retry_after = (
                parameters.get("retry_after")
                if isinstance(parameters, dict)
                else None
            )
            if (
                isinstance(retry_after, bool)
                or not isinstance(retry_after, int)
                or retry_after < 1
            ):
                return TelegramApiRejected(
                    "telegram_rate_limited",
                    retryable=True,
                )
            return TelegramApiRateLimited(
                retry_after_seconds=min(
                    retry_after,
                    MAX_RETRY_AFTER_SECONDS,
                )
            )
        if 300 <= status < 400:
            return TelegramApiRejected(
                "telegram_redirect_forbidden",
                retryable=False,
            )
        if status == 400 or error_code == 400:
            return TelegramApiRejected(
                "telegram_bad_request",
                retryable=False,
            )
        if status == 401 or error_code == 401:
            return TelegramApiRejected(
                "telegram_unauthorized",
                retryable=False,
            )
        if status == 403 or error_code == 403:
            return TelegramApiRejected(
                "telegram_forbidden",
                retryable=False,
            )
        if status >= 500 or error_code >= 500:
            return TelegramApiRejected(
                "telegram_transient",
                retryable=True,
            )
        return TelegramApiRejected("telegram_rejected", retryable=False)

    @staticmethod
    def _multipart_body(
        *,
        boundary: str,
        chat_id: str,
        filename: str,
        document: bytes,
        caption: str,
    ) -> bytes:
        marker = boundary.encode("ascii")
        chunks: list[bytes] = []

        def add_text(name: str, value: str) -> None:
            chunks.extend(
                [
                    b"--" + marker + b"\r\n",
                    (
                        f'Content-Disposition: form-data; name="{name}"\r\n\r\n'
                    ).encode("ascii"),
                    value.encode("utf-8"),
                    b"\r\n",
                ]
            )

        add_text("chat_id", chat_id)
        if caption:
            add_text("caption", caption)
        chunks.extend(
            [
                b"--" + marker + b"\r\n",
                (
                    "Content-Disposition: form-data; name=\"document\"; "
                    f"filename=\"{filename}\"\r\n"
                ).encode("ascii"),
                b"Content-Type: text/plain; charset=utf-8\r\n\r\n",
                document,
                b"\r\n",
                b"--" + marker + b"--\r\n",
            ]
        )
        return b"".join(chunks)
