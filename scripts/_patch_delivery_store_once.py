from __future__ import annotations

from pathlib import Path


PATH = Path("history_dispatcher/delivery_store.py")
OLD = """        if active:
            return "partial" if delivered or partial else "pending"
        if partial:
            return "partial"
        if failures:
            return "partial" if delivered or skipped else "failed"
"""
NEW = """        if active:
            return "partial" if partial else "pending"
        if partial:
            return "partial"
        if failures:
            return "partial" if delivered else "failed"
"""


def main() -> None:
    source = PATH.read_text(encoding="utf-8")
    count = source.count(OLD)
    if count != 1:
        raise SystemExit(f"expected one aggregate-state block, found {count}")
    PATH.write_text(source.replace(OLD, NEW, 1), encoding="utf-8")


if __name__ == "__main__":
    main()
