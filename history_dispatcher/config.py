from __future__ import annotations

import os
import tomllib
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


DEFAULT_SCAN_ROOTS = (
    Path("~/.codex/sessions").expanduser(),
    Path.home() / ".codex-agents/*/sessions",
)


def _positive(value: object, name: str, *, maximum: int) -> int:
    if isinstance(value, bool):
        raise ValueError(f"{name} must be an integer")
    try:
        number = int(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{name} must be an integer") from exc
    if number <= 0 or number > maximum:
        raise ValueError(f"{name} must be between 1 and {maximum}")
    return number


def _nonnegative(value: object, name: str, *, maximum: int) -> int:
    if isinstance(value, bool):
        raise ValueError(f"{name} must be an integer")
    try:
        number = int(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{name} must be an integer") from exc
    if number < 0 or number > maximum:
        raise ValueError(f"{name} must be between 0 and {maximum}")
    return number


def _path(value: object, name: str) -> Path:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{name} must be a non-empty path")
    text = value.strip()
    if "\\x00" in text:
        raise ValueError(f"{name} contains NUL")
    return Path(text).expanduser()


@dataclass(frozen=True)
class SourceConfig:
    name: str
    enabled: bool = True
    roots: tuple[Path, ...] = field(default_factory=tuple)
    scan_limit: int = 25
    max_file_bytes: int = 16 * 1024 * 1024


@dataclass(frozen=True)
class DispatcherConfig:
    config_path: Path
    state_dir: Path
    runtime_dir: Path
    database_path: Path
    socket_path: Path
    timezone: str = "Europe/Berlin"
    log_level: str = "INFO"
    status_heartbeat_seconds: int = 30
    frame_limit_bytes: int = 8 * 1024 * 1024
    collector_enabled: bool = True
    collector_interval_seconds: int = 300
    collector_scan_limit: int = 25
    dispatch_enabled: bool = True
    dispatch_paused: bool = False
    dispatch_batch_size: int = 20
    claim_ttl_seconds: int = 900
    retry_delays_seconds: tuple[int, ...] = (60, 300, 900, 3600, 21600)
    max_attempts: int = 12
    completed_retention_days: int = 30
    audit_retention_days: int = 365
    sources: tuple[SourceConfig, ...] = field(default_factory=tuple)

    @property
    def snapshot_path(self) -> Path:
        return self.runtime_dir / "status-v1.json"


def default_config(path: Path | None = None) -> DispatcherConfig:
    home = Path.home()
    state = Path(os.environ.get("XDG_STATE_HOME", home / ".local/state")) / "history-dispatcher"
    runtime = Path(os.environ.get("XDG_RUNTIME_DIR", f"/run/user/{os.getuid()}")) / "history-dispatcher"
    config_path = path or Path(os.environ.get("HISTORY_DISPATCHER_CONFIG", home / ".config/history-dispatcher/config.toml"))
    sources = (
        SourceConfig("codex", roots=tuple(DEFAULT_SCAN_ROOTS), scan_limit=25),
    )
    return DispatcherConfig(
        config_path=config_path.expanduser(),
        state_dir=state.expanduser(),
        runtime_dir=runtime.expanduser(),
        database_path=state.expanduser() / "history.sqlite3",
        socket_path=runtime.expanduser() / "control.sock",
        sources=sources,
    )


def load_config(path: Path | None = None) -> DispatcherConfig:
    base = default_config(path)
    if not base.config_path.exists():
        return base
    with base.config_path.open("rb") as handle:
        raw = tomllib.load(handle)
    if not isinstance(raw, dict):
        raise ValueError("config root must be a table")
    core = raw.get("core", {})
    api = raw.get("api", {})
    storage = raw.get("storage", {})
    collector = raw.get("collector", {})
    dispatch = raw.get("dispatch", {})
    retention = raw.get("retention", {})
    if not all(isinstance(section, dict) for section in (core, api, storage, collector, dispatch, retention)):
        raise ValueError("config sections must be tables")
    state_dir = _path(storage.get("state_dir", str(base.state_dir)), "storage.state_dir")
    runtime_dir = _path(api.get("runtime_dir", str(base.runtime_dir)), "api.runtime_dir")
    database_path = _path(storage.get("database_path", str(state_dir / "history.sqlite3")), "storage.database_path")
    socket_path = _path(api.get("socket_path", str(runtime_dir / "control.sock")), "api.socket_path")
    raw_sources = raw.get("sources", {}).get("codex", []) if isinstance(raw.get("sources", {}), dict) else []
    if isinstance(raw_sources, dict):
        raw_sources = [raw_sources]
    if not isinstance(raw_sources, list):
        raise ValueError("sources.codex must be an array of tables")
    sources: list[SourceConfig] = []
    for index, item in enumerate(raw_sources):
        if not isinstance(item, dict):
            raise ValueError(f"sources.codex[{index}] must be a table")
        name = str(item.get("name", "codex")).strip()
        if not name or len(name) > 96:
            raise ValueError(f"sources.codex[{index}].name is invalid")
        roots_raw = item.get("roots", [str(root) for root in DEFAULT_SCAN_ROOTS])
        if not isinstance(roots_raw, list) or not roots_raw:
            raise ValueError(f"sources.codex[{index}].roots must be a non-empty array")
        roots = tuple(_path(root, f"sources.codex[{index}].roots") for root in roots_raw)
        sources.append(SourceConfig(
            name=name,
            enabled=bool(item.get("enabled", True)),
            roots=roots,
            scan_limit=_positive(item.get("scan_limit", 25), "source.scan_limit", maximum=10000),
            max_file_bytes=_positive(item.get("max_file_bytes", 16 * 1024 * 1024), "source.max_file_bytes", maximum=1024 * 1024 * 1024),
        ))
    if not sources:
        sources = list(base.sources)
    retries = dispatch.get("retry_delays_seconds", list(base.retry_delays_seconds))
    if not isinstance(retries, list) or not retries or len(retries) > 32:
        raise ValueError("dispatch.retry_delays_seconds must contain 1..32 values")
    retry_delays = tuple(_positive(value, "dispatch.retry_delays_seconds", maximum=7 * 24 * 3600) for value in retries)
    return DispatcherConfig(
        config_path=base.config_path,
        state_dir=state_dir,
        runtime_dir=runtime_dir,
        database_path=database_path,
        socket_path=socket_path,
        timezone=str(core.get("timezone", base.timezone)).strip() or base.timezone,
        log_level=str(core.get("log_level", base.log_level)).strip().upper() or base.log_level,
        status_heartbeat_seconds=_positive(core.get("status_heartbeat_seconds", base.status_heartbeat_seconds), "core.status_heartbeat_seconds", maximum=3600),
        frame_limit_bytes=_positive(api.get("frame_limit_bytes", base.frame_limit_bytes), "api.frame_limit_bytes", maximum=64 * 1024 * 1024),
        collector_enabled=bool(collector.get("enabled", base.collector_enabled)),
        collector_interval_seconds=_positive(collector.get("interval_seconds", base.collector_interval_seconds), "collector.interval_seconds", maximum=24 * 3600),
        collector_scan_limit=_positive(collector.get("scan_limit", base.collector_scan_limit), "collector.scan_limit", maximum=10000),
        dispatch_enabled=bool(dispatch.get("enabled", base.dispatch_enabled)),
        dispatch_paused=bool(dispatch.get("paused", base.dispatch_paused)),
        dispatch_batch_size=_positive(dispatch.get("batch_size", base.dispatch_batch_size), "dispatch.batch_size", maximum=1000),
        claim_ttl_seconds=_positive(dispatch.get("claim_ttl_seconds", base.claim_ttl_seconds), "dispatch.claim_ttl_seconds", maximum=7 * 24 * 3600),
        retry_delays_seconds=retry_delays,
        max_attempts=_positive(dispatch.get("max_attempts", base.max_attempts), "dispatch.max_attempts", maximum=1000),
        completed_retention_days=_positive(retention.get("completed_days", base.completed_retention_days), "retention.completed_days", maximum=3650),
        audit_retention_days=_positive(retention.get("audit_days", base.audit_retention_days), "retention.audit_days", maximum=3650),
        sources=tuple(sources),
    )


def public_config(config: DispatcherConfig) -> dict[str, Any]:
    return {
        "config_path": str(config.config_path),
        "state_dir": str(config.state_dir),
        "runtime_dir": str(config.runtime_dir),
        "database_path": str(config.database_path),
        "socket_path": str(config.socket_path),
        "timezone": config.timezone,
        "log_level": config.log_level,
        "status_heartbeat_seconds": config.status_heartbeat_seconds,
        "frame_limit_bytes": config.frame_limit_bytes,
        "collector": {
            "enabled": config.collector_enabled,
            "interval_seconds": config.collector_interval_seconds,
            "scan_limit": config.collector_scan_limit,
        },
        "dispatch": {
            "enabled": config.dispatch_enabled,
            "paused": config.dispatch_paused,
            "batch_size": config.dispatch_batch_size,
            "claim_ttl_seconds": config.claim_ttl_seconds,
            "retry_delays_seconds": list(config.retry_delays_seconds),
            "max_attempts": config.max_attempts,
        },
        "retention": {
            "completed_days": config.completed_retention_days,
            "audit_days": config.audit_retention_days,
        },
        "sources": [
            {
                "name": source.name,
                "enabled": source.enabled,
                "roots": [str(root) for root in source.roots],
                "scan_limit": source.scan_limit,
                "max_file_bytes": source.max_file_bytes,
            }
            for source in config.sources
        ],
    }
