from __future__ import annotations

import json
import sqlite3
from pathlib import Path

import pytest

from history_dispatcher.classification_types import (
    AgentContext,
    ClassifiedEvent,
    ClassificationConfidence,
    HistoryKind,
)
from history_dispatcher.config import load_config
from history_dispatcher.crypto import StaticKeyProvider
from history_dispatcher.delivery_store import DeliveryStore
from history_dispatcher.migrations import DatabaseV2Migrator, DatabaseV3Migrator
from history_dispatcher.provider_api_v2 import (
    PROVIDER_API_OPERATIONS,
    PROVIDER_API_SCHEMA_VERSION,
    ProviderApiV2,
    ProviderApiValidationError,
)
from history_dispatcher.routing import RoutePlanner, RoutingPolicy, TelegramRoutingPolicy
from history_dispatcher.service import OPERATIONS, DispatcherService
from history_dispatcher.store import DispatcherStore
from history_dispatcher.telegram_provider import (
    TEEBOTUS_CAPABILITY_V2,
    TelegramTransportBinding,
)


FIXTURE = Path(__file__).parent / "fixtures" / "provider-v2" / "contract.json"


def _event(suffix: str = "provider-v2") -> ClassifiedEvent:
    return ClassifiedEvent(
        history_kind=HistoryKind.TASK_COMPLETION,
        confidence=ClassificationConfidence.AUTHORITATIVE,
        reason_code="fixture",
        source_schema_family="fixture",
        timestamp="2026-07-30T18:00:00+00:00",
        session_key=f"sess_{suffix}",
        turn_key=f"turn_{suffix}",
        parent_thread_key="parent_unknown",
        project_id="proj_provider_v2",
        project_label="Provider v2",
        agent_context=AgentContext.ROOT,
        source_ordinal=1,
        response_key=f"resp_{suffix}",
        text="Provider v2 visible payload",
        text_sha256="a" * 64,
        dedupe_key=(suffix.encode("utf-8").hex() + "b" * 64)[:64],
        event_id=f"evt_{suffix}",
        external_dispatchable=True,
    )


def _prepared_database(tmp_path: Path) -> tuple[Path, StaticKeyProvider]:
    provider = StaticKeyProvider(b"k" * 32)
    database = tmp_path / "state" / "history.sqlite3"
    legacy = DispatcherStore(database, provider)
    DatabaseV2Migrator(
        database,
        provider,
        backup_dir=tmp_path / "backups-v2",
        minimum_free_bytes=0,
    ).migrate()
    DatabaseV3Migrator(
        database,
        provider,
        backup_dir=tmp_path / "backups-v3",
    ).migrate()
    delivery = DeliveryStore(database, provider)
    event = _event()
    delivery.append_classified_event(event)
    plan = RoutePlanner(
        RoutingPolicy(
            telegram=TelegramRoutingPolicy(
                include_task_completion=True,
                binding=TelegramTransportBinding.teebotus(),
            )
        )
    ).plan(event, config_revision="provider-v2-fixture")
    delivery.create_route_plan(plan)
    return database, provider


def _api(tmp_path: Path) -> tuple[ProviderApiV2, Path]:
    database, provider = _prepared_database(tmp_path)
    return ProviderApiV2(DeliveryStore(database, provider)), database


def test_provider_contract_fixture_is_stable_and_secret_free() -> None:
    fixture = json.loads(FIXTURE.read_text(encoding="utf-8"))

    assert fixture["schema_version"] == PROVIDER_API_SCHEMA_VERSION == 2
    assert tuple(fixture["operations"]) == PROVIDER_API_OPERATIONS
    assert fixture["capability"] == TEEBOTUS_CAPABILITY_V2
    serialized = json.dumps(fixture, ensure_ascii=False, sort_keys=True)
    for forbidden in ("bot_token", "chat_id", "123456789:", "-1001234567890"):
        assert forbidden not in serialized


def test_teebotus_provider_v2_claim_register_record_complete_and_heartbeat(
    tmp_path: Path,
) -> None:
    api, database = _api(tmp_path)
    fixture = json.loads(FIXTURE.read_text(encoding="utf-8"))

    claimed = api.dispatch("provider.v2.claim", fixture["claim_request"])
    assert claimed["ok"] is True
    assert len(claimed["claims"]) == 1
    claim = claimed["claims"][0]
    assert claim["provider_id"] == "teebotus"
    assert claim["target_id"] == "telegram"
    assert claim["capability_version"] == TEEBOTUS_CAPABILITY_V2
    assert claim["payload"]["text"] == "Provider v2 visible payload"
    assert claim["successful_recipient_refs"] == []
    assert claim["open_recipient_refs"] == []
    assert len(claim["claim_token"]) >= 32

    renewed = api.dispatch(
        "provider.v2.renew",
        {
            "target_delivery_id": claim["target_delivery_id"],
            "worker_id": "teebotus-worker",
            "claim_token": claim["claim_token"],
            "lease_seconds": 180,
        },
    )
    assert renewed["ok"] is True
    assert renewed["claim_expires_at"] >= claim["claim_expires_at"]

    registered = api.dispatch(
        "provider.v2.register_recipients",
        {
            "target_delivery_id": claim["target_delivery_id"],
            "worker_id": "teebotus-worker",
            "claim_token": claim["claim_token"],
            "recipient_refs": fixture["recipient_refs"],
        },
    )
    assert [row["recipient_ref"] for row in registered["recipients"]] == fixture[
        "recipient_refs"
    ]

    recorded = api.dispatch(
        "provider.v2.record_recipients",
        {
            "target_delivery_id": claim["target_delivery_id"],
            "worker_id": "teebotus-worker",
            "claim_token": claim["claim_token"],
            "outcomes": fixture["recipient_outcomes"],
        },
    )
    assert [row["state"] for row in recorded["recipients"]] == [
        "accepted",
        "skipped",
    ]

    completed = api.dispatch(
        "provider.v2.complete",
        {
            "target_delivery_id": claim["target_delivery_id"],
            "worker_id": "teebotus-worker",
            "claim_token": claim["claim_token"],
        },
    )
    assert completed == {"ok": True, "state": "delivered"}

    heartbeat = api.dispatch(
        "provider.v2.heartbeat",
        {
            "worker_id": "teebotus-worker",
            "target_id": "telegram",
            "provider_id": "teebotus",
            "capability_version": TEEBOTUS_CAPABILITY_V2,
            "state": "idle",
            "details": {"queue_depth": 0},
        },
    )
    assert heartbeat == {"ok": True}
    with sqlite3.connect(database) as db:
        row = db.execute(
            "SELECT target_id,capability_version,state,details_json "
            "FROM worker_heartbeats WHERE worker_id='teebotus-worker'"
        ).fetchone()
    assert row is not None
    assert row[:3] == ("telegram", TEEBOTUS_CAPABILITY_V2, "idle")
    assert json.loads(row[3])["provider_id"] == "teebotus"


def test_provider_v2_validation_rejects_unknown_fields_and_provider_mismatch(
    tmp_path: Path,
) -> None:
    api, _database = _api(tmp_path)

    with pytest.raises(ProviderApiValidationError, match="unknown field"):
        api.dispatch(
            "provider.v2.claim",
            {
                "target_id": "telegram",
                "provider_id": "teebotus",
                "worker_id": "teebotus-worker",
                "capability_version": TEEBOTUS_CAPABILITY_V2,
                "bot_token": "123456789:ABCDEFGHIJKLMNOPQRSTUVWXYZabcdef",
            },
        )

    native = api.dispatch(
        "provider.v2.claim",
        {
            "target_id": "telegram",
            "provider_id": "history_dispatcher",
            "worker_id": "native-worker",
            "capability_version": "history-dispatcher-telegram-native-v1",
        },
    )
    assert native == {"ok": True, "claims": []}


def test_provider_v2_socket_claim_is_one_shot_and_never_cached_with_token(
    tmp_path: Path,
) -> None:
    database, provider = _prepared_database(tmp_path)
    config_file = tmp_path / "config.toml"
    config_file.write_text("", encoding="utf-8")
    config = load_config(config_file)
    config = config.__class__(
        **{
            **config.__dict__,
            "state_dir": tmp_path / "state",
            "runtime_dir": tmp_path / "runtime",
            "database_path": database,
            "socket_path": tmp_path / "runtime" / "control.sock",
        }
    )
    service = DispatcherService(config, key_provider=provider)
    body = json.loads(FIXTURE.read_text(encoding="utf-8"))["claim_request"]
    request = {
        "protocol_version": 1,
        "request_id": "provider-v2-one-shot-claim",
        "operation": "provider.v2.claim",
        "body": body,
    }

    first = service.handle(request)
    second = service.handle(request)
    conflict = service.handle(
        {
            **request,
            "body": {**body, "worker_id": "different-worker"},
        }
    )

    assert all(operation in OPERATIONS for operation in PROVIDER_API_OPERATIONS)
    assert first["ok"] is True
    assert len(first["data"]["claims"]) == 1
    claim_token = first["data"]["claims"][0]["claim_token"]
    assert second["ok"] is False
    assert second["error"]["code"] == "idempotency_in_progress"
    assert conflict["ok"] is False
    assert conflict["error"]["code"] == "idempotency_conflict"

    with sqlite3.connect(database) as db:
        row = db.execute(
            "SELECT response_json FROM idempotency_results WHERE request_id=?",
            ("provider-v2-one-shot-claim",),
        ).fetchone()
        attempt_count = db.execute(
            "SELECT attempt_count FROM target_deliveries "
            "WHERE target_id='telegram'"
        ).fetchone()[0]
        attempts = db.execute(
            "SELECT COUNT(*) FROM delivery_attempts "
            "WHERE recipient_delivery_id IS NULL"
        ).fetchone()[0]
    assert row == ("",)
    assert attempt_count == attempts == 1
    assert claim_token.encode("utf-8") not in database.read_bytes()
