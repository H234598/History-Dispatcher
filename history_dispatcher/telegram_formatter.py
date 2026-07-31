from __future__ import annotations

import hashlib
import json
import math
import re
import unicodedata
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any, Literal

from .redaction import redact_text


MAX_INLINE_CHARACTERS = 3900
MAX_DOCUMENT_BYTES = 1 * 1024 * 1024
MAX_CAPTION_CHARACTERS = 900
MAX_COLLECTION_ITEMS = 32
MAX_STRUCTURE_DEPTH = 5
MAX_SCALAR_CHARACTERS = 64 * 1024

_CHAT_ID_RE = re.compile(r"(?<!\d)-?\d{5,20}(?!\d)")


class TelegramFormattingError(ValueError):
    pass


@dataclass(frozen=True)
class FormattedTelegramDelivery:
    mode: Literal["text", "document"]
    text: str = ""
    filename: str = ""
    document: bytes = b""
    caption: str = ""


def _safe_text(value: object, *, maximum: int = MAX_SCALAR_CHARACTERS) -> str:
    text = redact_text(
        value,
        max_chars=maximum,
        max_bytes=maximum * 4,
    )
    return _CHAT_ID_RE.sub("[redacted-chat-id]", text)


def _validate_payload(value: object, *, depth: int = 0) -> None:
    if depth > MAX_STRUCTURE_DEPTH:
        raise TelegramFormattingError("payload_too_deep")
    if value is None or isinstance(value, (str, bool, int)):
        return
    if isinstance(value, float):
        if not math.isfinite(value):
            raise TelegramFormattingError("payload_non_finite")
        return
    if isinstance(value, Mapping):
        for key, item in value.items():
            if not isinstance(key, str):
                raise TelegramFormattingError("payload_key_invalid")
            _validate_payload(item, depth=depth + 1)
        return
    if isinstance(value, Sequence) and not isinstance(
        value,
        (str, bytes, bytearray),
    ):
        for item in value:
            _validate_payload(item, depth=depth + 1)
        return
    raise TelegramFormattingError("payload_type_invalid")


def _raw_size(value: Mapping[str, Any]) -> int:
    try:
        encoded = json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        ).encode("utf-8")
    except (TypeError, ValueError) as exc:
        raise TelegramFormattingError("payload_invalid") from exc
    return len(encoded)


def _scalar(value: object) -> str:
    if value is None:
        return "null"
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, float):
        return format(value, ".15g")
    return _safe_text(value)


def _flatten(
    value: object,
    *,
    prefix: str,
    lines: list[str],
    depth: int = 0,
) -> None:
    if depth > MAX_STRUCTURE_DEPTH:
        raise TelegramFormattingError("payload_too_deep")
    if isinstance(value, Mapping):
        items = sorted(value.items(), key=lambda item: item[0])
        for key, item in items[:MAX_COLLECTION_ITEMS]:
            child = f"{prefix}.{key}" if prefix else key
            _flatten(item, prefix=child, lines=lines, depth=depth + 1)
        if len(items) > MAX_COLLECTION_ITEMS:
            lines.append(f"{prefix}: [collection truncated]")
        return
    if isinstance(value, Sequence) and not isinstance(
        value,
        (str, bytes, bytearray),
    ):
        for index, item in enumerate(value[:MAX_COLLECTION_ITEMS]):
            child = f"{prefix}[{index}]"
            _flatten(item, prefix=child, lines=lines, depth=depth + 1)
        if len(value) > MAX_COLLECTION_ITEMS:
            lines.append(f"{prefix}: [collection truncated]")
        return
    lines.append(f"{prefix}: {_scalar(value)}")


def _known_text(payload: Mapping[str, Any], *keys: str) -> str:
    for key in keys:
        if key in payload:
            return _safe_text(payload.get(key))
    return ""


def _render(payload: Mapping[str, Any]) -> tuple[str, str, str]:
    history_kind = _known_text(payload, "history_kind", "kind", "type") or "unknown"
    project = _known_text(payload, "project_label", "project") or "Unbekanntes Projekt"
    source = _known_text(payload, "source_schema_family", "source") or "unknown"
    timestamp = _known_text(payload, "timestamp", "created_at") or "unknown"
    summary = _known_text(payload, "summary", "text", "content")

    header = [
        "History-Dispatcher",
        f"Type: {history_kind}",
        f"Projekt: {project}",
        f"Quelle: {source}",
        f"Zeit: {timestamp}",
    ]
    detail_lines: list[str] = []
    if "details" in payload:
        _flatten(payload["details"], prefix="details", lines=detail_lines)

    known = {
        "history_kind",
        "kind",
        "type",
        "project_label",
        "project",
        "source_schema_family",
        "source",
        "timestamp",
        "created_at",
        "summary",
        "text",
        "content",
        "details",
    }
    for key in sorted(key for key in payload if key not in known):
        _flatten(payload[key], prefix=key, lines=detail_lines)

    sections = ["\n".join(header)]
    if summary:
        sections.append(summary)
    if detail_lines:
        sections.append("Details:\n" + "\n".join(detail_lines))
    rendered = unicodedata.normalize("NFC", "\n\n".join(sections))
    rendered = rendered.replace("\r\n", "\n").replace("\r", "\n").strip()
    rendered = _CHAT_ID_RE.sub("[redacted-chat-id]", rendered)
    if not rendered:
        rendered = "History-Dispatcher\nType: unknown"
    return rendered, history_kind, project


def format_telegram_delivery(
    payload: Mapping[str, Any],
    *,
    event_id: str,
) -> FormattedTelegramDelivery:
    if not isinstance(payload, Mapping):
        raise TelegramFormattingError("payload_must_be_object")
    _validate_payload(payload)
    if _raw_size(payload) > MAX_DOCUMENT_BYTES:
        raise TelegramFormattingError("payload_too_large")

    rendered, history_kind, project = _render(payload)
    encoded = rendered.encode("utf-8")
    if len(encoded) > MAX_DOCUMENT_BYTES:
        raise TelegramFormattingError("payload_too_large")
    if len(rendered) <= MAX_INLINE_CHARACTERS:
        return FormattedTelegramDelivery(mode="text", text=rendered)

    normalized_event = unicodedata.normalize("NFC", str(event_id or "").strip())
    digest = hashlib.sha256(normalized_event.encode("utf-8")).hexdigest()[:20]
    filename = f"history-{digest}.txt"
    caption = _safe_text(
        f"History-Dispatcher · {history_kind} · {project}",
        maximum=MAX_CAPTION_CHARACTERS,
    )[:MAX_CAPTION_CHARACTERS]
    if not caption:
        caption = "History-Dispatcher"
    return FormattedTelegramDelivery(
        mode="document",
        filename=filename,
        document=encoded,
        caption=caption,
    )
