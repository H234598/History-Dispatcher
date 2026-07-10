from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
APPLET = ROOT / "files" / "history-dispatcher@H234598"


def test_applet_files_and_schema_are_present() -> None:
    metadata = json.loads((APPLET / "metadata.json").read_text(encoding="utf-8"))
    schema = json.loads((APPLET / "settings-schema.json").read_text(encoding="utf-8"))
    assert metadata["uuid"] == "history-dispatcher@H234598"
    assert (APPLET / "applet.js").is_file()
    assert (APPLET / "icon.svg").is_file()
    assert "main-page" in schema["layout"]["pages"]
    assert schema["refresh-seconds"]["min"] == 5
    assert schema["max-lines"]["max"] == 100


def test_applet_has_no_nul_or_blocking_shell_path() -> None:
    source = (APPLET / "applet.js").read_text(encoding="utf-8")
    assert "\\x00" not in source
    assert "spawn_sync" not in source
    assert "spawn_command_line_sync" not in source
    assert "MAX_SNAPSHOT_BYTES = 64 * 1024" in source
    assert "generation !== this.generation" in source
    assert "on_applet_removed_from_panel" in source


def test_applet_javascript_parses() -> None:
    node = shutil.which("node")
    if not node:
        pytest.skip("node is unavailable")
    result = subprocess.run(["node", "--check", str(APPLET / "applet.js")], capture_output=True, text=True, timeout=10)
    assert result.returncode == 0, result.stderr
