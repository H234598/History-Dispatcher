from __future__ import annotations

from pathlib import Path


PATH = Path("docs/superpowers/plans/2026-07-31-config-v2-writer.md")
PENDING = (
    "- [ ] **Step 2: Run complete verification**",
    "- [ ] **Step 6: Open PR and enforce gates**",
)


def main() -> None:
    source = PATH.read_text(encoding="utf-8")
    if not all(marker in source for marker in PENDING):
        raise SystemExit("expected pending final-plan markers are missing")
    source = source.replace("- [ ]", "- [x]")
    for marker in PENDING:
        source = source.replace(marker.replace("[ ]", "[x]"), marker, 1)
    PATH.write_text(source, encoding="utf-8")


if __name__ == "__main__":
    main()
