from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Any


CLASSIFICATION_SCHEMA_VERSION = 1
DEFAULT_MAX_JSONL_LINE_BYTES = 8 * 1024 * 1024
CURRENT_SOURCE_FAMILY = "codex_rollout_current"
LEGACY_SOURCE_FAMILY = "codex_rollout_legacy"
UNKNOWN_SOURCE_FAMILY = "unknown"


class HistoryKind(str, Enum):
    SUBAGENT_COMPLETION = "subagent_completion"
    INTERMEDIATE_UPDATE = "intermediate_update"
    TASK_COMPLETION = "task_completion"
    UNKNOWN = "unknown"


class ClassificationConfidence(str, Enum):
    AUTHORITATIVE = "authoritative"
    COMPATIBLE = "compatible"
    LEGACY = "legacy"
    AMBIGUOUS = "ambiguous"


class AgentContext(str, Enum):
    ROOT = "root"
    SUBAGENT = "subagent"
    UNKNOWN = "unknown"


@dataclass(frozen=True)
class ClassificationIssue:
    line_number: int
    code: str
    message: str
    source_ordinal: int | None = None

    def as_dict(self) -> dict[str, Any]:
        return {
            "line_number": self.line_number,
            "code": self.code,
            "message": self.message,
            "source_ordinal": self.source_ordinal,
        }


@dataclass(frozen=True)
class ClassifiedEvent:
    history_kind: HistoryKind
    confidence: ClassificationConfidence
    reason_code: str
    source_schema_family: str
    timestamp: str
    session_key: str
    turn_key: str
    parent_thread_key: str
    project_id: str
    project_label: str
    agent_context: AgentContext
    source_ordinal: int | None
    response_key: str
    text: str
    text_sha256: str
    dedupe_key: str
    event_id: str
    external_dispatchable: bool
    classification_schema_version: int = CLASSIFICATION_SCHEMA_VERSION

    def as_dict(self) -> dict[str, Any]:
        return {
            "classification_schema_version": self.classification_schema_version,
            "event_id": self.event_id,
            "dedupe_key": self.dedupe_key,
            "history_kind": self.history_kind.value,
            "classification_confidence": self.confidence.value,
            "classification_reason_code": self.reason_code,
            "source_schema_family": self.source_schema_family,
            "timestamp": self.timestamp,
            "session_key": self.session_key,
            "turn_key": self.turn_key,
            "parent_thread_key": self.parent_thread_key,
            "project_id": self.project_id,
            "project_label": self.project_label,
            "agent_context": self.agent_context.value,
            "source_ordinal": self.source_ordinal,
            "response_key": self.response_key,
            "text": self.text,
            "text_sha256": self.text_sha256,
            "external_dispatchable": self.external_dispatchable,
        }


@dataclass(frozen=True)
class ClassificationReport:
    events: tuple[ClassifiedEvent, ...]
    issues: tuple[ClassificationIssue, ...]
    records_seen: int
    records_ignored: int
    unknown_records: int

    def as_dict(self) -> dict[str, Any]:
        return {
            "events": [event.as_dict() for event in self.events],
            "issues": [issue.as_dict() for issue in self.issues],
            "records_seen": self.records_seen,
            "records_ignored": self.records_ignored,
            "unknown_records": self.unknown_records,
        }
