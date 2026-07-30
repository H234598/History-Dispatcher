from __future__ import annotations

import sqlite3

import pytest

from history_dispatcher.idempotency import IdempotencyConflict, IdempotencyStore
from history_dispatcher.service import _request_fingerprint


def test_release_removes_only_the_exact_pending_reservation(tmp_path) -> None:
    database = tmp_path / "idempotency.sqlite3"
    store = IdempotencyStore(database, client_scope="uid:test")
    fingerprint = _request_fingerprint(
        "provider.v2.claim",
        {"worker_id": "teebotus-worker"},
    )

    assert store.begin(
        "claim-request",
        "provider.v2.claim",
        fingerprint,
    ) is None
    assert store.release(
        "claim-request",
        "provider.v2.claim",
        fingerprint,
    ) is True
    assert store.begin(
        "claim-request",
        "provider.v2.claim",
        fingerprint,
    ) is None


def test_release_rejects_mismatched_identity_and_preserves_reservation(tmp_path) -> None:
    database = tmp_path / "idempotency.sqlite3"
    store = IdempotencyStore(database, client_scope="uid:test")
    fingerprint = _request_fingerprint(
        "provider.v2.claim",
        {"worker_id": "teebotus-worker"},
    )
    other = _request_fingerprint(
        "provider.v2.claim",
        {"worker_id": "different-worker"},
    )
    store.begin("claim-request", "provider.v2.claim", fingerprint)

    with pytest.raises(IdempotencyConflict):
        store.release("claim-request", "provider.v2.claim", other)

    with sqlite3.connect(database) as db:
        row = db.execute(
            "SELECT operation,request_fingerprint,response_json "
            "FROM idempotency_results WHERE request_id='claim-request'"
        ).fetchone()
    assert row == ("provider.v2.claim", fingerprint, "")


def test_release_never_deletes_a_completed_response(tmp_path) -> None:
    database = tmp_path / "idempotency.sqlite3"
    store = IdempotencyStore(database, client_scope="uid:test")
    fingerprint = _request_fingerprint(
        "history.append",
        {"payload": {"value": 1}},
    )
    store.begin("completed-request", "history.append", fingerprint)
    store.complete(
        "completed-request",
        "history.append",
        fingerprint,
        {"ok": True},
    )

    assert store.release(
        "completed-request",
        "history.append",
        fingerprint,
    ) is False
    assert store.begin(
        "completed-request",
        "history.append",
        fingerprint,
    ) == {"ok": True}
