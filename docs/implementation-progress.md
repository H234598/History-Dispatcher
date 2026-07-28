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
- [x] Verhaltensbasierte Negativtests für Socket, Peer-Credentials, Crypto, Snapshot, Appletaktionen, Removal und systemd-Härtung erstellt (`WP-001`).
- [x] GitHub-Actions-Run `30340982857` auf Commit `8606a765730b8bd244ec1971284036e7a903372c` vollständig grün; qlty ebenfalls grün.
- [x] Sieben CodeRabbit-Befunde fachlich umgesetzt: deterministischer Telegramfilter, messbare v1/v2-Grenze, strikte Request-Bodies, requestgebundene Idempotenz, breitere Security-Change-Control-Regel, Verhaltensnachweise und robuste ADR-ID-Prüfung.
- [x] Reviewbedingte v1-Härtung reserviert Request-IDs vor Mutationen und bindet sie an Same-User-Scope, Operation und kanonischen Body-Fingerprint; Queue-/Deliveryschema bleibt unverändert.
- [ ] GitHub-Actions-, qlty- und CodeRabbit-Gates auf dem Review-Fix-Commit vollständig grün.
- [ ] Alle sieben Reviewthreads nach erfolgreicher Revalidierung aufgelöst.
- [ ] Baseline-PR gemergt (`A-015`).

## Nächster Schnitt nach grünem Merge

`PR-HD-02-codex-fixtures-classifier`:

1. sanitisierten Fixture-Sanitizer anlegen;
2. aktuelle, Legacy-, Sub-Agent- und Malformed-Fixtures aufnehmen;
3. `HistoryKind`, Confidence, Parser, Redaction und Dedupe implementieren;
4. `T-CLS-*` und Leakgate aktivieren.

Vorbereitend wurde der aktuelle OpenAI-Codex-Protokollstand erneut gegen Commit `8e271dc02b23d42827875019924be0f5005642b0` geprüft. Dieser Upstreamstand wird im nächsten PR als Fixture-/Protokollreferenz dokumentiert; er ist kein Runtime-Dependency.

## Pflegevorgabe

Ein Haken wird nur gesetzt, wenn Code beziehungsweise Dokumentation vorhanden, die zugehörigen Tests grün und der GitHub-Nachweis im Pull Request verlinkt sind. Mergeabhängige Punkte bleiben bis zum tatsächlichen Merge offen.
