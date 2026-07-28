from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Sequence

from .config import load_config
from .crypto import KeyUnavailable, SecretServiceKeyProvider
from .migrations.v3 import (
    DatabaseV3Migrator,
    MigrationV3Error,
    verify_database_v3,
)
from .redaction import redact_text


APPLY_CONFIRMATION = "MIGRATE-V3"


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Preflight, dry-run, apply, or verify the additive provider-binding "
            "and delivery-store schema-v3 migration."
        )
    )
    parser.add_argument("--config", type=Path)
    parser.add_argument("--database", type=Path)
    parser.add_argument("--backup-dir", type=Path)
    subparsers = parser.add_subparsers(dest="command", required=True)
    subparsers.add_parser("preflight")
    migrate = subparsers.add_parser(
        "migrate",
        help="Run a write-free dry run unless --apply is explicitly supplied.",
    )
    migrate.add_argument("--apply", action="store_true")
    migrate.add_argument("--confirm", default="")
    subparsers.add_parser("verify")
    return parser


def _print(value: object) -> None:
    print(
        json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        )
    )


def _error(code: str, message: object) -> dict[str, object]:
    return {
        "ok": False,
        "error": {
            "code": str(code)[:96],
            "message": redact_text(message, max_chars=500, max_bytes=2000),
        },
    }


def main(
    argv: Sequence[str] | None = None,
    *,
    key_provider: SecretServiceKeyProvider | None = None,
) -> int:
    args = _parser().parse_args(list(argv) if argv is not None else None)
    try:
        config = load_config(args.config)
        database_path = (
            Path(args.database).expanduser()
            if args.database is not None
            else config.database_path
        )
        backup_dir = (
            Path(args.backup_dir).expanduser()
            if args.backup_dir is not None
            else database_path.parent / "backups"
        )
        if args.command == "verify":
            report = verify_database_v3(database_path)
            _print(report)
            return 0 if report["ok"] else 1

        provider = key_provider or SecretServiceKeyProvider()
        migrator = DatabaseV3Migrator(
            database_path,
            provider,
            backup_dir=backup_dir,
        )
        if args.command == "preflight":
            _print({"ok": True, "preflight": migrator.preflight()})
            return 0
        if args.command == "migrate":
            if args.apply and args.confirm != APPLY_CONFIRMATION:
                _print(
                    _error(
                        "confirmation_mismatch",
                        f"write mode requires --confirm {APPLY_CONFIRMATION}",
                    )
                )
                return 2
            report = migrator.migrate(dry_run=not args.apply)
            _print(report.as_dict())
            return 0 if report.ok else 1
        raise AssertionError(args.command)
    except (MigrationV3Error, KeyUnavailable, OSError, ValueError) as exc:
        _print(_error("delivery_schema_migration_failed", exc))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
