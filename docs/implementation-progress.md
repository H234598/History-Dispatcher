# Implementierungsfortschritt: Cinnamon-Applet-Ausbau

**Verbindliche Planquelle:** `HISTORY_DISPATCHER_CINNAMON_APPLET_IMPLEMENTIERUNGSPLAN`, Stand 28. Juli 2026, SHA-256 `a1f52c11117a063702f4cff008c9d24646f8f33a7540cdd1bf48ab220053ba0c`  
**Verifizierte ursprüngliche Ausgangsbasis:** `main@8f0bb05a540942e61c979a51bbaeca32d4308eb1`  
**Aktueller Main-Stand zu Beginn dieses Schnitts:** `d6b9fccdce5d429d07e182b1fff985c0fd1c8c40`  
**Aktueller Umsetzungsschnitt:** `PR-HD-03-db-v2-migration`  
**Arbeitsbranch:** `codex/db-v2-migration`

## Abgeschlossener Schnitt `PR-HD-01-baseline-adrs`

- [x] Baseline, ADR-001 bis ADR-016, Sicherheitsverträge und Reuse Ledger angelegt (`WP-001`).
- [x] verhaltensbasierte Invariantentests für Socket, Peer-Credentials, Crypto, Snapshot, systemd und Applet ergänzt.
- [x] sieben CodeRabbit-Befunde umgesetzt und sämtliche Threads gelöst.
- [x] GitHub Actions, qlty und CodeRabbit auf Head `3366bf63f208a7d6019b228dc67399b154d762c8` grün.
- [x] PR #1 per Squash mit erwarteter Head-SHA gemergt (`A-015`).
- [x] Mergecommit auf `main`: `4ff947aba6da390dcff7adaea41e9e4871132eef`.

## Abgeschlossener Schnitt `PR-HD-02-codex-fixtures-classifier`

- [x] sanitisiertes aktuelles/Legacy/Sub-Agent/Malformed-Fixture-Korpus und Manifest angelegt (`WP-010`).
- [x] streamingbasierten, veröffentlichungssicheren Fixture-Sanitizer mit Strict-JSON, bounded Line Reads, schreibfreiem Dry Run und atomarem Output implementiert.
- [x] `subagent_completion`, `intermediate_update`, `task_completion` und `unknown` samt Confidence, Reason-Code, Agentkontext und deterministischer Deduplizierung implementiert (`WP-011`).
- [x] Reasoning, Tool-, User-, System-, Developer- und nicht sichtbare Contentteile ausgeschlossen.
- [x] unbekannte, interne, turnlose, Legacy- und widersprüchliche Completionfälle extern fail-closed behandelt.
- [x] Token-, Authorization-, Credential-, Secret-, E-Mail- und Privatpfad-Redaction sowie issue-/rekursions-/bytebegrenztes Parsing implementiert.
- [x] sämtliche zehn CodeRabbit-Befunde und anwendbaren Nitpicks umgesetzt; alle Threads gelöst.
- [x] GitHub Actions, qlty und CodeRabbit auf finalem Head `f3edb3cea06ac06332f40fced67b94e656151830` grün; CodeRabbit freigegeben.
- [x] PR #2 per Squash mit erwarteter Head-SHA gemergt.
- [x] Mergecommit auf `main`: `d6b9fccdce5d429d07e182b1fff985c0fd1c8c40`.

## Status `PR-HD-03-db-v2-migration`

### Additives Schema und persistente Identitäten (`WP-020`, vorbereitend `WP-021`)

- [x] Branch vom exakten gemergten Main-Stand erstellt.
- [x] Draft-PR #3 eröffnet.
- [x] DB-Schema-Version 2 und Routing-Schema-Version 2 definiert.
- [x] Tabellen `history_events`, `route_plans`, `target_deliveries`, `recipient_deliveries`, `delivery_attempts`, `local_archive_entries`, `worker_heartbeats`, `config_audit` und `migration_journal` definiert.
- [x] v1-Tabellen und produktiven Collector-/Claimpfad unangetastet gelassen.
- [x] immutable Eventfelder und Routepläne durch SQLite-Trigger geschützt.
- [x] monotone Target-/Recipient-State-Machines in Python und SQLite implementiert.
- [x] HMAC-SHA-256-basierte, namespace-getrennte persistente IDs über einen vom Secret-Service-Masterkey abgeleiteten Subkey implementiert.

### Preflight, Backup, Migration und Restore

- [x] Owner-, Regular-File-, Symlink-, Secret-Key-, Speicherplatz-, `quick_check`-, Foreign-Key- und Active-Claim-Preflight implementiert.
- [x] Dry Run vollständig ohne Backup-, Verzeichnis-, Schema- oder Datenwrite implementiert.
- [x] vor dem ersten Write jede verschlüsselte Legacy-Payload entschlüsselt und gegen ihren Hash verifiziert.
- [x] owner-only SQLite-Online-Backup mit SHA-256 und eigenem `quick_check` implementiert.
- [x] Backup-/Restore-Tempfiles und SQLite-Sidecars deterministisch bereinigt.
- [x] additive DDL und Legacy-Mapping in einer `BEGIN IMMEDIATE`-Transaktion implementiert.
- [x] Fehler-Injection nach Schema/Rows führt zu vollständigem DB-Rollback bei erhaltenem Backup.
- [x] falscher Schlüssel und aktive v1-Claims scheitern vor jedem Backup-/Schemawrite.
- [x] `schema_migrations=2`, `user_version=2`, Migrationjournal und Post-Commit-Verifikation implementiert.
- [x] hash- und exakt-bestätigungsgebundenen atomaren Restore implementiert.

### Konservatives Legacy-Mapping und No-Redispatch-Garantie

- [x] nur explizit im verschlüsselten Payload vorhandene stabile `history_kind`-/Confidence-Werte übernommen.
- [x] pauschale `codex_run_summary`-Bestände auf `unknown/ambiguous` statt stiller Task-Completion-Umdeutung gemappt.
- [x] alle migrierten Events auf `legacy_hold` gesetzt.
- [x] bestehende `accepted`/`delivered`/`acknowledged` Empfängerzustände monoton erhalten.
- [x] partielle, fehlgeschlagene und uneindeutige Empfänger-/Zielzustände auf `legacy_hold` gesetzt.
- [x] Recipient-, Message-Ref-, Session-, Turn-, Parent- und Projektwerte persistent HMAC-pseudonymisiert.
- [x] verifiziert, dass Migration keine `pending`, `claimed` oder `failed_retryable` Legacy-Targetdelivery erzeugt.
- [x] idempotenten zweiten Migrationsaufruf ohne zweites Backup implementiert.

### Bedienung, Tests und Dokumentation

- [x] expliziten Operatorpfad `scripts/migrate_database_v2.py` implementiert.
- [x] `preflight`, standardmäßig schreibfreien `migrate`-Dry-Run, `verify` und `restore` implementiert.
- [x] echten Write an `--apply --confirm MIGRATE-V2` gebunden.
- [x] begrenzte JSON-Ausgaben ohne Payload-/Pfadleaks implementiert.
- [x] Runbook `docs/migration-v2.md` und README-Verweis ergänzt.
- [x] 16 fokussierte DB-v2-Tests nach Fehlerkorrektur grün.
- [x] vollständige bestehende GitHub-Actions-Suite nach Fehlerkorrektur grün.
- [x] temporären Diagnoseworkflow nach erfolgreicher Fehleranalyse wieder entfernt.

### Noch offen vor Merge

- [ ] GitHub Actions auf dem finalen Dokumentations-/CLI-Head grün.
- [ ] qlty auf dem finalen Head grün.
- [ ] CodeRabbit vollständig prüfen; alle neuen Threads fachlich bearbeiten und lösen.
- [ ] PR #3 aus dem Draft nehmen.
- [ ] finale Head-SHA und Gateevidenz in diesem Dokument nachpflegen.
- [ ] PR #3 per Squash mit erwarteter Head-SHA mergen.

## Bewusste Schnittgrenze

Schema v2 wird weder beim Dienststart noch beim normalen Storekonstruktor
automatisch aktiviert. Der produktive v1-Collector und globale v1-Claimvertrag
bleiben bis zu den folgenden Store-/Collector-Schnitten unverändert.

Migrierte Altbestände sind intern sichtbar und auditierbar, aber durch
`legacy_hold` nicht extern retrybar. Es findet weder Replan noch Backfill statt.

## Nächster Schnitt nach grünem Merge

Der nächste sequenzielle Schnitt vervollständigt den v2-Storevertrag aus
`WP-021`:

1. target-spezifische Claim-/Lease-/Heartbeat-Operationen;
2. owner- und tokengebundene Completion;
3. recipient-spezifische, monotone Resultate und Attempts;
4. Aggregation von pending/partial/delivered/failed/skipped;
5. Expiry-Recovery und konkurrierende Worker-Tests;
6. weiterhin ohne produktive Telegram-/Vault-/Router-Aktivierung.

Danach folgt `WP-012`: Collector-/Cursor-Adapter mit Byteoffset, Ordinal,
Partial-Line-, Rotation-, Resume- und verspäteten Sub-Agent-Fällen.

## Pflegevorgabe

Ein Haken wird nur gesetzt, wenn Code beziehungsweise Dokumentation vorhanden,
die zugehörigen Tests grün und der GitHub-Nachweis im Pull Request verlinkt
sind. Mergeabhängige Punkte bleiben bis zum tatsächlichen Merge offen.
