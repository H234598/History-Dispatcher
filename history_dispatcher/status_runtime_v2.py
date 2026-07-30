from __future__ import annotations

import json
import sqlite3
from collections.abc import Mapping
from pathlib import Path
from typing import Any
from urllib.parse import quote

from .status_v2 import (
    MAX_STATUS_WORKERS,
    CredentialStatus,
    HealthStatusV2,
    TelegramProviderStatus,
    WorkerHealthStatus,
)


def _readonly_connection(path: Path) -> sqlite3.Connection:
    uri = f"file:{quote(str(path.expanduser().absolute()), safe='/')}?mode=ro"
    connection = sqlite3.connect(uri, uri=True, timeout=5)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA query_only=ON")
    connection.execute("PRAGMA busy_timeout=5000")
    return connection


def _table_exists(db: sqlite3.Connection, table: str) -> bool:
    return (
        db.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?",
            (table,),
        ).fetchone()
        is not None
    )


def _provider_from_details(target: str, raw: Any) -> str:
    try:
        details = json.loads(str(raw or "{}"))
    except (TypeError, ValueError, json.JSONDecodeError):
        details = {}
    if isinstance(details, dict):
        provider = details.get("provider_id")
        if isinstance(provider, str) and provider.strip():
            return provider.strip()
    if target in {"vault", "local_archive"}:
        return target
    return "unknown"


def _read_workers(db: sqlite3.Connection) -> tuple[WorkerHealthStatus, ...]:
    if not _table_exists(db, "worker_heartbeats"):
        return ()
    rows = db.execute(
        "SELECT worker_id,target_id,capability_version,state,last_heartbeat_at,"
        "details_json FROM worker_heartbeats "
        "ORDER BY last_heartbeat_at DESC,worker_id LIMIT ?",
        (MAX_STATUS_WORKERS,),
    ).fetchall()
    workers: list[WorkerHealthStatus] = []
    for row in rows:
        target = str(row["target_id"] or "unknown").strip() or "unknown"
        workers.append(
            WorkerHealthStatus(
                worker_id=str(row["worker_id"]),
                target=target,
                provider=_provider_from_details(target, row["details_json"]),
                capability=str(row["capability_version"] or "unknown"),
                state=str(row["state"] or "unknown"),
                heartbeat=str(row["last_heartbeat_at"] or "") or None,
            )
        )
    return tuple(workers)


def _read_delivery_counts(db: sqlite3.Connection) -> dict[str, int]:
    if not _table_exists(db, "target_deliveries"):
        return {}
    return {
        str(row["state"]): int(row["count"])
        for row in db.execute(
            "SELECT state,COUNT(*) AS count FROM target_deliveries "
            "GROUP BY state ORDER BY state"
        ).fetchall()
    }


def build_runtime_health_status(
    *,
    database_path: Path,
    telegram_provider: str,
    credential: CredentialStatus,
    queue_counts: Mapping[str, Any],
    generated_at: str | None,
) -> HealthStatusV2:
    workers: tuple[WorkerHealthStatus, ...] = ()
    deliveries: dict[str, int] = {}
    database = Path(database_path)
    if database.is_file():
        try:
            with _readonly_connection(database) as db:
                workers = _read_workers(db)
                deliveries = _read_delivery_counts(db)
        except sqlite3.Error:
            # Status collection must not create or mutate a database. A locked,
            # partial or pre-migration database is represented by empty optional
            # v2 sections while the v1 queue counters remain available.
            workers = ()
            deliveries = {}
    return HealthStatusV2(
        telegram=TelegramProviderStatus(
            provider=telegram_provider,
            credential=credential,
        ),
        workers=workers,
        queue=dict(queue_counts),
        deliveries=deliveries,
        generated_at=generated_at,
    )
