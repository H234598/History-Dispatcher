from __future__ import annotations

from pathlib import Path


def main() -> None:
    path = Path("history_dispatcher/native_telegram_worker.py")
    source = path.read_text(encoding="utf-8")
    old = '''        if not isinstance(raw_claims, Sequence) or isinstance(
            raw_claims,
            (str, bytes, bytearray),
        ):
            raw_claims = []
            blocked = True
        for raw_claim in raw_claims:
'''
    new = '''        if not isinstance(raw_claims, Sequence) or isinstance(
            raw_claims,
            (str, bytes, bytearray),
        ):
            raw_claims = []
            blocked = True
        if raw_claims:
            self._heartbeat("active", report)
        for raw_claim in raw_claims:
'''
    if source.count(old) != 1:
        raise SystemExit("expected one native claim loop")
    path.write_text(source.replace(old, new, 1), encoding="utf-8")


if __name__ == "__main__":
    main()
