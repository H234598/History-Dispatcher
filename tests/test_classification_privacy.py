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


def test_reasoning_tool_system_developer_and_user_items_are_excluded() -> None:
    lines = [
        json.dumps(
            {
                "timestamp": "2026-07-28T11:00:00Z",
                "ordinal": 0,
                "type": "session_meta",
                "payload": {
                    "session_id": "session-exclusions",
                    "id": "thread-exclusions",
                    "cwd": "/workspace/exclusions",
                    "source": "cli",
                },
            }
        ),
        json.dumps(
            {
                "timestamp": "2026-07-28T11:00:01Z",
                "ordinal": 1,
                "type": "response_item",
                "payload": {
                    "type": "message",
                    "role": "user",
                    "content": [{"type": "output_text", "text": "user secret"}],
                },
            }
        ),
        json.dumps(
            {
                "timestamp": "2026-07-28T11:00:02Z",
                "ordinal": 2,
                "type": "response_item",
                "payload": {"type": "reasoning", "summary": "reasoning secret"},
            }
        ),
        json.dumps(
            {
                "timestamp": "2026-07-28T11:00:03Z",
                "ordinal": 3,
                "type": "response_item",
                "payload": {"type": "function_call", "arguments": "tool secret"},
            }
        ),
        json.dumps(
            {
                "timestamp": "2026-07-28T11:00:04Z",
                "ordinal": 4,
                "type": "response_item",
                "payload": {
                    "type": "message",
                    "role": "system",
                    "content": [{"type": "output_text", "text": "system secret"}],
                },
            }
        ),
        json.dumps(
            {
                "timestamp": "2026-07-28T11:00:05Z",
                "ordinal": 5,
                "type": "response_item",
                "payload": {
                    "type": "message",
                    "role": "developer",
                    "content": [{"type": "output_text", "text": "developer secret"}],
                },
            }
        ),
    ]

    report = CodexRolloutClassifier().classify_lines(lines)

    assert report.events == ()
    assert report.records_ignored == 6


def test_quiescent_fallback_is_explicit_and_never_automatic() -> None:
    lines = [
        json.dumps(
            {
                "timestamp": "2026-07-28T12:00:00Z",
                "ordinal": 0,
                "type": "session_meta",
                "payload": {
                    "session_id": "session-quiescent",
                    "id": "thread-quiescent",
                    "cwd": "/workspace/quiescent",
                    "source": "cli",
                },
            }
        ),
        json.dumps(
            {
                "timestamp": "2026-07-28T12:00:01Z",
                "ordinal": 1,
                "type": "response_item",
                "payload": {
                    "id": "response-quiescent",
                    "type": "message",
                    "role": "assistant",
                    "phase": "final_answer",
                    "turn_id": "turn-quiescent",
                    "content": [{"type": "output_text", "text": "Quiescent result"}],
                },
            }
        ),
    ]
    classifier = CodexRolloutClassifier()

    assert classifier.classify_lines(lines).events == ()
    report = classifier.classify_lines(lines, source_quiescent=True)
    assert len(report.events) == 1
    assert report.events[0].confidence is ClassificationConfidence.COMPATIBLE
    assert report.events[0].reason_code == "quiescent_final_answer"


def test_duplicate_rollout_rows_produce_one_event() -> None:
    lines = (FIXTURES / "current-main/root-turn.jsonl").read_text(encoding="utf-8").splitlines()
    lines.append(lines[-1])

    report = CodexRolloutClassifier().classify_lines(lines)

    assert [event.history_kind for event in report.events].count(HistoryKind.TASK_COMPLETION) == 1


def test_public_event_view_contains_no_raw_session_turn_parent_or_path() -> None:
    report = _classify("subagents/subagent-late.jsonl")
    serialized = json.dumps(report.as_dict(), ensure_ascii=False, sort_keys=True)

    for forbidden in (
        "session-subagent-0001",
        "thread-subagent-0001",
        "thread-root-parent-0001",
        "turn-subagent-0001",
        "/workspace/history-dispatcher",
        "agents/research",
    ):
        assert forbidden not in serialized


def test_redaction_removes_tokens_private_paths_credentials_and_email() -> None:
    raw = (
        "sk-proj-abcdefghijklmnop token=supersecret123 "
        "123456789:ABCDEFGHIJKLMNOPQRSTUVWXYZabcdef "
        "https://user:password@example.invalid/path "
        "/home/alice/private/file.md /run/user/1000/private.sock "
        "alice@example.org"
    )

    redacted = redact_text(raw)

    for forbidden in (
        "sk-proj-",
        "supersecret123",
        "123456789:",
        "user:password",
        "/home/alice",
        "/run/user/1000",
        "alice@example.org",
    ):
        assert forbidden not in redacted
    assert "[redacted-token]" in redacted
    assert "[redacted-path]" in redacted
    assert "[redacted-email]" in redacted


def test_completion_text_mismatch_is_visible_as_bounded_issue() -> None:
    lines = (FIXTURES / "current-main/root-turn.jsonl").read_text(encoding="utf-8").splitlines()
    completion = json.loads(lines[-1])
    completion["payload"]["last_agent_message"] = "A different final text"
    lines[-1] = json.dumps(completion)

    report = CodexRolloutClassifier().classify_lines(lines)

    assert [issue.code for issue in report.issues] == ["completion_text_mismatch"]
    assert report.events[-1].text == "A different final text"


def test_completion_without_session_context_is_unknown_and_fail_closed() -> None:
    report = CodexRolloutClassifier().classify_lines(
        [
            json.dumps(
                {
                    "timestamp": "2026-07-28T13:00:00Z",
                    "ordinal": 1,
                    "type": "event_msg",
                    "payload": {
                        "type": "turn_complete",
                        "turn_id": "turn-no-session",
                        "last_agent_message": "Done",
                    },
                }
            )
        ]
    )

    assert report.events[0].history_kind is HistoryKind.UNKNOWN
    assert report.events[0].external_dispatchable is False


def test_duplicate_completion_without_ordinal_is_deduplicated_by_turn() -> None:
    lines = [
        json.dumps(
            {
                "timestamp": "2026-07-28T14:00:00Z",
                "type": "session_meta",
                "payload": {
                    "session_id": "session-no-ordinal",
                    "id": "thread-no-ordinal",
                    "cwd": "/workspace/no-ordinal",
                    "source": "cli",
                },
            }
        ),
        json.dumps(
            {
                "timestamp": "2026-07-28T14:00:01Z",
                "type": "response_item",
                "payload": {
                    "id": "response-no-ordinal",
                    "type": "message",
                    "role": "assistant",
                    "phase": "final_answer",
                    "turn_id": "turn-no-ordinal",
                    "content": [{"type": "output_text", "text": "Done"}],
                },
            }
        ),
        json.dumps(
            {
                "timestamp": "2026-07-28T14:00:02Z",
                "type": "event_msg",
                "payload": {
                    "type": "turn_complete",
                    "turn_id": "turn-no-ordinal",
                    "last_agent_message": "Done",
                },
            }
        ),
    ]
    lines.append(lines[-1])

    report = CodexRolloutClassifier().classify_lines(lines)

    assert len(report.events) == 1
    assert report.events[0].history_kind is HistoryKind.TASK_COMPLETION
