from __future__ import annotations

import hashlib
import json
import os
import re
import tempfile
import unicodedata
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping

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
_SAFE_PROTOCOL_KEYS = {
    "type",
    "role",
    "phase",
    "source",
    "thread_source",
    "kind",
    "status",
    "cli_version",
    "model_provider",
    "history_mode",
    "memory_mode",
    "multi_agent_version",
}


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


def _digest(value: Any, *, prefix: str) -> str:
    raw = unicodedata.normalize("NFC", str(value or "")).encode("utf-8")
    return f"{prefix}_{hashlib.sha256(raw).hexdigest()[:20]}"


def _sanitize_path(value: Any) -> Any:
    if isinstance(value, list):
        return [_sanitize_path(item) for item in value[:256]]
    if isinstance(value, Mapping):
        return {str(key): _sanitize_path(item) for key, item in value.items()}
    if value in (None, ""):
        return value
    return f"fixture-path/{_digest(value, prefix='path')}"


def _sanitize_url(value: Any) -> Any:
    if value in (None, ""):
        return value
    return f"https://example.invalid/{_digest(value, prefix='repo')}.git"


def _sanitize_text(value: Any) -> Any:
    if value is None:
        return None
    if isinstance(value, list):
        return [_sanitize_text(item) for item in value[:256]]
    if isinstance(value, Mapping):
        return {str(key): sanitize_value(item, key=str(key)) for key, item in value.items()}
    if isinstance(value, str):
        return f"fixture text {_digest(value, prefix='txt')}"
    return value


def sanitize_value(value: Any, *, key: str = "") -> Any:
    normalized_key = str(key or "").strip().lower()
    if normalized_key and _SECRET_KEY_RE.search(normalized_key):
        return "[redacted]"
    if normalized_key in _IDENTIFIER_KEYS:
        return _digest(value, prefix=normalized_key or "id") if value not in (None, "") else value
    if normalized_key in _PATH_KEYS or normalized_key.endswith("_path"):
        return _sanitize_path(value)
    if normalized_key in _URL_KEYS or normalized_key.endswith("_url"):
        return _sanitize_url(value)
    if normalized_key in _PERSONAL_METADATA_KEYS:
        return _digest(value, prefix="meta") if value not in (None, "") else value
    if normalized_key in _TEXT_KEYS:
        return _sanitize_text(value)
    if isinstance(value, Mapping):
        return {
            str(child_key): sanitize_value(child_value, key=str(child_key))
            for child_key, child_value in value.items()
        }
    if isinstance(value, list):
        return [sanitize_value(item, key=normalized_key) for item in value[:1024]]
    if isinstance(value, str):
        normalized = unicodedata.normalize("NFC", value)
        if normalized_key in _SAFE_PROTOCOL_KEYS or normalized_key in {
            "timestamp",
            "created_at",
            "completed_at",
        }:
            return normalized[:512]
        return _digest(normalized, prefix="value")
    return value


def _sanitize_line(
    raw_line: bytes,
    *,
    line_number: int,
    max_line_bytes: int,
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
    except (json.JSONDecodeError, ValueError) as exc:
        raise ValueError(f"line {line_number} is invalid JSON") from exc
    if not isinstance(record, dict):
        raise ValueError(f"line {line_number} must be a JSON object")
    sanitized = sanitize_value(record)
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
    for line_number, raw_line in enumerate(source.splitlines(), start=1):
        encoded = _sanitize_line(
            raw_line,
            line_number=line_number,
            max_line_bytes=max_line_bytes,
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
    output.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    descriptor: int | None = None
    temporary: Path | None = None
    handle = None
    if not dry_run:
        descriptor, temporary_name = tempfile.mkstemp(
            prefix=f".{output.name}.", suffix=".tmp", dir=output.parent
        )
        temporary = Path(temporary_name)
        handle = os.fdopen(descriptor, "wb")
        descriptor = None
    try:
        with Path(source_path).open("rb") as source_handle:
            for line_number, raw_with_newline in enumerate(source_handle, start=1):
                source_hash.update(raw_with_newline)
                raw_line = raw_with_newline.rstrip(b"\r\n")
                encoded = _sanitize_line(
                    raw_line,
                    line_number=line_number,
                    max_line_bytes=max_line_bytes,
                )
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
