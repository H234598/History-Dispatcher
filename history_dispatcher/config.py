from __future__ import annotations

import hashlib
import json
import os
import re
import tomllib
import unicodedata
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Any

from .telegram_provider import TelegramDispatchProvider


DEFAULT_SCAN_ROOTS = (
    Path("~/.codex/sessions").expanduser(),
    Path.home() / ".codex-agents/*/sessions",
)
MAX_TELEGRAM_RECIPIENT_PROFILES = 32
_OPAQUE_PROFILE_RE = re.compile(r"^[a-z][a-z0-9_.-]{0,95}$")


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
    if "\x00" in text:
        raise ValueError(f"{name} contains NUL")
    path = Path(text).expanduser()
    if not path.is_absolute():
        raise ValueError(f"{name} must be absolute")
    if any(part == ".." for part in path.parts):
        raise ValueError(f"{name} contains a parent traversal")
    return path


def _opaque_profile(
    value: object,
    name: str,
    *,
    allow_empty: bool,
) -> str:
    if value in (None, "") and allow_empty:
        return ""
    if not isinstance(value, str):
        raise ValueError(f"{name} must be an opaque profile name")
    normalized = unicodedata.normalize("NFC", value.strip()).casefold()
    if not normalized:
        if allow_empty:
            return ""
        raise ValueError(f"{name} must not be empty")
    if any(ord(character) < 0x20 or ord(character) == 0x7F for character in normalized):
        raise ValueError(f"{name} contains control characters")
    if not _OPAQUE_PROFILE_RE.fullmatch(normalized):
        raise ValueError(f"{name} is invalid")
    return normalized


def _recipient_profiles(value: object) -> tuple[str, ...]:
    if value in (None, ()):
        return ()
    if not isinstance(value, list | tuple) or isinstance(value, (str, bytes, bytearray)):
        raise ValueError("routing.telegram.recipient_refs must be an array")
    profiles: list[str] = []
    seen: set[str] = set()
    for raw_profile in value:
        profile = _opaque_profile(
            raw_profile,
            "routing.telegram.recipient_refs",
            allow_empty=False,
        )
        if profile in seen:
            continue
        seen.add(profile)
        profiles.append(profile)
        if len(profiles) > MAX_TELEGRAM_RECIPIENT_PROFILES:
            raise ValueError(
                "routing.telegram.recipient_refs contains too many recipient profiles"
            )
    return tuple(profiles)


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
    telegram_provider: TelegramDispatchProvider = TelegramDispatchProvider.TEEBOTUS
    telegram_credential_ref: str = ""
    telegram_recipient_refs: tuple[str, ...] = ()
    sources: tuple[SourceConfig, ...] = field(default_factory=tuple)

    @property
    def snapshot_path(self) -> Path:
        return self.runtime_dir / "status-v1.json"


def default_config(path: Path | None = None) -> DispatcherConfig:
    home = Path.home()
    state = (
        Path(os.environ.get("XDG_STATE_HOME", home / ".local/state"))
        / "history-dispatcher"
    )
    runtime = (
        Path(os.environ.get("XDG_RUNTIME_DIR", f"/run/user/{os.getuid()}"))
        / "history-dispatcher"
    )
    config_path = path or Path(
        os.environ.get(
            "HISTORY_DISPATCHER_CONFIG",
            home / ".config/history-dispatcher/config.toml",
        )
    )
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
    routing = raw.get("routing", {})
    applet_policy = raw.get("applet_policy", {})
    allowed_root = {
        "core",
        "api",
        "storage",
        "collector",
        "dispatch",
        "retention",
        "sources",
        "routing",
        "applet_policy",
    }
    unknown_root = set(raw) - allowed_root
    if unknown_root:
        raise ValueError(
            "unknown config sections: " + ", ".join(sorted(unknown_root))
        )
    if not all(
        isinstance(section, dict)
        for section in (core, api, storage, collector, dispatch, retention, routing)
    ):
        raise ValueError("config sections must be tables")
    if not isinstance(applet_policy, dict):
        raise ValueError("applet_policy must be a table")
    section_keys = {
        "core": {"timezone", "log_level", "status_heartbeat_seconds"},
        "api": {"runtime_dir", "socket_path", "frame_limit_bytes"},
        "storage": {"state_dir", "database_path"},
        "collector": {"enabled", "interval_seconds", "scan_limit"},
        "dispatch": {
            "enabled",
            "paused",
            "batch_size",
            "claim_ttl_seconds",
            "retry_delays_seconds",
            "max_attempts",
        },
        "retention": {"completed_days", "audit_days"},
        "applet_policy": {
            "allow_service_actions",
            "allow_collect",
            "allow_retry",
            "allow_delete",
        },
    }
    for section_name, section in (
        ("core", core),
        ("api", api),
        ("storage", storage),
        ("collector", collector),
        ("dispatch", dispatch),
        ("retention", retention),
        ("applet_policy", applet_policy),
    ):
        unknown = set(section) - section_keys[section_name]
        if unknown:
            raise ValueError(
                f"unknown config keys in [{section_name}]: "
                + ", ".join(sorted(unknown))
            )

    unknown_routing = set(routing) - {"telegram"}
    if unknown_routing:
        raise ValueError(
            "unknown config routing tables: "
            + ", ".join(sorted(unknown_routing))
        )
    telegram = routing.get("telegram", {})
    if not isinstance(telegram, dict):
        raise ValueError("routing.telegram must be a table")
    unknown_telegram = set(telegram) - {
        "provider",
        "credential_ref",
        "recipient_refs",
    }
    if unknown_telegram:
        raise ValueError(
            "unknown config keys in [routing.telegram]: "
            + ", ".join(sorted(unknown_telegram))
        )
    try:
        telegram_provider = TelegramDispatchProvider.parse(
            telegram.get("provider", base.telegram_provider.value)
        )
    except ValueError as exc:
        raise ValueError("unsupported Telegram dispatch provider") from exc
    telegram_credential_ref = _opaque_profile(
        telegram.get("credential_ref", base.telegram_credential_ref),
        "routing.telegram.credential_ref",
        allow_empty=True,
    )
    telegram_recipient_refs = _recipient_profiles(
        telegram.get("recipient_refs", list(base.telegram_recipient_refs))
    )
    if telegram_provider is TelegramDispatchProvider.TEEBOTUS and (
        telegram_credential_ref or telegram_recipient_refs
    ):
        raise ValueError(
            "native Telegram credential and recipient profiles require "
            "provider history_dispatcher"
        )

    sources_table = raw.get("sources", {})
    if not isinstance(sources_table, dict):
        raise ValueError("sources must be a table")
    unknown_sources = set(sources_table) - {"codex"}
    if unknown_sources:
        raise ValueError(
            "unknown config source tables: "
            + ", ".join(sorted(unknown_sources))
        )
    state_dir = _path(
        storage.get("state_dir", str(base.state_dir)),
        "storage.state_dir",
    )
    runtime_dir = _path(
        api.get("runtime_dir", str(base.runtime_dir)),
        "api.runtime_dir",
    )
    database_path = _path(
        storage.get("database_path", str(state_dir / "history.sqlite3")),
        "storage.database_path",
    )
    socket_path = _path(
        api.get("socket_path", str(runtime_dir / "control.sock")),
        "api.socket_path",
    )
    raw_sources = sources_table.get("codex", [])
    if isinstance(raw_sources, dict):
        raw_sources = [raw_sources]
    if not isinstance(raw_sources, list):
        raise ValueError("sources.codex must be an array of tables")
    sources: list[SourceConfig] = []
    for index, item in enumerate(raw_sources):
        if not isinstance(item, dict):
            raise ValueError(f"sources.codex[{index}] must be a table")
        unknown_source_keys = set(item) - {
            "name",
            "enabled",
            "roots",
            "scan_limit",
            "max_file_bytes",
        }
        if unknown_source_keys:
            raise ValueError(
                f"unknown keys in sources.codex[{index}]: "
                + ", ".join(sorted(unknown_source_keys))
            )
        name = str(item.get("name", "codex")).strip()
        if not name or len(name) > 96:
            raise ValueError(f"sources.codex[{index}].name is invalid")
        roots_raw = item.get(
            "roots",
            [str(root) for root in DEFAULT_SCAN_ROOTS],
        )
        if not isinstance(roots_raw, list) or not roots_raw:
            raise ValueError(
                f"sources.codex[{index}].roots must be a non-empty array"
            )
        roots = tuple(
            _path(root, f"sources.codex[{index}].roots")
            for root in roots_raw
        )
        sources.append(
            SourceConfig(
                name=name,
                enabled=bool(item.get("enabled", True)),
                roots=roots,
                scan_limit=_positive(
                    item.get("scan_limit", 25),
                    "source.scan_limit",
                    maximum=10000,
                ),
                max_file_bytes=_positive(
                    item.get("max_file_bytes", 16 * 1024 * 1024),
                    "source.max_file_bytes",
                    maximum=1024 * 1024 * 1024,
                ),
            )
        )
    if not sources:
        sources = list(base.sources)
    retries = dispatch.get(
        "retry_delays_seconds",
        list(base.retry_delays_seconds),
    )
    if not isinstance(retries, list) or not retries or len(retries) > 32:
        raise ValueError(
            "dispatch.retry_delays_seconds must contain 1..32 values"
        )
    retry_delays = tuple(
        _positive(
            value,
            "dispatch.retry_delays_seconds",
            maximum=7 * 24 * 3600,
        )
        for value in retries
    )
    return DispatcherConfig(
        config_path=base.config_path,
        state_dir=state_dir,
        runtime_dir=runtime_dir,
        database_path=database_path,
        socket_path=socket_path,
        timezone=str(core.get("timezone", base.timezone)).strip() or base.timezone,
        log_level=(
            str(core.get("log_level", base.log_level)).strip().upper()
            or base.log_level
        ),
        status_heartbeat_seconds=_positive(
            core.get(
                "status_heartbeat_seconds",
                base.status_heartbeat_seconds,
            ),
            "core.status_heartbeat_seconds",
            maximum=3600,
        ),
        frame_limit_bytes=_positive(
            api.get("frame_limit_bytes", base.frame_limit_bytes),
            "api.frame_limit_bytes",
            maximum=64 * 1024 * 1024,
        ),
        collector_enabled=bool(
            collector.get("enabled", base.collector_enabled)
        ),
        collector_interval_seconds=_positive(
            collector.get(
                "interval_seconds",
                base.collector_interval_seconds,
            ),
            "collector.interval_seconds",
            maximum=24 * 3600,
        ),
        collector_scan_limit=_positive(
            collector.get("scan_limit", base.collector_scan_limit),
            "collector.scan_limit",
            maximum=10000,
        ),
        dispatch_enabled=bool(dispatch.get("enabled", base.dispatch_enabled)),
        dispatch_paused=bool(dispatch.get("paused", base.dispatch_paused)),
        dispatch_batch_size=_positive(
            dispatch.get("batch_size", base.dispatch_batch_size),
            "dispatch.batch_size",
            maximum=1000,
        ),
        claim_ttl_seconds=_positive(
            dispatch.get("claim_ttl_seconds", base.claim_ttl_seconds),
            "dispatch.claim_ttl_seconds",
            maximum=7 * 24 * 3600,
        ),
        retry_delays_seconds=retry_delays,
        max_attempts=_positive(
            dispatch.get("max_attempts", base.max_attempts),
            "dispatch.max_attempts",
            maximum=1000,
        ),
        completed_retention_days=_positive(
            retention.get(
                "completed_days",
                base.completed_retention_days,
            ),
            "retention.completed_days",
            maximum=3650,
        ),
        audit_retention_days=_positive(
            retention.get("audit_days", base.audit_retention_days),
            "retention.audit_days",
            maximum=3650,
        ),
        telegram_provider=telegram_provider,
        telegram_credential_ref=telegram_credential_ref,
        telegram_recipient_refs=telegram_recipient_refs,
        sources=tuple(sources),
    )


def config_revision(config: DispatcherConfig) -> str:
    """Return a stable revision for optimistic config updates."""

    value = public_config(config, include_revision=False)
    encoded = json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def public_config(
    config: DispatcherConfig,
    *,
    include_revision: bool = True,
) -> dict[str, Any]:
    value = {
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
        "routing": {
            "telegram": {
                "provider": config.telegram_provider.value,
                "credential_ref": config.telegram_credential_ref,
                "recipient_refs": list(config.telegram_recipient_refs),
            }
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
    value["config_revision"] = (
        config_revision(config) if include_revision else ""
    )
    return value


SAFE_CONFIG_KEYS = frozenset(
    {
        "log_level",
        "status_heartbeat_seconds",
        "collector_enabled",
        "collector_interval_seconds",
        "collector_scan_limit",
        "dispatch_enabled",
        "dispatch_paused",
        "dispatch_batch_size",
        "claim_ttl_seconds",
        "max_attempts",
        "completed_retention_days",
        "audit_retention_days",
    }
)


def apply_safe_values(
    config: DispatcherConfig,
    values: dict[str, Any],
) -> DispatcherConfig:
    unknown = set(values) - SAFE_CONFIG_KEYS
    if unknown:
        raise ValueError(
            "unsupported config keys: " + ", ".join(sorted(unknown))
        )
    changes: dict[str, Any] = {}
    if "log_level" in values:
        level = str(values["log_level"]).strip().upper()
        if level not in {"DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"}:
            raise ValueError("log_level is invalid")
        changes["log_level"] = level
    if "status_heartbeat_seconds" in values:
        changes["status_heartbeat_seconds"] = _positive(
            values["status_heartbeat_seconds"],
            "status_heartbeat_seconds",
            maximum=3600,
        )
    for key in ("collector_enabled", "dispatch_enabled", "dispatch_paused"):
        if key in values:
            if not isinstance(values[key], bool):
                raise ValueError(f"{key} must be boolean")
            changes[key] = values[key]
    for key, maximum in (
        ("collector_interval_seconds", 24 * 3600),
        ("collector_scan_limit", 10000),
        ("dispatch_batch_size", 1000),
        ("claim_ttl_seconds", 7 * 24 * 3600),
        ("max_attempts", 1000),
        ("completed_retention_days", 3650),
        ("audit_retention_days", 3650),
    ):
        if key in values:
            changes[key] = _positive(values[key], key, maximum=maximum)
    return replace(config, **changes)


def write_config(config: DispatcherConfig) -> None:
    config.config_path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    lines = [
        "[core]",
        f"timezone = {json.dumps(config.timezone)}",
        f"log_level = {json.dumps(config.log_level)}",
        f"status_heartbeat_seconds = {config.status_heartbeat_seconds}",
        "",
        "[api]",
        f"runtime_dir = {json.dumps(str(config.runtime_dir))}",
        f"socket_path = {json.dumps(str(config.socket_path))}",
        f"frame_limit_bytes = {config.frame_limit_bytes}",
        "",
        "[storage]",
        f"state_dir = {json.dumps(str(config.state_dir))}",
        f"database_path = {json.dumps(str(config.database_path))}",
        "",
        "[collector]",
        f"enabled = {str(config.collector_enabled).lower()}",
        f"interval_seconds = {config.collector_interval_seconds}",
        f"scan_limit = {config.collector_scan_limit}",
        "",
        "[dispatch]",
        f"enabled = {str(config.dispatch_enabled).lower()}",
        f"paused = {str(config.dispatch_paused).lower()}",
        f"batch_size = {config.dispatch_batch_size}",
        f"claim_ttl_seconds = {config.claim_ttl_seconds}",
        (
            "retry_delays_seconds = ["
            + ", ".join(str(value) for value in config.retry_delays_seconds)
            + "]"
        ),
        f"max_attempts = {config.max_attempts}",
        "",
        "[routing.telegram]",
        f"provider = {json.dumps(config.telegram_provider.value)}",
        f"credential_ref = {json.dumps(config.telegram_credential_ref)}",
        (
            "recipient_refs = ["
            + ", ".join(
                json.dumps(profile)
                for profile in config.telegram_recipient_refs
            )
            + "]"
        ),
        "",
        "[retention]",
        f"completed_days = {config.completed_retention_days}",
        f"audit_days = {config.audit_retention_days}",
    ]
    for source in config.sources:
        lines.extend(
            [
                "",
                "[[sources.codex]]",
                f"name = {json.dumps(source.name)}",
                f"enabled = {str(source.enabled).lower()}",
                (
                    "roots = ["
                    + ", ".join(
                        json.dumps(str(root)) for root in source.roots
                    )
                    + "]"
                ),
                f"scan_limit = {source.scan_limit}",
                f"max_file_bytes = {source.max_file_bytes}",
            ]
        )
    temporary = config.config_path.with_name(
        f".{config.config_path.name}.{os.getpid()}.tmp"
    )
    with temporary.open("w", encoding="utf-8") as handle:
        handle.write("\n".join(lines) + "\n")
        handle.flush()
        os.fsync(handle.fileno())
    os.chmod(temporary, 0o600)
    if config.config_path.exists():
        backup = config.config_path.with_name(f"{config.config_path.name}.bak")
        with config.config_path.open("rb") as source, backup.open("wb") as target:
            target.write(source.read())
            target.flush()
            os.fsync(target.fileno())
        os.chmod(backup, 0o600)
    os.replace(temporary, config.config_path)
