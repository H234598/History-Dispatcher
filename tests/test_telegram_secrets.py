from __future__ import annotations

import subprocess
from dataclasses import dataclass, field

import pytest

from history_dispatcher.telegram_secrets import (
    NativeTelegramSecretStore,
    SecretToolTelegramBackend,
    TelegramSecretError,
    TelegramSecretKind,
)


@dataclass
class RecordingRunner:
    responses: list[subprocess.CompletedProcess[bytes]] = field(default_factory=list)
    calls: list[tuple[list[str], dict[str, object]]] = field(default_factory=list)

    def __call__(self, argv: list[str], **kwargs):
        self.calls.append((list(argv), dict(kwargs)))
        if self.responses:
            return self.responses.pop(0)
        return subprocess.CompletedProcess(argv, 0, stdout=b"", stderr=b"")


def test_secret_tool_store_passes_secret_only_through_stdin() -> None:
    runner = RecordingRunner()
    backend = SecretToolTelegramBackend(runner=runner)
    token = "123456789:ABCDEFGHIJKLMNOPQRSTUVWXYZabcdef"

    backend.store(TelegramSecretKind.BOT_TOKEN, "telegram_primary", token)

    argv, kwargs = runner.calls[0]
    assert argv == [
        "secret-tool",
        "store",
        "--label=History-Dispatcher Telegram bot token",
        "application",
        "history-dispatcher",
        "purpose",
        "telegram-bot-token",
        "profile",
        "telegram_primary",
    ]
    assert kwargs["input"] == token.encode("utf-8")
    assert kwargs["capture_output"] is True
    assert kwargs["check"] is False
    assert kwargs["timeout"] == 5
    assert token not in " ".join(argv)


def test_secret_tool_chat_id_lookup_and_clear_use_exact_attributes() -> None:
    runner = RecordingRunner(
        responses=[
            subprocess.CompletedProcess([], 0, stdout=b"-1001234567890\n", stderr=b""),
            subprocess.CompletedProcess([], 0, stdout=b"", stderr=b""),
        ]
    )
    backend = SecretToolTelegramBackend(runner=runner)

    value = backend.lookup(TelegramSecretKind.CHAT_ID, "status_admin_primary")
    cleared = backend.clear(TelegramSecretKind.CHAT_ID, "status_admin_primary")

    assert value == "-1001234567890"
    assert cleared is True
    assert runner.calls[0][0] == [
        "secret-tool",
        "lookup",
        "application",
        "history-dispatcher",
        "purpose",
        "telegram-chat-id",
        "profile",
        "status_admin_primary",
    ]
    assert runner.calls[1][0] == [
        "secret-tool",
        "clear",
        "application",
        "history-dispatcher",
        "purpose",
        "telegram-chat-id",
        "profile",
        "status_admin_primary",
    ]


def test_secret_tool_errors_do_not_expose_stderr_or_secret() -> None:
    token = "123456789:ABCDEFGHIJKLMNOPQRSTUVWXYZabcdef"
    runner = RecordingRunner(
        responses=[
            subprocess.CompletedProcess(
                [],
                1,
                stdout=b"",
                stderr=f"failed for {token}".encode("utf-8"),
            )
        ]
    )
    backend = SecretToolTelegramBackend(runner=runner)

    with pytest.raises(TelegramSecretError) as raised:
        backend.store(TelegramSecretKind.BOT_TOKEN, "telegram_primary", token)

    assert token not in str(raised.value)
    assert "failed for" not in str(raised.value)


@pytest.mark.parametrize(
    "token",
    [
        "",
        " 123456789:ABCDEFGHIJKLMNOPQRSTUVWXYZabcdef",
        "123:short",
        "123456789 no-colon",
        "123456789:contains space",
        "123456789:" + "a" * 500,
        "123456789:abc\nnewline",
    ],
)
def test_bot_token_validation_is_strict(token: str) -> None:
    store = NativeTelegramSecretStore(backend=SecretToolTelegramBackend(runner=RecordingRunner()))

    with pytest.raises(TelegramSecretError, match="bot token"):
        store.validate_bot_token(token)


@pytest.mark.parametrize(
    "chat_id",
    ["", " 12345", "+12345", "chat", "-12", "1" * 30, "-10012\n345"],
)
def test_chat_id_validation_is_strict(chat_id: str) -> None:
    store = NativeTelegramSecretStore(backend=SecretToolTelegramBackend(runner=RecordingRunner()))

    with pytest.raises(TelegramSecretError, match="chat ID"):
        store.validate_chat_id(chat_id)


def test_native_store_validates_profiles_and_lookup_unavailability() -> None:
    runner = RecordingRunner(
        responses=[subprocess.CompletedProcess([], 1, stdout=b"", stderr=b"missing")]
    )
    store = NativeTelegramSecretStore(
        backend=SecretToolTelegramBackend(runner=runner)
    )

    with pytest.raises(TelegramSecretError, match="unavailable"):
        store.lookup_bot_token("telegram_primary")
    with pytest.raises(TelegramSecretError, match="profile"):
        store.lookup_chat_id("../raw-path")


def test_native_store_accepts_valid_values_and_never_returns_write_values() -> None:
    runner = RecordingRunner(
        responses=[
            subprocess.CompletedProcess([], 0, stdout=b"", stderr=b""),
            subprocess.CompletedProcess([], 0, stdout=b"", stderr=b""),
        ]
    )
    store = NativeTelegramSecretStore(
        backend=SecretToolTelegramBackend(runner=runner)
    )

    assert (
        store.store_bot_token(
            "telegram_primary",
            "123456789:ABCDEFGHIJKLMNOPQRSTUVWXYZabcdef",
        )
        is None
    )
    assert store.store_chat_id("status_admin_primary", "-1001234567890") is None
