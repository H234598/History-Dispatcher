from __future__ import annotations

import sqlite3
from pathlib import Path

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
from history_dispatcher.routing import RoutePlanner, RoutingPolicy, TelegramRoutingPolicy
from history_dispatcher.service import DispatcherService
from history_dispatcher.store import DispatcherStore
from history_dispatcher.telegram_provider import (
    TEEBOTUS_CAPABILITY_V2,
    TelegramTransportBinding,
)


def _service(tmp_path: Path) -> tuple[DispatcherService, Path]:
    provider = StaticKeyProvider(b"k" * 32)
    database = tmp_path / "state" / "history.sqlite3"
    DispatcherStore(database, provider)
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
    event = ClassifiedEvent(
        history_kind=HistoryKind.TASK_COMPLETION,
        confidence=ClassificationConfidence.AUTHORITATIVE,
        reason_code="fixture",
        source_schema_family="fixture",
        timestamp="2026-07-30T22:00:00+00:00",
        session_key="sess_reclaim_socket",
        turn_key="turn_reclaim_socket",
        parent_thread_key="parent_unknown",
        project_id="proj_reclaim_socket",
        project_label="Reclaim socket",
        agent_context=AgentContext.ROOT,
        source_ordinal=1,
        response_key="resp_reclaim_socket",
        text="Socket reclaim payload",
        text_sha256="a" * 64,
        dedupe_key="b" * 64,
        event_id="evt_reclaim_socket",
        external_dispatchable=True,
    )
    delivery.append_classified_event(event)
    delivery.create_route_plan(
        RoutePlanner(
            RoutingPolicy(
                telegram=TelegramRoutingPolicy(
                    include_task_completion=True,
                    binding=TelegramTransportBinding.teebotus(),
                )
            )
        ).plan(event, config_revision="reclaim-socket")
    )

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
    return DispatcherService(config, key_provider=provider), database


def _request(request_id: str, operation: str, body: dict[str, object]) -> dict[str, object]:
    return {
        "protocol_version": 1,
        "request_id": request_id,
        "operation": operation,
        "body": body,
    }


def test_reclaim_token_is_one_shot_and_never_cached(tmp_path: Path) -> None:
    service, database = _service(tmp_path)
    claim = service.handle(
        _request(
            "initial-claim",
            "provider.v2.claim",
            {
                "target_id": "telegram",
                "provider_id": "teebotus",
                "worker_id": "teebotus-worker",
                "capability_version": TEEBOTUS_CAPABILITY_V2,
                "limit": 1,
                "lease_seconds": 10,
            },
        )
    )["data"]["claims"][0]
    with sqlite3.connect(database) as db:
        db.execute(
            "UPDATE target_deliveries SET claim_expires_at='2000-01-01T00:00:00+00:00' "
            "WHERE id=?",
            (claim["target_delivery_id"],),
        )

    body = {
        "target_delivery_id": claim["target_delivery_id"],
        "provider_id": "teebotus",
        "worker_id": "teebotus-worker",
        "capability_version": TEEBOTUS_CAPABILITY_V2,
        "previous_attempt_no": claim["attempt_no"],
        "lease_seconds": 120,
    }
    first = service.handle(_request("reclaim-once", "provider.v2.reclaim", body))
    replay = service.handle(_request("reclaim-once", "provider.v2.reclaim", body))

    assert first["ok"] is True
    reclaimed = first["data"]["claims"][0]
    assert reclaimed["reconciliation_only"] is True
    assert replay["ok"] is False
    assert replay["error"]["code"] == "idempotency_in_progress"
    with sqlite3.connect(database) as db:
        stored = db.execute(
            "SELECT response_json FROM idempotency_results WHERE request_id='reclaim-once'"
        ).fetchone()
        attempt_count = db.execute(
            "SELECT attempt_count FROM target_deliveries WHERE id=?",
            (claim["target_delivery_id"],),
        ).fetchone()[0]
    assert stored == ("",)
    assert attempt_count == 2
    assert reclaimed["claim_token"].encode("utf-8") not in database.read_bytes()


def test_empty_reclaim_is_safely_cached(tmp_path: Path) -> None:
    service, _database = _service(tmp_path)
    body = {
        "target_delivery_id": "target_missing",
        "provider_id": "teebotus",
        "worker_id": "teebotus-worker",
        "capability_version": TEEBOTUS_CAPABILITY_V2,
        "previous_attempt_no": 1,
        "lease_seconds": 120,
    }
    request = _request("empty-reclaim", "provider.v2.reclaim", body)

    first = service.handle(request)
    second = service.handle(request)

    assert first == second == {
        "ok": True,
        "data": {"ok": True, "schema_version": 2, "claims": []},
    }
