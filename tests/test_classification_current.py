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


def test_root_turn_classifies_commentary_and_authoritative_completion() -> None:
    report = _classify("current-main/root-turn.jsonl")

    assert report.issues == ()
    assert [event.history_kind for event in report.events] == [
        HistoryKind.INTERMEDIATE_UPDATE,
        HistoryKind.TASK_COMPLETION,
    ]
    commentary, completion = report.events
    assert commentary.confidence is ClassificationConfidence.AUTHORITATIVE
    assert commentary.reason_code == "assistant_commentary"
    assert commentary.text == "Zwischenstand: Die Vertragsprüfung läuft."
    assert completion.confidence is ClassificationConfidence.AUTHORITATIVE
    assert completion.reason_code == "root_turn_complete"
    assert completion.text == "Die Aufgabe ist vollständig abgeschlossen."
    assert completion.agent_context is AgentContext.ROOT
    assert all(event.external_dispatchable for event in report.events)
    assert all(event.classification_schema_version == CLASSIFICATION_SCHEMA_VERSION for event in report.events)
    assert "interne Begründung" not in json.dumps(report.as_dict(), ensure_ascii=False)


def test_subagent_uses_parent_metadata_and_excludes_inherited_prefix() -> None:
    report = _classify("subagents/subagent-late.jsonl")

    assert [event.history_kind for event in report.events] == [
        HistoryKind.INTERMEDIATE_UPDATE,
        HistoryKind.SUBAGENT_COMPLETION,
    ]
    assert all(event.agent_context is AgentContext.SUBAGENT for event in report.events)
    assert report.events[-1].reason_code == "subagent_turn_complete"
    serialized = json.dumps(report.as_dict(), ensure_ascii=False, sort_keys=True)
    assert "Geerbter Parent" not in serialized
    assert "Geerbter Zwischenstand" not in serialized
    assert "thread-root-parent-0001" not in serialized
    assert report.events[-1].parent_thread_key.startswith("parent_")
    assert report.events[-1].source_ordinal == 6


def test_phase_missing_with_explicit_completion_is_compatible() -> None:
    report = _classify("current-main/phase-missing-complete.jsonl")

    assert len(report.events) == 1
    event = report.events[0]
    assert event.history_kind is HistoryKind.TASK_COMPLETION
    assert event.confidence is ClassificationConfidence.COMPATIBLE
    assert event.external_dispatchable is True


def test_multiple_turns_have_distinct_stable_keys() -> None:
    first = _classify("current-main/multi-turn.jsonl")
    second = _classify("current-main/multi-turn.jsonl")

    assert len(first.events) == 2
    assert [event.dedupe_key for event in first.events] == [
        event.dedupe_key for event in second.events
    ]
    assert len({event.turn_key for event in first.events}) == 2
    assert len({event.event_id for event in first.events}) == 2


def test_unknown_future_rollout_type_is_fail_closed() -> None:
    report = _classify("current-main/future-type.jsonl")

    assert report.unknown_records == 1
    assert len(report.events) == 1
    event = report.events[0]
    assert event.history_kind is HistoryKind.UNKNOWN
    assert event.confidence is ClassificationConfidence.AMBIGUOUS
    assert event.reason_code == "unknown_rollout_type"
    assert event.external_dispatchable is False
    assert event.text == ""


def test_legacy_final_event_is_retained_but_not_externally_dispatchable() -> None:
    report = _classify("legacy/final-event.jsonl")

    assert len(report.events) == 1
    event = report.events[0]
    assert event.history_kind is HistoryKind.TASK_COMPLETION
    assert event.confidence is ClassificationConfidence.LEGACY
    assert event.source_schema_family == "codex_rollout_legacy"
    assert event.external_dispatchable is False


def test_malformed_line_is_isolated_and_later_valid_record_is_processed() -> None:
    fixture = (FIXTURES / "malformed/invalid-json.jsonl").read_bytes().splitlines()
    fixture.append(
        json.dumps(
            {
                "timestamp": "2026-07-28T10:00:02Z",
                "ordinal": 2,
                "type": "future_after_malformed",
                "payload": {},
            }
        ).encode("utf-8")
    )

    report = CodexRolloutClassifier().classify_lines(fixture)

    assert [issue.code for issue in report.issues] == ["invalid_json"]
    assert report.unknown_records == 1
    assert report.events[0].history_kind is HistoryKind.UNKNOWN


def test_oversized_and_non_utf8_lines_are_bounded() -> None:
    classifier = CodexRolloutClassifier(max_jsonl_line_bytes=256)
    report = classifier.classify_lines([b"x" * 257, b"\xff\xfe"])

    assert [issue.code for issue in report.issues] == ["line_too_large", "invalid_utf8"]
    assert report.events == ()


def test_untrusted_non_object_envelopes_are_rejected() -> None:
    report = CodexRolloutClassifier().classify_lines(
        ["[]", '{"type":"response_item","payload":[]}', '{"payload":{}}']
    )

    assert [issue.code for issue in report.issues] == [
        "record_not_object",
        "invalid_rollout_envelope",
        "invalid_rollout_envelope",
    ]


def test_only_output_text_parts_are_visible() -> None:
    content = [
        {"type": "input_text", "text": "hidden input"},
        {"type": "output_text", "text": "visible"},
        {"type": "input_image", "image_url": "https://example.invalid/image"},
        {"type": "output_text", "text": "second"},
    ]

    assert visible_output_text(content) == "visible\nsecond"
