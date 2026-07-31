from __future__ import annotations

import json
from pathlib import Path

from history_dispatcher.crypto import StaticKeyProvider
from history_dispatcher.native_telegram_worker import NativeTelegramWorker
from history_dispatcher.telegram_bot_api import (
    TelegramApiPossibleDuplicate,
    TelegramApiRateLimited,
    TelegramApiRejected,
    TelegramApiSuccess,
)

from tests.test_native_telegram_worker import (
    FakeClient,
    FakeProviderApi,
    FakeSecretStore,
)


FIXTURE = Path(__file__).parent / "fixtures" / "provider-v2-contract.json"


def _result(value: dict[str, object]) -> object:
    kind = value["kind"]
    if kind == "success":
        return TelegramApiSuccess(message_id=int(value["message_id"]))
    if kind == "rate_limited":
        return TelegramApiRateLimited(
            retry_after_seconds=int(value["retry_after_seconds"])
        )
    if kind == "rejected":
        return TelegramApiRejected(
            reason_code=str(value["reason_code"]),
            retryable=bool(value["retryable"]),
        )
    if kind == "possible_duplicate":
        return TelegramApiPossibleDuplicate(
            reason_code=str(value["reason_code"])
        )
    raise AssertionError(kind)


def test_shared_provider_fixture_covers_native_fault_semantics() -> None:
    fixture = json.loads(FIXTURE.read_text(encoding="utf-8"))

    assert fixture["schema_version"] == 1
    assert fixture["provider_api_schema_version"] == 2
    assert fixture["native_capability"] == (
        "history-dispatcher-telegram-native-v1"
    )
    cases = fixture["cases"]
    assert [case["name"] for case in cases] == [
        "success",
        "terminal_chat_error",
        "rate_limited",
        "connect_failure",
        "crash_after_accept",
        "oversized_response",
        "malformed_response",
        "partial_recipients",
    ]

    worker = NativeTelegramWorker(
        provider_api=FakeProviderApi([]),
        secret_store=FakeSecretStore(),
        client=FakeClient([]),
        key_provider=StaticKeyProvider(b"k" * 32),
        worker_id="native_worker_1",
    )
    for case in cases:
        results = case["results"]
        expected = case["expected"]
        mapped = [
            worker._map_result("status_admin_primary", _result(item))
            for item in results
        ]
        assert [item[0].status for item in mapped] == expected["statuses"]
        assert [item[0].possible_duplicate for item in mapped] == expected[
            "possible_duplicate"
        ]
        assert [item[0].reason_code for item in mapped] == expected[
            "reason_codes"
        ]
        assert max((item[1] for item in mapped), default=0) == expected[
            "retry_after_seconds"
        ]
