from __future__ import annotations

import hashlib
import hmac
import re
import unicodedata
from typing import Any

from .crypto import SecretServiceKeyProvider


_ID_KDF_CONTEXT = b"history-dispatcher/persistent-identifiers/v1"
_NAMESPACE_RE = re.compile(r"^[a-z][a-z0-9_-]{0,63}$")


def _normalized_component(value: Any) -> str:
    return unicodedata.normalize("NFC", str(value or "").strip())


def _identifier_subkey(key_provider: SecretServiceKeyProvider) -> bytes:
    master_key = key_provider.get_key()
    return hmac.new(master_key, _ID_KDF_CONTEXT, hashlib.sha256).digest()


def persistent_opaque_id(
    key_provider: SecretServiceKeyProvider,
    namespace: str,
    value: Any,
    *,
    prefix: str | None = None,
    length: int = 32,
) -> str:
    """Derive a stable, namespace-separated local pseudonym with HMAC-SHA256.

    The master payload key never appears in the result. A dedicated subkey is
    derived first so identifier generation is cryptographically separated from
    AES-GCM payload encryption. Identifiers remain linkable inside installations
    that share the same Secret-Service key; they are not an anonymity boundary.
    """

    normalized_namespace = _normalized_component(namespace).lower()
    if not _NAMESPACE_RE.fullmatch(normalized_namespace):
        raise ValueError("identifier namespace is invalid")
    normalized_value = _normalized_component(value)
    normalized_prefix = _normalized_component(prefix or normalized_namespace).lower()
    if not _NAMESPACE_RE.fullmatch(normalized_prefix):
        raise ValueError("identifier prefix is invalid")
    safe_length = max(16, min(int(length), 64))
    if not normalized_value:
        return f"{normalized_prefix}_unknown"
    message = (
        normalized_namespace.encode("utf-8")
        + b"\x00"
        + normalized_value.encode("utf-8")
    )
    digest = hmac.new(
        _identifier_subkey(key_provider),
        message,
        hashlib.sha256,
    ).hexdigest()
    return f"{normalized_prefix}_{digest[:safe_length]}"
