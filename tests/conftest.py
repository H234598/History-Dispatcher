from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

import pytest

from history_dispatcher.classification import (
    ClassificationReport,
    CodexRolloutClassifier,
)


_CODEX_FIXTURE_ROOT = Path(__file__).parent / "fixtures" / "codex"


@pytest.fixture
def codex_fixture_root() -> Path:
    return _CODEX_FIXTURE_ROOT


@pytest.fixture
def classify_fixture(
    codex_fixture_root: Path,
) -> Callable[..., ClassificationReport]:
    def classify(relative: str, **kwargs: object) -> ClassificationReport:
        path = codex_fixture_root / relative
        classifier = CodexRolloutClassifier(max_jsonl_line_bytes=16 * 1024)
        return classifier.classify_lines(path.read_bytes().splitlines(), **kwargs)

    return classify
