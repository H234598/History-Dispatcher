from __future__ import annotations

import hashlib
import json
import os
import re
import tempfile
import unicodedata
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, BinaryIO, Mapping

from .redaction import contains_sensitive_marker


SANITIZER_SCHEMA_VERSION = 1
DEFAULT_MAX_LINE_BYTES = 8 * 1024 * 1024

_IDENTIFIER_KEYS = {
    "id",
    "session_id",
    "thread_id",
    "turn_id",
    "parent_thread_id",
    "forked_from_id",
    "call_id",
    "request_id",
    "conversation_id",
    "window_id",
    "item_id",
}
_PATH_KEYS = {
    "cwd",
    "path",
    "rollout_path",
    "saved_path",
    "agent_path",
    "local_image",
    "local_images",
    "preexisting_untracked_dirs",
    "preexisting_untracked_files",
}
_URL_KEYS = {
    "url",
    "remote_url",
    "origin_url",
    "repository_url",
    "git_remote",
}
_TEXT_KEYS = {
    "message",
    "text",
    "last_agent_message",
    "content",
    "summary",
    "reason",
    "error",
    "base_instructions",
    "developer_message",
    "user_message",
}
_PERSONAL_METADATA_KEYS = {
    "originator",
    "agent_nickname",
    "agent_role",
    "agent_type",
    "user_name",
    "username",
    "email",
    "name",
    "title",
    "label",
    "project",
    "repository",
    "repo_name",
}
_SECRET_KEY_RE = re.compile(
    r"(?i)(token|secret|password|passwd|api[_-]?key|authorization|credential|chat[_-]?id|recipient[_-]?id)"
)
_TIMESTAMP_KEYS = {"timestamp", "created_at", "completed_at", "occurred_at"}
_APPROVED_NUMERIC_KEYS = {
    "ordinal",
    "depth",
    "subagent_history_start_ordinal",
    "completed_at_ms",
}
_APPROVED_BOOLEAN_KEYS = {"success", "is_error"}
_APPROVED_PROTOCOL_VALUES = {
    "type": {
        "session_meta",
        "response_item",
        "turn_context",
        "event_msg",
        "event",
        "message",
        "user_message",
        "agent_message",
        "task_started",
        "turn_started",
        "task_complete",
        "turn_complete",
        "output_text",
        "input_text",
        "input_image",
        "reasoning",
        "function_call",
        "ghost_snapshot",
    },
    "role": {"assistant", "user", "system", "developer", "tool"},
    "phase": {"commentary", "final_answer", "final"},
    "source": {"cli", "vscode", "exec", "mcp", "unknown"},
    "thread_source": {"user", "subagent", "memory_consolidation"},
    "history_mode": {"legacy", "paginated"},
    "memory_mode": {"enabled", "disabled"},
    "multi_agent_version": {"disabled", "v1", "v2"},
    "status": {
        "queued",
        "delivering",
        "delivered",
        "failed",
        "skipped",
        "discarded",
    },
    "kind": {"plain"},
}
_PRESERVED_MAPPING_KEYS = frozenset(
    _IDENTIFIER_KEYS
    | _PATH_KEYS
    | _URL_KEYS
    | _TEXT_KEYS
    | _PERSONAL_METADATA_KEYS
    | _TIMESTAMP_KEYS
    | _APPROVED_NUMERIC_KEYS
    | _APPROVED_BOOLEAN_KEYS
    | set(_APPROVED_PROTOCOL_VALUES)
    | {
        "payload",
        "git",
        "branch",
        "commit_hash",
        "dynamic_tools",
        "selected_capability_roots",
        "history_base",
        "context_window",
        "subagent",
        "thread_spawn",
        "internal",
        "unknown",
        "review",
        "compact",
        "memory_consolidation",
        "value",
        "arguments",
        "result",
        "image_url",
        "images",
        "local_images",
        "text_elements",
    }
)


@dataclass
class _FixturePseudonyms:
    aliases: dict[tuple[str, str], str] = field(default_factory=dict)
    counters: dict[str, int] = field(default_factory=dict)

    def alias(self, value: Any, *, prefix: str) -> str:
        if isinstance(value, str):
            canonical = unicodedata.normalize("NFC", value)
        else:
            canonical = json.dumps(
                value,
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
                default=str,
            )
        key = (prefix, f"{type(value).__name__}:{canonical}")
        existing = self.aliases.get(key)
        if existing is not None:
            return existing
        next_value = self.counters.get(prefix, 0) + 1
        self.counters[prefix] = next_value
        alias = f"{prefix}_{next_value:04d}"
        self.aliases[key] = alias
        return alias


@dataclass(frozen=True)
class SanitizedFixture:
    sanitizer_schema_version: int
    source_sha256: str
    output_sha256: str
    line_count: int
    output_bytes: bytes | None

    def manifest_entry(self, *, upstream_commit: str = "") -> dict[str, Any]:
        return {
            "sanitizer_schema_version": self.sanitizer_schema_version,
            "source_ref": f"source-{self.source_sha256[:12]}.jsonl",
            "source_sha256": self.source_sha256,
            "output_sha256": self.output_sha256,
            "line_count": self.line_count,
            "upstream_commit": str(upstream_commit or ""),
        }


def _reject_json_constant(value: str) -> None:
    raise ValueError(f"non-finite JSON constant: {value}")


def _reject_duplicate_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"duplicate JSON key: {key}")
        result[key] = value
    return result


def _strict_json_loads(value: str) -> Any:
    return json.loads(
        value,
        parse_constant=_reject_json_constant,
        object_pairs_hook=_reject_duplicate_keys,
    )


def _sanitize_mapping(
    value: Mapping[Any, Any],
    *,
    pseudonyms: _FixturePseudonyms,
) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for child_key, child_value in value.items():
        raw_key = unicodedata.normalize("NFC", str(child_key))
        normalized_key = raw_key.strip().lower()
        output_key = (
            raw_key
            if normalized_key in _PRESERVED_MAPPING_KEYS
            else pseudonyms.alias(raw_key, prefix="field")
        )
        result[output_key] = _sanitize_value(
            child_value,
            key=normalized_key,
            pseudonyms=pseudonyms,
        )
    return result


def _sanitize_path(value: Any, *, pseudonyms: _FixturePseudonyms) -> Any:
    if isinstance(value, list):
        return [
            _sanitize_path(item, pseudonyms=pseudonyms)
            for item in value[:256]
        ]
    if isinstance(value, Mapping):
        return _sanitize_mapping(value, pseudonyms=pseudonyms)
    if value in (None, ""):
        return value
    return f"fixture-path/{pseudonyms.alias(value, prefix='path')}"


def _sanitize_url(value: Any, *, pseudonyms: _FixturePseudonyms) -> Any:
    if value in (None, ""):
        return value
    return f"https://example.invalid/{pseudonyms.alias(value, prefix='repo')}.git"


def _sanitize_text(value: Any, *, pseudonyms: _FixturePseudonyms) -> Any:
    if value is None:
        return None
    if isinstance(value, list):
        return [
            _sanitize_text(item, pseudonyms=pseudonyms)
            for item in value[:256]
        ]
    if isinstance(value, Mapping):
        return _sanitize_mapping(value, pseudonyms=pseudonyms)
    if isinstance(value, str):
        return f"fixture text {pseudonyms.alias(value, prefix='txt')}"
    return pseudonyms.alias(value, prefix="txt")


def _sanitize_value(
    value: Any,
    *,
    key: str,
    pseudonyms: _FixturePseudonyms,
) -> Any:
    normalized_key = str(key or "").strip().lower()
    if normalized_key and _SECRET_KEY_RE.search(normalized_key):
        return "[redacted]"
    if normalized_key in _IDENTIFIER_KEYS:
        return (
            pseudonyms.alias(value, prefix=normalized_key or "id")
            if value not in (None, "")
            else value
        )
    if normalized_key in _PATH_KEYS or normalized_key.endswith("_path"):
        return _sanitize_path(value, pseudonyms=pseudonyms)
    if normalized_key in _URL_KEYS or normalized_key.endswith("_url"):
        return _sanitize_url(value, pseudonyms=pseudonyms)
    if normalized_key in _PERSONAL_METADATA_KEYS:
        return (
            pseudonyms.alias(value, prefix="meta")
            if value not in (None, "")
            else value
        )
    if normalized_key in _TEXT_KEYS:
        return _sanitize_text(value, pseudonyms=pseudonyms)
    if isinstance(value, Mapping):
        return _sanitize_mapping(value, pseudonyms=pseudonyms)
    if isinstance(value, list):
        return [
            _sanitize_value(item, key=normalized_key, pseudonyms=pseudonyms)
            for item in value[:1024]
        ]
    if value is None:
        return None
    if isinstance(value, str):
        normalized = unicodedata.normalize("NFC", value)
        if normalized_key in _TIMESTAMP_KEYS:
            return normalized[:512]
        approved = _APPROVED_PROTOCOL_VALUES.get(normalized_key)
        if approved is not None and normalized in approved:
            return normalized
        return pseudonyms.alias(normalized, prefix="value")
    if isinstance(value, bool):
        if normalized_key in _APPROVED_BOOLEAN_KEYS:
            return value
        return pseudonyms.alias(value, prefix="value")
    if isinstance(value, (int, float)):
        if normalized_key in _APPROVED_NUMERIC_KEYS:
            return value
        return pseudonyms.alias(value, prefix="value")
    return pseudonyms.alias(value, prefix="value")


def sanitize_value(value: Any, *, key: str = "") -> Any:
    """Sanitize one value with an isolated first-seen pseudonym namespace."""

    return _sanitize_value(
        value,
        key=key,
        pseudonyms=_FixturePseudonyms(),
    )


def _sanitize_line(
    raw_line: bytes,
    *,
    line_number: int,
    max_line_bytes: int,
    pseudonyms: _FixturePseudonyms,
) -> bytes | None:
    if not raw_line.strip():
        return None
    if len(raw_line) > max(256, int(max_line_bytes)):
        raise ValueError(f"line {line_number} exceeds maximum size")
    try:
        decoded = raw_line.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise ValueError(f"line {line_number} is not UTF-8") from exc
    try:
        record = _strict_json_loads(decoded)
    except (ValueError, RecursionError) as exc:
        raise ValueError(f"line {line_number} is invalid JSON") from exc
    if not isinstance(record, dict):
        raise ValueError(f"line {line_number} must be a JSON object")
    sanitized = _sanitize_mapping(record, pseudonyms=pseudonyms)
    encoded = json.dumps(
        sanitized,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")
    if contains_sensitive_marker(encoded.decode("utf-8")):
        raise ValueError(f"line {line_number} still contains a sensitive marker")
    return encoded


def sanitize_jsonl_bytes(
    source: bytes,
    *,
    max_line_bytes: int = DEFAULT_MAX_LINE_BYTES,
) -> SanitizedFixture:
    source_sha = hashlib.sha256(source).hexdigest()
    output_lines: list[bytes] = []
    line_count = 0
    pseudonyms = _FixturePseudonyms()
    for line_number, raw_line in enumerate(source.splitlines(), start=1):
        encoded = _sanitize_line(
            raw_line,
            line_number=line_number,
            max_line_bytes=max_line_bytes,
            pseudonyms=pseudonyms,
        )
        if encoded is None:
            continue
        output_lines.append(encoded)
        line_count += 1
    output = b"\n".join(output_lines) + (b"\n" if output_lines else b"")
    return SanitizedFixture(
        sanitizer_schema_version=SANITIZER_SCHEMA_VERSION,
        source_sha256=source_sha,
        output_sha256=hashlib.sha256(output).hexdigest(),
        line_count=line_count,
        output_bytes=output,
    )


def _read_bounded_line(
    handle: BinaryIO,
    *,
    line_number: int,
    max_line_bytes: int,
) -> bytes:
    safe_limit = max(256, int(max_line_bytes))
    raw = handle.readline(safe_limit + 3)
    if not raw:
        return b""
    raw_without_newline = raw.rstrip(b"\r\n")
    if len(raw_without_newline) > safe_limit:
        raise ValueError(f"line {line_number} exceeds maximum size")
    if not raw.endswith(b"\n") and len(raw) > safe_limit:
        raise ValueError(f"line {line_number} exceeds maximum size")
    return raw


def sanitize_jsonl_file(
    source_path: Path,
    output_path: Path,
    *,
    max_line_bytes: int = DEFAULT_MAX_LINE_BYTES,
    dry_run: bool = False,
) -> SanitizedFixture:
    source_hash = hashlib.sha256()
    output_hash = hashlib.sha256()
    line_count = 0
    output = Path(output_path)
    descriptor: int | None = None
    temporary: Path | None = None
    handle = None
    pseudonyms = _FixturePseudonyms()
    if not dry_run:
        output.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        descriptor, temporary_name = tempfile.mkstemp(
            prefix=f".{output.name}.", suffix=".tmp", dir=output.parent
        )
        temporary = Path(temporary_name)
        handle = os.fdopen(descriptor, "wb")
        descriptor = None
    try:
        with Path(source_path).open("rb") as source_handle:
            line_number = 1
            while True:
                raw_with_newline = _read_bounded_line(
                    source_handle,
                    line_number=line_number,
                    max_line_bytes=max_line_bytes,
                )
                if not raw_with_newline:
                    break
                source_hash.update(raw_with_newline)
                raw_line = raw_with_newline.rstrip(b"\r\n")
                encoded = _sanitize_line(
                    raw_line,
                    line_number=line_number,
                    max_line_bytes=max_line_bytes,
                    pseudonyms=pseudonyms,
                )
                line_number += 1
                if encoded is None:
                    continue
                rendered = encoded + b"\n"
                output_hash.update(rendered)
                line_count += 1
                if handle is not None:
                    handle.write(rendered)
        if handle is not None:
            handle.flush()
            os.fsync(handle.fileno())
            handle.close()
            handle = None
            assert temporary is not None
            os.chmod(temporary, 0o600)
            os.replace(temporary, output)
        return SanitizedFixture(
            sanitizer_schema_version=SANITIZER_SCHEMA_VERSION,
            source_sha256=source_hash.hexdigest(),
            output_sha256=output_hash.hexdigest(),
            line_count=line_count,
            output_bytes=None,
        )
    finally:
        if handle is not None:
            handle.close()
        if descriptor is not None:
            os.close(descriptor)
        if temporary is not None:
            try:
                temporary.unlink()
            except FileNotFoundError:
                pass


def write_manifest(
    path: Path,
    entries: list[dict[str, Any]],
    *,
    upstream_commit: str = "",
) -> None:
    payload = {
        "sanitizer_schema_version": SANITIZER_SCHEMA_VERSION,
        "upstream_commit": str(upstream_commit or ""),
        "files": entries,
    }
    encoded = (
        json.dumps(payload, ensure_ascii=False, sort_keys=True, indent=2, allow_nan=False)
        + "\n"
    ).encode("utf-8")
    _atomic_write(Path(path), encoded)


def _atomic_write(path: Path, data: bytes) -> None:
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{path.name}.", suffix=".tmp", dir=path.parent
    )
    temporary = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        os.chmod(temporary, 0o600)
        os.replace(temporary, path)
    finally:
        try:
            temporary.unlink()
        except FileNotFoundError:
            pass
