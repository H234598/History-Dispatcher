from __future__ import annotations

from pathlib import Path


FILES = {
    "plan": Path("docs/superpowers/plans/2026-07-31-native-telegram-credentials.md"),
    "design": Path("docs/superpowers/specs/2026-07-31-native-telegram-credentials-design.md"),
    "progress": Path("docs/implementation-progress.md"),
    "addendum": Path("docs/implementation-plan-addendum-telegram.md"),
}


def replace_once(source: str, old: str, new: str, *, label: str) -> str:
    count = source.count(old)
    if count != 1:
        raise SystemExit(f"{label}: expected one match, found {count}")
    return source.replace(old, new, 1)


def main() -> None:
    plan = FILES["plan"].read_text(encoding="utf-8")
    plan = replace_once(plan, "status: active", "status: completed", label="plan status")
    plan = replace_once(
        plan,
        "- [ ] **Step 6: Enforce merge gates**",
        "- [x] **Step 6: Enforce merge gates**",
        label="plan merge gate",
    )
    FILES["plan"].write_text(plan, encoding="utf-8")

    design = FILES["design"].read_text(encoding="utf-8")
    design = replace_once(
        design,
        "status: approved",
        "status: implemented",
        label="design status",
    )
    FILES["design"].write_text(design, encoding="utf-8")

    progress = FILES["progress"].read_text(encoding="utf-8")
    progress = replace_once(
        progress,
        "**Aktueller History-Dispatcher-Main:** `decd370f8359979beff59da0b4dbf81208fb044a`  \n",
        "**Aktueller History-Dispatcher-Main:** `cd35d5807cef1834e0c4d6d6f0a18e81b7e3cda4`\n",
        label="progress main sha",
    )
    progress = replace_once(
        progress,
        "**Aktiver Schnitt:** PR #13 `codex/native-telegram-credentials`  \n**Nächster Schnitt:** nativer Telegram-Bot-API-Worker",
        "**Abgeschlossener Schnitt:** PR #13 native Telegram-Credentialgrenze\n\n**Aktiver nächster Schnitt:** nativer Telegram-Bot-API-Worker",
        label="progress active slice",
    )
    progress = replace_once(
        progress,
        "| PR-HD-12 | produktiver Config-v2-Writer, Preview/Apply, Audit und Same-User-API | `decd370f8359979beff59da0b4dbf81208fb044a` |",
        "| PR-HD-12 | produktiver Config-v2-Writer, Preview/Apply, Audit und Same-User-API | `decd370f8359979beff59da0b4dbf81208fb044a` |\n| PR-HD-13 | Secret-Service-Credentialgrenze, Schema v4, Kompensation und write-only Same-User-API | `cd35d5807cef1834e0c4d6d6f0a18e81b7e3cda4` |",
        label="progress merge row",
    )
    for old, new, label in (
        (
            "- [ ] GitHub Actions, qlty und CodeRabbit auf finalem Head grün;",
            "- [x] GitHub Actions, qlty und CodeRabbit auf finalem Head `c8da7593d235af6e03c101bc0ee4242690c9a0f9` grün;",
            "progress gates",
        ),
        (
            "- [ ] keine offenen Reviewthreads;",
            "- [x] keine offenen Reviewthreads;",
            "progress threads",
        ),
        (
            "- [ ] PR #13 aus Draft nehmen und gegen exakte Head-SHA squash-mergen.",
            "- [x] PR #13 gegen `c8da7593d235af6e03c101bc0ee4242690c9a0f9` squash-gemergt; Main-Commit `cd35d5807cef1834e0c4d6d6f0a18e81b7e3cda4`.",
            "progress merge",
        ),
    ):
        progress = replace_once(progress, old, new, label=label)
    progress = progress.replace(
        "PR #13 führt keine Telegram-Netzwerkoperation aus.",
        "Der gemergte PR #13 führt keine Telegram-Netzwerkoperation aus.",
        1,
    )
    progress = progress.replace(
        "Nach Merge von PR #13 folgt der native Telegramworker:",
        "Als nächster Schnitt folgt der native Telegramworker:",
        1,
    )
    FILES["progress"].write_text(progress, encoding="utf-8")

    addendum = FILES["addendum"].read_text(encoding="utf-8")
    addendum = replace_once(
        addendum,
        "- [ ] **PR-HD-13** – Secret-Service-Credentialgrenze, Schema v4 und write-only\n  Same-User-API; funktional grün, finale Dokumentations-/Merge-Gates offen;",
        "- [x] **PR-HD-13** – Secret-Service-Credentialgrenze, Schema v4, Kompensation und write-only Same-User-API; gemergt als `cd35d5807cef1834e0c4d6d6f0a18e81b7e3cda4`;",
        label="addendum pr13",
    )
    addendum = addendum.replace(
        "## 9. Bewusste Schnittgrenze von PR #13",
        "## 9. Bewusste Grenze des gemergten PR #13",
        1,
    )
    addendum = addendum.replace(
        "Nach Merge von PR #13 folgen:",
        "Als nächster Schnitt folgen:",
        1,
    )
    FILES["addendum"].write_text(addendum, encoding="utf-8")


if __name__ == "__main__":
    main()
