# Implementierungsfortschritt: Cinnamon-Applet-Ausbau

**Planquelle:** `HISTORY_DISPATCHER_CINNAMON_APPLET_IMPLEMENTIERUNGSPLAN`, SHA-256 `a1f52c11117a063702f4cff008c9d24646f8f33a7540cdd1bf48ab220053ba0c`  
**Telegram-Addendum:** `docs/implementation-plan-addendum-telegram.md`  
**Ausgangsbasis:** `main@8f0bb05a540942e61c979a51bbaeca32d4308eb1`  
**Aktueller History-Dispatcher-Main:** `0934e85e53ae03d97df57ef494cd1aec7d141ef3`  
**Aktueller TeeBotus-Main:** `36c75843a5910cc3b22ffdd9a5ec87eb1d5b2ea9`  
**Nächster Produktschnitt:** produktiver Config-v2-Writer und native write-only Credentialgrenze

## Gemergte History-Dispatcher-Schnitte

| Schnitt | Inhalt | Main-Commit |
|---|---|---|
| PR-HD-01 | Baseline, ADRs und Sicherheitsverträge | `4ff947aba6da390dcff7adaea41e9e4871132eef` |
| PR-HD-02 | Codex-Fixtures, Sanitizer und Classifier | `d6b9fccdce5d429d07e182b1fff985c0fd1c8c40` |
| PR-HD-03 | transaktionale DB-v2-Migration | `ec3acf360cabc793835ecf3a8106fd1501897ba4` |
| PR-HD-04 | dualer Telegram-Providervertrag | `9d3f9420805986720e458d18876539962eab893f` |
| PR-HD-05 | providergebundener Route-/Delivery-Store | `74cec04ef6f06edf3ea3e5826f9fd4f3e5a1afc3` |
| PR-HD-06 | Config-v2-Vertrags- und Previewgrenze | `278f9a3198a54cde7495b1a3ce4fb0c85dabc246` |
| PR-HD-07 | redigierte Status-v2-API und Snapshot | `2efc7c7f68225936c79d06745ef0645cb3ec5999` |
| PR-HD-08a | versionierte Provider-v2-Worker-API | `01c791c252547c3766edfae97f2628a5c3cf6183` |
| PR-HD-09-plan | Cross-Repository-Rollout und Reihenfolge gepflegt | `c10623c24885618fbacdb4c84e6430359914a185` |
| PR-HD-08c | gezielter Reclaim abgelaufener Providerclaims | `0934e85e53ae03d97df57ef494cd1aec7d141ef3` |

## Gemergte TeeBotus-Schnitte

| Schnitt | Inhalt | Main-Commit |
|---|---|---|
| TB-HD-01 / PR-HD-08b | Provider-v2-Client, Claim-/Lease-/Recipient-API und verschlüsselter Callback-Spool | `5989b5129808486a9be272324285e6b5a02e76ab` |
| TB-HD-02 | expliziter `provider_v2`-Cutover, Batchworker, Reclaim/Rebind und Fault-Härtung | `36c75843a5910cc3b22ffdd9a5ec87eb1d5b2ea9` |

## Abgeschlossener Target-Reclaim

- [x] additive Operation `provider.v2.reclaim` implementiert;
- [x] exakte Target-, Provider-, Capability-, Binding- und Attemptprüfung;
- [x] aktive Claims werden nicht gestohlen;
- [x] terminale Targets werden nicht wieder geöffnet;
- [x] stale und Cross-Provider-Reclaims liefern keinen Claim;
- [x] abgelaufener Claim erzeugt neuen Attempt und neuen One-shot-Token;
- [x] alter offener Attempt wird als `reclaimed_expired` abgeschlossen;
- [x] Payload, Binding und Recipientzustände bleiben erhalten;
- [x] Antwort ist hart mit `reconciliation_only=true` markiert;
- [x] tokenhaltige Reclaims werden nicht im Idempotenz-Responsecache gespeichert;
- [x] leere Reclaimantworten sind tokenfrei und sicher replaybar;
- [x] Test-only-Head rot verifiziert, danach vollständige Actions-, qlty- und
  CodeRabbit-Gates grün;
- [x] PR #10 mit erwarteter Head-SHA gemergt.

## Abgeschlossener TeeBotus-Provider-v2-Cutover

### Aktivierung und Kompatibilität

- [x] expliziten Modus `TEEBOTUS_HISTORY_DISPATCHER_MODE=provider_v2` ergänzt;
- [x] `legacy`, `shadow` und `bridge` unverändert gelassen;
- [x] unbekannte Moduswerte fallen weiter auf `legacy`;
- [x] innerhalb von `provider_v2` kein automatischer Fallback auf Bridge, Legacy
  oder den nativen History-Dispatcher-Provider.

### Fail-closed Worker

- [x] verschlüsselten Callback-Spool vor jedem neuen Claim flushen;
- [x] unresolved Spool blockiert alle neuen Claims und Sends;
- [x] private routbare Recipientrefs vor dem Claim auflösen;
- [x] ohne routbare private Route keinen Claim anfordern;
- [x] dynamische opaque Recipientrefs registrieren;
- [x] erfolgreiche und `possible_duplicate`-Empfänger nicht erneut senden;
- [x] Lease vor jedem offenen Telegramtransport verlängern;
- [x] Recipientresultate vor Targetcompletion persistieren;
- [x] gespulte Recipient- oder Completioncallbacks blockieren den Batch;
- [x] phasen-, Target- und Attempt-gebundene Request-IDs verwenden;
- [x] Heartbeats vor und nach dem Batch senden;
- [x] rohe Telegram-Message-Refs vor zentraler Persistenz hashen.

### Verschlüsselter Callback-Rebind

- [x] spoolbare Envelopes enthalten Target, Provider, Worker, Capability und
  vorherige Attemptnummer;
- [x] ursprünglichen Callback vor jedem Reclaim exakt replayen;
- [x] Reclaim nur bei eindeutigen Claimablauf-Fehlern versuchen;
- [x] andere Protokoll-, Transport- und Berechtigungsfehler bleiben unverändert
  blockierend;
- [x] gezielt dieselbe Target-Delivery reclaimen;
- [x] neuen Token, nächsten Attempt und `reconciliation_only=true` prüfen;
- [x] verschlüsselte Spooldatei atomar auf neuen Token, Attempt und Request-ID
  umschreiben;
- [x] ausschließlich den ursprünglichen Recipient-/Completioncallback replayen;
- [x] nach erneutem Callbackfehler den bereits regebundenen Stand erhalten;
- [x] Transportadapter und Batchworker lehnen `reconciliation_only` im normalen
  Sendpfad vor Registrierung und Send ab;
- [x] kein Claimtoken liegt im Klartext auf Platte.

### Gateevidenz

- [x] fokussierter Provider-v2-/Rebind-Lauf grün;
- [x] fehlende Reconciliation-Sendgrenze zunächst mit zwei roten Tests
  reproduziert;
- [x] Defense-in-depth anschließend in Adapter und Worker umgesetzt;
- [x] finaler Actions-Lauf `30589642144`: Core, Benchmark, Audit und
  Plan2-Acceptance vollständig grün;
- [x] qlty und CodeRabbit auf finalem Head grün;
- [x] sämtliche Reviewthreads gelöst oder durch entfernte Hilfsworkflows
  veraltet;
- [x] TeeBotus PR #3 mit erwarteter Head-SHA gemergt.

## Noch offene Telegram-Arbeit

- [ ] produktiven Config-v2-Writer mit Revision, Validate, Preview, Apply und
  Audit implementieren;
- [ ] `routing.telegram.provider = teebotus | history_dispatcher` tatsächlich in
  der produktiven Konfiguration persistieren;
- [ ] native Credentialprofile und write-only Secret-Service-Tokenoperationen
  implementieren;
- [ ] native Recipientprofile ohne rohe Chat-IDs in Status, Config oder Applet
  implementieren;
- [ ] nativen Telegram-Bot-API-Client, Formatter und Segmentierung umsetzen;
- [ ] Telegram-`retry_after`, Rate-Limit, Backoff und Transport-Reconciliation
  gegen den gemeinsamen Storevertrag anbinden;
- [ ] nativen systemd-Worker und Heartbeatloop implementieren;
- [ ] vollständigen gemeinsamen Fault-Korpus für TeeBotus und nativen Provider
  abschließen;
- [ ] getrennte Canaries durchführen;
- [ ] Cinnamon-Settingsschalter erst auf vollständig vorhandener Backend- und
  Credentialgrenze aktivieren.

## Nächster sequenzieller Schnitt

Der nächste Schnitt ist **nicht** sofort der Bot-API-Worker. Zuerst wird die
bereits dokumentierte, aber noch nicht produktiv integrierte Config-v2- und
Credentialgrenze abgeschlossen:

1. striktes produktives Config-Schema für `routing.telegram.provider`;
2. revisionsgesicherte `get_redacted → validate → preview → apply`-Kette;
3. atomare Configbackups und `config_audit`;
4. write-only Secret-Service-Operationen für native Bot-Tokens;
5. opaque native Recipientprofile und redigierter Credentialstatus;
6. Tests gegen Token-, Chat-ID-, Snapshot-, Log- und dconf-Leaks.

Erst darauf folgt der native History-Dispatcher-Telegramworker.

## Pflegevorgabe

Ein Haken wird nur gesetzt, wenn Code oder Dokumentation vorhanden, die
zugehörigen Tests grün und der GitHub-Nachweis im Pull Request nachvollziehbar
ist. Mergeabhängige Punkte bleiben bis zum tatsächlichen Merge offen.
