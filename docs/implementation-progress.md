# Implementierungsfortschritt: Cinnamon-Applet-Ausbau

**Verbindliche Planquelle:** `HISTORY_DISPATCHER_CINNAMON_APPLET_IMPLEMENTIERUNGSPLAN`, Stand 28. Juli 2026, SHA-256 `a1f52c11117a063702f4cff008c9d24646f8f33a7540cdd1bf48ab220053ba0c`  
**Verbindliches Zusatzartefakt:** `docs/implementation-plan-addendum-telegram.md`  
**Verifizierte ursprüngliche Ausgangsbasis:** `main@8f0bb05a540942e61c979a51bbaeca32d4308eb1`  
**Aktueller Main-Stand zu Beginn dieses Schnitts:** `ec3acf360cabc793835ecf3a8106fd1501897ba4`  
**Aktueller Umsetzungsschnitt:** `PR-HD-04-telegram-provider-contract`  
**Arbeitsbranch:** `codex/telegram-provider-contract`

## Abgeschlossener Schnitt `PR-HD-01-baseline-adrs`

- [x] Baseline, ADR-001 bis ADR-016, Sicherheitsverträge und Reuse Ledger angelegt (`WP-001`).
- [x] verhaltensbasierte Invariantentests für Socket, Peer-Credentials, Crypto, Snapshot, systemd und Applet ergänzt.
- [x] sieben CodeRabbit-Befunde umgesetzt und sämtliche Threads gelöst.
- [x] GitHub Actions, qlty und CodeRabbit auf Head `3366bf63f208a7d6019b228dc67399b154d762c8` grün.
- [x] PR #1 per Squash gemergt; Main-Commit `4ff947aba6da390dcff7adaea41e9e4871132eef`.

## Abgeschlossener Schnitt `PR-HD-02-codex-fixtures-classifier`

- [x] sanitisiertes aktuelles/Legacy/Sub-Agent/Malformed-Fixture-Korpus und Manifest angelegt (`WP-010`).
- [x] veröffentlichungssicheren Fixture-Sanitizer mit Strict-JSON, bounded Line Reads, schreibfreiem Dry Run und atomarem Output implementiert.
- [x] `subagent_completion`, `intermediate_update`, `task_completion` und `unknown` samt Confidence, Reason-Code und Deduplizierung implementiert (`WP-011`).
- [x] Reasoning, Tool-, User-, System-, Developer- und nicht sichtbare Inhalte ausgeschlossen.
- [x] sämtliche CodeRabbit-Befunde bearbeitet; GitHub Actions, qlty und CodeRabbit auf finalem Head `f3edb3cea06ac06332f40fced67b94e656151830` grün.
- [x] PR #2 per Squash gemergt; Main-Commit `d6b9fccdce5d429d07e182b1fff985c0fd1c8c40`.

## Abgeschlossener Schnitt `PR-HD-03-db-v2-migration`

### Schema, Migration und Sicherheitsgrenzen

- [x] additive Tabellen `history_events`, `route_plans`, `target_deliveries`, `recipient_deliveries`, `delivery_attempts`, `local_archive_entries`, `worker_heartbeats`, `config_audit` und `migration_journal` definiert.
- [x] HMAC-SHA-256-basierte, namespace-getrennte persistente IDs über einen separaten Secret-Service-Subkey implementiert.
- [x] monotone Target-/Recipient-State-Machines in Python und SQLite implementiert.
- [x] owner-, symlink-, key-, disk-, integrity- und claimgeprüften Preflight implementiert.
- [x] schreibfreien Dry Run, verifiziertes owner-only Backup, eine `BEGIN IMMEDIATE`-Migrationstransaktion und hashgebundenen Restore implementiert.
- [x] Legacybestand konservativ auf explizite Klassifikation oder `unknown/ambiguous` gemappt und vollständig auf `legacy_hold` gesetzt.
- [x] keine neue `pending`, `claimed` oder `failed_retryable` Legacy-Delivery erzeugt.
- [x] bestehende `accepted`/`delivered`/`acknowledged` Empfängerzustände erhalten; `possible_duplicate` auf Reconciliation-Hold gesetzt.
- [x] v1-Retention kann Altzeilen entfernen, ohne die verschlüsselte v2-Kopie zu löschen.

### Reviewhärtung und Mergeevidenz

- [x] SQLite-Verbindungen über Context Manager deterministisch geschlossen.
- [x] aktive v1-Claims nach `BEGIN IMMEDIATE` erneut autoritativ geprüft.
- [x] unvollständige v1-Schemata vor Backup und Row-Copy klar abgewiesen.
- [x] Backup-/Restoreverzeichnisse vor und nach Erstellung symlink-/owner-/typegeprüft.
- [x] Restore validiert und kopiert denselben geöffneten Backup-Inode in eine private Stagingdatei und verhindert TOCTOU-Austausch.
- [x] zusätzliche Tests für Connection-Cleanup, Claim-TOCTOU, Partialschema, Verzeichnisfehler und Restore-Inode-Austausch ergänzt.
- [x] GitHub Actions auf finalem Head `94d0e887cb09a4f4160127dd69722eafe713d8fa` grün, Lauf `30362866142`.
- [x] qlty und CodeRabbit auf dem finalen Head grün; sämtliche Reviewthreads gelöst.
- [x] PR #3 per Squash mit erwarteter Head-SHA gemergt.
- [x] Main-Commit `ec3acf360cabc793835ecf3a8106fd1501897ba4`.

## Status `PR-HD-04-telegram-provider-contract`

### Planpflege und Architektur

- [x] Zusatzanforderung „Dispatch über TeeBotus oder direkt über History-Dispatcher“ als verbindliches Planaddendum aufgenommen.
- [x] `REQ-TG-001` bis `REQ-TG-010`, neue PR-Reihenfolge, Zusatz-Checkboxen und Definition of Done dokumentiert.
- [x] ADR-007 in ihrer exklusiven Form als ersetzt markiert.
- [x] ADR-017 mit zwei Providern und strikt verbotenem automatischem Cross-Provider-Fallback angelegt.
- [x] TeeBotus-Quellcommit und adaptierte Symbole im Reuse Ledger verankert.
- [x] Settingsfeld `routing.telegram.provider` sowie die spätere Combobox „Über TeeBotus / Direkt über History-Dispatcher“ exakt spezifiziert.

### Provider- und Recipientvertrag

- [x] stabile Enum `teebotus | history_dispatcher` implementiert.
- [x] immutable `TelegramTransportBinding` mit Provider-Schema implementiert.
- [x] TeeBotus-Capability beziehungsweise native opaque Credential-/Recipientreferenzen streng getrennt.
- [x] rohe Tokens, numerische Chat-IDs, Pfade, Kontrollzeichen und übergroße Recipientlisten fail-closed abgewiesen.
- [x] Provider in kanonisches Route-Plan-Fragment und Planhash gebunden.
- [x] Worker-/Plan-Provider-Missmatch ohne Fallback abgewiesen.
- [x] redigierte Statussicht ohne Credential-/Recipientreferenzen implementiert.
- [x] TeeBotus-Erfolgsrang und Recipient-Reconciliation transportneutral adaptiert.
- [x] erfolgreiche Empfänger gegen Downgrade durch spätere Fehler geschützt.
- [x] `possible_duplicate` bis zu einer belastbaren Erfolgsquittung erhalten.
- [x] negative und monotone Providertests ergänzt.

### Noch offen vor Merge

- [x] PR #4 zunächst sauber auf PR #3 gestapelt und separat getestet.
- [x] gestapelter Head `7758ed0181dc2b6f8d1bcc08b06df7444f7e9ef1`: GitHub Actions, qlty und CodeRabbit grün; keine Reviewthreads.
- [x] nach Merge von PR #3 den Providercommit auf `main@ec3acf360cabc793835ecf3a8106fd1501897ba4` neu aufgebaut.
- [x] PR #4 auf `main` retargetet.
- [ ] GitHub Actions, qlty und CodeRabbit auf dem neuen finalen Head grün.
- [ ] PR #4 aus dem Draft nehmen.
- [ ] mögliche neue Reviewthreads bearbeiten und lösen.
- [ ] PR #4 per Squash mit erwarteter Head-SHA mergen.

## Bewusste Schnittgrenze

Dieser Schnitt versendet noch keine Telegramnachricht und speichert noch keinen
Bot-Token. Der Cinnamon-Schalter wird nicht als tote UI vorgezogen, sondern erst
mit Config v2 und dem revisionsgesicherten Backend-Routingeditor aktiviert.

Providerentscheidungen sind bereits unveränderlich und planhashgebunden. Der
spätere native Worker kann daher nicht still als Fallback für einen TeeBotus-
Plan einspringen und umgekehrt.

## Nächster Schnitt nach grünem Merge

`PR-HD-05-route-planner-deliveries` vervollständigt den v2-Storevertrag:

1. target- und provider-spezifische Claims;
2. Lease, Heartbeat, Claimtoken und Workerownership;
3. recipient-spezifische Completion und Attempts;
4. Aggregation von pending/partial/delivered/failed/skipped;
5. Expiry-Recovery und konkurrierende Worker-Tests;
6. Provider-Capability-Handschlag für TeeBotus und den nativen Worker;
7. weiterhin noch ohne produktiven Bot-API-Versand.

Danach folgen Config v2/Settings und der eigene History-Dispatcher-Telegramworker
mit Secret-Service-Credentials, Formatter, Rate-Limit und Reconciliation.

## Pflegevorgabe

Ein Haken wird nur gesetzt, wenn Code beziehungsweise Dokumentation vorhanden,
die zugehörigen Tests grün und der GitHub-Nachweis im Pull Request verlinkt
sind. Mergeabhängige Punkte bleiben bis zum tatsächlichen Merge offen.
