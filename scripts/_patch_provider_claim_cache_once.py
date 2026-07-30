from __future__ import annotations

from pathlib import Path


PATH = Path("history_dispatcher/service.py")


def replace_once(source: str, old: str, new: str, *, label: str) -> str:
    count = source.count(old)
    if count != 1:
        raise SystemExit(f"{label}: expected one match, found {count}")
    return source.replace(old, new, 1)


def main() -> None:
    source = PATH.read_text(encoding="utf-8")
    source = replace_once(
        source,
        """from .provider_api_v2 import (
    PROVIDER_API_OPERATIONS,
    ProviderApiV2,
    ProviderApiValidationError,
)
""",
        """from .provider_api_v2 import (
    PROVIDER_API_OPERATIONS,
    PROVIDER_API_SCHEMA_VERSION,
    ProviderApiV2,
    ProviderApiValidationError,
)
""",
        label="provider API import",
    )
    source = replace_once(
        source,
        """        if reservation_active and operation in ONE_SHOT_SENSITIVE_OPERATIONS:
            if isinstance(operation_exception, ProviderApiValidationError):
                try:
                    self.idempotency.release(
                        request_id,
                        operation,
                        fingerprint,
                    )
                except IdempotencyConflict:
                    return self._error(
                        "idempotency_conflict",
                        "request_id was already used with a different operation or body",
                    )
                except Exception:
                    return self._error(
                        "idempotency_persist_failed",
                        "one-shot request reservation could not be released",
                    )
            # A successful or operationally ambiguous claim response contains a
            # secret token and is deliberately never persisted in response_json.
            return response
""",
        """        if reservation_active and operation in ONE_SHOT_SENSITIVE_OPERATIONS:
            if isinstance(operation_exception, ProviderApiValidationError):
                try:
                    self.idempotency.release(
                        request_id,
                        operation,
                        fingerprint,
                    )
                except IdempotencyConflict:
                    return self._error(
                        "idempotency_conflict",
                        "request_id was already used with a different operation or body",
                    )
                except Exception:
                    return self._error(
                        "idempotency_persist_failed",
                        "one-shot request reservation could not be released",
                    )
                return response

            response_data = response.get("data")
            cacheable_empty_claim = (
                operation_exception is None
                and response.get("ok") is True
                and isinstance(response_data, dict)
                and response_data.get("ok") is True
                and response_data.get("schema_version")
                == PROVIDER_API_SCHEMA_VERSION
                and response_data.get("claims") == []
            )
            if not cacheable_empty_claim:
                # Token-bearing or operationally ambiguous claims remain one-shot
                # and are deliberately never persisted in response_json.
                return response
""",
        label="one-shot claim cache decision",
    )
    PATH.write_text(source, encoding="utf-8")


if __name__ == "__main__":
    main()
