from __future__ import annotations

import hashlib
import json
from typing import Any, Iterable, Mapping

from .classification_current import ClassificationHandlersMixin
from .classification_support import (
    _SessionState,
    _can_dispatch,
    _event_key,
    _normalized_string,
    _optional_int,
    _reason,
    _strict_json_loads,
)
from .classification_types import (
    CLASSIFICATION_SCHEMA_VERSION,
    CURRENT_SOURCE_FAMILY,
    DEFAULT_MAX_JSONL_LINE_BYTES,
    LEGACY_SOURCE_FAMILY,
    UNKNOWN_SOURCE_FAMILY,
    AgentContext,
    ClassifiedEvent,
    ClassificationConfidence,
    ClassificationIssue,
    ClassificationReport,
    HistoryKind,
)
from .redaction import (
    MAX_VISIBLE_TEXT_BYTES,
    MAX_VISIBLE_TEXT_CHARS,
    redact_text,
    stable_opaque_id,
    visible_output_text,
)


class CodexRolloutClassifier(ClassificationHandlersMixin):
    def __init__(
        self,
        *,
        max_jsonl_line_bytes: int = DEFAULT_MAX_JSONL_LINE_BYTES,
        max_visible_text_bytes: int = MAX_VISIBLE_TEXT_BYTES,
    ) -> None:
        self.max_jsonl_line_bytes = max(256, int(max_jsonl_line_bytes))
        self.max_visible_text_bytes = max(128, min(int(max_visible_text_bytes), MAX_VISIBLE_TEXT_BYTES))
        self.max_visible_text_chars = min(self.max_visible_text_bytes, MAX_VISIBLE_TEXT_CHARS)

    def classify_lines(
        self,
        lines: Iterable[str | bytes],
        *,
        source_quiescent: bool = False,
    ) -> ClassificationReport:
        state = _SessionState()
        events: list[ClassifiedEvent] = []
        issues: list[ClassificationIssue] = []
        seen_dedupe: set[str] = set()
        records_seen = 0
        records_ignored = 0
        unknown_records = 0

        def add_event(event: ClassifiedEvent) -> None:
            if event.dedupe_key in seen_dedupe:
                return
            seen_dedupe.add(event.dedupe_key)
            events.append(event)

        for line_number, raw_line in enumerate(lines, start=1):
            if isinstance(raw_line, bytes):
                raw_bytes = raw_line
                try:
                    text_line = raw_line.decode("utf-8")
                except UnicodeDecodeError:
                    issues.append(
                        ClassificationIssue(line_number, "invalid_utf8", "JSONL-Zeile ist nicht UTF-8")
                    )
                    continue
            else:
                text_line = str(raw_line)
                raw_bytes = text_line.encode("utf-8")
            if not text_line.strip():
                continue
            records_seen += 1
            if len(raw_bytes) > self.max_jsonl_line_bytes:
                issues.append(
                    ClassificationIssue(
                        line_number,
                        "line_too_large",
                        f"JSONL-Zeile überschreitet {self.max_jsonl_line_bytes} Byte",
                    )
                )
                continue
            try:
                record = _strict_json_loads(text_line)
            except (json.JSONDecodeError, ValueError):
                issues.append(
                    ClassificationIssue(line_number, "invalid_json", "JSONL-Zeile ist kein eindeutiges gültiges JSON")
                )
                continue
            if not isinstance(record, dict):
                issues.append(
                    ClassificationIssue(line_number, "record_not_object", "Rollout-Datensatz muss ein Objekt sein")
                )
                continue
            top_type = _normalized_string(record.get("type"), limit=96).lower()
            payload = record.get("payload", {})
            ordinal = _optional_int(record.get("ordinal"))
            timestamp = _normalized_string(record.get("timestamp"), limit=64)
            if not top_type or not isinstance(payload, dict):
                issues.append(
                    ClassificationIssue(
                        line_number,
                        "invalid_rollout_envelope",
                        "Rollout-Datensatz benötigt type und ein payload-Objekt",
                        ordinal,
                    )
                )
                continue

            if top_type == "session_meta":
                self._consume_session_meta(state, payload)
                records_ignored += 1
                continue
            if top_type == "turn_context":
                if not self._is_inherited_subagent_record(state, ordinal):
                    turn_id = _normalized_string(payload.get("turn_id"), limit=256)
                    if turn_id:
                        state.current_turn_id = turn_id
                records_ignored += 1
                continue
            if top_type == "response_item":
                emitted, ignored, response_issues = self._consume_response_item(
                    state,
                    payload,
                    timestamp=timestamp,
                    ordinal=ordinal,
                    line_number=line_number,
                )
                issues.extend(response_issues)
                for event in emitted:
                    add_event(event)
                records_ignored += int(ignored)
                continue
            if top_type == "event_msg":
                emitted, ignored, event_issues = self._consume_event_message(
                    state,
                    payload,
                    timestamp=timestamp,
                    ordinal=ordinal,
                    line_number=line_number,
                )
                issues.extend(event_issues)
                for event in emitted:
                    add_event(event)
                records_ignored += int(ignored)
                continue
            if top_type == "event":
                event = self._consume_legacy_event(
                    state,
                    payload,
                    timestamp=timestamp,
                    ordinal=ordinal,
                )
                if event is None:
                    records_ignored += 1
                else:
                    add_event(event)
                continue

            unknown_records += 1
            add_event(
                self._build_event(
                    state=state,
                    kind=HistoryKind.UNKNOWN,
                    confidence=ClassificationConfidence.AMBIGUOUS,
                    reason_code="unknown_rollout_type",
                    source_family=UNKNOWN_SOURCE_FAMILY,
                    timestamp=timestamp,
                    turn_id=state.current_turn_id,
                    ordinal=ordinal,
                    response_identity=(
                        f"unknown:{top_type}:"
                        f"{ordinal if ordinal is not None else hashlib.sha256(json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(',', ':'), default=str).encode('utf-8')).hexdigest()[:16]}"
                    ),
                    text="",
                    external_dispatchable=False,
                )
            )

        if source_quiescent:
            for candidate in tuple(state.final_candidates.values()):
                kind = (
                    HistoryKind.SUBAGENT_COMPLETION
                    if state.agent_context is AgentContext.SUBAGENT
                    else HistoryKind.TASK_COMPLETION
                    if state.agent_context is AgentContext.ROOT
                    else HistoryKind.UNKNOWN
                )
                add_event(
                    self._build_event(
                        state=state,
                        kind=kind,
                        confidence=(
                            ClassificationConfidence.COMPATIBLE
                            if kind is not HistoryKind.UNKNOWN
                            else ClassificationConfidence.AMBIGUOUS
                        ),
                        reason_code="quiescent_final_answer",
                        source_family=CURRENT_SOURCE_FAMILY,
                        timestamp=candidate.timestamp,
                        turn_id=candidate.turn_id,
                        ordinal=candidate.ordinal,
                        response_identity=candidate.response_id or str(candidate.ordinal or "quiescent"),
                        text=candidate.text,
                        external_dispatchable=_can_dispatch(state, kind),
                    )
                )

        return ClassificationReport(
            events=tuple(events),
            issues=tuple(issues),
            records_seen=records_seen,
            records_ignored=records_ignored,
            unknown_records=unknown_records,
        )

    def _consume_legacy_event(
        self,
        state: _SessionState,
        payload: Mapping[str, Any],
        *,
        timestamp: str,
        ordinal: int | None,
    ) -> ClassifiedEvent | None:
        role = _normalized_string(payload.get("role"), limit=32).lower()
        phase = _normalized_string(payload.get("phase"), limit=64).lower()
        if role != "assistant" or phase not in {"final", "final_answer"}:
            return None
        content = payload.get("content")
        if isinstance(content, list):
            text = visible_output_text(
                content,
                max_chars=self.max_visible_text_chars,
                max_bytes=self.max_visible_text_bytes,
            )
        else:
            text = redact_text(
                content,
                max_chars=self.max_visible_text_chars,
                max_bytes=self.max_visible_text_bytes,
            )
        if not text:
            return None
        turn_id = _normalized_string(payload.get("turn_id"), limit=256)
        kind = (
            HistoryKind.SUBAGENT_COMPLETION
            if state.agent_context is AgentContext.SUBAGENT
            else HistoryKind.TASK_COMPLETION
        )
        return self._build_event(
            state=state,
            kind=kind,
            confidence=ClassificationConfidence.LEGACY,
            reason_code="legacy_final_assistant_event",
            source_family=LEGACY_SOURCE_FAMILY,
            timestamp=timestamp,
            turn_id=turn_id,
            ordinal=ordinal,
            response_identity=f"legacy:{ordinal if ordinal is not None else hashlib.sha256(text.encode()).hexdigest()[:12]}",
            text=text,
            external_dispatchable=False,
        )

    def _build_event(
        self,
        *,
        state: _SessionState,
        kind: HistoryKind,
        confidence: ClassificationConfidence,
        reason_code: str,
        source_family: str,
        timestamp: str,
        turn_id: str,
        ordinal: int | None,
        response_identity: str,
        text: str,
        external_dispatchable: bool,
    ) -> ClassifiedEvent:
        safe_text = redact_text(
            text,
            max_chars=self.max_visible_text_chars,
            max_bytes=self.max_visible_text_bytes,
        )
        text_sha = hashlib.sha256(safe_text.encode("utf-8")).hexdigest()
        session_id = state.effective_session_id
        effective_turn = turn_id or state.current_turn_id
        response_id = response_identity or f"ordinal:{ordinal}"
        dedupe = _event_key(
            source_family=source_family,
            session_id=session_id,
            turn_id=effective_turn,
            parent_thread_id=state.parent_thread_id,
            kind=kind,
            response_identity=response_id,
            text_sha256=text_sha,
        )
        return ClassifiedEvent(
            history_kind=kind,
            confidence=confidence,
            reason_code=_reason(reason_code),
            source_schema_family=source_family,
            timestamp=_normalized_string(timestamp, limit=64),
            session_key=stable_opaque_id("sess", session_id),
            turn_key=stable_opaque_id("turn", effective_turn),
            parent_thread_key=stable_opaque_id("parent", state.parent_thread_id),
            project_id=state.project_id,
            project_label=state.project_label,
            agent_context=state.agent_context,
            source_ordinal=ordinal,
            response_key=stable_opaque_id("resp", response_id),
            text=safe_text,
            text_sha256=text_sha,
            dedupe_key=dedupe,
            event_id=f"evt_{dedupe[:24]}",
            external_dispatchable=bool(external_dispatchable),
        )
