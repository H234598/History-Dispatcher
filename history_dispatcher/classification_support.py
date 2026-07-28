from __future__ import annotations

import hashlib
import json
import re
import unicodedata
from dataclasses import dataclass, field
from typing import Any, Mapping

from .classification_types import CLASSIFICATION_SCHEMA_VERSION, AgentContext, HistoryKind


@dataclass(frozen=True)
class _Candidate:
    text: str
    timestamp: str
    turn_id: str
    response_id: str
    ordinal: int | None
    phase: str


@dataclass
class _SessionState:
    session_id: str = ""
    thread_id: str = ""
    parent_thread_id: str = ""
    current_turn_id: str = ""
    agent_context: AgentContext = AgentContext.UNKNOWN
    subagent_history_start_ordinal: int | None = None
    project_id: str = "proj_unknown"
    project_label: str = "Unbekanntes Projekt"
    final_candidates: dict[str, _Candidate] = field(default_factory=dict)

    @property
    def effective_session_id(self) -> str:
        return self.session_id or self.thread_id


_REASON_CODE_RE = re.compile(r"[^a-z0-9_]+")


def _reason(value: str) -> str:
    normalized = _REASON_CODE_RE.sub("_", str(value or "").strip().lower()).strip("_")
    return normalized[:96] or "unknown"


def _reject_json_constant(value: str) -> None:
    raise ValueError(f"non-finite JSON constant: {value}")


def _reject_duplicate_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"duplicate JSON key: {key}")
        result[key] = value
    return result


def _strict_json_loads(value: str) -> Any:
    return json.loads(
        value,
        parse_constant=_reject_json_constant,
        object_pairs_hook=_reject_duplicate_keys,
    )


def _normalized_string(value: Any, *, limit: int = 4096) -> str:
    if value is None:
        return ""
    text = unicodedata.normalize("NFC", str(value).strip())
    return text[:limit]


def _optional_int(value: Any) -> int | None:
    if isinstance(value, bool) or value is None:
        return None
    try:
        number = int(value)
    except (TypeError, ValueError):
        return None
    return number if number >= 0 else None


def _nested_string(value: Any, key: str, *, depth: int = 0) -> str:
    if depth > 5:
        return ""
    if isinstance(value, Mapping):
        direct = value.get(key)
        if isinstance(direct, (str, int)) and not isinstance(direct, bool):
            return _normalized_string(direct)
        for nested in value.values():
            found = _nested_string(nested, key, depth=depth + 1)
            if found:
                return found
    elif isinstance(value, list):
        for nested in value[:32]:
            found = _nested_string(nested, key, depth=depth + 1)
            if found:
                return found
    return ""


def _source_is_subagent(source: Any, thread_source: str, parent_thread_id: str) -> bool:
    if parent_thread_id or thread_source.lower() == "subagent":
        return True
    if isinstance(source, str):
        normalized = source.lower()
        return normalized == "subagent" or normalized.startswith("subagent_")
    if isinstance(source, Mapping):
        keys = {str(key).lower() for key in source}
        if "subagent" in keys or "thread_spawn" in keys:
            return True
        return any(_source_is_subagent(value, "", "") for value in source.values())
    if isinstance(source, list):
        return any(_source_is_subagent(value, "", "") for value in source[:32])
    return False


def _source_is_internal(source: Any) -> bool:
    if isinstance(source, str):
        normalized = source.lower()
        return normalized == "internal" or normalized.startswith("internal_")
    if isinstance(source, Mapping):
        if "internal" in {str(key).lower() for key in source}:
            return True
        return any(_source_is_internal(value) for value in source.values())
    if isinstance(source, list):
        return any(_source_is_internal(value) for value in source[:32])
    return False


def _source_is_explicitly_unknown(source: Any) -> bool:
    if isinstance(source, str):
        return source.strip().lower() == "unknown"
    if isinstance(source, Mapping):
        if "unknown" in {str(key).lower() for key in source}:
            return True
        return any(_source_is_explicitly_unknown(value) for value in source.values())
    if isinstance(source, list):
        return any(_source_is_explicitly_unknown(value) for value in source[:32])
    return False


def _can_dispatch(state: _SessionState, kind: HistoryKind) -> bool:
    return (
        kind is not HistoryKind.UNKNOWN
        and state.agent_context is not AgentContext.UNKNOWN
        and bool(state.effective_session_id)
        and state.project_id != "proj_unknown"
    )


def _git_remote(payload: Mapping[str, Any]) -> str:
    candidates: list[Any] = [
        payload.get("repository_url"),
        payload.get("remote_url"),
        payload.get("git_remote"),
    ]
    git = payload.get("git")
    if isinstance(git, Mapping):
        candidates.extend(
            [
                git.get("repository_url"),
                git.get("remote_url"),
                git.get("origin_url"),
                git.get("url"),
            ]
        )
    for candidate in candidates:
        if isinstance(candidate, str) and candidate.strip():
            return candidate
    return ""


def _candidate_key(turn_id: str) -> str:
    return turn_id or "__unbound__"


def _pick_candidate(state: _SessionState, turn_id: str) -> _Candidate | None:
    if turn_id and turn_id in state.final_candidates:
        return state.final_candidates[turn_id]
    unbound = state.final_candidates.get("__unbound__")
    if unbound is not None:
        return unbound
    if len(state.final_candidates) == 1:
        return next(iter(state.final_candidates.values()))
    return None


def _event_key(
    *,
    source_family: str,
    session_id: str,
    turn_id: str,
    parent_thread_id: str,
    kind: HistoryKind,
    response_identity: str,
    text_sha256: str,
) -> str:
    components = (
        source_family,
        session_id,
        turn_id,
        parent_thread_id,
        kind.value,
        response_identity,
        text_sha256,
        str(CLASSIFICATION_SCHEMA_VERSION),
    )
    return hashlib.sha256("\x1f".join(components).encode("utf-8")).hexdigest()
