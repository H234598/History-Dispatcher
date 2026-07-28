from __future__ import annotations

import json
from pathlib import Path

import pytest

from history_dispatcher.classification import (
    CLASSIFICATION_SCHEMA_VERSION,
    AgentContext,
    ClassificationConfidence,
    CodexRolloutClassifier,
    HistoryKind,
)
from history_dispatcher.redaction import redact_text, visible_output_text


FIXTURES = Path(__file__).parent / "fixtures" / "codex"


def _classify(relative: str, **kwargs: object):
    path = FIXTURES / relative
    classifier = CodexRolloutClassifier(max_jsonl_line_bytes=16 * 1024)
    return classifier.classify_lines(path.read_bytes().splitlines(), **kwargs)


def test_internal_session_source_is_not_misclassified_as_root_completion() -> None:
    lines = [
        json.dumps(
            {
                "timestamp": "2026-07-28T15:00:00Z",
                "ordinal": 0,
                "type": "session_meta",
                "payload": {
                    "session_id": "session-internal",
                    "id": "thread-internal",
                    "cwd": "/workspace/internal",
                    "source": {"internal": "memory_consolidation"},
                },
            }
        ),
        json.dumps(
            {
                "timestamp": "2026-07-28T15:00:01Z",
                "ordinal": 1,
                "type": "event_msg",
                "payload": {
                    "type": "turn_complete",
                    "turn_id": "turn-internal",
                    "last_agent_message": "Internal result",
                },
            }
        ),
    ]

    report = CodexRolloutClassifier().classify_lines(lines)

    assert report.events[0].agent_context is AgentContext.UNKNOWN
    assert report.events[0].history_kind is HistoryKind.UNKNOWN
    assert report.events[0].external_dispatchable is False


def test_subagent_inherited_completion_before_history_boundary_is_ignored() -> None:
    lines = [
        json.dumps(
            {
                "timestamp": "2026-07-28T16:00:00Z",
                "ordinal": 0,
                "type": "session_meta",
                "payload": {
                    "session_id": "session-child-boundary",
                    "id": "thread-child-boundary",
                    "parent_thread_id": "thread-parent-boundary",
                    "cwd": "/workspace/boundary",
                    "source": {"subagent": {"thread_spawn": {"parent_thread_id": "thread-parent-boundary", "depth": 1}}},
                    "thread_source": "subagent",
                    "subagent_history_start_ordinal": 5,
                },
            }
        ),
        json.dumps(
            {
                "timestamp": "2026-07-28T16:00:01Z",
                "ordinal": 2,
                "type": "turn_context",
                "payload": {"turn_id": "inherited-turn"},
            }
        ),
        json.dumps(
            {
                "timestamp": "2026-07-28T16:00:02Z",
                "ordinal": 3,
                "type": "event_msg",
                "payload": {
                    "type": "turn_complete",
                    "turn_id": "inherited-turn",
                    "last_agent_message": "Inherited result",
                },
            }
        ),
    ]

    report = CodexRolloutClassifier().classify_lines(lines)

    assert report.events == ()
    assert report.records_ignored == 3


def test_new_session_metadata_clears_unfinished_final_candidate() -> None:
    lines = [
        json.dumps(
            {
                "timestamp": "2026-07-28T17:00:00Z",
                "ordinal": 0,
                "type": "session_meta",
                "payload": {
                    "session_id": "session-first",
                    "id": "thread-first",
                    "cwd": "/workspace/first",
                    "source": "cli",
                },
            }
        ),
        json.dumps(
            {
                "timestamp": "2026-07-28T17:00:01Z",
                "ordinal": 1,
                "type": "response_item",
                "payload": {
                    "id": "response-first",
                    "type": "message",
                    "role": "assistant",
                    "phase": "final_answer",
                    "turn_id": "turn-first",
                    "content": [{"type": "output_text", "text": "First unfinished"}],
                },
            }
        ),
        json.dumps(
            {
                "timestamp": "2026-07-28T17:00:02Z",
                "ordinal": 2,
                "type": "session_meta",
                "payload": {
                    "session_id": "session-second",
                    "id": "thread-second",
                    "cwd": "/workspace/second",
                    "source": "cli",
                },
            }
        ),
    ]

    report = CodexRolloutClassifier().classify_lines(lines, source_quiescent=True)

    assert report.events == ()


def test_duplicate_json_keys_and_nonfinite_constants_are_rejected() -> None:
    report = CodexRolloutClassifier().classify_lines(
        [
            '{"type":"event_msg","type":"response_item","payload":{}}',
            '{"type":"future","payload":{"value":NaN}}',
        ]
    )

    assert [issue.code for issue in report.issues] == ["invalid_json", "invalid_json"]
    assert report.events == ()


def test_missing_session_identity_keeps_completion_fail_closed() -> None:
    lines = [
        json.dumps(
            {
                "timestamp": "2026-07-28T18:00:00Z",
                "ordinal": 0,
                "type": "session_meta",
                "payload": {"cwd": "/workspace/no-session", "source": "cli"},
            }
        ),
        json.dumps(
            {
                "timestamp": "2026-07-28T18:00:01Z",
                "ordinal": 1,
                "type": "event_msg",
                "payload": {
                    "type": "turn_complete",
                    "turn_id": "turn-no-session-id",
                    "last_agent_message": "Done",
                },
            }
        ),
    ]

    report = CodexRolloutClassifier().classify_lines(lines)

    assert report.events[0].agent_context is AgentContext.UNKNOWN
    assert report.events[0].history_kind is HistoryKind.UNKNOWN
    assert report.events[0].external_dispatchable is False


def test_visible_text_limit_is_enforced_in_utf8_bytes() -> None:
    classifier = CodexRolloutClassifier(max_visible_text_bytes=160)
    text = "🦎" * 200
    lines = [
        json.dumps(
            {
                "timestamp": "2026-07-28T19:00:00Z",
                "ordinal": 0,
                "type": "session_meta",
                "payload": {
                    "session_id": "session-byte-limit",
                    "id": "thread-byte-limit",
                    "cwd": "/workspace/byte-limit",
                    "source": "cli",
                },
            }
        ),
        json.dumps(
            {
                "timestamp": "2026-07-28T19:00:01Z",
                "ordinal": 1,
                "type": "event_msg",
                "payload": {
                    "type": "turn_complete",
                    "turn_id": "turn-byte-limit",
                    "last_agent_message": text,
                },
            }
        ),
    ]

    report = classifier.classify_lines(lines)

    rendered = report.events[0].text.encode("utf-8")
    assert len(rendered) <= 160
    assert "[truncated]" in report.events[0].text


def test_unknown_visible_message_phase_is_preserved_as_unknown_fail_closed() -> None:
    lines = [
        json.dumps(
            {
                "timestamp": "2026-07-28T20:00:00Z",
                "ordinal": 0,
                "type": "session_meta",
                "payload": {
                    "session_id": "session-future-phase",
                    "id": "thread-future-phase",
                    "cwd": "fixture-projects/future-phase",
                    "source": "cli",
                },
            }
        ),
        json.dumps(
            {
                "timestamp": "2026-07-28T20:00:01Z",
                "ordinal": 1,
                "type": "response_item",
                "payload": {
                    "id": "response-future-phase",
                    "type": "message",
                    "role": "assistant",
                    "phase": "future_phase",
                    "turn_id": "turn-future-phase",
                    "content": [{"type": "output_text", "text": "Visible future message"}],
                },
            }
        ),
    ]

    report = CodexRolloutClassifier().classify_lines(lines)

    assert [issue.code for issue in report.issues] == ["unknown_message_phase"]
    assert report.events[0].history_kind is HistoryKind.UNKNOWN
    assert report.events[0].text == "Visible future message"
    assert report.events[0].external_dispatchable is False


def test_internal_commentary_never_becomes_external_dispatchable() -> None:
    lines = [
        json.dumps(
            {
                "timestamp": "2026-07-28T21:00:00Z",
                "ordinal": 0,
                "type": "session_meta",
                "payload": {
                    "session_id": "session-internal-commentary",
                    "id": "thread-internal-commentary",
                    "cwd": "fixture-projects/internal-commentary",
                    "source": {"internal": "memory_consolidation"},
                },
            }
        ),
        json.dumps(
            {
                "timestamp": "2026-07-28T21:00:01Z",
                "ordinal": 1,
                "type": "response_item",
                "payload": {
                    "id": "response-internal-commentary",
                    "type": "message",
                    "role": "assistant",
                    "phase": "commentary",
                    "turn_id": "turn-internal-commentary",
                    "content": [{"type": "output_text", "text": "Internal commentary"}],
                },
            }
        ),
    ]

    report = CodexRolloutClassifier().classify_lines(lines)

    assert report.events[0].history_kind is HistoryKind.INTERMEDIATE_UPDATE
    assert report.events[0].agent_context is AgentContext.UNKNOWN
    assert report.events[0].external_dispatchable is False


def test_explicit_unknown_session_source_is_fail_closed() -> None:
    lines = [
        json.dumps(
            {
                "timestamp": "2026-07-28T22:00:00Z",
                "ordinal": 0,
                "type": "session_meta",
                "payload": {
                    "session_id": "session-unknown-source",
                    "id": "thread-unknown-source",
                    "cwd": "fixture-projects/unknown-source",
                    "source": "unknown",
                },
            }
        ),
        json.dumps(
            {
                "timestamp": "2026-07-28T22:00:01Z",
                "ordinal": 1,
                "type": "event_msg",
                "payload": {
                    "type": "turn_complete",
                    "turn_id": "turn-unknown-source",
                    "last_agent_message": "Unknown source result",
                },
            }
        ),
    ]

    report = CodexRolloutClassifier().classify_lines(lines)

    assert report.events[0].history_kind is HistoryKind.UNKNOWN
    assert report.events[0].external_dispatchable is False
