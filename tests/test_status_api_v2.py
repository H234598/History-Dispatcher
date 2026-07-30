from __future__ import annotations

import pytest

from history_dispatcher.status_api_v2 import (
    StatusApiError,
    build_redacted_status_response,
)
from history_dispatcher.status_v2 import (
    CredentialStatus,
    HealthStatusV2,
    TelegramProviderStatus,
    WorkerHealthStatus,
)


def _status() -> HealthStatusV2:
    return HealthStatusV2(
        telegram=TelegramProviderStatus(
            provider="history_dispatcher",
            credential=CredentialStatus(
                configured=True,
                last_changed="2026-07-30T12:00:00Z",
            ),
        ),
        workers=(
            WorkerHealthStatus(
                worker_id="telegram-worker",
                target="telegram",
                provider="history_dispatcher",
                capability="history-dispatcher-telegram-native-v1",
                state="idle",
                heartbeat="2026-07-30T12:00:00Z",
            ),
        ),
        generated_at="2026-07-30T12:00:00Z",
    )


def test_status_api_wraps_redacted_health_status() -> None:
    response = build_redacted_status_response(_status()).as_dict()

    assert response["version"] == 2
    assert response["status"]["schema_version"] == 2
    assert response["status"]["telegram"]["provider"] == "history_dispatcher"


def test_status_api_response_returns_a_nested_copy() -> None:
    response = build_redacted_status_response(_status())
    first = response.as_dict()
    first["status"]["telegram"]["provider"] = "modified"

    second = response.as_dict()

    assert second["status"]["telegram"]["provider"] == "history_dispatcher"


def test_status_api_rejects_secret_fields() -> None:
    class Unsafe:
        def as_dict(self):
            return {"schema_version": 2, "token": "secret"}

    with pytest.raises(StatusApiError, match="forbidden"):
        build_redacted_status_response(Unsafe())


def test_status_api_rejects_wrong_schema_version() -> None:
    class WrongVersion:
        def as_dict(self):
            return {"schema_version": 1}

    with pytest.raises(StatusApiError, match="schema version"):
        build_redacted_status_response(WrongVersion())
