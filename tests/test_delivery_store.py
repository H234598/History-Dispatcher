from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path

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
    DeliveryClaimRejected,
    DeliverySchemaUnavailable,
    DeliveryStore,
)
from history_dispatcher.migrations import DatabaseV2Migrator, DatabaseV3Migrator
from history_dispatcher.routing import (
    RoutePlanner,
    RoutingPolicy,
    TelegramRoutingPolicy,
)
from history_dispatcher.store import DispatcherStore
from history_dispatcher.telegram_provider import (
    TEEBOTUS_CAPABILITY_V2,
    TelegramRecipientOutcome,
    TelegramTransportBinding,
)


@dataclass
class MutableClock:
    value: datetime

    def __call__(self) -> datetime:
        return self.value

    def advance(self, seconds: int) -> None:
        self.value += timedelta(seconds=seconds)


def _database(tmp_path: Path) -> tuple[Path, StaticKeyProvider]:
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
    return legacy.database_path, provider


def _event(
    suffix: str = "one",
    *,
    kind: HistoryKind = HistoryKind.TASK_COMPLETION,
) -> ClassifiedEvent:
    return ClassifiedEvent(
        history_kind=kind,
        confidence=ClassificationConfidence.AUTHORITATIVE,
        reason_code="fixture",
        source_schema_family="fixture",
        timestamp="2026-07-28T00:00:00+00:00",
        session_key=f"sess_{suffix}",
        turn_key=f"turn_{suffix}",
        parent_thread_key="parent_unknown",
        project_id="proj_example",
        project_label="Example",
        agent_context=AgentContext.ROOT,
        source_ordinal=1,
        response_key=f"resp_{suffix}",
        text=f"Visible result {suffix}",
        text_sha256=(suffix.encode("utf-8").hex() + "0" * 64)[:64],
        dedupe_key=(suffix.encode("utf-8").hex() + "1" * 64)[:64],
        event_id=f"evt_{suffix}",
        external_dispatchable=True,
    )


def _native_policy(*recipients: str) -> RoutingPolicy:
    return RoutingPolicy(
        telegram=TelegramRoutingPolicy(
            include_task_completion=True,
            include_subagent_completion=True,
            include_intermediate_update=True,
            binding=TelegramTransportBinding.history_dispatcher(
                credential_ref="telegram_primary",
                recipient_refs=recipients,
            ),
        )
    )


def _teebotus_policy() -> RoutingPolicy:
    return RoutingPolicy(
        telegram=TelegramRoutingPolicy(
            include_task_completion=True,
            include_subagent_completion=True,
            include_intermediate_update=True,
            binding=TelegramTransportBinding.teebotus(),
        )
    )


def _store_with_event(
    tmp_path: Path,
    *,
    policy: RoutingPolicy,
    suffix: str = "one",
    clock: MutableClock | None = None,
) -> tuple[DeliveryStore, ClassifiedEvent, str]:
    database, provider = _database(tmp_path)
    clock = clock or MutableClock(datetime(2026, 7, 28, tzinfo=timezone.utc))
    token_counter = iter(
        [
            "token_" + "a" * 40,
            "token_" + "b" * 40,
            "token_" + "c" * 40,
            "token_" + "d" * 40,
        ]
    )
    store = DeliveryStore(
        database,
        provider,
        clock=clock,
        token_factory=lambda: next(token_counter),
    )
    event = _event(suffix)
    assert store.append_classified_event(event) == event.event_id
    plan = RoutePlanner(policy).plan(event, config_revision="revision-1")
    route_id = store.create_route_plan(plan)
    return store, event, route_id


def test_store_requires_verified_schema_v3(tmp_path: Path) -> None:
    provider = StaticKeyProvider(b"k" * 32)
    legacy = DispatcherStore(tmp_path / "history.sqlite3", provider)

    with pytest.raises(DeliverySchemaUnavailable, match="schema-v3"):
        DeliveryStore(legacy.database_path, provider)


def test_event_and_route_plan_are_encrypted_idempotent_and_provider_bound(
    tmp_path: Path,
) -> None:
    store, event, route_id = _store_with_event(
        tmp_path,
        policy=_native_policy("status_admin"),
    )
    assert store.append_classified_event(event) == event.event_id
    repeated = RoutePlanner(_native_policy("status_admin")).plan(
        event,
        config_revision="revision-1",
    )
    assert store.create_route_plan(repeated) == route_id

    with sqlite3.connect(store.database_path) as db:
        db.row_factory = sqlite3.Row
        raw_database = store.database_path.read_bytes()
        assert b"Visible result one" not in raw_database
        assert db.execute(
            "SELECT COUNT(*) FROM route_plans WHERE plan_state='active'"
        ).fetchone()[0] == 1
        targets = db.execute(
            "SELECT td.target_id,td.state,b.provider_id,b.binding_json "
            "FROM target_deliveries td JOIN target_delivery_bindings b "
            "ON b.target_delivery_id=td.id ORDER BY td.target_id"
        ).fetchall()
        assert [(row["target_id"], row["state"]) for row in targets] == [
            ("local_archive", "skipped_disabled"),
            ("telegram", "pending"),
            ("vault", "skipped_disabled"),
        ]
        telegram = next(row for row in targets if row["target_id"] == "telegram")
        assert telegram["provider_id"] == "history_dispatcher"
        assert json.loads(telegram["binding_json"])["recipient_refs"] == [
            "status_admin"
        ]
        recipient = db.execute(
            "SELECT rd.state,rb.recipient_ref FROM recipient_deliveries rd "
            "JOIN recipient_delivery_bindings rb "
            "ON rb.recipient_delivery_id=rd.id"
        ).fetchone()
        assert (recipient["state"], recipient["recipient_ref"]) == (
            "pending",
            "status_admin",
        )


def test_native_claim_is_provider_and_capability_specific(tmp_path: Path) -> None:
    store, _event_value, _route_id = _store_with_event(
        tmp_path,
        policy=_native_policy("status_admin"),
    )

    wrong_provider = store.claim_target_deliveries(
        target_id="telegram",
        provider_id="teebotus",
        worker_id="teebotus-worker",
        capability_version=TEEBOTUS_CAPABILITY_V2,
    )
    wrong_capability = store.claim_target_deliveries(
        target_id="telegram",
        provider_id="history_dispatcher",
        worker_id="native-worker",
        capability_version="wrong-capability",
    )
    claims = store.claim_target_deliveries(
        target_id="telegram",
        provider_id="history_dispatcher",
        worker_id="native-worker",
        capability_version=NATIVE_TELEGRAM_CAPABILITY_V1,
    )
    duplicate_claim = store.claim_target_deliveries(
        target_id="telegram",
        provider_id="history_dispatcher",
        worker_id="second-worker",
        capability_version=NATIVE_TELEGRAM_CAPABILITY_V1,
    )

    assert wrong_provider == ()
    assert wrong_capability == ()
    assert len(claims) == 1
    claim = claims[0]
    assert claim.provider_id == "history_dispatcher"
    assert claim.successful_recipient_refs == ()
    assert claim.open_recipient_refs == ("status_admin",)
    assert claim.payload["text"] == "Visible result one"
    assert duplicate_claim == ()


def test_claim_renewal_enforces_worker_token_and_max_lifetime(tmp_path: Path) -> None:
    clock = MutableClock(datetime(2026, 7, 28, tzinfo=timezone.utc))
    store, _event_value, _route_id = _store_with_event(
        tmp_path,
        policy=_native_policy("status_admin"),
        clock=clock,
    )
    claim = store.claim_target_deliveries(
        target_id="telegram",
        provider_id="history_dispatcher",
        worker_id="native-worker",
        capability_version=NATIVE_TELEGRAM_CAPABILITY_V1,
        lease_seconds=30,
    )[0]

    with pytest.raises(DeliveryClaimRejected, match="another worker"):
        store.renew_claim(
            target_delivery_id=claim.target_delivery_id,
            worker_id="wrong-worker",
            claim_token=claim.claim_token,
        )
    with pytest.raises(DeliveryClaimRejected, match="token"):
        store.renew_claim(
            target_delivery_id=claim.target_delivery_id,
            worker_id="native-worker",
            claim_token="wrong_" + "x" * 40,
        )

    renewed = store.renew_claim(
        target_delivery_id=claim.target_delivery_id,
        worker_id="native-worker",
        claim_token=claim.claim_token,
        lease_seconds=120,
        max_claim_lifetime_seconds=180,
    )
    assert renewed > claim.claim_expires_at

    clock.advance(181)
    with pytest.raises(DeliveryClaimRejected, match="expired"):
        store.renew_claim(
            target_delivery_id=claim.target_delivery_id,
            worker_id="native-worker",
            claim_token=claim.claim_token,
        )


def test_recipient_success_cannot_be_downgraded_and_completes_event(
    tmp_path: Path,
) -> None:
    store, event, _route_id = _store_with_event(
        tmp_path,
        policy=_native_policy("status_admin"),
    )
    claim = store.claim_target_deliveries(
        target_id="telegram",
        provider_id="history_dispatcher",
        worker_id="native-worker",
        capability_version=NATIVE_TELEGRAM_CAPABILITY_V1,
    )[0]

    first = store.record_recipient_outcomes(
        target_delivery_id=claim.target_delivery_id,
        worker_id="native-worker",
        claim_token=claim.claim_token,
        outcomes=(
            TelegramRecipientOutcome(
                recipient_ref="status_admin",
                status="delivered",
                message_ref_key="message_1",
            ),
        ),
    )
    repeated_failure = store.record_recipient_outcomes(
        target_delivery_id=claim.target_delivery_id,
        worker_id="native-worker",
        claim_token=claim.claim_token,
        outcomes=(
            TelegramRecipientOutcome(
                recipient_ref="status_admin",
                status="failed",
                reason_code="temporary_failure",
            ),
        ),
    )
    state = store.complete_target(
        target_delivery_id=claim.target_delivery_id,
        worker_id="native-worker",
        claim_token=claim.claim_token,
    )
    summary = store.event_delivery_summary(event.event_id)

    assert first[0].state == "delivered"
    assert repeated_failure[0].state == "delivered"
    assert repeated_failure[0].message_ref_key == "message_1"
    assert state == "delivered"
    assert summary.aggregate_state == "delivered"
    assert summary.operational_state == "terminal"
    with pytest.raises(DeliveryClaimRejected, match="not actively claimed"):
        store.complete_target(
            target_delivery_id=claim.target_delivery_id,
            worker_id="native-worker",
            claim_token=claim.claim_token,
        )


def test_partial_delivery_reclaims_only_open_recipient(tmp_path: Path) -> None:
    clock = MutableClock(datetime(2026, 7, 28, tzinfo=timezone.utc))
    store, _event_value, _route_id = _store_with_event(
        tmp_path,
        policy=_native_policy("first_admin", "second_admin"),
        clock=clock,
    )
    first_claim = store.claim_target_deliveries(
        target_id="telegram",
        provider_id="history_dispatcher",
        worker_id="native-worker",
        capability_version=NATIVE_TELEGRAM_CAPABILITY_V1,
    )[0]
    store.record_recipient_outcomes(
        target_delivery_id=first_claim.target_delivery_id,
        worker_id="native-worker",
        claim_token=first_claim.claim_token,
        outcomes=(
            {"recipient_ref": "first_admin", "status": "delivered"},
            {
                "recipient_ref": "second_admin",
                "status": "failed",
                "reason_code": "temporary_failure",
            },
        ),
    )
    assert store.complete_target(
        target_delivery_id=first_claim.target_delivery_id,
        worker_id="native-worker",
        claim_token=first_claim.claim_token,
        base_backoff_seconds=1,
        max_backoff_seconds=1,
        jitter_ratio=0,
    ) == "partial"

    clock.advance(2)
    second_claim = store.claim_target_deliveries(
        target_id="telegram",
        provider_id="history_dispatcher",
        worker_id="native-worker",
        capability_version=NATIVE_TELEGRAM_CAPABILITY_V1,
    )[0]
    assert second_claim.successful_recipient_refs == ("first_admin",)
    assert second_claim.open_recipient_refs == ("second_admin",)

    store.record_recipient_outcomes(
        target_delivery_id=second_claim.target_delivery_id,
        worker_id="native-worker",
        claim_token=second_claim.claim_token,
        outcomes=(
            {"recipient_ref": "second_admin", "status": "acknowledged"},
        ),
    )
    assert store.complete_target(
        target_delivery_id=second_claim.target_delivery_id,
        worker_id="native-worker",
        claim_token=second_claim.claim_token,
    ) == "delivered"


def test_teebotus_registers_dynamic_recipients_under_same_store_contract(
    tmp_path: Path,
) -> None:
    store, _event_value, _route_id = _store_with_event(
        tmp_path,
        policy=_teebotus_policy(),
    )
    claim = store.claim_target_deliveries(
        target_id="telegram",
        provider_id="teebotus",
        worker_id="teebotus-worker",
        capability_version=TEEBOTUS_CAPABILITY_V2,
    )[0]

    recipients = store.register_recipients(
        target_delivery_id=claim.target_delivery_id,
        worker_id="teebotus-worker",
        claim_token=claim.claim_token,
        recipient_refs=("account_primary", "account_secondary"),
    )
    assert [recipient.recipient_ref for recipient in recipients] == [
        "account_primary",
        "account_secondary",
    ]
    store.record_recipient_outcomes(
        target_delivery_id=claim.target_delivery_id,
        worker_id="teebotus-worker",
        claim_token=claim.claim_token,
        outcomes=(
            {"recipient_ref": "account_primary", "status": "accepted"},
            {"recipient_ref": "account_secondary", "status": "skipped"},
        ),
    )
    assert store.complete_target(
        target_delivery_id=claim.target_delivery_id,
        worker_id="teebotus-worker",
        claim_token=claim.claim_token,
    ) == "delivered"


def test_expired_claim_is_retryable_then_quarantined_at_max_attempts(
    tmp_path: Path,
) -> None:
    clock = MutableClock(datetime(2026, 7, 28, tzinfo=timezone.utc))
    store, event, _route_id = _store_with_event(
        tmp_path,
        policy=_native_policy("status_admin"),
        clock=clock,
    )
    claim = store.claim_target_deliveries(
        target_id="telegram",
        provider_id="history_dispatcher",
        worker_id="native-worker",
        capability_version=NATIVE_TELEGRAM_CAPABILITY_V1,
        lease_seconds=10,
    )[0]
    clock.advance(11)

    assert store.release_expired_claims(max_attempts=1) == 1
    summary = store.event_delivery_summary(event.event_id)
    assert summary.counts["quarantined"] == 1
    assert summary.aggregate_state == "failed"
    assert summary.operational_state == "quarantined"
    with pytest.raises(DeliveryClaimRejected, match="not actively claimed"):
        store.renew_claim(
            target_delivery_id=claim.target_delivery_id,
            worker_id="native-worker",
            claim_token=claim.claim_token,
        )


def test_heartbeat_is_bounded_and_redacted(tmp_path: Path) -> None:
    store, _event_value, _route_id = _store_with_event(
        tmp_path,
        policy=_native_policy("status_admin"),
    )
    store.heartbeat(
        worker_id="native-worker",
        target_id="telegram",
        provider_id="history_dispatcher",
        capability_version=NATIVE_TELEGRAM_CAPABILITY_V1,
        state="idle",
        details={
            "last_error_class": "none",
            "message": "token=supersecret /home/alice/private",
        },
    )

    with sqlite3.connect(store.database_path) as db:
        details = db.execute(
            "SELECT details_json FROM worker_heartbeats WHERE worker_id='native-worker'"
        ).fetchone()[0]
    assert "supersecret" not in details
    assert "/home/alice" not in details
    assert json.loads(details)["provider_id"] == "history_dispatcher"


def test_backoff_is_deterministic_bounded_and_attempt_sensitive() -> None:
    first = DeliveryStore.compute_backoff_seconds(
        "target_one",
        1,
        base_seconds=10,
        max_seconds=1000,
        jitter_ratio=0.2,
    )
    repeated = DeliveryStore.compute_backoff_seconds(
        "target_one",
        1,
        base_seconds=10,
        max_seconds=1000,
        jitter_ratio=0.2,
    )
    later = DeliveryStore.compute_backoff_seconds(
        "target_one",
        5,
        base_seconds=10,
        max_seconds=1000,
        jitter_ratio=0.2,
    )

    assert first == repeated
    assert 8 <= first <= 12
    assert later > first
    assert later <= 1000
