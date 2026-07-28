from __future__ import annotations

import argparse
import json
from pathlib import Path

from history_dispatcher.fixture_sanitizer import (
    DEFAULT_MAX_LINE_BYTES,
    sanitize_jsonl_file,
    write_manifest,
)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Deterministically sanitize a Codex rollout JSONL fixture."
    )
    parser.add_argument("source", type=Path)
    parser.add_argument("output", type=Path)
    parser.add_argument("--manifest", type=Path)
    parser.add_argument("--upstream-commit", default="")
    parser.add_argument("--max-line-bytes", type=int, default=DEFAULT_MAX_LINE_BYTES)
    parser.add_argument("--dry-run", action="store_true")
    return parser


def main() -> int:
    args = _parser().parse_args()
    result = sanitize_jsonl_file(
        args.source,
        args.output,
        max_line_bytes=args.max_line_bytes,
        dry_run=args.dry_run,
    )
    entry = result.manifest_entry(upstream_commit=args.upstream_commit)
    if args.manifest and not args.dry_run:
        write_manifest(
            args.manifest,
            [entry],
            upstream_commit=args.upstream_commit,
        )
    print(json.dumps(entry, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
