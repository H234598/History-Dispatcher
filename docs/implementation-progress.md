# Implementierungsfortschritt: Cinnamon-Applet-Ausbau

**Verbindliche Planquelle:** `HISTORY_DISPATCHER_CINNAMON_APPLET_IMPLEMENTIERUNGSPLAN`, Stand 28. Juli 2026, SHA-256 `a1f52c11117a063702f4cff008c9d24646f8f33a7540cdd1bf48ab220053ba0c`  
**Verifizierte Ausgangsbasis:** `main@8f0bb05a540942e61c979a51bbaeca32d4308eb1`  
**Aktueller Umsetzungsschnitt:** `PR-HD-01-baseline-adrs`  
**Arbeitsbranch:** `codex/implementation-baseline-adrs`

## Status dieses Schnitts

- [x] Default-Branch und Ausgangs-HEAD erneut verifiziert (`A-001`).
- [x] Kein offener eigener Pull Request im Zielrepository; eigener Branch vom exakten HEAD angelegt (`A-002`).
- [x] v1-Control-, Snapshot-, Applet- und systemd-Grenzen inventarisiert (`A-007` bis `A-010`).
- [x] ADR-001 bis ADR-016 als akzeptierte Entscheidungen angelegt (`A-011`).
- [x] Sicherheitsinvarianten dokumentiert und mit Tests verknüpft (`A-012`).
- [x] Reuse Ledger initialisiert; in diesem Schnitt wurde kein externer Code übernommen (`A-014`).
- [x] Architektur-, Applet- und v1-Vertragsdokumentation erstellt (`WP-001`).
- [x] Negativtests für Socket-, Crypto-, Snapshot-, Applet- und systemd-Grenzen erstellt (`WP-001`).
- [x] GitHub-Actions-Run `30340908142` auf Commit `a7b883b11b57d84c899bc7a94b6b3e1eb2d17f02` vollständig grün: Installation, Syntax/tests und Build.
- [ ] Reviewbefunde abgearbeitet; vor Merge werden Threads und Reviews erneut geprüft.
- [ ] Baseline-PR gemergt (`A-015`).

## Nächster Schnitt nach grünem Merge

`PR-HD-02-codex-fixtures-classifier`:

1. sanitisierten Fixture-Sanitizer anlegen;
2. aktuelle, Legacy-, Sub-Agent- und Malformed-Fixtures aufnehmen;
3. `HistoryKind`, Confidence, Parser, Redaction und Dedupe implementieren;
4. `T-CLS-*` und Leakgate aktivieren.

## Pflegevorgabe

Ein Haken wird nur gesetzt, wenn Code beziehungsweise Dokumentation vorhanden, die zugehörigen Tests grün und der GitHub-Nachweis im Pull Request verlinkt sind. Mergeabhängige Punkte bleiben bis zum tatsächlichen Merge offen.
