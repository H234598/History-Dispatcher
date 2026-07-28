# Implementierungsfortschritt: Cinnamon-Applet-Ausbau

**Verbindliche Planquelle:** `HISTORY_DISPATCHER_CINNAMON_APPLET_IMPLEMENTIERUNGSPLAN`, Stand 28. Juli 2026, SHA-256 `a1f52c11117a063702f4cff008c9d24646f8f33a7540cdd1bf48ab220053ba0c`  
**Verifizierte ursprüngliche Ausgangsbasis:** `main@8f0bb05a540942e61c979a51bbaeca32d4308eb1`  
**Aktueller Main-Stand zu Beginn dieses Schnitts:** `4ff947aba6da390dcff7adaea41e9e4871132eef`  
**Aktueller Umsetzungsschnitt:** `PR-HD-02-codex-fixtures-classifier`  
**Arbeitsbranch:** `codex/codex-fixtures-classifier`

## Abgeschlossener Schnitt `PR-HD-01-baseline-adrs`

- [x] Baseline, ADR-001 bis ADR-016, Sicherheitsverträge und Reuse Ledger angelegt (`WP-001`).
- [x] verhaltensbasierte Invariantentests für Socket, Peer-Credentials, Crypto, Snapshot, systemd und Applet ergänzt.
- [x] sieben CodeRabbit-Befunde umgesetzt und sämtliche Threads gelöst.
- [x] GitHub Actions, qlty und CodeRabbit auf Head `3366bf63f208a7d6019b228dc67399b154d762c8` grün.
- [x] PR #1 per Squash mit erwarteter Head-SHA gemergt (`A-015`).
- [x] Mergecommit auf `main`: `4ff947aba6da390dcff7adaea41e9e4871132eef`.

## Status `PR-HD-02-codex-fixtures-classifier`

### Fixture-Korpus und Sanitizer (`WP-010`, `B-001` bis `B-011`)

- [x] Verzeichnisse für aktuelle, Legacy-, Sub-Agent- und Malformed-Fixtures angelegt.
- [x] aktuellen `openai/codex`-Protokollstand gegen Commit `8e271dc02b23d42827875019924be0f5005642b0` verifiziert.
- [x] deterministischen, streamingbasierten Fixture-Sanitizer implementiert.
- [x] IDs, Pfade, URLs, Namen, Text und secretartige Schlüssel pseudonymisiert beziehungsweise redigiert.
- [x] Doppelkeys, nicht endliche JSON-Werte, Nicht-Objekte, ungültiges UTF-8 und übergroße Zeilen fail-closed behandelt.
- [x] atomaren privaten Output und Dry Run implementiert.
- [x] Fixturemanifest mit SHA-256, Zeilenzahlen, erwarteten Kinds/Issues und Upstreamcommit erzeugt.
- [x] Root-, phase-missing-, Multi-Turn-, Future-Type-, Sub-Agent-, Legacy- und Malformed-Fixtures aufgenommen.
- [x] Leaktests verhindern reale Token-, E-Mail- und Privatpfadmarker.

### Classifier, Redaction und Dedupe (`WP-011`, `B-012` bis `B-024`)

- [x] `HistoryKind`, Confidence, Agentkontext, Issues, Events und Report immutable typisiert.
- [x] strikten versionierten Rollout-Envelope-Parser implementiert.
- [x] Session-, Turn-, Parent-, Sub-Agent- und Ordinalkorrelation implementiert.
- [x] `subagent_completion`, `intermediate_update`, `task_completion` und `unknown` implementiert.
- [x] geerbten Sub-Agent-Präfix vor `subagent_history_start_ordinal` ausgeschlossen.
- [x] Reasoning, Tool-, User-, System-, Developer- und nicht sichtbare Contentteile ausgeschlossen.
- [x] expliziten Quiescence-Fallback implementiert, aber nicht automatisch aktiviert.
- [x] Legacyfallback als `legacy` und extern fail-closed implementiert.
- [x] zentrale Text-/Token-/Pfad-/E-Mail-Redaction und UTF-8-Bytegrenze implementiert.
- [x] rohe Session-/Turn-/Parent-/Response-IDs aus der öffentlichen Eventansicht entfernt.
- [x] stabile Event-/Dedupe-Keys implementiert und doppelte Completionzeilen dedupliziert.
- [x] interne Sessions oder fehlende Sessionidentität extern fail-closed behandelt.
- [x] lokale Vollsuite: 50 Tests grün; davon 34 neue Classifier-/Sanitizer-/Fixturetests.

### Noch offen vor Merge

- [ ] Dateien auf den Arbeitsbranch committen und Draft-PR #2 eröffnen.
- [ ] GitHub Actions auf dem exakten PR-Head grün.
- [ ] qlty grün.
- [ ] CodeRabbit vollständig grün; alle neuen Threads fachlich bearbeiten und lösen.
- [ ] Test-/Reviewevidenz mit finaler Head-SHA in diesem Dokument nachpflegen.
- [ ] PR #2 per Squash mit erwarteter Head-SHA mergen.

## Bewusste Schnittgrenze

Der produktive Collector, Source-Cursor, Store, das DB-Schema und Routing werden
in diesem PR **nicht** umgestellt. Dadurch bleibt der bestehende
`codex_run_summary`-Produktionspfad bis zum eigenen Integrations-/Migrations-PR
unverändert.

## Nächster Schnitt nach grünem Merge

`PR-HD-03-collector-classifier-adapter` beziehungsweise der im Plan vorgesehene
Collector-v2-Vorbereitungsschnitt:

1. Classifier über eine additive Adaptergrenze in `sources.py`/`collector.py`
   einführen;
2. Cursor um Byteoffset, vollständiges Ordinal und File-Identität erweitern;
3. Partial-Line-, Rotation-, Resume- und verspätete Sub-Agent-Fälle abdecken;
4. noch ohne externe v2-Routepläne arbeiten, bis DB-v2 bereitsteht.

## Pflegevorgabe

Ein Haken wird nur gesetzt, wenn Code beziehungsweise Dokumentation vorhanden,
die zugehörigen Tests grün und der GitHub-Nachweis im Pull Request verlinkt
sind. Mergeabhängige Punkte bleiben bis zum tatsächlichen Merge offen.
