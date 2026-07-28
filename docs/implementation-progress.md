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
- [x] streamingbasierten Fixture-Sanitizer implementiert.
- [x] IDs, Pfade, URLs, Namen, Text, unbekannte Felder und secretartige Schlüssel pseudonymisiert beziehungsweise redigiert.
- [x] veröffentlichte Pseudonyme durch fixturelokale First-seen-Aliasse ersetzt; sie sind nicht aus erratbaren Klartext-Hashes abgeleitet.
- [x] Doppelkeys, nicht endliche JSON-Werte, Nicht-Objekte, ungültiges UTF-8, Rekursion und übergroße Zeilen fail-closed behandelt.
- [x] Zeilengrenze vor unbeschränktem Buffering und vor UTF-8-Decoding durchgesetzt.
- [x] atomaren privaten Output und vollständig schreibfreien Dry Run implementiert.
- [x] Fixturemanifest mit SHA-256, Zeilenzahlen, erwarteten Kinds, Confidence, Dispatchfähigkeit, Issues und Upstreamcommit erzeugt.
- [x] Root-, phase-missing-, Multi-Turn-, Future-Type-, Sub-Agent-, Legacy- und Malformed-Fixtures aufgenommen.
- [x] Leaktests verhindern Token-, Authorization-, Secret-Zuweisungs-, Credential-URL-, E-Mail- und Privatpfadmarker.

### Classifier, Redaction und Dedupe (`WP-011`, `B-012` bis `B-024`)

- [x] `HistoryKind`, Confidence, Agentkontext, Issues, Events und Report immutable typisiert.
- [x] strikten versionierten Rollout-Envelope-Parser implementiert.
- [x] Session-, Turn-, Parent-, Sub-Agent- und Ordinalkorrelation implementiert.
- [x] `subagent_completion`, `intermediate_update`, `task_completion` und `unknown` implementiert.
- [x] geerbten Sub-Agent-Präfix vor `subagent_history_start_ordinal` ausgeschlossen.
- [x] Reasoning, Tool-, User-, System-, Developer- und nicht sichtbare Contentteile ausgeschlossen.
- [x] expliziten Quiescence-Fallback implementiert, aber nicht automatisch aktiviert.
- [x] Legacyfallback als `legacy` und extern fail-closed implementiert.
- [x] zentrale Text-/Token-/Credential-/Pfad-/E-Mail-Redaction und UTF-8-Bytegrenze implementiert.
- [x] vollständige Authorization-/WWW-Authenticate-Werte und gequotete Secretwerte mit Leerzeichen redigiert.
- [x] rohe Session-/Turn-/Parent-/Response-IDs aus der öffentlichen Eventansicht entfernt.
- [x] stabile Event-/Dedupe-Keys implementiert und doppelte Completionzeilen dedupliziert.
- [x] interne Sessions sowie fehlende Session-, Turn- oder Projektidentität extern fail-closed behandelt.
- [x] explizite Turn-IDs greifen niemals auf Kandidaten eines anderen Turns zurück.
- [x] widersprüchliche `last_agent_message`-Werte überschreiben keinen validierten sichtbaren Assistanttext und erzeugen `unknown`/nicht dispatchfähig.
- [x] Rekursion und gespeicherte Einzelissues hart begrenzt.
- [x] GitHub-Actions-Lauf `30357023199` auf Head `aa5bf894df07270bd900cb67ab38ccd4839861fd` vollständig grün.

### Noch offen vor Merge

- [x] Dateien auf den Arbeitsbranch veröffentlicht und PR #2 eröffnet.
- [x] PR #2 aus dem Draft genommen.
- [x] sämtliche zehn konkreten CodeRabbit-Befunde sowie die anwendbaren Nitpicks implementiert.
- [x] GitHub Actions auf dem aktuellen Review-Fix-Head grün.
- [ ] qlty auf dem finalen Head grün.
- [ ] CodeRabbit auf dem finalen Head freigegeben; alle Threads gelöst.
- [ ] Test-/Reviewevidenz mit endgültiger Head-SHA nachpflegen.
- [ ] PR #2 per Squash mit erwarteter Head-SHA mergen.

## Bewusste Schnittgrenze

Der produktive Collector, Source-Cursor, Store, das DB-Schema und Routing werden
in diesem PR **nicht** umgestellt. Dadurch bleibt der bestehende
`codex_run_summary`-Produktionspfad bis zum eigenen Integrations-/Migrations-PR
unverändert.

Die stabilen öffentlichen Korrelationswerte dieses isolierten Classifiers sind
Pseudonyme, keine Anonymitätsgrenze. Vor einer externen v2-Auslieferung bindet
der DB-v2-/Integrationsschnitt Projekt-, Session-, Turn- und Parent-IDs an einen
lokal persistenten Secret-Service-Schlüssel. Der aktuelle PR führt bewusst noch
keinen persistenten Secretzugriff in den reinen Classifier ein.

## Nächster Schnitt nach grünem Merge

`PR-HD-03-db-v2-migration` gemäß der verbindlichen PR-Reihenfolge und `WP-020`
mit vorbereitendem Anteil aus `WP-021`:

1. additive Tabellen für `history_events`, `route_plans`,
   `target_deliveries`, `recipient_deliveries`, `delivery_attempts`,
   `local_archive_entries`, Heartbeats, Config-Audit und Migrationsjournal
   definieren;
2. SQLite-Backup, Preflight, Migrationsjournal, Verify und Restoretest
   implementieren;
3. monotone Ziel-/Empfängerzustände und eindeutige Delivery-/Dedupe-Constraints
   als Store-Vertrag anlegen;
4. v1-Bestand ohne neuen externen Dispatch auf eindeutige Legacyzuordnung oder
   `unknown/legacy_hold` migrieren;
5. den produktiven Collector weiterhin unverändert lassen, bis die sichere
   v2-Persistenzschnittstelle gemergt ist.

Der Collector-/Cursor-Umbau aus `WP-012` folgt danach auf der gemergten
DB-v2-Schnittstelle. Dadurch werden klassifizierte Events nicht vorzeitig in ein
unzureichendes v1-Queue-/Deliverymodell geschrieben.

## Pflegevorgabe

Ein Haken wird nur gesetzt, wenn Code beziehungsweise Dokumentation vorhanden,
die zugehörigen Tests grün und der GitHub-Nachweis im Pull Request verlinkt
sind. Mergeabhängige Punkte bleiben bis zum tatsächlichen Merge offen.
