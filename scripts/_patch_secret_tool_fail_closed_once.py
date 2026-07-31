from __future__ import annotations

from pathlib import Path


PATH = Path("history_dispatcher/telegram_secrets.py")


def replace_once(source: str, old: str, new: str, *, label: str) -> str:
    count = source.count(old)
    if count != 1:
        raise SystemExit(f"{label}: expected one match, found {count}")
    return source.replace(old, new, 1)


def main() -> None:
    source = PATH.read_text(encoding="utf-8")
    source = replace_once(
        source,
        """        if completed.returncode != 0:
            return None
        try:
""",
        """        if completed.returncode != 0:
            if completed.stderr:
                raise TelegramSecretError("Secret Service lookup failed")
            return None
        try:
""",
        label="lookup nonzero handling",
    )
    source = replace_once(
        source,
        """        completed = self._run(
            ["secret-tool", "clear", *self._attributes(kind, profile_ref)]
        )
        return completed.returncode == 0
""",
        """        completed = self._run(
            ["secret-tool", "clear", *self._attributes(kind, profile_ref)]
        )
        if completed.returncode != 0 and completed.stderr:
            raise TelegramSecretError("Secret Service clear failed")
        return completed.returncode == 0
""",
        label="clear nonzero handling",
    )
    PATH.write_text(source, encoding="utf-8")


if __name__ == "__main__":
    main()
