#!/usr/bin/env python3
from __future__ import annotations

import argparse
import shutil
from pathlib import Path

APPLET_UUID = "history-dispatcher@H234598"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Install the History-Dispatcher Cinnamon applet.")
    parser.add_argument("--repo-root", type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument("--target-root", type=Path, default=Path.home() / ".local/share/cinnamon/applets")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args(argv)
    source = args.repo_root / "files" / APPLET_UUID
    target = args.target_root / APPLET_UUID
    if not source.is_dir():
        raise SystemExit(f"Applet source not found: {source}")
    print(f"source={source}")
    print(f"target={target}")
    if args.dry_run:
        print("status=dry-run")
        return 0
    target.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    staging = target.parent / f".{APPLET_UUID}.staging"
    if staging.exists():
        shutil.rmtree(staging)
    shutil.copytree(source, staging)
    if target.exists():
        backup = target.parent / f".{APPLET_UUID}.previous"
        if backup.exists():
            shutil.rmtree(backup)
        target.rename(backup)
    staging.rename(target)
    print("status=installed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

