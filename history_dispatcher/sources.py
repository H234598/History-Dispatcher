from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Iterator, Mapping, Sequence
from pathlib import Path
from typing import Any


def _content_text(content: object) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, Mapping):
        return str(content.get("text") or "")
    if isinstance(content, Sequence) and not isinstance(content, (str, bytes, bytearray)):
        values: list[str] = []
        for item in content:
            if isinstance(item, str):
                values.append(item)
            elif isinstance(item, Mapping) and isinstance(item.get("text"), str):
                values.append(str(item["text"]))
        return "\\n".join(values)
    return ""


def _payload_text(payload: Mapping[str, Any]) -> str:
    return _content_text(payload.get("content")).strip()


def _visible_user_text(text: str) -> str:
    text = re.sub(r"<codex_internal_context\b[^>]*>.*?</codex_internal_context>", " ", text, flags=re.I | re.S)
    text = re.sub(r"<environment_context>.*?</environment_context>", " ", text, flags=re.I | re.S)
    return re.sub(r"\s+", " ", text).strip()[:500]


def _title(text: str) -> str:
    first = next((line.strip() for line in text.splitlines() if line.strip()), "Codex run summary")
    return first[:160]


def _bullets(text: str) -> list[str]:
    return [line.strip("- *\t ")[:500] for line in text.splitlines() if line.strip()][:8]


def _tests(text: str) -> list[str]:
    return [line.strip()[:500] for line in text.splitlines() if "test" in line.casefold()][:8]


class CodexJsonlSource:
    name = "codex"

    def __init__(self, roots: Sequence[Path], *, scan_limit: int = 25, max_file_bytes: int = 16 * 1024 * 1024) -> None:
        self.roots = tuple(roots)
        self.scan_limit = max(1, min(int(scan_limit), 10000))
        self.max_file_bytes = max(1, min(int(max_file_bytes), 1024 * 1024 * 1024))

    def files(self) -> tuple[Path, ...]:
        candidates: set[Path] = set()
        for root in self.roots:
            text = str(root)
            matches = [Path(item) for item in __import__("glob").glob(text)] if any(char in text for char in "*?[") else [root]
            for candidate in matches:
                if candidate.is_file() and candidate.suffix == ".jsonl":
                    candidates.add(candidate)
                elif candidate.is_dir():
                    candidates.update(path for path in candidate.rglob("*.jsonl") if path.is_file() and "sessions" in path.parts)
        ordered: list[tuple[int, str, Path]] = []
        for path in candidates:
            try:
                stat = path.stat()
            except OSError:
                continue
            if stat.st_size <= self.max_file_bytes:
                ordered.append((-int(stat.st_mtime_ns), str(path), path))
        ordered.sort()
        return tuple(item[2] for item in ordered[: self.scan_limit])

    def parse(self, path: Path) -> dict[str, Any]:
        session_id = ""
        turn_id = ""
        cwd = ""
        user_by_turn: dict[str, str] = {}
        final_messages: list[dict[str, str]] = []
        source_mtime = ""
        try:
            source_mtime = __import__("datetime").datetime.fromtimestamp(path.stat().st_mtime, __import__("datetime").timezone.utc).isoformat(timespec="seconds")
            with path.open("r", encoding="utf-8", errors="replace") as handle:
                for raw in handle:
                    if not raw.strip():
                        continue
                    try:
                        row = json.loads(raw)
                    except json.JSONDecodeError:
                        continue
                    if not isinstance(row, Mapping):
                        continue
                    payload = row.get("payload") if isinstance(row.get("payload"), Mapping) else row
                    row_type = str(row.get("type") or payload.get("type") or "").strip()
                    if row_type == "session_meta":
                        session_id = str(payload.get("id") or session_id)
                        cwd = str(payload.get("cwd") or cwd)
                    elif row_type == "turn_context":
                        turn_id = str(payload.get("turn_id") or turn_id)
                    cwd = str(payload.get("cwd") or cwd)
                    role = str(payload.get("role") or "").strip()
                    text = _payload_text(payload)
                    if role == "user" and text:
                        user_by_turn[turn_id] = _visible_user_text(text)
                    if role == "assistant" and text:
                        phase = str(payload.get("phase") or "").casefold()
                        if not phase or phase in {"final", "final_answer"}:
                            final_messages.append({
                                "turn_id": turn_id,
                                "final_text": text,
                                "auftrag": user_by_turn.get(turn_id, ""),
                            })
        except OSError:
            return {"session_id": "", "turn_id": "", "cwd": "", "final_messages": [], "source_mtime": source_mtime}
        return {"session_id": session_id or path.stem, "turn_id": turn_id, "cwd": cwd, "final_messages": final_messages, "source_mtime": source_mtime}

    def items(self) -> Iterator[dict[str, Any]]:
        for path in self.files():
            parsed = self.parse(path)
            session_id = str(parsed.get("session_id") or path.stem)
            for message in parsed.get("final_messages", []):
                text = str(message.get("final_text") or "").strip()
                if not text:
                    continue
                turn_id = str(message.get("turn_id") or parsed.get("turn_id") or "")
                final_hash = "sha256:" + hashlib.sha256(text.encode("utf-8")).hexdigest()
                dedupe = "sha256:" + hashlib.sha256(f"{session_id}\n{turn_id}\n{final_hash}".encode("utf-8")).hexdigest()
                yield {
                    "source": self.name,
                    "kind": "codex_run_summary",
                    "dedupe_key": dedupe,
                    "target_group": "status_admins",
                    "project": str(parsed.get("cwd") or path.parent),
                    "created_at": str(parsed.get("source_mtime") or ""),
                    "payload": {
                        "codex": {
                            "session_id": session_id,
                            "turn_id": turn_id,
                            "source_path_hash": "sha256:" + hashlib.sha256(str(path).encode("utf-8")).hexdigest(),
                            "final_message_hash": final_hash,
                            "auftrag": str(message.get("auftrag") or ""),
                        },
                        "summary": {
                            "title": _title(text),
                            "bullets": _bullets(text),
                            "tests": _tests(text),
                            "text": text[:12000],
                        },
                    },
                }
