from __future__ import annotations

from dataclasses import dataclass, field

import pytest

from history_dispatcher.crypto import StaticKeyProvider
from history_dispatcher.native_telegram_worker import (
    NATIVE_TELEGRAM_CAPABILITY_V1,
    NativeTelegramWorker,
    TelegramRateLimiter,
)
from history_dispatcher.telegram_bot_api import (
    TelegramApiPossibleDuplicate,
    TelegramApiRejected,
)
from history_dispatcher.telegram_provider import TelegramRecipientOutcome
from history_dispatcher.telegram_secrets import TelegramSecretError

from tests.test_native_telegram_worker import (
    FakeClient,
    FakeClock,
    FakeProviderApi,
    FakeSecretStore,
    _claim,
)


def _fault_worker(
    provider: FakeProviderApi,
    client: FakeClient,
    secrets: FakeSecretStore | None = None,
) -> NativeTelegramWorker:
    clock = FakeClock()
    return NativeTelegramWorker(
        provider_api=provider,
        secret_store=secrets or FakeSecretStore(),
        client=client,
        key_provider=StaticKeyProvider(b"k" * 32),
        worker_id="native_worker_1",
        rate_limiter=TelegramRateLimiter(clock=clock, sleeper=clock.sleep),
        sleeper=clock.sleep,
    )


@pytest.mark.parametrize(
    ("overrides", "reason"),
    (
        ({"provider_id": "teebotus"}, "provider_mismatch"),
        ({"target_id": "vault"}, "target_mismatch"),
        ({"capability_version": "wrong-capability"}, "capability_mismatch"),
        ({"reconciliation_only": True}, "reconciliation_only"),
    ),
)
def test_invalid_or_reconciliation_claims_block_before_secret_or_send(
    overrides: dict[str, object],
    reason: str,
) -> None:
    provider = FakeProviderApi([_claim(**overrides)])
    client = FakeClient([])
    secrets = FakeSecretStore()

    report = _fault_worker(provider, client, secrets).run_once()

    assert report.failed == 1
    assert client.calls == []
    assert secrets.token_calls == []
    assert secrets.chat_calls == []
    assert provider.completions[0]["outcome"] == "quarantined"
    assert provider.completions[0]["error_class"] == reason
    heartbeat_states = [
        body["state"]
        for operation, body in provider.operations
        if operation == "provider.v2.heartbeat"
    ]
    assert heartbeat_states[-1] == "blocked"


def test_missing_bot_token_fails_closed_without_network() -> None:
    provider = FakeProviderApi([_claim()])
    secrets = FakeSecretStore(
        token_error=TelegramSecretError("private keyring failure")
    )
    client = FakeClient([])

    report = _fault_worker(provider, client, secrets).run_once()

    assert report.failed == 1
    assert client.calls == []
    assert provider.recorded_outcomes[0]["reason_code"] == "credential_unavailable"
    assert "private" not in repr(report)


def test_missing_recipient_chat_id_isolated_to_that_recipient() -> None:
    provider = FakeProviderApi(
        [_claim(recipients=("status_admin_primary", "ops_admin"))]
    )
    secrets = FakeSecretStore(
        chat_errors={
            "ops_admin": TelegramSecretError("private recipient failure")
        }
    )
    client = FakeClient([TelegramApiRejected("telegram_transient", retryable=True)])

    report = _fault_worker(provider, client, secrets).run_once()

    assert report.failed == 2
    assert len(client.calls) == 1
    assert [item["reason_code"] for item in provider.recorded_outcomes] == [
        "telegram_transient",
        "credential_unavailable",
    ]


def test_retryable_transport_failure_stays_retryable() -> None:
    provider = FakeProviderApi([_claim()])
    client = FakeClient(
        [TelegramApiRejected("telegram_connect_failed", retryable=True)]
    )

    report = _fault_worker(provider, client).run_once()

    assert report.failed == 1
    assert provider.recorded_outcomes[0]["status"] == "failed"
    assert provider.recorded_outcomes[0]["reason_code"] == "telegram_connect_failed"
    assert provider.completions[0]["outcome"] is None


def test_explicit_terminal_error_is_terminal_per_recipient() -> None:
    provider = FakeProviderApi([_claim()])
    client = FakeClient(
        [TelegramApiRejected("telegram_forbidden", retryable=False)]
    )

    report = _fault_worker(provider, client).run_once()

    assert report.failed == 1
    assert provider.recorded_outcomes[0]["status"] == "failed_terminal"
    assert provider.completions[0]["outcome"] is None
    terminal = TelegramRecipientOutcome(
        recipient_ref="status_admin_primary",
        status="failed_terminal",
        reason_code="telegram_forbidden",
    )
    assert terminal.status == "failed_terminal"


def test_possible_duplicate_claim_is_not_automatically_resent() -> None:
    first_provider = FakeProviderApi([_claim()])
    first_client = FakeClient(
        [TelegramApiPossibleDuplicate("telegram_accept_unknown")]
    )
    _fault_worker(first_provider, first_client).run_once()

    second_provider = FakeProviderApi(
        [
            _claim(
                successful=(),
                open_refs=(),
                recipients=("status_admin_primary",),
            )
        ]
    )
    second_provider.claims[0]["successful_recipient_refs"] = []
    second_provider.claims[0]["open_recipient_refs"] = []
    second_provider.claims[0]["binding"] = {
        "schema_version": 1,
        "provider": "history_dispatcher",
        "credential_ref": "telegram_primary",
        "recipient_refs": [],
    }
    second_client = FakeClient([])

    report = _fault_worker(second_provider, second_client).run_once()

    assert report.skipped == 1
    assert second_client.calls == []


@dataclass
class StopEvent:
    checks: int = 0

    def is_set(self) -> bool:
        self.checks += 1
        return self.checks > 2


def test_run_forever_obeys_stop_event_and_bounded_idle_sleep() -> None:
    provider = FakeProviderApi([])
    client = FakeClient([])
    clock = FakeClock()
    worker = NativeTelegramWorker(
        provider_api=provider,
        secret_store=FakeSecretStore(),
        client=client,
        key_provider=StaticKeyProvider(b"k" * 32),
        worker_id="native_worker_1",
        rate_limiter=TelegramRateLimiter(clock=clock, sleeper=clock.sleep),
        sleeper=clock.sleep,
        idle_seconds=2.0,
    )

    worker.run_forever(StopEvent())

    assert clock.sleeps == [2.0]
    assert client.calls == []


def test_heartbeat_details_are_bounded_and_secret_free() -> None:
    provider = FakeProviderApi([_claim()])
    client = FakeClient(
        [TelegramApiPossibleDuplicate("telegram_accept_unknown")]
    )

    _fault_worker(provider, client).run_once()

    heartbeats = [
        body
        for operation, body in provider.operations
        if operation == "provider.v2.heartbeat"
    ]
    assert heartbeats
    for heartbeat in heartbeats:
        assert len(heartbeat["details"]) <= 16
        rendered = repr(heartbeat)
        assert "123456789:" not in rendered
        assert "-1001234567890" not in rendered
        assert "private" not in rendered
