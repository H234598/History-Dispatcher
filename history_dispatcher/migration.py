from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
from typing import Any

from .store import DispatcherStore


MAX_LEGACY_LINE_BYTES = 8 * 1024 * 1024


def migrate_legacy_jsonl(path: Path, store: DispatcherStore, *, dry_run: bool = False) -> dict[str, Any]:
    """Stream a TeeBotus history JSONL file into encrypted Dispatcher storage.

    The source is never rewritten and no plaintext staging file is created. The
    digest covers canonical source records so a second run can be compared
    without decrypting the new database.
    """
    path = path.expanduser()
    if not path.is_absolute() or "\x00" in str(path):
        raise ValueError("legacy path must be absolute")
    if path.is_symlink() or not path.is_file():
        raise ValueError("legacy path must be a regular file")
    digest = hashlib.sha256()
    total = 0
    imported = 0
    deduplicated = 0
    skipped = 0
    statuses: dict[str, int] = {}
    with path.open("rb") as handle:
        for line_number, raw_line in enumerate(handle, 1):
            if len(raw_line) > MAX_LEGACY_LINE_BYTES:
                raise ValueError(f"legacy line {line_number} exceeds {MAX_LEGACY_LINE_BYTES} bytes")
            stripped = raw_line.strip()
            if not stripped:
                continue
            try:
                item = json.loads(stripped.decode("utf-8"))
            except (UnicodeDecodeError, json.JSONDecodeError) as exc:
                raise ValueError(f"invalid legacy JSON at line {line_number}") from exc
            if not isinstance(item, dict):
                skipped += 1
                continue
            canonical = json.dumps(item, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
            digest.update(hashlib.sha256(canonical).digest())
            total += 1
            source_status = str(item.get("status") or "queued").strip().casefold()
            statuses[source_status] = statuses.get(source_status, 0) + 1
            payload = dict(item)
            project = item.get("project", "")
            if isinstance(project, dict):
                project = str(project.get("repo_root") or project.get("repo_name") or "")
            import_item = {
                "id": str(item.get("id") or "").strip(),
                "source": str(item.get("source") or "teebotus-legacy"),
                "dedupe_key": str(item.get("dedupe_key") or item.get("id") or hashlib.sha256(canonical).hexdigest()),
                "kind": str(item.get("kind") or "codex_run_summary"),
                "target_group": str(item.get("target_group") or (item.get("delivery") or {}).get("target_group") or "status_admins"),
                "project": str(project or ""),
                "created_at": str(item.get("created_at") or ""),
                "status": source_status,
                "attempt_count": int((item.get("delivery") or {}).get("attempts", 0) or 0) if isinstance(item.get("delivery"), dict) else 0,
                "possible_duplicate": bool((item.get("delivery") or {}).get("possible_duplicate")) if isinstance(item.get("delivery"), dict) else False,
                "payload": payload,
            }
            if dry_run:
                imported += 1
                continue
            result = store.append(import_item, idempotency_key=import_item["dedupe_key"])
            if result.get("deduplicated"):
                deduplicated += 1
            else:
                imported += 1
    return {
        "ok": True,
        "path": str(path),
        "dry_run": dry_run,
        "total": total,
        "imported": imported,
        "deduplicated": deduplicated,
        "skipped": skipped,
        "statuses": statuses,
        "source_digest": digest.hexdigest(),
    }
