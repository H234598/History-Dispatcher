# Datenbankmigration v1 → v2

**Stand:** 28. Juli 2026  
**Implementierungsschnitt:** `PR-HD-03-db-v2-migration`  
**Zielschema:** `2`

## 1. Sicherheitsgrenze dieses Schnitts

Die Migration ist **nicht** Bestandteil des normalen Dienststarts. Weder
`DispatcherStore` noch Collector, Service oder Applet führen sie automatisch
aus. Der bestehende v1-Produktionspfad bleibt nach Installation des Codes
unverändert, bis ein Operator die Migration ausdrücklich startet.

Der Schnitt aktiviert außerdem noch nicht:

- den neuen Codex-Classifier im Collector;
- target-spezifische Workerclaims;
- Router, Telegram v2, Vault oder lokales Archiv;
- Backfill oder Replan alter Queueeinträge;
- neue externe Zustellungen.

Jeder migrierte v1-Eintrag erhält zunächst `legacy_hold=1`. Bereits belegte
Empfängererfolge bleiben erhalten; fehlgeschlagene, partielle oder uneindeutige
Ergebnisse werden nicht retrybar gemacht.

## 2. Additive Tabellen

Schema v2 ergänzt die bestehenden v1-Tabellen um:

- `history_events`;
- `route_plans`;
- `target_deliveries`;
- `recipient_deliveries`;
- `delivery_attempts`;
- `local_archive_entries`;
- `worker_heartbeats`;
- `config_audit`;
- `migration_journal`.

Die v1-Tabellen werden weder gelöscht noch umbenannt. Immutable Eventfelder,
Routepläne und monotone Deliveryzustände werden zusätzlich durch SQLite-Trigger
geschützt.

## 3. Voraussetzungen

Vor einem echten Lauf müssen erfüllt sein:

1. Der verwendete Secret-Service-Schlüssel ist derselbe Schlüssel, mit dem die
   v1-Payloads verschlüsselt wurden.
2. Die Datenbank ist eine reguläre, vom aktuellen Benutzer besessene Datei.
3. Datenbankpfad und Backupziel enthalten keine Symlinkkomponente.
4. `PRAGMA quick_check` und `PRAGMA foreign_key_check` sind sauber.
5. Es gibt keine noch gültigen globalen v1-Claims.
6. Freier Speicher beträgt mindestens das Doppelte der Datenbankgröße und
   standardmäßig mindestens 256 MiB.
7. Collector und externe Dispatchprozesse sind für das Wartungsfenster
   kontrolliert pausiert.

Der Migrator prüft die Punkte 1 bis 6 selbst. Punkt 7 bleibt eine explizite
Operatoraufgabe, weil dieser PR noch keine neue Service-Orchestrierung einführt.

## 4. Kommandos

Alle Beispiele verwenden den dünnen, repositorylokalen Einstiegspunkt:

```bash
python scripts/migrate_database_v2.py --help
```

Ein abweichender Konfigurationspfad kann mit `--config` angegeben werden. Für
eine isolierte Kopie kann `--database` direkt auf die Testdatenbank zeigen.

### 4.1 Preflight

```bash
python scripts/migrate_database_v2.py preflight
```

Die Ausgabe ist ein begrenztes JSON-Dokument mit Schema-Versionen,
Datenbankgröße, Modus, freiem/erforderlichem Speicher, aktiven Claims,
Zeilenzahlen und Integritätschecks. Payloads, Pfade aus Historyinhalten,
Empfänger oder Secrets werden nicht ausgegeben.

### 4.2 Dry Run

`migrate` ist ohne weitere Option immer schreibfrei:

```bash
python scripts/migrate_database_v2.py migrate
```

Der Dry Run:

- entschlüsselt und hashprüft jede v1-Payload im Speicher;
- ermittelt konservative Kind-/Confidence-Mappings;
- legt kein Backupverzeichnis an;
- schreibt keine Tabelle, Migration oder Datei;
- meldet `no_external_dispatch_created=true`.

### 4.3 Echter Apply

Ein Schreibvorgang verlangt beide Optionen:

```bash
python scripts/migrate_database_v2.py migrate \
  --apply \
  --confirm MIGRATE-V2
```

Fehlt der exakte Bestätigungstext, wird kein Backup und kein Datenbankwrite
ausgeführt.

Ablauf des echten Laufs:

1. vollständiger Preflight;
2. Entschlüsselungs- und Hashprüfung aller Legacy-Payloads;
3. owner-only SQLite-Online-Backup;
4. SHA-256 und `quick_check` des Backups;
5. `BEGIN IMMEDIATE`;
6. additive DDL, Mapping, Constraints und Trigger;
7. Zeilen-, Foreign-Key- und No-Redispatch-Verifikation;
8. Migrationjournal und Schema-Version `2`;
9. Commit;
10. unabhängige Post-Commit-Verifikation.

Ein Fehler zwischen DDL und Commit rollt Schema und Daten vollständig zurück.
Das bereits verifizierte Backup bleibt als separater Recoverypunkt erhalten.

### 4.4 Verifizieren

```bash
python scripts/migrate_database_v2.py verify
```

Erfolgreich ist die Verifikation nur, wenn:

- Schema-Version 2 vorhanden ist;
- alle additiven Tabellen existieren;
- `quick_check` und Foreign Keys sauber sind;
- alle v1-Historyzeilen genau einmal als `legacy_item_id` vertreten sind;
- keine durch die Migration erzeugte Legacy-Delivery `pending`, `claimed` oder
  `failed_retryable` ist.

### 4.5 Restore

Der Restorepfad ist für eine isolierte Zielkopie oder für einen kontrollierten
Rollback vor produktiven v2-Writes vorgesehen:

```bash
python scripts/migrate_database_v2.py restore \
  --backup ~/.local/state/history-dispatcher/backups/<backup>.sqlite3 \
  --sha256 <vollständiger-sha256> \
  --confirm 'RESTORE <erste-12-hashzeichen>' \
  --destination /sicherer/pfad/restored-v1.sqlite3
```

Der Restore:

- prüft Symlinks und Backupdateityp;
- verlangt den vollständigen erwarteten SHA-256;
- verlangt den exakten hashgebundenen Bestätigungstext;
- prüft das Backup mit `quick_check`;
- schreibt über eine private temporäre Datei und atomaren Replace;
- entfernt nur eigene temporäre Sidecars;
- setzt Datei- und Zielverzeichnisrechte auf `0600` beziehungsweise `0700`.

## 5. Konservatives Legacy-Mapping

| v1-Bestand | v2-Mapping |
|---|---|
| explizites gültiges `history_kind` im verschlüsselten Payload | Kind und gültige Confidence bleiben erhalten; trotzdem `legacy_hold` |
| pauschales `kind=codex_run_summary` ohne explizite Klassifikation | `unknown`, Confidence `ambiguous`, Reason `legacy_v1_unclassified` |
| Telegram-Recipient mit `accepted`, `delivered` oder `acknowledged` | gleicher monotone Erfolg, HMAC-pseudonymisierte Recipient-/Message-Referenzen |
| gemischte erfolgreiche und fehlgeschlagene Empfänger | Target `legacy_hold`, Outcome `partial`; Erfolgsempfänger bleiben erfolgreich |
| fehlgeschlagener oder unbekannter Empfänger | `legacy_hold`; keine automatische Retryfreigabe |
| nicht eindeutig als Telegram erkennbarer Channel | Target `legacy_unknown`, `legacy_hold` |

Session-, Turn-, Parent-, Projekt-, Recipient- und Message-Referenzen werden
über HMAC-SHA-256 und einen vom Secret-Service-Masterkey getrennt abgeleiteten
Subkey stabil pseudonymisiert. Die IDs sind innerhalb derselben Installation
korrelierbar, aber nicht aus einem erratbaren Klartext-SHA-256 abgeleitet.

## 6. Backup und Recovery

Das Backup wird standardmäßig unter
`<state-dir>/backups/` mit Modus `0700` angelegt. Die einzelne SQLite-Datei
besitzt Modus `0600`; temporäre `-wal`, `-shm`, `-journal` und `.tmp`-Dateien
werden nach Abschluss entfernt.

Ein Backup allein ist noch keine Freigabe zum blinden Downgrade. Sobald nach der
Migration neue v2-Events oder Deliveryzustände geschrieben wurden, darf eine
alte v1-Kopie nicht einfach über die produktive Datenbank gelegt werden. Dann
ist der im Gesamtplan beschriebene Export-/Reconciliationpfad erforderlich.

## 7. Verbotene Abkürzungen

- `PRAGMA user_version` niemals manuell herabsetzen.
- v2-Tabellen niemals von Hand löschen.
- bei falschem oder fehlendem Schlüssel keinen neuen Zufallsschlüssel erzeugen.
- keine entschlüsselten Payloads in temporäre Dateien exportieren.
- queued/failed Legacyzustände nicht pauschal auf `pending` setzen.
- Restore nicht bei laufenden Writerprozessen ausführen.
- Backuphash oder Bestätigungstext nicht umgehen.

## 8. Tests und Fehlereinjektion

Der Schnitt prüft mindestens:

- schreibfreien Dry Run;
- Additivität und Verschlüsselung;
- HMAC-Pseudonyme ohne Klartext-/SHA-Präfix;
- monotone Python- und SQLite-State-Machines;
- keine neu retrybaren externen Deliveries;
- idempotenten zweiten Migrationsaufruf;
- vollständigen Transaktionsrollback nach injiziertem Fehler;
- Abbruch vor Backup bei aktivem v1-Claim;
- Abbruch vor jedem Write bei falschem Schlüssel;
- genau eine aufgeräumte Backupdatei;
- verifizierten v1-Restore;
- Ablehnung falscher Hashes und Bestätigungstexte;
- CLI-Preflight, Dry Run, Confirmation und Verify.

## 9. Nächster Schnitt

Nach Merge dieses PRs folgt die v2-Store-API für target-spezifische Claims,
Leases, Attempts und Completion. Erst danach werden Collector und Classifier an
die neue Persistenzgrenze angeschlossen. Router, Telegram, Vault und lokales
Archiv bleiben weitere getrennte Schnitte.
