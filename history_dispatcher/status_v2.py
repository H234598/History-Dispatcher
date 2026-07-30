from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Mapping

from .redaction import contains_sensitive_marker, redact_text


STATUS_SCHEMA_VERSION = 2
MAX_STATUS_BYTES = 64 * 1024
MAX_STATUS_WORKERS = 64

_SAFE_IDENTIFIER_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}$")
_FORBIDDEN_KEY_FRAGMENTS = (
    "token",
    "secret",
    "password",
    "chat_id",
    "recipient_id",
    "recipient_ref",
    "message_ref",
    "payload",
    "encrypted_payload",
)


class StatusProvider(str, Enum):
    TEEBOTUS = "teebotus"
    HISTORY_DISPATCHER = "history_dispatcher"

    @classmethod
    def parse(cls, value: StatusProvider | str) -> StatusProvider:
        if isinstance(value, cls):
            return value
        try:
            return cls(str(value or "").strip().casefold())
        except ValueError as exc:
            raise ValueError("unsupported status provider") from exc


def _safe_identifier(value: Any, *, field_name: str) -> str:
    if not isinstance(value, str):
        raise ValueError(f"{field_name} must be a string")
    normalized = value.strip()
    if not _SAFE_IDENTIFIER_RE.fullmatch(normalized):
        raise ValueError(f"{field_name} is invalid")
    return normalized


def _safe_optional_timestamp(value: Any, *, field_name: str) -> str | None:
    if value in (None, ""):
        return None
    if not isinstance(value, str):
        raise ValueError(f"{field_name} must be a string or null")
    normalized = value.strip()
    if len(normalized) > 64 or any(ord(character) < 0x20 for character in normalized):
        raise ValueError(f"{field_name} is invalid")
    return normalized


def _bounded_counts(value: Mapping[str, Any], *, field_name: str) -> dict[str, int]:
    if len(value) > 64:
        raise ValueError(f"{field_name} contains too many counters")
    result: dict[str, int] = {}
    for key, raw_count in value.items():
        normalized_key = _safe_identifier(str(key), field_name=f"{field_name} key")
        if isinstance(raw_count, bool):
            raise ValueError(f"{field_name}.{normalized_key} must be an integer")
        try:
            count = int(raw_count)
        except (TypeError, ValueError) as exc:
            raise ValueError(
                f"{field_name}.{normalized_key} must be an integer"
            ) from exc
        if count < 0 or count > 2**63 - 1:
            raise ValueError(f"{field_name}.{normalized_key} is out of range")
        result[normalized_key] = count
    return dict(sorted(result.items()))


@dataclass(frozen=True)
class CredentialStatus:
    configured: bool
    last_changed: str | None = None

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "last_changed",
            _safe_optional_timestamp(self.last_changed, field_name="last_changed"),
        )

    def as_dict(self) -> dict[str, Any]:
        return {
            "configured": bool(self.configured),
            "last_changed": self.last_changed,
        }


@dataclass(frozen=True)
class TelegramProviderStatus:
    provider: StatusProvider | str
    credential: CredentialStatus

    def __post_init__(self) -> None:
        object.__setattr__(self, "provider", StatusProvider.parse(self.provider))
        if not isinstance(self.credential, CredentialStatus):
            raise ValueError("credential must be a CredentialStatus")

    def as_dict(self) -> dict[str, Any]:
        return {
            "provider": self.provider.value,
            "credential": self.credential.as_dict(),
        }


@dataclass(frozen=True)
class WorkerHealthStatus:
    worker_id: str
    target: str
    provider: str
    capability: str
    state: str
    heartbeat: str | None = None

    def __post_init__(self) -> None:
        for field_name in ("worker_id", "target", "provider", "capability"):
            object.__setattr__(
                self,
                field_name,
                _safe_identifier(getattr(self, field_name), field_name=field_name),
            )
        state = redact_text(self.state, max_chars=64, max_bytes=256)
        if not state:
            raise ValueError("state must not be empty")
        object.__setattr__(self, "state", state)
        object.__setattr__(
            self,
            "heartbeat",
            _safe_optional_timestamp(self.heartbeat, field_name="heartbeat"),
        )

    def as_dict(self) -> dict[str, Any]:
        return {
            "worker_id": self.worker_id,
            "target": self.target,
            "provider": self.provider,
            "capability": self.capability,
            "state": self.state,
            "heartbeat": self.heartbeat,
        }


@dataclass(frozen=True)
class HealthStatusV2:
    telegram: TelegramProviderStatus
    workers: tuple[WorkerHealthStatus, ...] = ()
    queue: Mapping[str, int] = field(default_factory=dict)
    deliveries: Mapping[str, int] = field(default_factory=dict)
    generated_at: str | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.telegram, TelegramProviderStatus):
            raise ValueError("telegram must be a TelegramProviderStatus")
        workers = tuple(self.workers)
        if len(workers) > MAX_STATUS_WORKERS:
            raise ValueError("too many worker health rows")
        if not all(isinstance(worker, WorkerHealthStatus) for worker in workers):
            raise ValueError("workers must contain WorkerHealthStatus values")
        object.__setattr__(self, "workers", workers)
        object.__setattr__(self, "queue", _bounded_counts(self.queue, field_name="queue"))
        object.__setattr__(
            self,
            "deliveries",
            _bounded_counts(self.deliveries, field_name="deliveries"),
        )
        object.__setattr__(
            self,
            "generated_at",
            _safe_optional_timestamp(self.generated_at, field_name="generated_at"),
        )

    def as_dict(self) -> dict[str, Any]:
        payload = {
            "schema_version": STATUS_SCHEMA_VERSION,
            "generated_at": self.generated_at,
            "telegram": self.telegram.as_dict(),
            "workers": [worker.as_dict() for worker in self.workers],
            "queue": dict(self.queue),
            "deliveries": dict(self.deliveries),
        }
        validate_redacted_status(payload)
        return payload

    def redacted(self) -> dict[str, Any]:
        return self.as_dict()


# Compatibility aliases for the initial PR-HD-07 draft contract.
StatusV2 = HealthStatusV2
WorkerHealth = WorkerHealthStatus


def validate_redacted_status(payload: Mapping[str, Any]) -> None:
    if not isinstance(payload, Mapping):
        raise ValueError("status payload must be an object")

    nodes = 0

    def check(value: Any, *, depth: int = 0) -> None:
        nonlocal nodes
        nodes += 1
        if nodes > 4096:
            raise ValueError("status payload contains too many values")
        if depth > 12:
            raise ValueError("status payload is nested too deeply")
        if isinstance(value, Mapping):
            for key, child in value.items():
                normalized_key = str(key).strip().casefold().replace("-", "_")
                if any(fragment in normalized_key for fragment in _FORBIDDEN_KEY_FRAGMENTS):
                    raise ValueError("status payload contains forbidden secret fields")
                check(child, depth=depth + 1)
        elif isinstance(value, (list, tuple)):
            for child in value:
                check(child, depth=depth + 1)
        elif isinstance(value, str):
            if contains_sensitive_marker(value):
                raise ValueError("status payload contains a sensitive value")
        elif value is not None and not isinstance(value, (bool, int, float)):
            raise ValueError("status payload contains an unsupported value")

    check(payload)
    try:
        encoded = json.dumps(
            payload,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        ).encode("utf-8")
    except (TypeError, ValueError) as exc:
        raise ValueError("status payload is not finite JSON") from exc
    if len(encoded) > MAX_STATUS_BYTES:
        raise ValueError("status payload exceeds 64 KiB")
