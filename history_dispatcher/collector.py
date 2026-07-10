from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .config import DispatcherConfig
from .sources import CodexJsonlSource
from .store import DispatcherStore


@dataclass(frozen=True)
class CollectionReport:
    ok: bool
    source: str
    scanned: int
    imported: int
    duplicates: int
    skipped: int
    errors: tuple[str, ...]

    def as_dict(self) -> dict[str, Any]:
        return {
            "ok": self.ok,
            "source": self.source,
            "scanned": self.scanned,
            "imported": self.imported,
            "duplicates": self.duplicates,
            "skipped": self.skipped,
            "errors": list(self.errors),
        }


class Collector:
    def __init__(self, config: DispatcherConfig, store: DispatcherStore) -> None:
        self.config = config
        self.store = store

    def collect_once(self) -> CollectionReport:
        source_config = next((item for item in self.config.sources if item.name == "codex" and item.enabled), None)
        if source_config is None or not self.config.collector_enabled:
            return CollectionReport(True, "codex", 0, 0, 0, 0, ())
        source = CodexJsonlSource(source_config.roots, scan_limit=min(self.config.collector_scan_limit, source_config.scan_limit), max_file_bytes=source_config.max_file_bytes)
        scanned = imported = duplicates = skipped = 0
        errors: list[str] = []
        for item in source.items():
            scanned += 1
            try:
                result = self.store.append(item, idempotency_key=str(item.get("dedupe_key") or ""))
            except Exception as exc:  # One damaged source must not stop the scan.
                errors.append(f"{type(exc).__name__}: {str(exc)[:240]}")
                continue
            if result.get("deduplicated"):
                duplicates += 1
            else:
                imported += 1
        return CollectionReport(not errors, "codex", scanned, imported, duplicates, skipped, tuple(errors))

