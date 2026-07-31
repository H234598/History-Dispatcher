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
    plan = replace_once(
        plan,
        "- [ ] **Step 2: Run complete verification**",
        "- [x] **Step 2: Run complete verification**",
        label="plan full verification",
    )
    plan = replace_once(
        plan,
        "- [ ] **Step 3: Inspect leak and network boundaries**",
        "- [x] **Step 3: Inspect leak and network boundaries**",
        label="plan boundary scan",
    )
    evidence_marker = (
        "- Task 4 cleaned status GREEN: Actions run `30635389842` passed after "
        "the one-shot status helper and workflow were removed.\n"
    )
    evidence = (
        evidence_marker
        + "- Active-heartbeat RED: Actions run `30636282681` passed 363 tests and failed only because the `active` state was absent.\n"
        + "- Active-heartbeat implementation alignment: Actions run `30636493474` passed 363 tests and failed only because the older lifecycle expectation did not yet include the new heartbeat.\n"
        + "- Active-heartbeat GREEN: Actions run `30636841087` passed 364 tests, syntax and package build after the lifecycle expectation was updated.\n"
        + "- Final documentation-head GREEN: Actions run `30637002376` passed 364 tests, syntax and package build.\n"
        + "- Final PR diff inspection confirmed fixed `api.telegram.org:443`, no configurable URL/proxy/redirect/local-server path, Internet address families only in the dedicated worker unit, no raw Telegram message ID persistence, and concrete token/chat-ID values only in negative tests.\n"
    )
    plan = replace_once(
        plan,
        evidence_marker,
        evidence,
        label="plan final evidence",
    )
    PLAN.write_text(plan, encoding="utf-8")

    progress = PROGRESS.read_text(encoding="utf-8")
    progress = replace_once(
        progress,
        "- [x] redigierte Status-v2-Providererkennung aus Heartbeatdetails implementiert;",
        "- [x] redigierte Status-v2-Providererkennung mit `starting → active → idle/degraded/blocked` aus Heartbeatdetails implementiert;",
        label="progress heartbeat",
    )
    progress = replace_once(
        progress,
        "- [ ] vollständigen Leak-/Netzwerkgrenzenscan auf finalem Dokumentationshead durchführen;",
        "- [x] vollständigen Leak-/Netzwerkgrenzenscan durchgeführt: fixed Host, keine Proxy-/Redirect-/URL-Konfiguration, nur Worker mit `AF_INET/AF_INET6`, keine rohe Message-ID-Persistenz und konkrete Secrets nur in Negativtests;",
        label="progress boundary scan",
    )
    insert_after = (
        "- [x] Betreiber-Runbook `docs/native-telegram-worker.md`, README, Telegram-Addendum und Control-Protokoll aktualisiert;\n"
    )
    progress = replace_once(
        progress,
        insert_after,
        insert_after
        + "- [x] finaler Dokumentationshead auf Actions-Lauf `30637002376` mit 364 Tests, Syntax und Paketbuild grün;\n",
        label="progress final actions",
    )
    PROGRESS.write_text(progress, encoding="utf-8")


if __name__ == "__main__":
    main()
