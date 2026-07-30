from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path

from history_dispatcher.classification_types import (
    AgentContext,
    ClassifiedEvent,
    ClassificationConfidence,
    HistoryKind,
)
from history_dispatcher.crypto import StaticKeyProvider
from history_dispatcher.delivery_store import DeliveryStore
from history_dispatcher.migrations import DatabaseV2Migrator, DatabaseV3Migrator
from history_dispatcher.provider_api_v2 import (
    PROVIDER_API_OPERATIONS,
    ProviderApiV2,
)
from history_dispatcher.routing import RoutePlanner, RoutingPolicy, TelegramRoutingPolicy
from history_dispatcher.store import DispatcherStore
from history_dispatcher.telegram_provider import (
    TEEBOTUS_CAPABILITY_V2,
    TelegramTransportBinding,
)


@dataclass
class MutableClock:
    value: datetime

    def __call__(self) -> datetime:
        return self.value

    def advance(self, seconds: int) -> None:
        self.value += timedelta(seconds=seconds)


def _event(suffix: str) -> ClassifiedEvent:
    return ClassifiedEvent(
        history_kind=HistoryKind.TASK_COMPLETION,
        confidence=ClassificationConfidence.AUTHORITATIVE,
        reason_code="fixture",
        source_schema_family="fixture",
        timestamp="2026-07-30T22:00:00+00:00",
        session_key=f"sess_{suffix}",
        turn_key=f"turn_{suffix}",
        parent_thread_key="parent_unknown",
        project_id="proj_reclaim",
        project_label="Reclaim",
        agent_context=AgentContext.ROOT,
        source_ordinal=1,
        response_key=f"resp_{suffix}",
        text="Reclaim callback payload",
        text_sha256="a" * 64,
        dedupe_key=(suffix.encode("utf-8").hex() + "b" * 64)[:64],
        event_id=f"evt_{suffix}",
        external_dispatchable=True,
    )


def _api(tmp_path: Path, *, suffix: str = "reclaim") -> tuple[ProviderApiV2, MutableClock]:
    provider = StaticKeyProvider(b"k" * 32)
    database = tmp_path / f"{suffix}.sqlite3"
    DispatcherStore(database, provider)
    DatabaseV2Migrator(
        database,
        provider,
        backup_dir=tmp_path / f"backups-v2-{suffix}",
        minimum_free_bytes=0,
    ).migrate()
    DatabaseV3Migrator(
        database,
        provider,
        backup_dir=tmp_path / f"backups-v3-{suffix}",
    ).migrate()
    clock = MutableClock(datetime(2026, 7, 30, 22, 0, tzinfo=timezone.utc))
    tokens = iter(
        (
            "token_" + "a" * 40,
            "token_" + "b" * 40,
            "token_" + "c" * 40,
        )
    )
    store = DeliveryStore(
        database,
        provider,
        clock=clock,
        token_factory=lambda: next(tokens),
    )
    event = _event(suffix)
    store.append_classified_event(event)
    store.create_route_plan(
        RoutePlanner(
            RoutingPolicy(
                telegram=TelegramRoutingPolicy(
                    include_task_completion=True,
                    binding=TelegramTransportBinding.teebotus(),
                )
            )
        ).plan(event, config_revision="reclaim-fixture")
    )
    return ProviderApiV2(store), clock


def _claim(api: ProviderApiV2, *, worker_id: str = "teebotus-worker") -> dict[str, object]:
    response = api.dispatch(
        "provider.v2.claim",
        {
            "target_id": "telegram",
            "provider_id": "teebotus",
            "worker_id": worker_id,
            "capability_version": TEEBOTUS_CAPABILITY_V2,
            "limit": 1,
            "lease_seconds": 10,
        },
    )
    return response["claims"][0]


def _reclaim(
    api: ProviderApiV2,
    claim: dict[str, object],
    *,
    worker_id: str = "teebotus-worker",
    previous_attempt_no: int | None = None,
    provider_id: str = "teebotus",
) -> dict[str, object]:
    return api.dispatch(
        "provider.v2.reclaim",
        {
            "target_delivery_id": claim["target_delivery_id"],
            "provider_id": provider_id,
            "worker_id": worker_id,
            "capability_version": TEEBOTUS_CAPABILITY_V2,
            "previous_attempt_no": (
                int(claim["attempt_no"])
                if previous_attempt_no is None
                else previous_attempt_no
            ),
            "lease_seconds": 120,
        },
    )


def test_reclaim_is_a_versioned_provider_operation() -> None:
    assert "provider.v2.reclaim" in PROVIDER_API_OPERATIONS


def test_expired_target_can_be_reclaimed_for_callback_reconciliation(
    tmp_path: Path,
) -> None:
    api, clock = _api(tmp_path)
    first = _claim(api)
    clock.advance(11)

    response = _reclaim(api, first)

    assert response["ok"] is True
    assert response["schema_version"] == 2
    assert len(response["claims"]) == 1
    reclaimed = response["claims"][0]
    assert reclaimed["target_delivery_id"] == first["target_delivery_id"]
    assert reclaimed["provider_id"] == "teebotus"
    assert reclaimed["attempt_no"] == 2
    assert reclaimed["claim_token"] != first["claim_token"]
    assert reclaimed["reconciliation_only"] is True
    assert reclaimed["payload"]["text"] == "Reclaim callback payload"


def test_reclaim_does_not_steal_an_active_claim(tmp_path: Path) -> None:
    api, _clock = _api(tmp_path, suffix="active")
    first = _claim(api)

    response = _reclaim(api, first, worker_id="other-worker")

    assert response == {"ok": True, "schema_version": 2, "claims": []}


def test_reclaim_rejects_stale_attempt_after_another_reconciliation_claim(
    tmp_path: Path,
) -> None:
    api, clock = _api(tmp_path, suffix="stale")
    first = _claim(api)
    clock.advance(11)
    second = _reclaim(api, first)["claims"][0]
    clock.advance(121)

    stale = _reclaim(
        api,
        first,
        previous_attempt_no=int(first["attempt_no"]),
    )
    current = _reclaim(
        api,
        second,
        previous_attempt_no=int(second["attempt_no"]),
    )

    assert stale == {"ok": True, "schema_version": 2, "claims": []}
    assert len(current["claims"]) == 1
    assert current["claims"][0]["attempt_no"] == 3


def test_reclaim_never_crosses_provider_binding(tmp_path: Path) -> None:
    api, clock = _api(tmp_path, suffix="provider")
    first = _claim(api)
    clock.advance(11)

    response = _reclaim(api, first, provider_id="history_dispatcher")

    assert response == {"ok": True, "schema_version": 2, "claims": []}


def test_terminal_target_cannot_be_reclaimed(tmp_path: Path) -> None:
    api, _clock = _api(tmp_path, suffix="terminal")
    first = _claim(api)
    completed = api.dispatch(
        "provider.v2.complete",
        {
            "target_delivery_id": first["target_delivery_id"],
            "worker_id": "teebotus-worker",
            "claim_token": first["claim_token"],
            "outcome": "delivered",
        },
    )
    assert completed["state"] == "delivered"

    response = _reclaim(api, first)

    assert response == {"ok": True, "schema_version": 2, "claims": []}
