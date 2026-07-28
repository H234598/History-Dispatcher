from __future__ import annotations

import hashlib
import json
import re
import unicodedata
from dataclasses import dataclass, field
from enum import Enum
from typing import Any

from .classification_types import ClassifiedEvent, HistoryKind
from .delivery_state import TargetDeliveryState
from .schema_v3 import ROUTING_SCHEMA_VERSION
from .telegram_provider import (
    TELEGRAM_PROVIDER_SCHEMA_VERSION,
    TelegramDispatchProvider,
    TelegramTransportBinding,
)


ROUTE_PLANNER_VERSION = "history-dispatcher-route-planner-v1"
MAX_PROJECT_FILTER_ENTRIES = 200
MAX_PROJECT_FILTER_ENTRY_CHARS = 128
MAX_PROJECT_FILTER_BYTES = 16 * 1024
_PROJECT_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")


class RoutingPlanError(ValueError):
    pass


class ProjectFilterMode(str, Enum):
    BLACKLIST = "blacklist"
    WHITELIST = "whitelist"

    @classmethod
    def parse(cls, value: ProjectFilterMode | str) -> ProjectFilterMode:
        if isinstance(value, cls):
            return value
        normalized = unicodedata.normalize("NFC", str(value or "").strip()).casefold()
        try:
            return cls(normalized)
        except ValueError as exc:
            raise RoutingPlanError("unsupported project filter mode") from exc


def normalize_project_ids(values: tuple[str, ...] | list[str]) -> tuple[str, ...]:
    if isinstance(values, (str, bytes, bytearray)):
        raise RoutingPlanError("project_ids must be a sequence")
    normalized: list[str] = []
    seen: set[str] = set()
    total_bytes = 0
    for value in values:
        if not isinstance(value, str):
            raise RoutingPlanError("project_ids must contain strings")
        project_id = unicodedata.normalize("NFC", value.strip())
        if not project_id:
            raise RoutingPlanError("project_id must not be empty")
        if len(project_id) > MAX_PROJECT_FILTER_ENTRY_CHARS:
            raise RoutingPlanError("project_id exceeds the maximum length")
        if not _PROJECT_ID_RE.fullmatch(project_id):
            raise RoutingPlanError("project_id contains unsupported characters")
        if project_id in seen:
            continue
        seen.add(project_id)
        normalized.append(project_id)
        total_bytes += len(project_id.encode("utf-8")) + 1
        if len(normalized) > MAX_PROJECT_FILTER_ENTRIES:
            raise RoutingPlanError("too many project filter entries")
        if total_bytes > MAX_PROJECT_FILTER_BYTES:
            raise RoutingPlanError("project filter exceeds the byte limit")
    return tuple(normalized)


@dataclass(frozen=True)
class LocalArchiveRoutingPolicy:
    include_subagent_completion: bool = False
    include_intermediate_update: bool = False


@dataclass(frozen=True)
class TelegramRoutingPolicy:
    include_subagent_completion: bool = False
    include_intermediate_update: bool = False
    include_task_completion: bool = False
    project_filter_mode: ProjectFilterMode | str = ProjectFilterMode.BLACKLIST
    project_ids: tuple[str, ...] = ()
    binding: TelegramTransportBinding | None = None

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "project_filter_mode",
            ProjectFilterMode.parse(self.project_filter_mode),
        )
        object.__setattr__(
            self,
            "project_ids",
            normalize_project_ids(self.project_ids),
        )


@dataclass(frozen=True)
class VaultRoutingPolicy:
    include_subagent_completion: bool = False
    include_intermediate_update: bool = False
    include_task_completion: bool = False


@dataclass(frozen=True)
class RoutingPolicy:
    local_archive: LocalArchiveRoutingPolicy = field(
        default_factory=LocalArchiveRoutingPolicy
    )
    telegram: TelegramRoutingPolicy = field(default_factory=TelegramRoutingPolicy)
    vault: VaultRoutingPolicy = field(default_factory=VaultRoutingPolicy)


@dataclass(frozen=True)
class RouteTargetDecision:
    target_id: str
    initial_state: TargetDeliveryState | str
    reason_code: str
    provider_id: str
    provider_schema_version: int
    binding: dict[str, Any]

    def __post_init__(self) -> None:
        target_id = str(self.target_id or "").strip().casefold()
        if target_id not in {"local_archive", "telegram", "vault"}:
            raise RoutingPlanError("unsupported route target")
        state = TargetDeliveryState(self.initial_state)
        if state not in {
            TargetDeliveryState.PENDING,
            TargetDeliveryState.SKIPPED_DISABLED,
            TargetDeliveryState.SKIPPED_FILTERED,
            TargetDeliveryState.SKIPPED_UNKNOWN,
        }:
            raise RoutingPlanError("invalid initial route target state")
        reason_code = str(self.reason_code or "").strip().casefold()
        if state is TargetDeliveryState.PENDING and reason_code:
            raise RoutingPlanError("pending target decisions must not have a reason")
        if state is not TargetDeliveryState.PENDING and not reason_code:
            raise RoutingPlanError("skipped target decisions require a reason")
        provider_id = str(self.provider_id or "").strip().casefold()
        if target_id == "telegram":
            TelegramDispatchProvider.parse(provider_id)
        elif provider_id != target_id:
            raise RoutingPlanError("local target provider must match target_id")
        if not isinstance(self.binding, dict):
            raise RoutingPlanError("target binding must be a JSON object")
        rendered = json.dumps(
            self.binding,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        )
        if len(rendered.encode("utf-8")) > 16 * 1024:
            raise RoutingPlanError("target binding exceeds the byte limit")
        object.__setattr__(self, "target_id", target_id)
        object.__setattr__(self, "initial_state", state)
        object.__setattr__(self, "reason_code", reason_code)
        object.__setattr__(self, "provider_id", provider_id)
        object.__setattr__(self, "binding", json.loads(rendered))

    @property
    def binding_json(self) -> str:
        return json.dumps(
            self.binding,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        )

    @property
    def binding_hash(self) -> str:
        return hashlib.sha256(self.binding_json.encode("utf-8")).hexdigest()

    def as_dict(self) -> dict[str, Any]:
        return {
            "target_id": self.target_id,
            "initial_state": self.initial_state.value,
            "reason_code": self.reason_code,
            "provider_id": self.provider_id,
            "provider_schema_version": int(self.provider_schema_version),
            "binding": self.binding,
        }


@dataclass(frozen=True)
class RoutePlan:
    event_id: str
    config_revision: str
    targets: tuple[RouteTargetDecision, ...]
    routing_schema_version: int = ROUTING_SCHEMA_VERSION
    planner_version: str = ROUTE_PLANNER_VERSION

    def __post_init__(self) -> None:
        event_id = str(self.event_id or "").strip()
        config_revision = str(self.config_revision or "").strip()
        if not event_id or len(event_id) > 160:
            raise RoutingPlanError("event_id is missing or too long")
        if not config_revision or len(config_revision) > 160:
            raise RoutingPlanError("config_revision is missing or too long")
        if int(self.routing_schema_version) != ROUTING_SCHEMA_VERSION:
            raise RoutingPlanError("unsupported routing schema version")
        if not self.targets:
            raise RoutingPlanError("route plan must contain targets")
        ordered = tuple(sorted(self.targets, key=lambda target: target.target_id))
        target_ids = [target.target_id for target in ordered]
        if len(target_ids) != len(set(target_ids)):
            raise RoutingPlanError("route plan contains duplicate targets")
        object.__setattr__(self, "event_id", event_id)
        object.__setattr__(self, "config_revision", config_revision)
        object.__setattr__(self, "targets", ordered)

    def as_dict(self) -> dict[str, Any]:
        return {
            "event_id": self.event_id,
            "config_revision": self.config_revision,
            "routing_schema_version": self.routing_schema_version,
            "planner_version": self.planner_version,
            "targets": [target.as_dict() for target in self.targets],
        }

    @property
    def plan_hash(self) -> str:
        encoded = json.dumps(
            self.as_dict(),
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        ).encode("utf-8")
        return hashlib.sha256(encoded).hexdigest()


class RoutePlanner:
    def __init__(self, policy: RoutingPolicy) -> None:
        self.policy = policy

    def plan(self, event: ClassifiedEvent, *, config_revision: str) -> RoutePlan:
        return RoutePlan(
            event_id=event.event_id,
            config_revision=config_revision,
            targets=(
                self._local_archive_decision(event),
                self._telegram_decision(event),
                self._vault_decision(event),
            ),
        )

    @staticmethod
    def _local_binding() -> dict[str, Any]:
        return {"schema_version": 1, "provider": "local_archive"}

    @staticmethod
    def _vault_binding() -> dict[str, Any]:
        return {"schema_version": 1, "provider": "vault"}

    def _local_archive_decision(self, event: ClassifiedEvent) -> RouteTargetDecision:
        enabled = (
            event.history_kind is HistoryKind.SUBAGENT_COMPLETION
            and self.policy.local_archive.include_subagent_completion
        ) or (
            event.history_kind is HistoryKind.INTERMEDIATE_UPDATE
            and self.policy.local_archive.include_intermediate_update
        )
        if event.history_kind is HistoryKind.UNKNOWN:
            return self._skipped(
                "local_archive",
                TargetDeliveryState.SKIPPED_UNKNOWN,
                "unknown_history_kind",
                "local_archive",
                1,
                self._local_binding(),
            )
        if event.history_kind is HistoryKind.TASK_COMPLETION:
            return self._skipped(
                "local_archive",
                TargetDeliveryState.SKIPPED_DISABLED,
                "task_completion_retained_in_operational_database",
                "local_archive",
                1,
                self._local_binding(),
            )
        if not enabled:
            return self._skipped(
                "local_archive",
                TargetDeliveryState.SKIPPED_DISABLED,
                "history_kind_disabled",
                "local_archive",
                1,
                self._local_binding(),
            )
        return self._pending("local_archive", "local_archive", 1, self._local_binding())

    def _telegram_decision(self, event: ClassifiedEvent) -> RouteTargetDecision:
        binding = self.policy.telegram.binding
        if binding is None:
            fragment = {
                "schema_version": TELEGRAM_PROVIDER_SCHEMA_VERSION,
                "provider": "teebotus",
                "configured": False,
            }
            return self._skipped(
                "telegram",
                TargetDeliveryState.SKIPPED_UNKNOWN,
                "telegram_provider_unconfigured",
                "teebotus",
                TELEGRAM_PROVIDER_SCHEMA_VERSION,
                fragment,
            )
        fragment = binding.as_route_plan_fragment()
        provider_id = binding.provider.value
        if not event.external_dispatchable or event.history_kind is HistoryKind.UNKNOWN:
            return self._skipped(
                "telegram",
                TargetDeliveryState.SKIPPED_UNKNOWN,
                "event_not_external_dispatchable",
                provider_id,
                binding.provider_schema_version,
                fragment,
            )
        enabled = {
            HistoryKind.SUBAGENT_COMPLETION: self.policy.telegram.include_subagent_completion,
            HistoryKind.INTERMEDIATE_UPDATE: self.policy.telegram.include_intermediate_update,
            HistoryKind.TASK_COMPLETION: self.policy.telegram.include_task_completion,
        }.get(event.history_kind, False)
        if not enabled:
            return self._skipped(
                "telegram",
                TargetDeliveryState.SKIPPED_DISABLED,
                "history_kind_disabled",
                provider_id,
                binding.provider_schema_version,
                fragment,
            )
        if event.project_id == "proj_unknown" or event.project_id.endswith("_unknown"):
            return self._skipped(
                "telegram",
                TargetDeliveryState.SKIPPED_UNKNOWN,
                "project_unknown",
                provider_id,
                binding.provider_schema_version,
                fragment,
            )
        listed = event.project_id in self.policy.telegram.project_ids
        filtered = (
            self.policy.telegram.project_filter_mode is ProjectFilterMode.BLACKLIST
            and listed
        ) or (
            self.policy.telegram.project_filter_mode is ProjectFilterMode.WHITELIST
            and not listed
        )
        if filtered:
            return self._skipped(
                "telegram",
                TargetDeliveryState.SKIPPED_FILTERED,
                "project_filtered",
                provider_id,
                binding.provider_schema_version,
                fragment,
            )
        return self._pending(
            "telegram",
            provider_id,
            binding.provider_schema_version,
            fragment,
        )

    def _vault_decision(self, event: ClassifiedEvent) -> RouteTargetDecision:
        if not event.external_dispatchable or event.history_kind is HistoryKind.UNKNOWN:
            return self._skipped(
                "vault",
                TargetDeliveryState.SKIPPED_UNKNOWN,
                "event_not_external_dispatchable",
                "vault",
                1,
                self._vault_binding(),
            )
        enabled = {
            HistoryKind.SUBAGENT_COMPLETION: self.policy.vault.include_subagent_completion,
            HistoryKind.INTERMEDIATE_UPDATE: self.policy.vault.include_intermediate_update,
            HistoryKind.TASK_COMPLETION: self.policy.vault.include_task_completion,
        }.get(event.history_kind, False)
        if not enabled:
            return self._skipped(
                "vault",
                TargetDeliveryState.SKIPPED_DISABLED,
                "history_kind_disabled",
                "vault",
                1,
                self._vault_binding(),
            )
        return self._pending("vault", "vault", 1, self._vault_binding())

    @staticmethod
    def _pending(
        target_id: str,
        provider_id: str,
        provider_schema_version: int,
        binding: dict[str, Any],
    ) -> RouteTargetDecision:
        return RouteTargetDecision(
            target_id=target_id,
            initial_state=TargetDeliveryState.PENDING,
            reason_code="",
            provider_id=provider_id,
            provider_schema_version=provider_schema_version,
            binding=binding,
        )

    @staticmethod
    def _skipped(
        target_id: str,
        state: TargetDeliveryState,
        reason_code: str,
        provider_id: str,
        provider_schema_version: int,
        binding: dict[str, Any],
    ) -> RouteTargetDecision:
        return RouteTargetDecision(
            target_id=target_id,
            initial_state=state,
            reason_code=reason_code,
            provider_id=provider_id,
            provider_schema_version=provider_schema_version,
            binding=binding,
        )
