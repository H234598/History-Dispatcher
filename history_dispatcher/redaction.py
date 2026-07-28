from __future__ import annotations

import hashlib
import re
import unicodedata
from pathlib import PurePosixPath
from typing import Any, Iterable
from urllib.parse import urlsplit, urlunsplit


MAX_VISIBLE_TEXT_BYTES = 512 * 1024
MAX_VISIBLE_TEXT_CHARS = 512 * 1024
MAX_PROJECT_LABEL_CHARS = 80

_OPENAI_TOKEN_RE = re.compile(r"\bsk-(?:proj-)?[A-Za-z0-9_-]{12,}\b")
_TELEGRAM_TOKEN_RE = re.compile(r"\b\d{6,12}:[A-Za-z0-9_-]{20,}\b")
_BEARER_RE = re.compile(r"(?i)\bBearer\s+[A-Za-z0-9._~+\-/=]{8,}")
_SECRET_ASSIGNMENT_RE = re.compile(
    r"(?i)\b(api[_-]?key|access[_-]?token|refresh[_-]?token|token|password|passwd|secret|authorization)"
    r"\s*[:=]\s*(['\"]?)([^\s'\"`,;]{4,})\2"
)
_EMAIL_RE = re.compile(r"(?i)\b[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}\b")
_UNIX_PRIVATE_PATH_RE = re.compile(
    r"(?<![A-Za-z0-9_.:/-])(?:"
    r"/(?:home|root|mnt|media|tmp|opt|srv|workspace)/[^\s'\"`<>]+"
    r"|/run/user/\d+/[^\s'\"`<>]*"
    r"|/var/tmp/[^\s'\"`<>]+"
    r"|/Users/[^\s'\"`<>]+"
    r")"
)
_WINDOWS_PRIVATE_PATH_RE = re.compile(r"(?i)\b[A-Z]:\\[^\r\n'\"`<>]+")
_URL_WITH_CREDENTIALS_RE = re.compile(r"(?i)\b(https?://)([^/@\s:]+):([^/@\s]+)@")
_CONTROL_RE = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f-\x9f]")
_SPACE_BEFORE_NEWLINE_RE = re.compile(r"[ \t]+\n")
_EXCESSIVE_BLANKS_RE = re.compile(r"\n{4,}")


def _truncate(
    text: str,
    *,
    max_chars: int,
    max_bytes: int,
) -> str:
    safe_chars = max(1, min(int(max_chars), MAX_VISIBLE_TEXT_CHARS))
    safe_bytes = max(1, min(int(max_bytes), MAX_VISIBLE_TEXT_BYTES))
    marker = "\n… [truncated]"
    truncated = text
    needs_marker = False
    if len(truncated) > safe_chars:
        truncated = truncated[:safe_chars]
        needs_marker = True
    encoded = truncated.encode("utf-8")
    if len(encoded) > safe_bytes:
        marker_bytes = marker.encode("utf-8")
        content_budget = max(0, safe_bytes - len(marker_bytes))
        truncated = encoded[:content_budget].decode("utf-8", errors="ignore")
        needs_marker = True
    if not needs_marker:
        return truncated
    if safe_bytes <= len(marker.encode("utf-8")) or safe_chars <= len(marker):
        return marker.encode("utf-8")[:safe_bytes].decode("utf-8", errors="ignore")[:safe_chars]
    candidate = truncated.rstrip() + marker
    while len(candidate) > safe_chars or len(candidate.encode("utf-8")) > safe_bytes:
        truncated = truncated[:-1]
        candidate = truncated.rstrip() + marker
    return candidate


def redact_text(
    value: Any,
    *,
    max_chars: int = MAX_VISIBLE_TEXT_CHARS,
    max_bytes: int = MAX_VISIBLE_TEXT_BYTES,
) -> str:
    """Normalize and redact untrusted visible text deterministically.

    This is intentionally conservative for UI and external-delivery preparation:
    common credentials, private home/runtime paths, credential-bearing URLs and
    email addresses are removed. The function never raises on arbitrary values.
    """

    if value is None:
        return ""
    text = value if isinstance(value, str) else str(value)
    text = unicodedata.normalize("NFC", text).replace("\r\n", "\n").replace("\r", "\n")
    text = _CONTROL_RE.sub("�", text)
    text = _URL_WITH_CREDENTIALS_RE.sub(r"\1[redacted]@", text)
    text = _OPENAI_TOKEN_RE.sub("[redacted-token]", text)
    text = _TELEGRAM_TOKEN_RE.sub("[redacted-token]", text)
    text = _BEARER_RE.sub("Bearer [redacted-token]", text)
    text = _SECRET_ASSIGNMENT_RE.sub(lambda match: f"{match.group(1)}=[redacted]", text)
    text = _EMAIL_RE.sub("[redacted-email]", text)
    text = _UNIX_PRIVATE_PATH_RE.sub("[redacted-path]", text)
    text = _WINDOWS_PRIVATE_PATH_RE.sub("[redacted-path]", text)
    text = _SPACE_BEFORE_NEWLINE_RE.sub("\n", text)
    text = _EXCESSIVE_BLANKS_RE.sub("\n\n\n", text)
    return _truncate(text.strip(), max_chars=max_chars, max_bytes=max_bytes)


def visible_output_text(
    content: Any,
    *,
    max_chars: int = MAX_VISIBLE_TEXT_CHARS,
    max_bytes: int = MAX_VISIBLE_TEXT_BYTES,
) -> str:
    """Return only visible assistant output_text parts from a response item."""

    if not isinstance(content, list):
        return ""
    parts: list[str] = []
    total = 0
    for item in content:
        if not isinstance(item, dict) or str(item.get("type") or "") != "output_text":
            continue
        raw = item.get("text")
        if not isinstance(raw, str):
            continue
        safe = redact_text(raw, max_chars=max_chars, max_bytes=max_bytes)
        if not safe:
            continue
        parts.append(safe)
        total += len(safe)
        if total >= max_chars:
            break
    return _truncate("\n".join(parts), max_chars=max_chars, max_bytes=max_bytes)


def stable_opaque_id(prefix: str, value: Any, *, length: int = 24) -> str:
    normalized = unicodedata.normalize("NFC", str(value or "").strip())
    if not normalized:
        return f"{prefix}_unknown"
    digest = hashlib.sha256(normalized.encode("utf-8")).hexdigest()
    return f"{prefix}_{digest[: max(8, min(int(length), 64))]}"


def normalize_git_remote(value: Any) -> str:
    """Return a credential-free canonical remote used only for hashing/labels."""

    text = unicodedata.normalize("NFC", str(value or "").strip())
    if not text:
        return ""
    if text.startswith("git@") and ":" in text:
        host_and_path = text[4:]
        host, repo_path = host_and_path.split(":", 1)
        text = f"ssh://{host}/{repo_path}"
    try:
        parsed = urlsplit(text)
    except ValueError:
        parsed = None
    if parsed and parsed.scheme and parsed.hostname:
        host = parsed.hostname.lower()
        port = f":{parsed.port}" if parsed.port else ""
        path = re.sub(r"/+", "/", parsed.path or "").rstrip("/")
        if path.endswith(".git"):
            path = path[:-4]
        return urlunsplit((parsed.scheme.lower(), host + port, path, "", ""))
    path = re.sub(r"/+", "/", text).rstrip("/")
    if path.endswith(".git"):
        path = path[:-4]
    return path


def _basename(value: str) -> str:
    normalized = value.replace("\\", "/").rstrip("/")
    if not normalized:
        return ""
    try:
        return PurePosixPath(normalized).name
    except Exception:
        return ""


def project_identity(*, remote: Any = "", cwd: Any = "") -> tuple[str, str]:
    canonical_remote = normalize_git_remote(remote)
    raw_cwd = unicodedata.normalize("NFC", str(cwd or "").strip())
    identity_source = canonical_remote or raw_cwd
    if not identity_source:
        return "proj_unknown", "Unbekanntes Projekt"
    project_id = stable_opaque_id("proj", identity_source)
    label_source = _basename(canonical_remote) or _basename(raw_cwd) or "Projekt"
    label = safe_project_label(label_source)
    return project_id, label


def safe_project_label(value: Any, *, max_chars: int = MAX_PROJECT_LABEL_CHARS) -> str:
    text = redact_text(value, max_chars=max_chars, max_bytes=max_chars * 4)
    text = text.replace("/", "-").replace("\\", "-")
    text = re.sub(r"\s+", " ", text).strip(" .-")
    if not text:
        return "Unbekanntes Projekt"
    return _truncate(text, max_chars=max_chars, max_bytes=max_chars * 4)


def contains_sensitive_marker(text: str) -> bool:
    """Return True for markers that must never survive fixture sanitization."""

    checks: Iterable[re.Pattern[str]] = (
        _OPENAI_TOKEN_RE,
        _TELEGRAM_TOKEN_RE,
        _EMAIL_RE,
        _UNIX_PRIVATE_PATH_RE,
        _WINDOWS_PRIVATE_PATH_RE,
    )
    return any(pattern.search(text) for pattern in checks)
