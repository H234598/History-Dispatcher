from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path
from threading import Barrier

import pytest

from history_dispatcher.classification_types import (
    AgentContext,
    ClassifiedEvent,
    ClassificationConfidence,
    HistoryKind,
)
from history_dispatcher.crypto import StaticKeyProvider
from history_dispatcher.delivery_store import (
    NATIVE_TELEGRAM_CAPABILITY_V1,
    VAULT_CAPABILITY_V1,
    DeliveryClaimRejected,
    DeliveryStore,
)
from history_dispatcher.migrations import DatabaseV2Migrator, DatabaseV3Migrator
from history_dispatcher.routing import (
    RoutePlanner,
    RoutingPolicy,
    TelegramRoutingPolicy,
    VaultRoutingPolicy,
)
from history_dispatcher.store import DispatcherStore
from history_dispatcher.telegram_provider import TelegramTransportBinding


def _event() -> ClassifiedEvent:
    return ClassifiedEvent(
        history_kind=HistoryKind.TASK_COMPLETION,
        confidence=ClassificationConfidence.AUTHORITATIVE,
        reason_code="fixture",
        source_schema_family="fixture",
        timestamp="2026-07-28T00:00:00+00:00",
        session_key="sess_concurrency",
        turn_key="turn_concurrency",
        parent_thread_key="parent_unknown",
        project_id="proj_concurrency",
        project_label="Concurrency",
        agent_context=AgentContext.ROOT,
        source_ordinal=1,
        response_key="resp_concurrency",
        text="Concurrent delivery",
        text_sha256="a" * 64,
        dedupe_key="b" * 64,
        event_id="evt_concurrency",
        external_dispatchable=True,
    )


def _setup(tmp_path: Path) -> tuple[Path, StaticKeyProvider]:
    provider = StaticKeyProvider(b"k" * 32)
    legacy = DispatcherStore(tmp_path / "history.sqlite3", provider)
    DatabaseV2Migrator(
        legacy.database_path,
        provider,
        backup_dir=tmp_path / "backups-v2",
        minimum_free_bytes=0,
    ).migrate()
    DatabaseV3Migrator(
        legacy.database_path,
        provider,
        backup_dir=tmp_path / "backups-v3",
    ).migrate()
    store = DeliveryStore(
        legacy.database_path,
        provider,
        clock=lambda: datetime(2026, 7, 28, tzinfo=timezone.utc),
        token_factory=lambda: "setup_" + "s" * 40,
    )
    event = _event()
    store.append_classified_event(event)
    plan = RoutePlanner(
        RoutingPolicy(
            telegram=TelegramRoutingPolicy(
                include_task_completion=True,
                binding=TelegramTransportBinding.history_dispatcher(
                    credential_ref="telegram_primary",
                    recipient_refs=("status_admin",),
                ),
            ),
            vault=VaultRoutingPolicy(include_task_completion=True),
        )
    ).plan(event, config_revision="revision-concurrency")
    store.create_route_plan(plan)
    return legacy.database_path, provider


def test_two_workers_cannot_claim_the_same_target_concurrently(
    tmp_path: Path,
) -> None:
    database, provider = _setup(tmp_path)
    barrier = Barrier(2)

    def claim(worker: str, token_char: str) -> int:
        store = DeliveryStore(
            database,
            provider,
            clock=lambda: datetime(2026, 7, 28, tzinfo=timezone.utc),
            token_factory=lambda: "token_" + token_char * 40,
        )
        barrier.wait(timeout=5)
        return len(
            store.claim_target_deliveries(
                target_id="telegram",
                provider_id="history_dispatcher",
                worker_id=worker,
                capability_version=NATIVE_TELEGRAM_CAPABILITY_V1,
            )
        )

    with ThreadPoolExecutor(max_workers=2) as executor:
        first = executor.submit(claim, "worker-one", "a")
        second = executor.submit(claim, "worker-two", "b")
        results = sorted((first.result(timeout=10), second.result(timeout=10)))

    assert results == [0, 1]


def test_target_claims_are_independent_for_telegram_and_vault(tmp_path: Path) -> None:
    database, provider = _setup(tmp_path)
    store = DeliveryStore(
        database,
        provider,
        clock=lambda: datetime(2026, 7, 28, tzinfo=timezone.utc),
        token_factory=iter(
            ["telegram_" + "a" * 40, "vault_" + "b" * 40]
        ).__next__,
    )

    telegram = store.claim_target_deliveries(
        target_id="telegram",
        provider_id="history_dispatcher",
        worker_id="telegram-worker",
        capability_version=NATIVE_TELEGRAM_CAPABILITY_V1,
    )
    vault = store.claim_target_deliveries(
        target_id="vault",
        provider_id="vault",
        worker_id="vault-worker",
        capability_version=VAULT_CAPABILITY_V1,
    )

    assert len(telegram) == len(vault) == 1
    assert telegram[0].event_id == vault[0].event_id == "evt_concurrency"
    assert telegram[0].target_delivery_id != vault[0].target_delivery_id

    assert store.complete_target(
        target_delivery_id=vault[0].target_delivery_id,
        worker_id="vault-worker",
        claim_token=vault[0].claim_token,
        outcome="delivered",
    ) == "delivered"
    assert store.event_delivery_summary("evt_concurrency").aggregate_state == "pending"


def test_native_worker_cannot_register_unplanned_recipient(tmp_path: Path) -> None:
    database, provider = _setup(tmp_path)
    store = DeliveryStore(
        database,
        provider,
        clock=lambda: datetime(2026, 7, 28, tzinfo=timezone.utc),
        token_factory=lambda: "token_" + "a" * 40,
    )
    claim = store.claim_target_deliveries(
        target_id="telegram",
        provider_id="history_dispatcher",
        worker_id="telegram-worker",
        capability_version=NATIVE_TELEGRAM_CAPABILITY_V1,
    )[0]

    with pytest.raises(DeliveryClaimRejected, match="unplanned recipient"):
        store.register_recipients(
            target_delivery_id=claim.target_delivery_id,
            worker_id="telegram-worker",
            claim_token=claim.claim_token,
            recipient_refs=("unplanned_admin",),
        )
