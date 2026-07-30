from __future__ import annotations

import pytest

from history_dispatcher.status_v2 import (
    CredentialStatus,
    HealthStatusV2,
    StatusProvider,
    StatusV2,
    TelegramProviderStatus,
    WorkerHealth,
    WorkerHealthStatus,
    validate_redacted_status,
)


def test_status_v2_redacts_operational_view() -> None:
    status = HealthStatusV2(
        telegram=TelegramProviderStatus(
            provider=StatusProvider.HISTORY_DISPATCHER,
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
                state="healthy",
            ),
        ),
        queue={"queued": 2},
        deliveries={"pending": 1},
        generated_at="2026-07-30T12:00:00Z",
    )

    payload = status.as_dict()

    assert payload["schema_version"] == 2
    assert payload["telegram"]["provider"] == "history_dispatcher"
    assert payload["telegram"]["credential"] == {
        "configured": True,
        "last_changed": "2026-07-30T12:00:00Z",
    }
    assert payload["queue"] == {"queued": 2}
    validate_redacted_status(payload)


def test_initial_status_contract_aliases_remain_compatible() -> None:
    assert StatusV2 is HealthStatusV2
    assert WorkerHealth is WorkerHealthStatus


def test_worker_state_is_redacted_before_status_output() -> None:
    worker = WorkerHealthStatus(
        worker_id="telegram-worker",
        target="telegram",
        provider="history_dispatcher",
        capability="history-dispatcher-telegram-native-v1",
        state="token=supersecret /home/alice/private",
    )

    rendered = worker.as_dict()["state"]

    assert "supersecret" not in rendered
    assert "/home/alice" not in rendered


@pytest.mark.parametrize(
    "unsafe",
    [
        {"bot_token": "secret"},
        {"telegram": {"chat_id": "-1001234567890"}},
        {"worker": {"payload": "private"}},
        {"state": "sk-proj-abcdefghijklmnopqrstuv"},
    ],
)
def test_status_v2_rejects_secret_fields_and_values(unsafe: dict[str, object]) -> None:
    with pytest.raises(ValueError, match="forbidden|sensitive"):
        validate_redacted_status(unsafe)


def test_status_v2_rejects_oversized_payload() -> None:
    with pytest.raises(ValueError, match="64 KiB"):
        validate_redacted_status({"state": "x" * (65 * 1024)})
