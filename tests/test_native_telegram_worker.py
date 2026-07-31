from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from history_dispatcher.crypto import StaticKeyProvider
from history_dispatcher.native_telegram_worker import (
    NATIVE_TELEGRAM_CAPABILITY_V1,
    NativeTelegramWorker,
    NativeTelegramWorkerReport,
    TelegramRateLimiter,
)
from history_dispatcher.telegram_bot_api import (
    TelegramApiPossibleDuplicate,
    TelegramApiRateLimited,
    TelegramApiRejected,
    TelegramApiSuccess,
)
from history_dispatcher.telegram_formatter import FormattedTelegramDelivery


BOT_TOKEN = "123456789:ABCDEFGHIJKLMNOPQRSTUVWXYZabcdef"
CHAT_IDS = {
    "status_admin_primary": "-1001234567890",
    "ops_admin": "-1009876543210",
}


def _claim(
    *,
    recipients: tuple[str, ...] = ("status_admin_primary",),
    successful: tuple[str, ...] = (),
    open_refs: tuple[str, ...] = (),
    **overrides: object,
) -> dict[str, object]:
    value: dict[str, object] = {
        "target_delivery_id": "target_delivery_1",
        "route_plan_id": "route_plan_1",
        "event_id": "event_1",
        "target_id": "telegram",
        "provider_id": "history_dispatcher",
        "provider_schema_version": 1,
        "binding": {
            "schema_version": 1,
            "provider": "history_dispatcher",
            "credential_ref": "telegram_primary",
            "recipient_refs": list(recipients),
        },
        "attempt_no": 1,
        "worker_id": "native_worker_1",
        "capability_version": NATIVE_TELEGRAM_CAPABILITY_V1,
        "claim_token": "a" * 32,
        "claim_expires_at": "2026-07-31T13:00:00+00:00",
        "payload": {
            "history_kind": "overall_completion",
            "project_label": "History-Dispatcher",
            "summary": "Native delivery completed.",
        },
        "successful_recipient_refs": list(successful),
        "open_recipient_refs": list(open_refs),
    }
    value.update(overrides)
    return value


@dataclass
class FakeProviderApi:
    claims: list[dict[str, object]]
    operations: list[tuple[str, dict[str, Any]]] = field(default_factory=list)
    recorded_outcomes: list[dict[str, Any]] = field(default_factory=list)
    completions: list[dict[str, Any]] = field(default_factory=list)

    def dispatch(self, operation: str, body: dict[str, Any]) -> dict[str, Any]:
        self.operations.append((operation, dict(body)))
        if operation == "provider.v2.heartbeat":
            return {"ok": True}
        if operation == "provider.v2.claim":
            claims = list(self.claims)
            self.claims.clear()
            return {"ok": True, "schema_version": 2, "claims": claims}
        if operation == "provider.v2.register_recipients":
            return {
                "ok": True,
                "recipients": [
                    {
                        "recipient_delivery_id": f"delivery_{ref}",
                        "recipient_ref": ref,
                        "state": "pending",
                        "possible_duplicate": False,
                        "message_ref_key": "",
                        "last_error_class": "",
                        "attempt_count": 0,
                    }
                    for ref in body["recipient_refs"]
                ],
            }
        if operation == "provider.v2.renew":
            return {"ok": True, "claim_expires_at": "2026-07-31T13:02:00+00:00"}
        if operation == "provider.v2.record_recipients":
            self.recorded_outcomes.extend(body["outcomes"])
            return {"ok": True, "recipients": list(body["outcomes"])}
        if operation == "provider.v2.complete":
            self.completions.append(dict(body))
            return {"ok": True, "state": body.get("outcome") or "delivered"}
        raise AssertionError(operation)


@dataclass
class FakeSecretStore:
    token: str = BOT_TOKEN
    chats: dict[str, str] = field(default_factory=lambda: dict(CHAT_IDS))
    token_calls: list[str] = field(default_factory=list)
    chat_calls: list[str] = field(default_factory=list)
    token_error: Exception | None = None
    chat_errors: dict[str, Exception] = field(default_factory=dict)

    def lookup_bot_token(self, profile_ref: str) -> str:
        self.token_calls.append(profile_ref)
        if self.token_error is not None:
            raise self.token_error
        return self.token

    def lookup_chat_id(self, profile_ref: str) -> str:
        self.chat_calls.append(profile_ref)
        error = self.chat_errors.get(profile_ref)
        if error is not None:
            raise error
        return self.chats[profile_ref]


@dataclass
class FakeClient:
    results: list[object]
    calls: list[tuple[str, tuple[object, ...]]] = field(default_factory=list)

    def send_message(self, token: str, chat_id: str, text: str) -> object:
        self.calls.append(("send_message", (token, chat_id, text)))
        return self.results.pop(0)

    def send_document(
        self,
        token: str,
        chat_id: str,
        filename: str,
        document: bytes,
        caption: str,
    ) -> object:
        self.calls.append(
            ("send_document", (token, chat_id, filename, document, caption))
        )
        return self.results.pop(0)


@dataclass
class FakeClock:
    value: float = 1000.0
    sleeps: list[float] = field(default_factory=list)

    def __call__(self) -> float:
        return self.value

    def sleep(self, seconds: float) -> None:
        self.sleeps.append(seconds)
        self.value += seconds


def _worker(
    provider: FakeProviderApi,
    client: FakeClient,
    secrets: FakeSecretStore | None = None,
    *,
    formatter=None,
    clock: FakeClock | None = None,
) -> NativeTelegramWorker:
    selected_clock = clock or FakeClock()
    limiter = TelegramRateLimiter(
        clock=selected_clock,
        sleeper=selected_clock.sleep,
    )
    return NativeTelegramWorker(
        provider_api=provider,
        secret_store=secrets or FakeSecretStore(),
        client=client,
        key_provider=StaticKeyProvider(b"k" * 32),
        worker_id="native_worker_1",
        formatter=formatter,
        rate_limiter=limiter,
        sleeper=selected_clock.sleep,
    )


def test_worker_delivers_native_claim_through_provider_v2_lifecycle() -> None:
    provider = FakeProviderApi([_claim()])
    client = FakeClient([TelegramApiSuccess(message_id=42)])
    formatter_calls: list[tuple[dict[str, object], str]] = []

    def formatter(payload: dict[str, object], *, event_id: str):
        formatter_calls.append((dict(payload), event_id))
        return FormattedTelegramDelivery(mode="text", text="safe text")

    worker = _worker(provider, client, formatter=formatter)

    report = worker.run_once()

    assert report == NativeTelegramWorkerReport(
        claimed=1,
        delivered=1,
        failed=0,
        possible_duplicate=0,
        rate_limited=0,
        skipped=0,
    )
    assert formatter_calls == [
        (
            {
                "history_kind": "overall_completion",
                "project_label": "History-Dispatcher",
                "summary": "Native delivery completed.",
            },
            "event_1",
        )
    ]
    assert [name for name, _body in provider.operations] == [
        "provider.v2.heartbeat",
        "provider.v2.claim",
        "provider.v2.heartbeat",
        "provider.v2.register_recipients",
        "provider.v2.renew",
        "provider.v2.record_recipients",
        "provider.v2.complete",
        "provider.v2.heartbeat",
    ]
    claim_body = provider.operations[1][1]
    assert claim_body["target_id"] == "telegram"
    assert claim_body["provider_id"] == "history_dispatcher"
    assert claim_body["capability_version"] == NATIVE_TELEGRAM_CAPABILITY_V1
    assert client.calls == [
        ("send_message", (BOT_TOKEN, CHAT_IDS["status_admin_primary"], "safe text"))
    ]
    outcome = provider.recorded_outcomes[0]
    assert outcome["recipient_ref"] == "status_admin_primary"
    assert outcome["status"] == "delivered"
    assert outcome["possible_duplicate"] is False
    assert str(outcome["message_ref_key"]).startswith("message_")
    assert "42" not in str(outcome["message_ref_key"])
    assert provider.completions[0]["retry_after_seconds"] == 0


def test_worker_sends_document_fallback_as_one_request() -> None:
    provider = FakeProviderApi([_claim()])
    client = FakeClient([TelegramApiSuccess(message_id=77)])

    def formatter(_payload: dict[str, object], *, event_id: str):
        assert event_id == "event_1"
        return FormattedTelegramDelivery(
            mode="document",
            filename="history-deadbeef.txt",
            document=b"document payload",
            caption="History export",
        )

    report = _worker(provider, client, formatter=formatter).run_once()

    assert report.delivered == 1
    assert client.calls == [
        (
            "send_document",
            (
                BOT_TOKEN,
                CHAT_IDS["status_admin_primary"],
                "history-deadbeef.txt",
                b"document payload",
                "History export",
            ),
        )
    ]


def test_successful_recipient_is_never_sent_again() -> None:
    provider = FakeProviderApi(
        [
            _claim(
                recipients=("status_admin_primary",),
                successful=("status_admin_primary",),
            )
        ]
    )
    client = FakeClient([])
    secrets = FakeSecretStore()

    report = _worker(provider, client, secrets).run_once()

    assert report.claimed == 1
    assert report.skipped == 1
    assert client.calls == []
    assert secrets.token_calls == []
    assert secrets.chat_calls == []
    assert provider.recorded_outcomes == []
    assert len(provider.completions) == 1


def test_partial_recipients_are_recorded_independently_before_completion() -> None:
    provider = FakeProviderApi(
        [_claim(recipients=("status_admin_primary", "ops_admin"))]
    )
    client = FakeClient(
        [
            TelegramApiSuccess(message_id=10),
            TelegramApiRejected("telegram_forbidden", retryable=False),
        ]
    )

    report = _worker(provider, client).run_once()

    assert report.delivered == 1
    assert report.failed == 1
    assert [outcome["recipient_ref"] for outcome in provider.recorded_outcomes] == [
        "status_admin_primary",
        "ops_admin",
    ]
    assert provider.recorded_outcomes[0]["status"] == "delivered"
    assert provider.recorded_outcomes[1]["status"] == "failed_terminal"
    record_positions = [
        index
        for index, (operation, _body) in enumerate(provider.operations)
        if operation == "provider.v2.record_recipients"
    ]
    complete_position = next(
        index
        for index, (operation, _body) in enumerate(provider.operations)
        if operation == "provider.v2.complete"
    )
    assert all(position < complete_position for position in record_positions)


def test_rate_limit_is_recorded_and_propagated_to_target_completion() -> None:
    provider = FakeProviderApi([_claim()])
    client = FakeClient([TelegramApiRateLimited(retry_after_seconds=17)])

    report = _worker(provider, client).run_once()

    assert report.rate_limited == 1
    assert report.failed == 1
    assert provider.recorded_outcomes == [
        {
            "recipient_ref": "status_admin_primary",
            "status": "failed",
            "possible_duplicate": False,
            "message_ref_key": "",
            "reason_code": "rate_limited",
        }
    ]
    assert provider.completions[0]["retry_after_seconds"] == 17
    assert provider.completions[0]["error_class"] == "rate_limited"


def test_post_connect_ambiguity_becomes_monotone_possible_duplicate() -> None:
    provider = FakeProviderApi([_claim()])
    client = FakeClient(
        [TelegramApiPossibleDuplicate("telegram_accept_unknown")]
    )

    report = _worker(provider, client).run_once()

    assert report.possible_duplicate == 1
    assert provider.recorded_outcomes == [
        {
            "recipient_ref": "status_admin_primary",
            "status": "possible_duplicate",
            "possible_duplicate": True,
            "message_ref_key": "",
            "reason_code": "telegram_accept_unknown",
        }
    ]
    assert provider.completions[0]["retry_after_seconds"] == 0


def test_rate_limiter_enforces_global_and_per_recipient_spacing() -> None:
    clock = FakeClock()
    limiter = TelegramRateLimiter(clock=clock, sleeper=clock.sleep)

    limiter.wait("status_admin_primary")
    limiter.wait("status_admin_primary")
    limiter.wait("ops_admin")

    assert clock.sleeps[0] == 1.05
    assert clock.sleeps[1] == 0.04


def test_worker_renews_before_every_send_and_resolves_secrets_after_renew() -> None:
    provider = FakeProviderApi(
        [_claim(recipients=("status_admin_primary", "ops_admin"))]
    )
    client = FakeClient(
        [TelegramApiSuccess(message_id=1), TelegramApiSuccess(message_id=2)]
    )
    secrets = FakeSecretStore()

    _worker(provider, client, secrets).run_once()

    operations = [name for name, _body in provider.operations]
    assert operations.count("provider.v2.renew") == 2
    assert secrets.token_calls == ["telegram_primary", "telegram_primary"]
    assert secrets.chat_calls == ["status_admin_primary", "ops_admin"]
