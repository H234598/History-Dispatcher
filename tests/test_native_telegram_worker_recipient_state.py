from __future__ import annotations

from typing import Any

from history_dispatcher.crypto import StaticKeyProvider
from history_dispatcher.native_telegram_worker import (
    NativeTelegramWorker,
    TelegramRateLimiter,
)

from tests.test_native_telegram_worker import (
    FakeClient,
    FakeClock,
    FakeProviderApi,
    FakeSecretStore,
    _claim,
)


class PossibleDuplicateProvider(FakeProviderApi):
    def dispatch(self, operation: str, body: dict[str, Any]) -> dict[str, Any]:
        if operation == "provider.v2.register_recipients":
            self.operations.append((operation, dict(body)))
            return {
                "ok": True,
                "recipients": [
                    {
                        "recipient_delivery_id": "delivery_status_admin_primary",
                        "recipient_ref": "status_admin_primary",
                        "state": "possible_duplicate",
                        "possible_duplicate": True,
                        "message_ref_key": "",
                        "last_error_class": "telegram_accept_unknown",
                        "attempt_count": 1,
                    }
                ],
            }
        return super().dispatch(operation, body)


def test_registered_possible_duplicate_recipient_is_never_sent_again() -> None:
    provider = PossibleDuplicateProvider([_claim()])
    client = FakeClient([])
    secrets = FakeSecretStore()
    clock = FakeClock()
    worker = NativeTelegramWorker(
        provider_api=provider,
        secret_store=secrets,
        client=client,
        key_provider=StaticKeyProvider(b"k" * 32),
        worker_id="native_worker_1",
        rate_limiter=TelegramRateLimiter(clock=clock, sleeper=clock.sleep),
        sleeper=clock.sleep,
    )

    report = worker.run_once()

    assert report.skipped == 1
    assert client.calls == []
    assert secrets.token_calls == []
    assert secrets.chat_calls == []
    assert provider.recorded_outcomes == []
    assert provider.completions[0]["outcome"] is None
