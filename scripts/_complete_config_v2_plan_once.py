from __future__ import annotations

from pathlib import Path


PATH = Path("docs/superpowers/plans/2026-07-31-config-v2-writer.md")
MARKERS = (
    "- [ ] **Step 2: Run complete verification**",
    "- [ ] **Step 6: Open PR and enforce gates**",
)


def main() -> None:
    source = PATH.read_text(encoding="utf-8")
    for marker in MARKERS:
        count = source.count(marker)
        if count != 1:
            raise SystemExit(f"expected one plan marker, found {count}: {marker}")
        source = source.replace(marker, marker.replace("[ ]", "[x]"), 1)
    PATH.write_text(source, encoding="utf-8")


if __name__ == "__main__":
    main()
