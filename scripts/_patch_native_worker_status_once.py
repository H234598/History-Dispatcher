from __future__ import annotations

from pathlib import Path


def main() -> None:
    path = Path("history_dispatcher/native_telegram_worker.py")
    source = path.read_text(encoding="utf-8")
    old = '''                "details": {
                    "claimed": report.claimed,
'''
    new = '''                "details": {
                    "provider_id": NATIVE_PROVIDER_ID,
                    "claimed": report.claimed,
'''
    if source.count(old) != 1:
        raise SystemExit("expected exactly one native heartbeat details block")
    path.write_text(source.replace(old, new, 1), encoding="utf-8")


if __name__ == "__main__":
    main()
