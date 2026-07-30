from __future__ import annotations

import json
import sqlite3
from pathlib import Path

from history_dispatcher.crypto import StaticKeyProvider
from history_dispatcher.delivery_migration_cli import APPLY_CONFIRMATION, main
from history_dispatcher.migrations import DatabaseV2Migrator
from history_dispatcher.store import DispatcherStore


def _v2_database(tmp_path: Path) -> tuple[Path, StaticKeyProvider]:
    provider = StaticKeyProvider(b"k" * 32)
    store = DispatcherStore(tmp_path / "history.sqlite3", provider)
    DatabaseV2Migrator(
        store.database_path,
        provider,
        backup_dir=tmp_path / "backups-v2",
        minimum_free_bytes=0,
    ).migrate()
    return store.database_path, provider


def _versions(path: Path) -> list[int]:
    with sqlite3.connect(path) as db:
        return [
            int(row[0])
            for row in db.execute(
                "SELECT version FROM schema_migrations ORDER BY version"
            )
        ]


def _base_args(database: Path, backup_dir: Path) -> list[str]:
    return [
        "--database",
        str(database),
        "--backup-dir",
        str(backup_dir),
    ]


def test_delivery_cli_defaults_to_write_free_dry_run(
    tmp_path: Path,
    capsys,
) -> None:
    database, provider = _v2_database(tmp_path)
    backup_dir = tmp_path / "backups-v3"

    result = main(
        [*_base_args(database, backup_dir), "migrate"],
        key_provider=provider,
    )

    output = json.loads(capsys.readouterr().out)
    assert result == 0
    assert output["ok"] is True
    assert output["dry_run"] is True
    assert output["target_schema_version"] == 3
    assert backup_dir.exists() is False
    assert _versions(database) == [1, 2]


def test_delivery_cli_write_mode_requires_exact_confirmation(
    tmp_path: Path,
    capsys,
) -> None:
    database, provider = _v2_database(tmp_path)
    backup_dir = tmp_path / "backups-v3"

    result = main(
        [*_base_args(database, backup_dir), "migrate", "--apply"],
        key_provider=provider,
    )

    output = json.loads(capsys.readouterr().out)
    assert result == 2
    assert output["error"]["code"] == "confirmation_mismatch"
    assert APPLY_CONFIRMATION in output["error"]["message"]
    assert backup_dir.exists() is False
    assert _versions(database) == [1, 2]


def test_delivery_cli_apply_and_verify(tmp_path: Path, capsys) -> None:
    database, provider = _v2_database(tmp_path)
    backup_dir = tmp_path / "backups-v3"

    applied = main(
        [
            *_base_args(database, backup_dir),
            "migrate",
            "--apply",
            "--confirm",
            APPLY_CONFIRMATION,
        ],
        key_provider=provider,
    )
    apply_output = json.loads(capsys.readouterr().out)
    verified = main(
        [*_base_args(database, backup_dir), "verify"],
        key_provider=provider,
    )
    verify_output = json.loads(capsys.readouterr().out)

    assert applied == 0
    assert apply_output["ok"] is True
    assert apply_output["backup"]["sha256"]
    assert verified == 0
    assert verify_output["ok"] is True
    assert verify_output["schema_versions"] == [1, 2, 3]
    assert verify_output["target_deliveries"] == verify_output["bindings"]
    assert verify_output["recipient_deliveries"] == verify_output["recipient_bindings"]
