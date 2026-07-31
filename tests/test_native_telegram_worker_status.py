from __future__ import annotations

from history_dispatcher.crypto import StaticKeyProvider
from history_dispatcher.native_telegram_worker import (
    NativeTelegramWorker,
    TelegramRateLimiter,
)
from history_dispatcher.status_runtime_v2 import _provider_from_details
from history_dispatcher.telegram_bot_api import TelegramApiSuccess

from tests.test_native_telegram_worker import (
    FakeClient,
    FakeClock,
    FakeProviderApi,
    FakeSecretStore,
    _claim,
)


def test_native_worker_heartbeat_identifies_provider_for_status_v2() -> None:
    provider = FakeProviderApi([_claim()])
    clock = FakeClock()
    worker = NativeTelegramWorker(
        provider_api=provider,
        secret_store=FakeSecretStore(),
        client=FakeClient([TelegramApiSuccess(message_id=42)]),
        key_provider=StaticKeyProvider(b"k" * 32),
        worker_id="native_worker_1",
        rate_limiter=TelegramRateLimiter(clock=clock, sleeper=clock.sleep),
        sleeper=clock.sleep,
    )

    worker.run_once()

    heartbeats = [
        body
        for operation, body in provider.operations
        if operation == "provider.v2.heartbeat"
    ]
    assert [heartbeat["state"] for heartbeat in heartbeats] == [
        "starting",
        "active",
        "idle",
    ]
    for heartbeat in heartbeats:
        details = heartbeat["details"]
        assert details["provider_id"] == "history_dispatcher"
        assert _provider_from_details(
            "telegram",
            __import__("json").dumps(details),
        ) == "history_dispatcher"
        assert len(details) <= 16
