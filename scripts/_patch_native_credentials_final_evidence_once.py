from __future__ import annotations

from pathlib import Path


PLAN = Path("docs/superpowers/plans/2026-07-31-native-telegram-credentials.md")
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
        "- [ ] **Step 2: Run full verification**",
        "- [x] **Step 2: Run full verification**",
        label="verification plan marker",
    )
    plan = replace_once(
        plan,
        "- [ ] **Step 3: Inspect leak boundary**",
        "- [x] **Step 3: Inspect leak boundary**",
        label="leak plan marker",
    )
    PLAN.write_text(plan, encoding="utf-8")

    progress = PROGRESS.read_text(encoding="utf-8")
    progress = replace_once(
        progress,
        "- [ ] Telegram-Addendum und README final aktualisiert;",
        "- [x] Telegram-Addendum und README final aktualisiert;",
        label="docs progress",
    )
    progress = replace_once(
        progress,
        "- [ ] ausführbaren TDD-Plan mit belegter Evidenz abhaken;",
        "- [x] ausführbaren TDD-Plan mit belegter Evidenz abgeglichen;",
        label="plan progress",
    )
    progress = replace_once(
        progress,
        "- [ ] repositoryweiten Leakscan und vollständige Verifikation auf finalem Dokumentationshead durchführen;",
        "- [x] repositoryweiten Leakscan durchgeführt; Funktionshead `60103e66d8785a79abe6a7dd3f90d3e116789cc1` mit 298 Tests, Syntax und Paketbuild grün;",
        label="leak evidence",
    )
    PROGRESS.write_text(progress, encoding="utf-8")


if __name__ == "__main__":
    main()
