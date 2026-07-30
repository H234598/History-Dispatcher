# Implementierungsfortschritt: Cinnamon-Applet-Ausbau

**Planquelle:** `HISTORY_DISPATCHER_CINNAMON_APPLET_IMPLEMENTIERUNGSPLAN`, SHA-256 `a1f52c11117a063702f4cff008c9d24646f8f33a7540cdd1bf48ab220053ba0c`  
**Telegram-Addendum:** `docs/implementation-plan-addendum-telegram.md`  
**Ausgangsbasis:** `main@8f0bb05a540942e61c979a51bbaeca32d4308eb1`  
**Aktuelle PR-Basis:** `main@74cec04ef6f06edf3ea3e5826f9fd4f3e5a1afc3`  
**Aktueller Schnitt:** `PR-HD-07-status-v2-health`  
**Branch:** `codex/status-v2-health`

## Gemergte Schnitte

| Schnitt | Inhalt | Main-Commit |
|---|---|---|
| PR-HD-01 | Baseline, ADRs, Sicherheitsverträge | `4ff947aba6da390dcff7adaea41e9e4871132eef` |
| PR-HD-02 | Codex-Fixtures, Sanitizer, Classifier | `d6b9fccdce5d429d07e182b1fff985c0fd1c8c40` |
| PR-HD-03 | transaktionale DB-v2-Migration | `ec3acf360cabc793835ecf3a8106fd1501897ba4` |
| PR-HD-04 | dualer Telegram-Providervertrag | `9d3f9420805986720e458d18876539962eab893f` |
| PR-HD-06 | Config-v2-Vertrags- und Previewgrenze | `278f9a3198a54cde7495b1a3ce4fb0c85dabc246` |
| PR-HD-05 | providergebundener Route-/Delivery-Store | `74cec04ef6f06edf3ea3e5826f9fd4f3e5a1afc3` |

PR-HD-05 wurde nach Prüfung seines bereits vollständig grünen Heads nachträglich
vor PR-HD-07 geschlossen. Damit basiert der Statusschnitt nun auf der im Plan
vorgesehenen vollständigen Delivery-/Heartbeat-Persistenzgrenze.

## Status PR-HD-07

### Typ- und Leakvertrag

- [x] einheitliche Typen `HealthStatusV2`, `TelegramProviderStatus`,
  `CredentialStatus` und `WorkerHealthStatus` implementiert;
- [x] vorläufige Aliasnamen des ersten Drafts kompatibel gehalten;
- [x] Provider auf `teebotus | history_dispatcher` begrenzt;
- [x] Worker-, Zähler- und Zeitfelder begrenzt und validiert;
- [x] rekursive Leakprüfung für Secret-, Token-, Chat-/Recipient-/Message- und
  Payloadfelder implementiert;
- [x] sensible Stringmuster, nicht endliches JSON, mehr als zwölf Ebenen, mehr
  als 4096 Werte und mehr als 64 KiB fail-closed behandelt.

### Runtime-Health

- [x] Queuezähler aus dem bestehenden v1-Store eingebunden;
- [x] Deliveryzustände read-only und gruppiert aus `target_deliveries` gelesen;
- [x] höchstens 64 Workerheartbeats read-only ausgegeben;
- [x] Vor-Migrationsdatenbanken ohne v2/v3-Tabellen sicher unterstützt;
- [x] malformed Details auf `unknown` reduziert;
- [x] unbekannte Providerwerte neutralisiert;
- [x] strukturell ungültige Workerzeilen ausgelassen;
- [x] Read-only-Verbindungen deterministisch geschlossen.

### API und Snapshot

- [x] additive Operation `status.get_redacted` in die feste Socket-Allowlist
  aufgenommen;
- [x] Same-User-Unix-Socket-End-to-End-Test ergänzt;
- [x] `status.get`, `health.get`, `report.get` und `status-v1.json` unverändert
  gelassen;
- [x] separaten `status-v2.json`-Snapshot implementiert;
- [x] Modus `0600`, Runtimeverzeichnis `0700`, atomaren Replace, Datei-/Dir-fsync
  und 64-KiB-Limit umgesetzt;
- [x] bestehende Datei bei Validierungs- oder Größenfehler nicht ersetzt;
- [x] v2 wird vor v1 geschrieben, sodass die v1-Kompatibilitätsgrenze zuletzt
  atomar veröffentlicht bleibt.

### TDD- und Gateevidenz

- [x] ursprünglichen Draftfehler `HealthStatusV2`/`StatusV2` in Actions
  reproduziert und behoben;
- [x] Test-only-Head `6f5788d48c3f28170ebd776151767bf6e960aaab`
  erwartungsgemäß rot wegen fehlender Runtime-/Snapshotmodule;
- [x] Funktionslauf mit 192 bestandenen Tests; einzige rote Fixture anschließend
  als fehlerhafte Sortierannahme korrigiert;
- [x] vollständiger Integrationslauf `30567009528` grün;
- [x] Heartbeat-Härtung zunächst rot reproduziert, anschließend Lauf
  `30567282941` grün;
- [ ] GitHub Actions, qlty und CodeRabbit auf dem finalen Dokumentationshead grün;
- [ ] alle finalen Reviewthreads bearbeitet und gelöst;
- [ ] PR #7 aus Draft genommen und mit erwarteter Head-SHA gemergt.

## Bewusste Schnittgrenze

PR-HD-07 liest oder schreibt keinen Telegram-Bot-Token und führt keine
Netzwerkdiagnose aus. Der Credentialstatus ist bis zur produktiven
Secret-Service-Grenze ausschließlich `configured=false`. Der produktive
Providerwert bleibt bis zum echten Config-v2-Writer kompatibel `teebotus`.

## Nächster Schnitt

`PR-HD-08-teebotus-provider-v2` verbindet TeeBotus mit dem gemeinsamen
providergebundenen Claim-/Recipient-/Attempt-Vertrag:

1. Capability- und Provider-Handshake;
2. Claimtoken-/Lease-Verwendung;
3. dynamische opaque Accountrefs;
4. monotone Empfängerresultate und Callback-Spool;
5. gemeinsamer Contract-Fixture-Korpus als Vorbereitung für den nativen Worker;
6. weiterhin kein Cross-Provider-Fallback.

Danach folgt `PR-HD-09-native-telegram-worker` mit Secret-Service-Credentials,
Bot-API, Formatter, Segmentierung, Rate-Limit und Crash-Reconciliation.

## Pflegevorgabe

Ein Haken wird nur gesetzt, wenn Code oder Dokumentation vorhanden, die
zugehörigen Tests grün und der GitHub-Nachweis im Pull Request nachvollziehbar
ist. Mergeabhängige Punkte bleiben bis zum tatsächlichen Merge offen.
