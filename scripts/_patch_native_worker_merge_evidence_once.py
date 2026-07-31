from __future__ import annotations

from pathlib import Path


PLAN = Path("docs/superpowers/plans/2026-07-31-native-telegram-worker.md")
DESIGN = Path("docs/superpowers/specs/2026-07-31-native-telegram-worker-design.md")
RUNBOOK = Path("docs/native-telegram-worker.md")
PROGRESS = Path("docs/implementation-progress.md")
ADDENDUM = Path("docs/implementation-plan-addendum-telegram.md")


def replace_once(source: str, old: str, new: str, *, label: str) -> str:
    count = source.count(old)
    if count != 1:
        raise SystemExit(f"{label}: expected one match, found {count}")
    return source.replace(old, new, 1)


def main() -> None:
    plan = PLAN.read_text(encoding="utf-8")
    plan = replace_once(plan, "status: active", "status: completed", label="plan status")
    plan = replace_once(
        plan,
        "- [ ] **Step 6: Enforce hard merge gates**",
        "- [x] **Step 6: Enforce hard merge gates**",
        label="plan merge gate",
    )
    plan += """

## Merge evidence

- Final verified PR head: `0bb736ee4b6360b12c2a291d8ae3b1c5a4842f63`.
- GitHub Actions run `30637266609` passed syntax, 364 tests and package build.
- qlty and CodeRabbit were green on the exact final head.
- Pull request #15 had zero unresolved review threads.
- Pull request #15 was squash-merged against the exact final head.
- Main commit: `495202ce28592b707a20bb3faeacf020c4d9f639`.
- Live Telegram canaries and Cinnamon settings remain intentionally outside this completed implementation plan.
"""
    PLAN.write_text(plan, encoding="utf-8")

    design = DESIGN.read_text(encoding="utf-8")
    design = replace_once(
        design,
        "status: approved",
        "status: implemented",
        label="design status",
    )
    DESIGN.write_text(design, encoding="utf-8")

    runbook = RUNBOOK.read_text(encoding="utf-8")
    runbook = replace_once(
        runbook,
        "status: implemented-awaiting-merge",
        "status: implemented",
        label="runbook status",
    )
    RUNBOOK.write_text(runbook, encoding="utf-8")

    progress = PROGRESS.read_text(encoding="utf-8")
    progress = replace_once(
        progress,
        "**Aktueller History-Dispatcher-Main:** `bb335259f16797ec385b2eee13d0fcc49a931426`",
        "**Aktueller History-Dispatcher-Main:** `495202ce28592b707a20bb3faeacf020c4d9f639`",
        label="progress main sha",
    )
    progress = replace_once(
        progress,
        "**Abgeschlossene Schnitte:** PR #13 native Telegram-Credentialgrenze und PR #14 Plan-Sync\n\n**Aktiver Schnitt:** PR #15 `codex/native-telegram-worker`",
        "**Abgeschlossene Schnitte:** PR #13 Credentialgrenze, PR #14 Plan-Sync und PR #15 nativer Telegramworker\n\n**Aktiver Schnitt:** gemeinsamer TeeBotus/Native-Fault-Abgleich und getrennte Live-Canaries",
        label="progress active slice",
    )
    progress = replace_once(
        progress,
        "| PR-HD-13 | Secret-Service-Credentialgrenze, Schema v4, Kompensation und write-only Same-User-API | `cd35d5807cef1834e0c4d6d6f0a18e81b7e3cda4` |",
        "| PR-HD-13 | Secret-Service-Credentialgrenze, Schema v4, Kompensation und write-only Same-User-API | `cd35d5807cef1834e0c4d6d6f0a18e81b7e3cda4` |\n| PR-HD-14-plan | Credential-Merge-Evidenz und nächster aktiver Schnitt synchronisiert | `bb335259f16797ec385b2eee13d0fcc49a931426` |\n| PR-HD-15 | fixed-host Bot API, Formatter, nativer Provider-v2-Worker, Rate-Limit und hardened systemd | `495202ce28592b707a20bb3faeacf020c4d9f639` |",
        label="progress merge rows",
    )
    progress = replace_once(
        progress,
        "## Aktiver sequenzieller Schnitt\n\nPR #15 implementiert den nativen Telegramworker:",
        "## Abgeschlossener sequenzieller Schnitt: nativer Telegramworker\n\nPR #15 implementierte den nativen Telegramworker:",
        label="progress worker heading",
    )
    progress = replace_once(
        progress,
        "- [ ] qlty und CodeRabbit auf finalem Head grün;",
        "- [x] qlty und CodeRabbit auf finalem Head `0bb736ee4b6360b12c2a291d8ae3b1c5a4842f63` grün;",
        label="progress gates",
    )
    progress = replace_once(
        progress,
        "- [ ] keine offenen Reviewthreads;",
        "- [x] keine offenen Reviewthreads;",
        label="progress threads",
    )
    progress = replace_once(
        progress,
        "- [ ] PR #15 gegen exakte geprüfte Head-SHA squash-mergen;",
        "- [x] PR #15 gegen `0bb736ee4b6360b12c2a291d8ae3b1c5a4842f63` squash-gemergt; Main-Commit `495202ce28592b707a20bb3faeacf020c4d9f639`;",
        label="progress merge",
    )
    marker = (
        "\nDer Cinnamon-Settingsschalter folgt erst nach vollständig grüner nativer\n"
        "Credential- und Workergrenze.\n"
    )
    next_section = """

## Nächster aktiver Schnitt

1. den erweiterten vollständigen Fault-Korpus erneut gegen TeeBotus und Native gemeinsam abnehmen;
2. getrennte TeeBotus- und Native-Live-Canaries mit dedizierten Testempfängern durchführen;
3. explizit nachweisen, dass kein Cross-Provider-Doppelversand entsteht;
4. erst danach Cinnamon-Providerauswahl und Settings-UX aktivieren.
"""
    progress = replace_once(
        progress,
        marker,
        next_section + marker,
        label="progress next slice",
    )
    PROGRESS.write_text(progress, encoding="utf-8")

    addendum = ADDENDUM.read_text(encoding="utf-8")
    addendum = replace_once(
        addendum,
        "- [ ] **PR-HD-15 / PR-HD-Native-Telegram** – nativer Telegramworker mit\n  fixed-host Bot API, Formatter, Provider-v2-Lifecycle, Rate-Limit und\n  Reconciliation; funktional grün, finale Gates und Merge offen.",
        "- [x] **PR-HD-15 / PR-HD-Native-Telegram** – nativer Telegramworker mit fixed-host Bot API, Formatter, Provider-v2-Lifecycle, Rate-Limit und Reconciliation; gemergt als `495202ce28592b707a20bb3faeacf020c4d9f639`.",
        label="addendum pr15",
    )
    addendum = replace_once(
        addendum,
        "## 10. Aktiver Schnitt: nativer Telegramworker\n\nPR #15 hat funktional umgesetzt:",
        "## 10. Abgeschlossener Schnitt: nativer Telegramworker\n\nPR #15 hat umgesetzt:",
        label="addendum worker heading",
    )
    addendum += """

## 11. Nächster aktiver Schnitt

- erweiterten gemeinsamen Fault-Korpus gegen TeeBotus und Native abnehmen;
- getrennte Live-Canaries mit dedizierten Testempfängern durchführen;
- keinen Cross-Provider-Doppelversand nachweisen;
- Cinnamon-Settingsschalter erst nach diesen Gates aktivieren.
"""
    ADDENDUM.write_text(addendum, encoding="utf-8")


if __name__ == "__main__":
    main()
