from __future__ import annotations

import json
from pathlib import Path

from history_dispatcher.collector import Collector
from history_dispatcher.config import load_config
from history_dispatcher.crypto import StaticKeyProvider
from history_dispatcher.service import DispatcherService


def test_codex_source_imports_and_deduplicates_session(tmp_path: Path) -> None:
    sessions = tmp_path / "sessions"
    sessions.mkdir()
    session = sessions / "run.jsonl"
    rows = [
        {"type": "session_meta", "payload": {"id": "session-1", "cwd": "/repo"}},
        {"type": "turn_context", "payload": {"turn_id": "turn-1"}},
        {"type": "event", "payload": {"role": "user", "content": "Do the thing"}},
        {"type": "event", "payload": {"role": "assistant", "phase": "final", "content": "Implemented the thing\nTests: 4 passed"}},
    ]
    session.write_text("\n".join(json.dumps(row) for row in rows) + "\n", encoding="utf-8")
    config = load_config(tmp_path / "missing.toml")
    config = config.__class__(**{
        **config.__dict__,
        "state_dir": tmp_path / "state",
        "runtime_dir": tmp_path / "runtime",
        "database_path": tmp_path / "state/db.sqlite3",
        "socket_path": tmp_path / "runtime/control.sock",
        "sources": (config.sources[0].__class__("codex", roots=(sessions,), scan_limit=10),),
    })
    service = DispatcherService(config, key_provider=StaticKeyProvider(b"k" * 32))
    report = Collector(config, service.store).collect_once()
    assert report.imported == 1
    assert Collector(config, service.store).collect_once().duplicates == 1
    rows = service.store.query(status="queued", limit=10, include_payload=True)
    assert rows[0]["payload"]["codex"]["session_id"] == "session-1"
    collected = service.handle({"protocol_version": 1, "operation": "collector.collect", "body": {}})
    assert collected["ok"] and collected["data"]["source"] == "codex"
