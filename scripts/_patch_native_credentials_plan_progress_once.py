from __future__ import annotations

from pathlib import Path


PATH = Path("docs/superpowers/plans/2026-07-31-native-telegram-credentials.md")
TASK5 = "### Task 5: Contracts, Plan Tracking and Full Verification"
TASK5_DONE = (
    "- [ ] **Step 1: Document migration and credential operations**",
    "- [ ] **Step 4: Update plan evidence**",
    "- [ ] **Step 5: Commit documentation**",
)


def main() -> None:
    source = PATH.read_text(encoding="utf-8")
    if source.count(TASK5) != 1:
        raise SystemExit("Task 5 marker is missing or ambiguous")
    before, after = source.split(TASK5, 1)
    before = before.replace("- [ ]", "- [x]")
    for marker in TASK5_DONE:
        count = after.count(marker)
        if count != 1:
            raise SystemExit(f"expected one marker, found {count}: {marker}")
        after = after.replace(marker, marker.replace("[ ]", "[x]"), 1)
    PATH.write_text(before + TASK5 + after, encoding="utf-8")


if __name__ == "__main__":
    main()
