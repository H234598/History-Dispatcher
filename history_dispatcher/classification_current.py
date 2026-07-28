from __future__ import annotations

from typing import Any, Mapping

from .classification_support import (
    _Candidate,
    _SessionState,
    _can_dispatch,
    _candidate_key,
    _git_remote,
    _nested_string,
    _normalized_string,
    _optional_int,
    _pick_candidate,
    _source_is_explicitly_unknown,
    _source_is_internal,
    _source_is_subagent,
)
from .classification_types import (
    CURRENT_SOURCE_FAMILY,
    AgentContext,
    ClassifiedEvent,
    ClassificationConfidence,
    ClassificationIssue,
    HistoryKind,
)
from .redaction import project_identity, redact_text, visible_output_text


class ClassificationHandlersMixin:
    def _consume_session_meta(self, state: _SessionState, payload: Mapping[str, Any]) -> None:
        next_session_id = _normalized_string(
            payload.get("session_id") or payload.get("id"), limit=256
        )
        if state.effective_session_id and next_session_id != state.effective_session_id:
            state.current_turn_id = ""
            state.final_candidates.clear()
        state.session_id = next_session_id
        state.thread_id = _normalized_string(
            payload.get("id") or payload.get("session_id"), limit=256
        )
        source = payload.get("source")
        parent = _normalized_string(payload.get("parent_thread_id"), limit=256)
        if not parent:
            parent = _nested_string(source, "parent_thread_id")
        state.parent_thread_id = parent
        thread_source = _normalized_string(payload.get("thread_source"), limit=96)
        state.agent_context = (
            AgentContext.UNKNOWN
            if (
                not state.effective_session_id
                or _source_is_internal(source)
                or _source_is_explicitly_unknown(source)
                or thread_source.lower() == "memory_consolidation"
            )
            else AgentContext.SUBAGENT
            if _source_is_subagent(source, thread_source, parent)
            else AgentContext.ROOT
        )
        state.subagent_history_start_ordinal = _optional_int(
            payload.get("subagent_history_start_ordinal")
        )
        state.project_id, state.project_label = project_identity(
            remote=_git_remote(payload),
            cwd=payload.get("cwd"),
        )

    def _is_inherited_subagent_record(self, state: _SessionState, ordinal: int | None) -> bool:
        return (
            state.agent_context is AgentContext.SUBAGENT
            and state.subagent_history_start_ordinal is not None
            and ordinal is not None
            and ordinal < state.subagent_history_start_ordinal
        )

    def _consume_response_item(
        self,
        state: _SessionState,
        payload: Mapping[str, Any],
        *,
        timestamp: str,
        ordinal: int | None,
        line_number: int,
    ) -> tuple[list[ClassifiedEvent], bool, list[ClassificationIssue]]:
        issues: list[ClassificationIssue] = []
        if self._is_inherited_subagent_record(state, ordinal):
            return [], True, issues
        if _normalized_string(payload.get("type"), limit=64).lower() != "message":
            return [], True, issues
        if _normalized_string(payload.get("role"), limit=32).lower() != "assistant":
            return [], True, issues
        text = visible_output_text(
            payload.get("content"),
            max_chars=self.max_visible_text_chars,
            max_bytes=self.max_visible_text_bytes,
        )
        if not text:
            return [], True, issues
        phase = _normalized_string(payload.get("phase"), limit=64).lower()
        turn_id = _normalized_string(payload.get("turn_id"), limit=256) or state.current_turn_id
        response_id = _normalized_string(payload.get("id"), limit=256) or f"ordinal:{ordinal}"
        if phase == "commentary":
            return [
                self._build_event(
                    state=state,
                    kind=HistoryKind.INTERMEDIATE_UPDATE,
                    confidence=ClassificationConfidence.AUTHORITATIVE,
                    reason_code="assistant_commentary",
                    source_family=CURRENT_SOURCE_FAMILY,
                    timestamp=timestamp,
                    turn_id=turn_id,
                    ordinal=ordinal,
                    response_identity=response_id,
                    text=text,
                    external_dispatchable=_can_dispatch(state, HistoryKind.INTERMEDIATE_UPDATE),
                )
            ], False, issues
        if phase in {"final_answer", ""}:
            state.final_candidates[_candidate_key(turn_id)] = _Candidate(
                text=text,
                timestamp=timestamp,
                turn_id=turn_id,
                response_id=response_id,
                ordinal=ordinal,
                phase=phase,
            )
            return [], True, issues
        issues.append(
            ClassificationIssue(
                line_number,
                "unknown_message_phase",
                "Assistant-Nachricht besitzt eine unbekannte Phase",
                ordinal,
            )
        )
        return [
            self._build_event(
                state=state,
                kind=HistoryKind.UNKNOWN,
                confidence=ClassificationConfidence.AMBIGUOUS,
                reason_code="unknown_message_phase",
                source_family=CURRENT_SOURCE_FAMILY,
                timestamp=timestamp,
                turn_id=turn_id,
                ordinal=ordinal,
                response_identity=response_id,
                text=text,
                external_dispatchable=False,
            )
        ], False, issues

    def _consume_event_message(
        self,
        state: _SessionState,
        payload: Mapping[str, Any],
        *,
        timestamp: str,
        ordinal: int | None,
        line_number: int,
    ) -> tuple[list[ClassifiedEvent], bool, list[ClassificationIssue]]:
        issues: list[ClassificationIssue] = []
        if self._is_inherited_subagent_record(state, ordinal):
            return [], True, issues
        event_type = _normalized_string(payload.get("type"), limit=96).lower()
        if event_type in {"task_started", "turn_started"}:
            turn_id = _normalized_string(payload.get("turn_id"), limit=256)
            if turn_id:
                state.current_turn_id = turn_id
            return [], True, issues
        if event_type == "agent_message":
            if self._is_inherited_subagent_record(state, ordinal):
                return [], True, issues
            text = redact_text(
                payload.get("message"),
                max_chars=self.max_visible_text_chars,
                max_bytes=self.max_visible_text_bytes,
            )
            phase = _normalized_string(payload.get("phase"), limit=64).lower()
            turn_id = _normalized_string(payload.get("turn_id"), limit=256) or state.current_turn_id
            if not text:
                return [], True, issues
            if phase == "commentary":
                return [
                    self._build_event(
                        state=state,
                        kind=HistoryKind.INTERMEDIATE_UPDATE,
                        confidence=ClassificationConfidence.COMPATIBLE,
                        reason_code="event_agent_commentary",
                        source_family=CURRENT_SOURCE_FAMILY,
                        timestamp=timestamp,
                        turn_id=turn_id,
                        ordinal=ordinal,
                        response_identity=f"event:{ordinal if ordinal is not None else line_number}",
                        text=text,
                        external_dispatchable=_can_dispatch(state, HistoryKind.INTERMEDIATE_UPDATE),
                    )
                ], False, issues
            if phase in {"final_answer", ""}:
                state.final_candidates[_candidate_key(turn_id)] = _Candidate(
                    text=text,
                    timestamp=timestamp,
                    turn_id=turn_id,
                    response_id=f"event:{ordinal if ordinal is not None else line_number}",
                    ordinal=ordinal,
                    phase=phase,
                )
            return [], True, issues
        if event_type not in {"task_complete", "turn_complete"}:
            return [], True, issues

        turn_id = _normalized_string(payload.get("turn_id"), limit=256) or state.current_turn_id
        candidate = _pick_candidate(state, turn_id)
        completion_text = redact_text(
            payload.get("last_agent_message"),
            max_chars=self.max_visible_text_chars,
            max_bytes=self.max_visible_text_bytes,
        )
        text = completion_text or (candidate.text if candidate else "")
        if not text:
            return [
                self._build_event(
                    state=state,
                    kind=HistoryKind.UNKNOWN,
                    confidence=ClassificationConfidence.AMBIGUOUS,
                    reason_code="completion_without_visible_text",
                    source_family=CURRENT_SOURCE_FAMILY,
                    timestamp=timestamp,
                    turn_id=turn_id,
                    ordinal=ordinal,
                    response_identity=f"completion:{ordinal if ordinal is not None else line_number}",
                    text="",
                    external_dispatchable=False,
                )
            ], False, issues

        if candidate and completion_text and candidate.text != completion_text:
            issues.append(
                ClassificationIssue(
                    line_number,
                    "completion_text_mismatch",
                    "Turn-Abschluss und letzte sichtbare Assistant-Antwort unterscheiden sich",
                    ordinal,
                )
            )
        kind = (
            HistoryKind.SUBAGENT_COMPLETION
            if state.agent_context is AgentContext.SUBAGENT
            else HistoryKind.TASK_COMPLETION
            if state.agent_context is AgentContext.ROOT
            else HistoryKind.UNKNOWN
        )
        authoritative = bool(candidate and candidate.phase == "final_answer" and turn_id)
        confidence = (
            ClassificationConfidence.AUTHORITATIVE
            if authoritative and kind is not HistoryKind.UNKNOWN
            else ClassificationConfidence.COMPATIBLE
            if kind is not HistoryKind.UNKNOWN
            else ClassificationConfidence.AMBIGUOUS
        )
        completion_turn = turn_id or (candidate.turn_id if candidate else "")
        response_identity = (
            f"completion:{completion_turn}"
            if completion_turn
            else f"completion:{ordinal if ordinal is not None else line_number}"
        )
        if candidate is not None:
            state.final_candidates.pop(_candidate_key(candidate.turn_id), None)
        state.current_turn_id = ""
        return [
            self._build_event(
                state=state,
                kind=kind,
                confidence=confidence,
                reason_code=(
                    "subagent_turn_complete"
                    if kind is HistoryKind.SUBAGENT_COMPLETION
                    else "root_turn_complete"
                    if kind is HistoryKind.TASK_COMPLETION
                    else "completion_without_session_context"
                ),
                source_family=CURRENT_SOURCE_FAMILY,
                timestamp=timestamp or (candidate.timestamp if candidate else ""),
                turn_id=turn_id or (candidate.turn_id if candidate else ""),
                ordinal=ordinal,
                response_identity=response_identity,
                text=text,
                external_dispatchable=_can_dispatch(state, kind),
            )
        ], False, issues
