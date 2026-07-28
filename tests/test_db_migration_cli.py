from __future__ import annotations

import json
import sqlite3
from pathlib import Path

from history_dispatcher.crypto import StaticKeyProvider
from history_dispatcher.db_migration_cli import APPLY_CONFIRMATION, main
from history_dispatcher.store import DispatcherStore


def _store(tmp_path: Path) -> DispatcherStore:
    store = DispatcherStore(
        tmp_path / "history.sqlite3",
        StaticKeyProvider(b"k" * 32),
    )
    store.append(
        {
            "id": "legacy-cli-item",
            "dedupe_key": "legacy-cli-item",
            "source": "codex",
            "project": "/home/alice/PrivateProject",
            "payload": {
                "codex": {
                    "session_id": "private-session",
                    "turn_id": "private-turn",
                },
                "summary": {"text": "private payload"},
            },
        }
    )
    return store


def _versions(path: Path) -> list[int]:
    with sqlite3.connect(path) as db:
        return [
            int(row[0])
            for row in db.execute(
                "SELECT version FROM schema_migrations ORDER BY version"
            )
        ]


def _base_args(store: DispatcherStore, backup_dir: Path) -> list[str]:
    return [
        "--database",
        str(store.database_path),
        "--backup-dir",
        str(backup_dir),
        "--minimum-free-bytes",
        "0",
    ]


def test_cli_migrate_defaults_to_write_free_dry_run(
    tmp_path: Path,
    capsys,
) -> None:
    store = _store(tmp_path)
    backup_dir = tmp_path / "backups"

    result = main(
        [*_base_args(store, backup_dir), "migrate"],
        key_provider=store.key_provider,
    )

    output = json.loads(capsys.readouterr().out)
    assert result == 0
    assert output["ok"] is True
    assert output["dry_run"] is True
    assert output["no_external_dispatch_created"] is True
    assert backup_dir.exists() is False
    assert _versions(store.database_path) == [1]


def test_cli_write_mode_requires_exact_confirmation(
    tmp_path: Path,
    capsys,
) -> None:
    store = _store(tmp_path)
    backup_dir = tmp_path / "backups"

    result = main(
        [*_base_args(store, backup_dir), "migrate", "--apply"],
        key_provider=store.key_provider,
    )

    output = json.loads(capsys.readouterr().out)
    assert result == 2
    assert output["ok"] is False
    assert output["error"]["code"] == "confirmation_mismatch"
    assert APPLY_CONFIRMATION in output["error"]["message"]
    assert backup_dir.exists() is False
    assert _versions(store.database_path) == [1]


def test_cli_apply_and_verify_use_bounded_json_reports(
    tmp_path: Path,
    capsys,
) -> None:
    store = _store(tmp_path)
    backup_dir = tmp_path / "backups"

    applied = main(
        [
            *_base_args(store, backup_dir),
            "migrate",
            "--apply",
            "--confirm",
            APPLY_CONFIRMATION,
        ],
        key_provider=store.key_provider,
    )
    apply_output = json.loads(capsys.readouterr().out)

    verified = main(
        [*_base_args(store, backup_dir), "verify"],
        key_provider=store.key_provider,
    )
    verify_output = json.loads(capsys.readouterr().out)

    assert applied == 0
    assert apply_output["ok"] is True
    assert apply_output["dry_run"] is False
    assert apply_output["backup"]["sha256"]
    assert "/home/alice" not in json.dumps(apply_output)
    assert "private payload" not in json.dumps(apply_output)
    assert verified == 0
    assert verify_output["ok"] is True
    assert verify_output["schema_versions"] == [1, 2]
    assert verify_output["no_external_dispatch_created"] is True


def test_cli_preflight_reports_active_claims_without_mutation(
    tmp_path: Path,
    capsys,
) -> None:
    store = _store(tmp_path)
    store.claim(worker_id="legacy-worker", limit=1, claim_ttl_seconds=300)
    backup_dir = tmp_path / "backups"

    result = main(
        [*_base_args(store, backup_dir), "preflight"],
        key_provider=store.key_provider,
    )

    output = json.loads(capsys.readouterr().out)
    assert result == 0
    assert output["ok"] is True
    assert output["preflight"]["active_claims"] == 1
    assert backup_dir.exists() is False
    assert _versions(store.database_path) == [1]
