from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, Mapping, Protocol

from .status_v2 import STATUS_SCHEMA_VERSION, validate_redacted_status


STATUS_API_VERSION = 2


class StatusApiError(ValueError):
    pass


class StatusPayloadSource(Protocol):
    def as_dict(self) -> Mapping[str, Any]: ...


@dataclass(frozen=True)
class RedactedStatusResponse:
    version: int
    status: Mapping[str, Any]

    def as_dict(self) -> dict[str, Any]:
        # Canonical JSON round-tripping prevents callers from mutating nested
        # objects retained by the response instance.
        return json.loads(
            json.dumps(
                {
                    "version": self.version,
                    "status": dict(self.status),
                },
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
                allow_nan=False,
            )
        )


def build_redacted_status_response(
    status: StatusPayloadSource,
) -> RedactedStatusResponse:
    try:
        payload = dict(status.as_dict())
        if int(payload.get("schema_version", 0) or 0) != STATUS_SCHEMA_VERSION:
            raise StatusApiError("status schema version mismatch")
        validate_redacted_status(payload)
    except StatusApiError:
        raise
    except (TypeError, ValueError) as exc:
        raise StatusApiError(str(exc)) from exc
    return RedactedStatusResponse(
        version=STATUS_API_VERSION,
        status=payload,
    )
