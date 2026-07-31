from __future__ import annotations

import math
import unicodedata

import pytest

from history_dispatcher.telegram_formatter import (
    MAX_DOCUMENT_BYTES,
    FormattedTelegramDelivery,
    TelegramFormattingError,
    format_telegram_delivery,
)


def _payload(**overrides: object) -> dict[str, object]:
    value: dict[str, object] = {
        "history_kind": "overall_completion",
        "project_label": "History-Dispatcher",
        "source_schema_family": "codex_rollout",
        "timestamp": "2026-07-31T12:00:00+00:00",
        "summary": "Implemented the native Telegram formatter.",
        "details": {"tests": 298, "status": "green"},
    }
    value.update(overrides)
    return value


def test_short_payload_formats_as_deterministic_plain_text() -> None:
    first = format_telegram_delivery(_payload(), event_id="evt_private_123")
    second = format_telegram_delivery(_payload(), event_id="evt_private_123")

    assert first == second
    assert first == FormattedTelegramDelivery(
        mode="text",
        text=(
            "History-Dispatcher\n"
            "Type: overall_completion\n"
            "Projekt: History-Dispatcher\n"
            "Quelle: codex_rollout\n"
            "Zeit: 2026-07-31T12:00:00+00:00\n\n"
            "Implemented the native Telegram formatter.\n\n"
            "Details:\n"
            "details.status: green\n"
            "details.tests: 298"
        ),
        filename="",
        document=b"",
        caption="",
    )
    assert 1 <= len(first.text) <= 3900
    assert "parse_mode" not in first.text
    assert "<b>" not in first.text


def test_formatter_normalizes_unicode_and_line_endings() -> None:
    decomposed = "Cafe\u0301\r\nLine two\rLine three"

    formatted = format_telegram_delivery(
        _payload(summary=decomposed),
        event_id="evt_unicode",
    )

    assert formatted.mode == "text"
    assert "Café\nLine two\nLine three" in formatted.text
    assert formatted.text == unicodedata.normalize("NFC", formatted.text)
    assert "\r" not in formatted.text


def test_formatter_redacts_tokens_chat_ids_emails_and_private_paths() -> None:
    token = "123456789:ABCDEFGHIJKLMNOPQRSTUVWXYZabcdef"
    chat_id = "-1001234567890"
    formatted = format_telegram_delivery(
        _payload(
            summary=(
                f"token={token} chat_id={chat_id} "
                "mail=test@example.com path=/home/master/private/file.txt"
            )
        ),
        event_id="evt_secret",
    )

    rendered = formatted.text or formatted.document.decode("utf-8")
    assert token not in rendered
    assert chat_id not in rendered
    assert "test@example.com" not in rendered
    assert "/home/master/private" not in rendered
    assert "[redacted-token]" in rendered or "token=[redacted]" in rendered
    assert "[redacted-chat-id]" in rendered
    assert "[redacted-email]" in rendered
    assert "[redacted-path]" in rendered


def test_long_payload_uses_exactly_one_text_document_fallback() -> None:
    formatted = format_telegram_delivery(
        _payload(summary="long " * 1200),
        event_id="evt_private_long_identifier",
    )

    assert formatted.mode == "document"
    assert formatted.text == ""
    assert formatted.filename.startswith("history-")
    assert formatted.filename.endswith(".txt")
    assert "evt_private_long_identifier" not in formatted.filename
    assert 1 <= len(formatted.document) <= MAX_DOCUMENT_BYTES
    assert formatted.document.decode("utf-8").startswith("History-Dispatcher\n")
    assert 1 <= len(formatted.caption) <= 900
    assert "evt_private_long_identifier" not in formatted.caption


def test_filename_is_stable_and_opaque() -> None:
    first = format_telegram_delivery(
        _payload(summary="x" * 5000),
        event_id="raw/private/event/id",
    )
    second = format_telegram_delivery(
        _payload(summary="x" * 5000),
        event_id="raw/private/event/id",
    )
    different = format_telegram_delivery(
        _payload(summary="x" * 5000),
        event_id="another-event",
    )

    assert first.filename == second.filename
    assert first.filename != different.filename
    assert "/" not in first.filename
    assert "raw" not in first.filename


def test_field_and_collection_counts_are_bounded() -> None:
    payload = _payload(
        details={f"key_{index:03d}": "value" * 1000 for index in range(100)},
        extra_list=list(range(100)),
    )

    formatted = format_telegram_delivery(payload, event_id="evt_bounds")

    rendered = formatted.text or formatted.document.decode("utf-8")
    assert len(rendered.encode("utf-8")) <= MAX_DOCUMENT_BYTES
    assert "details.key_000" in rendered
    assert "details.key_031" in rendered
    assert "details.key_099" not in rendered
    assert "extra_list[31]" in rendered
    assert "extra_list[99]" not in rendered
    assert "[collection truncated]" in rendered


def test_payload_above_one_mib_is_rejected() -> None:
    with pytest.raises(TelegramFormattingError, match="payload_too_large"):
        format_telegram_delivery(
            _payload(summary="x" * (MAX_DOCUMENT_BYTES + 100_000)),
            event_id="evt_too_large",
        )


@pytest.mark.parametrize(
    "payload",
    [
        None,
        [],
        "text",
        {"summary": math.nan},
        {"summary": math.inf},
        {"bad": {1: "non-string-key"}},
    ],
)
def test_invalid_payloads_fail_with_bounded_reason(payload: object) -> None:
    with pytest.raises(TelegramFormattingError) as raised:
        format_telegram_delivery(payload, event_id="evt_invalid")  # type: ignore[arg-type]

    assert len(str(raised.value)) <= 96


def test_deeply_nested_payload_is_rejected() -> None:
    value: object = "leaf"
    for _ in range(10):
        value = {"nested": value}

    with pytest.raises(TelegramFormattingError, match="payload_too_deep"):
        format_telegram_delivery(
            _payload(details=value),
            event_id="evt_deep",
        )


def test_empty_visible_content_still_produces_non_empty_message() -> None:
    formatted = format_telegram_delivery(
        {
            "history_kind": "intermediate",
            "project_label": "",
            "source_schema_family": "",
            "timestamp": "",
            "summary": "",
        },
        event_id="evt_empty",
    )

    assert formatted.mode == "text"
    assert formatted.text
    assert len(formatted.text) <= 3900
