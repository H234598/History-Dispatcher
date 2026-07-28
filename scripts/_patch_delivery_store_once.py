from __future__ import annotations

from pathlib import Path


PATH = Path("history_dispatcher/delivery_store.py")
OLD = ") VALUES (?,NULL,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,'ready','',0,?,?, '')"
NEW = ") VALUES (?,NULL,?,?,?,?,?,?,?,?,?,?,?,?,?,?,'ready','',0,?,?,'')"


def main() -> None:
    source = PATH.read_text(encoding="utf-8")
    count = source.count(OLD)
    if count != 1:
        raise SystemExit(f"expected one INSERT value list, found {count}")
    PATH.write_text(source.replace(OLD, NEW, 1), encoding="utf-8")


if __name__ == "__main__":
    main()
