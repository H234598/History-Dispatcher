from __future__ import annotations

import base64
import os
import subprocess
from collections.abc import Callable

from cryptography.hazmat.primitives.ciphers.aead import AESGCM


class KeyUnavailable(RuntimeError):
    pass


class SecretServiceKeyProvider:
    def __init__(self, *, lookup: Callable[[], bytes] | None = None) -> None:
        self._lookup = lookup
        self._cached: bytes | None = None

    def get_key(self) -> bytes:
        if self._cached is not None:
            return self._cached
        if self._lookup is not None:
            value = self._lookup()
        else:
            try:
                completed = subprocess.run(
                    ["secret-tool", "lookup", "application", "history-dispatcher", "purpose", "payload-key"],
                    check=False,
                    capture_output=True,
                    timeout=5,
                )
            except (OSError, subprocess.TimeoutExpired) as exc:
                raise KeyUnavailable("Secret Service lookup failed") from exc
            if completed.returncode != 0:
                raise KeyUnavailable("History-Dispatcher payload key is unavailable")
            value = completed.stdout.strip()
            try:
                value = base64.b64decode(value, validate=True)
            except Exception:
                pass
        if not isinstance(value, bytes) or len(value) != 32:
            raise KeyUnavailable("History-Dispatcher payload key must be exactly 32 bytes")
        self._cached = value
        return value


class StaticKeyProvider(SecretServiceKeyProvider):
    def __init__(self, key: bytes) -> None:
        super().__init__(lookup=lambda: key)


def encrypt_json(payload: bytes, key_provider: SecretServiceKeyProvider, *, aad: bytes) -> bytes:
    nonce = os.urandom(12)
    ciphertext = AESGCM(key_provider.get_key()).encrypt(nonce, payload, aad)
    return nonce + ciphertext


def decrypt_json(blob: bytes, key_provider: SecretServiceKeyProvider, *, aad: bytes) -> bytes:
    if not isinstance(blob, bytes) or len(blob) < 12 + 16:
        raise KeyUnavailable("encrypted payload is malformed")
    return AESGCM(key_provider.get_key()).decrypt(blob[:12], blob[12:], aad)

