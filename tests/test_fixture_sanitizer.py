from __future__ import annotations

import hashlib
import json
import stat
import subprocess
import sys
from pathlib import Path

import pytest

from history_dispatcher.fixture_sanitizer import (
    SANITIZER_SCHEMA_VERSION,
    sanitize_jsonl_bytes,
    sanitize_jsonl_file,
    write_manifest,
)
from history_dispatcher.redaction import contains_sensitive_marker


ROOT = Path(__file__).resolve().parents[1]
FIXTURES = ROOT / "tests" / "fixtures" / "codex"
UPSTREAM_COMMIT = "8e271dc02b23d42827875019924be0f5005642b0"


def _private_source() -> bytes:
    records = [
        {
            "timestamp": "2026-07-28T08:00:00Z",
            "type": "session_meta",
            "payload": {
                "session_id": "real-session-123",
                "id": "real-thread-123",
                "parent_thread_id": "real-parent-123",
                "cwd": "/home/alice/private/repository",
                "originator": "alice@example.org",
                "source": "cli",
                "thread_source": "subagent",
                "git": {
                    "repository_url": "https://alice:password@example.org/private/repo.git"
                },
                "api_token": "sk-proj-abcdefghijklmnopqrstuv",
                "custom_private_field": "Bernhard private internal label",
                "name": "Private repository name",
            },
        },
        {
            "timestamp": "2026-07-28T08:00:01Z",
            "type": "response_item",
            "payload": {
                "id": "real-response-123",
                "type": "message",
                "role": "assistant",
                "phase": "final_answer",
                "content": [
                    {
                        "type": "output_text",
                        "text": "Private answer for alice@example.org in /home/alice/private",
                    }
                ],
            },
        },
    ]
    return ("\n".join(json.dumps(record) for record in records) + "\n").encode("utf-8")


def test_sanitizer_is_deterministic_and_preserves_protocol_shape() -> None:
    source = _private_source()

    first = sanitize_jsonl_bytes(source)
    second = sanitize_jsonl_bytes(source)

    assert first == second
    assert first.sanitizer_schema_version == SANITIZER_SCHEMA_VERSION
    assert first.source_sha256 == hashlib.sha256(source).hexdigest()
    assert first.output_sha256 == hashlib.sha256(first.output_bytes).hexdigest()
    assert first.line_count == 2
    text = first.output_bytes.decode("utf-8")
    assert contains_sensitive_marker(text) is False
    for forbidden in (
        "real-session-123",
        "real-thread-123",
        "real-parent-123",
        "real-response-123",
        "/home/alice",
        "alice@example.org",
        "alice:password",
        "sk-proj-",
        "Private answer",
        "Bernhard private internal label",
        "Private repository name",
    ):
        assert forbidden not in text

    records = [json.loads(line) for line in text.splitlines()]
    assert records[0]["type"] == "session_meta"
    assert records[0]["payload"]["source"] == "cli"
    assert records[0]["payload"]["thread_source"] == "subagent"
    assert records[1]["type"] == "response_item"
    assert records[1]["payload"]["type"] == "message"
    assert records[1]["payload"]["role"] == "assistant"
    assert records[1]["payload"]["phase"] == "final_answer"
    assert records[0]["payload"]["session_id"].startswith("session_id_")
    assert records[1]["payload"]["content"][0]["text"].startswith("fixture text txt_")


def test_sanitizer_rejects_invalid_json_utf8_non_objects_and_oversize() -> None:
    with pytest.raises(ValueError, match="invalid JSON"):
        sanitize_jsonl_bytes(b'{"type":')
    with pytest.raises(ValueError, match="not UTF-8"):
        sanitize_jsonl_bytes(b"\xff\xfe")
    with pytest.raises(ValueError, match="JSON object"):
        sanitize_jsonl_bytes(b"[]\n")
    with pytest.raises(ValueError, match="maximum size"):
        sanitize_jsonl_bytes(b"x" * 257, max_line_bytes=256)

    with pytest.raises(ValueError, match="invalid JSON"):
        sanitize_jsonl_bytes(b'{"type":"x","type":"y","payload":{}}\n')
    with pytest.raises(ValueError, match="invalid JSON"):
        sanitize_jsonl_bytes(b'{"type":"x","payload":{"value":NaN}}\n')


def test_file_sanitizer_dry_run_writes_nothing_and_atomic_write_is_private(tmp_path: Path) -> None:
    source = tmp_path / "private.jsonl"
    output = tmp_path / "not-created-during-dry-run" / "sanitized.jsonl"
    source.write_bytes(_private_source())
    assert output.parent.exists() is False

    result = sanitize_jsonl_file(source, output, dry_run=True)
    assert result.line_count == 2
    assert output.exists() is False
    assert output.parent.exists() is False

    written = sanitize_jsonl_file(source, output)
    assert written.output_bytes is None
    assert hashlib.sha256(output.read_bytes()).hexdigest() == written.output_sha256
    assert stat.S_IMODE(output.stat().st_mode) == 0o600
    assert not list(output.parent.glob("*.tmp"))


def test_manifest_contains_only_hash_reference_and_upstream_commit(tmp_path: Path) -> None:
    result = sanitize_jsonl_bytes(_private_source())
    manifest = tmp_path / "manifest.json"
    entry = result.manifest_entry(upstream_commit=UPSTREAM_COMMIT)

    write_manifest(manifest, [entry], upstream_commit=UPSTREAM_COMMIT)

    parsed = json.loads(manifest.read_text(encoding="utf-8"))
    assert parsed["sanitizer_schema_version"] == SANITIZER_SCHEMA_VERSION
    assert parsed["upstream_commit"] == UPSTREAM_COMMIT
    assert parsed["files"][0]["source_ref"].startswith("source-")
    serialized = json.dumps(parsed)
    assert "/home/" not in serialized
    assert "private.jsonl" not in serialized


def test_cli_dry_run_outputs_manifest_entry_without_writes(tmp_path: Path) -> None:
    source = tmp_path / "private.jsonl"
    output = tmp_path / "sanitized.jsonl"
    manifest = tmp_path / "manifest.json"
    source.write_bytes(_private_source())

    completed = subprocess.run(
        [
            sys.executable,
            str(ROOT / "scripts" / "sanitize_codex_fixture.py"),
            str(source),
            str(output),
            "--manifest",
            str(manifest),
            "--upstream-commit",
            UPSTREAM_COMMIT,
            "--dry-run",
        ],
        cwd=ROOT,
        capture_output=True,
        text=True,
        timeout=10,
        check=False,
    )

    assert completed.returncode == 0, completed.stderr
    parsed = json.loads(completed.stdout)
    assert parsed["upstream_commit"] == UPSTREAM_COMMIT
    assert output.exists() is False
    assert manifest.exists() is False


def test_checked_in_fixture_manifest_matches_all_jsonl_files() -> None:
    manifest = json.loads((FIXTURES / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["sanitizer_schema_version"] == SANITIZER_SCHEMA_VERSION
    assert manifest["upstream_commit"] == UPSTREAM_COMMIT

    expected_paths = {
        path.relative_to(FIXTURES).as_posix()
        for path in FIXTURES.rglob("*.jsonl")
    }
    actual_paths = {entry["path"] for entry in manifest["files"]}
    assert actual_paths == expected_paths

    for entry in manifest["files"]:
        path = FIXTURES / entry["path"]
        data = path.read_bytes()
        assert hashlib.sha256(data).hexdigest() == entry["sha256"]
        assert len([line for line in data.splitlines() if line.strip()]) == entry["line_count"]
        assert contains_sensitive_marker(data.decode("utf-8", errors="replace")) is False


def test_checked_in_fixture_manifest_expectations_match_classifier() -> None:
    from history_dispatcher.classification import CodexRolloutClassifier

    manifest = json.loads((FIXTURES / "manifest.json").read_text(encoding="utf-8"))
    classifier = CodexRolloutClassifier(max_jsonl_line_bytes=16 * 1024)
    for entry in manifest["files"]:
        data = (FIXTURES / entry["path"]).read_bytes()
        report = classifier.classify_lines(data.splitlines())
        assert [event.history_kind.value for event in report.events] == entry[
            "expected_history_kinds"
        ]
        assert [issue.code for issue in report.issues] == entry["expected_issue_codes"]
