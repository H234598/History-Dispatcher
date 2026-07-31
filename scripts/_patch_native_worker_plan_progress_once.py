from __future__ import annotations

from pathlib import Path


PLAN = Path("docs/superpowers/plans/2026-07-31-native-telegram-worker.md")
PROGRESS = Path("docs/implementation-progress.md")


def replace_once(source: str, old: str, new: str, *, label: str) -> str:
    count = source.count(old)
    if count != 1:
        raise SystemExit(f"{label}: expected one match, found {count}")
    return source.replace(old, new, 1)


def main() -> None:
    plan = PLAN.read_text(encoding="utf-8")
    task5 = "### Task 5: Contracts, Plan Tracking, Full Verification and Merge Gates"
    before, separator, after = plan.partition(task5)
    if not separator:
        raise SystemExit("plan task 5 marker missing")
    before = before.replace("- [ ] **Step", "- [x] **Step")
    evidence = """## Verified implementation evidence through Task 4

- Task 1 RED: Actions run `30633131916` failed only because `telegram_bot_api` was absent.
- Task 1 GREEN: Actions run `30633249959` passed syntax, the complete test suite and package build.
- Task 2 RED: Actions run `30633400212` failed only because `telegram_formatter` was absent.
- Task 2 GREEN: Actions run `30633528283` passed syntax, the complete test suite and package build.
- Task 3 RED: Actions run `30633862761` failed only because `native_telegram_worker` was absent.
- Task 3 GREEN: Actions run `30634269111` passed the native lifecycle, recipient-state, rate-limit and complete repository gates.
- Shared provider fixture RED: Actions run `30634443309` passed 358 tests and failed only because `tests/fixtures/provider-v2-contract.json` was absent.
- Shared provider fixture GREEN: rerun job `91168900382` in run `30634527086` passed the complete suite and package build.
- Task 4 RED: Actions run `30634792670` passed 359 tests and failed only on the missing CLI composition, worker unit and opt-in flag.
- Task 4 functional GREEN: Actions run `30635017382` passed syntax, the complete suite and package build.
- Task 4 cleaned status GREEN: Actions run `30635389842` passed after the one-shot status helper and workflow were removed.
- No live Telegram or production Secret-Service call was executed by these tests.

---

"""
    PLAN.write_text(before + evidence + separator + after, encoding="utf-8")

    progress = PROGRESS.read_text(encoding="utf-8")
    progress = replace_once(
        progress,
        "**Aktueller History-Dispatcher-Main:** `cd35d5807cef1834e0c4d6d6f0a18e81b7e3cda4`",
        "**Aktueller History-Dispatcher-Main:** `bb335259f16797ec385b2eee13d0fcc49a931426`",
        label="main sha",
    )
    progress = replace_once(
        progress,
        "**Abgeschlossener Schnitt:** PR #13 native Telegram-Credentialgrenze\n\n**Aktiver nächster Schnitt:** nativer Telegram-Bot-API-Worker",
        "**Abgeschlossene Schnitte:** PR #13 native Telegram-Credentialgrenze und PR #14 Plan-Sync\n\n**Aktiver Schnitt:** PR #15 `codex/native-telegram-worker`",
        label="active slice",
    )
    progress = replace_once(
        progress,
        "## Aktiver Schnitt: native write-only Telegram-Credentials",
        "## Abgeschlossener Schnitt: native write-only Telegram-Credentials",
        label="credential heading",
    )
    progress = replace_once(
        progress,
        "## Nächster sequenzieller Schnitt\n\nAls nächster Schnitt folgt der native Telegramworker:",
        "## Aktiver sequenzieller Schnitt\n\nPR #15 implementiert den nativen Telegramworker:",
        label="worker heading",
    )
    marker = "\nDer Cinnamon-Settingsschalter folgt erst nach vollständig grüner nativer\nCredential- und Workergrenze.\n"
    worker_evidence = """

### PR #15: belegter Fortschritt

- [x] Designspezifikation `docs/superpowers/specs/2026-07-31-native-telegram-worker-design.md` angelegt;
- [x] ausführbaren TDD-Plan `docs/superpowers/plans/2026-07-31-native-telegram-worker.md` angelegt;
- [x] festen HTTPS-Client für `api.telegram.org:443` ohne Proxy-, Redirect- oder konfigurierbaren URL-Pfad implementiert;
- [x] TLS-, Timeout-, Request-, Multipart- und Responsegrenzen getestet;
- [x] Telegram `retry_after` auf den gemeinsamen Backoffvertrag abgebildet;
- [x] Fehler vor dem Request retrybar und Fehler nach erfolgreichem Connect als `possible_duplicate` klassifiziert;
- [x] deterministischen Plain-Text-Formatter mit genau einem UTF-8-Textdokument-Fallback implementiert;
- [x] native Provider-v2-Claim-/Renew-/Recipient-/Complete-Lifecycle implementiert;
- [x] Recipientzustand vor jedem Send idempotent geprüft; `possible_duplicate` und andere terminale Empfänger werden nicht erneut gesendet;
- [x] terminalen Recipientstatus `failed_terminal` im gemeinsamen Telegramvertrag monotone ergänzt;
- [x] versionierten gemeinsamen Native-Fault-Korpus mit acht Szenarien angelegt;
- [x] CLI-Befehl `telegram-worker` und Signalstop implementiert;
- [x] separate gehärtete systemd-Workerunit implementiert; ausschließlich diese Unit erhält `AF_INET/AF_INET6`;
- [x] Workeraktivierung bleibt explizites Opt-in `--enable-telegram-worker`;
- [x] redigierte Status-v2-Providererkennung aus Heartbeatdetails implementiert;
- [x] Task-4-Abschlusshead auf Actions-Lauf `30635389842` mit Syntax, vollständiger Testsuite und Paketbuild grün;
- [ ] Betreiber-Runbook, README, Telegram-Addendum und finalen PR-Vertrag aktualisieren;
- [ ] vollständigen Leak-/Netzwerkgrenzenscan auf finalem Dokumentationshead durchführen;
- [ ] qlty und CodeRabbit auf finalem Head grün;
- [ ] keine offenen Reviewthreads;
- [ ] PR #15 gegen exakte geprüfte Head-SHA squash-mergen;
- [ ] Live-Canary ohne Cross-Provider-Doppelversand durchführen;
- [ ] Cinnamon-Providerauswahl aktivieren.
"""
    progress = replace_once(
        progress,
        marker,
        worker_evidence + marker,
        label="worker evidence insertion",
    )
    PROGRESS.write_text(progress, encoding="utf-8")


if __name__ == "__main__":
    main()
