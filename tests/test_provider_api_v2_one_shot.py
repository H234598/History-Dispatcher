from __future__ import annotations

import json
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
        timestamp="2026-07-30T18:30:00+00:00",
        session_key="sess_one_shot",
        turn_key="turn_one_shot",
        parent_thread_key="parent_unknown",
        project_id="proj_one_shot",
        project_label="One shot",
        agent_context=AgentContext.ROOT,
        source_ordinal=1,
        response_key="resp_one_shot",
        text="One-shot fixture",
        text_sha256="a" * 64,
        dedupe_key="b" * 64,
        event_id="evt_one_shot",
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
        ).plan(event, config_revision="one-shot")
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


def _request(request_id: str, body: dict[str, object]) -> dict[str, object]:
    return {
        "protocol_version": 1,
        "request_id": request_id,
        "operation": "provider.v2.claim",
        "body": body,
    }


def test_validation_failure_releases_pending_one_shot_reservation(tmp_path: Path) -> None:
    service, database = _service(tmp_path)
    valid = {
        "target_id": "telegram",
        "provider_id": "teebotus",
        "worker_id": "teebotus-worker",
        "capability_version": TEEBOTUS_CAPABILITY_V2,
    }

    invalid = service.handle(
        _request(
            "claim-validation-retry",
            {
                **valid,
                "bot_token": "123456789:ABCDEFGHIJKLMNOPQRSTUVWXYZabcdef",
            },
        )
    )
    corrected = service.handle(_request("claim-validation-retry", valid))

    assert invalid["ok"] is False
    assert invalid["error"]["code"] == "operation_failed"
    assert corrected["ok"] is True
    assert len(corrected["data"]["claims"]) == 1
    with sqlite3.connect(database) as db:
        assert db.execute(
            "SELECT COUNT(*) FROM delivery_attempts "
            "WHERE recipient_delivery_id IS NULL"
        ).fetchone()[0] == 1


def test_empty_claim_response_is_safely_cached_and_replayed(tmp_path: Path) -> None:
    service, database = _service(tmp_path)
    body = {
        "target_id": "telegram",
        "provider_id": "history_dispatcher",
        "worker_id": "native-worker",
        "capability_version": "history-dispatcher-telegram-native-v1",
    }
    request = _request("empty-native-claim", body)

    first = service.handle(request)
    second = service.handle(request)

    assert first == second == {
        "ok": True,
        "data": {"ok": True, "schema_version": 2, "claims": []},
    }
    with sqlite3.connect(database) as db:
        response_json = db.execute(
            "SELECT response_json FROM idempotency_results WHERE request_id=?",
            ("empty-native-claim",),
        ).fetchone()[0]
        assert db.execute(
            "SELECT COUNT(*) FROM delivery_attempts "
            "WHERE recipient_delivery_id IS NULL"
        ).fetchone()[0] == 0
    assert json.loads(response_json) == first
    assert "claim_token" not in response_json
