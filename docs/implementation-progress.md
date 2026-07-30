# Implementierungsfortschritt: Cinnamon-Applet-Ausbau

**Planquelle:** `HISTORY_DISPATCHER_CINNAMON_APPLET_IMPLEMENTIERUNGSPLAN`, SHA-256 `a1f52c11117a063702f4cff008c9d24646f8f33a7540cdd1bf48ab220053ba0c`  
**Telegram-Addendum:** `docs/implementation-plan-addendum-telegram.md`  
**Ausgangsbasis:** `main@8f0bb05a540942e61c979a51bbaeca32d4308eb1`  
**Aktueller Main-Stand:** `c10623c24885618fbacdb4c84e6430359914a185`  
**Aktiver History-Dispatcher-Schnitt:** `PR-HD-08c-provider-v2-target-reclaim` / PR #10  
**Aktiver TeeBotus-Schnitt:** `TB-HD-02-provider-v2-cutover` / PR #3

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

## Gemergte TeeBotus-Grundlage

| Schnitt | Inhalt | Main-Commit |
|---|---|---|
| TB-HD-01 / PR-HD-08b | Provider-v2-Client, Claim-/Lease-/Recipient-API und verschlüsselter Callback-Spool | `5989b5129808486a9be272324285e6b5a02e76ab` |

Die Adaptergrundlage verwendet semantisch denselben secretfreien Fixture-Korpus
wie der History-Dispatcher. Claimtokens werden im separaten
`ProviderCallbackSpool` ausschließlich AES-256-GCM-verschlüsselt mit einem
per-instance Secret-Purpose und Instanzbindung als AAD gespeichert. Legacy-
Client, Legacy-Spool und die alten Bridgeoperationen bleiben kompatibel.

## Aktiver TeeBotus-Cutover: PR #3

Repository: `H234598/TeeBotus`  
Branch: `codex/history-dispatcher-provider-v2-cutover`  
Aktuell geprüfter Head: `ea44a025176ddef92154f37e64340048e6baf18c`

### Bereits umgesetzt

- [x] expliziten Modus `TEEBOTUS_HISTORY_DISPATCHER_MODE=provider_v2` ergänzt;
- [x] `legacy`, `shadow` und `bridge` unverändert gelassen;
- [x] kein automatischer Fallback bei Fehlern des Provider-v2-Pfads;
- [x] verschlüsselten Callback-Spool vor neuen Claims flushen;
- [x] unresolved Spool blockiert alle neuen Claims und Sends;
- [x] private routbare Empfänger vor dem Claim auflösen;
- [x] ohne routbare Empfänger keinen Claim anfordern;
- [x] dynamische opaque Recipientrefs registrieren;
- [x] erfolgreiche und `possible_duplicate`-Recipients nicht erneut senden;
- [x] Lease vor jedem offenen Transport verlängern;
- [x] Recipientresultate vor Targetcompletion persistieren;
- [x] gespulte Recipient- oder Completioncallbacks blockieren den Batch;
- [x] phasen-, Target- und Attempt-gebundene Request-IDs verwenden;
- [x] Heartbeats vor und nach dem Batch senden;
- [x] Claim-Payload begrenzt in das bestehende Telegram-Anhangformat übersetzen;
- [x] rohe Telegram-Message-Refs vor zentraler Persistenz hashen;
- [x] fokussierte Worker-/Bridge-/Legacy-Kompatibilitätstests grün.

### Blockierender Langzeitausfallfall

Nach Telegram-Accept kann der verschlüsselte Callback länger als die Claim-Lease
im Spool liegen. Der alte Claimtoken ist danach korrekt ungültig. Ohne gezielten
Reclaim könnte der Worker nur dauerhaft fail-closed blockieren oder unsicher
erneut senden. Deshalb bleibt TeeBotus PR #3 Draft, bis der folgende
History-Dispatcher-Reclaimvertrag gemergt und im Spool-Rebind konsumiert ist.

## Aktiver History-Dispatcher-Schnitt PR-HD-08c / PR #10

Branch: `codex/provider-v2-target-reclaim`

### Neuer Vertrag

- [x] additive Operation `provider.v2.reclaim` in Provider-API, Fixture und feste
  Same-User-Socket-Allowlist aufgenommen;
- [x] Reclaim verlangt exakte `target_delivery_id`, Provider, Worker,
  Capability, `previous_attempt_no` und Lease;
- [x] Reclaim ist ausschließlich für Callback-/Completion-Reconciliation
  bestimmt und liefert `reconciliation_only=true`;
- [x] aktive Claims werden nicht gestohlen;
- [x] terminale Targets werden nicht wieder geöffnet;
- [x] Provider-/Capability-/Binding-Mismatch liefert keinen Claim;
- [x] stale Attemptnummern werden abgewiesen;
- [x] abgelaufener Claim erzeugt einen neuen Attempt und neuen Token;
- [x] alte offene Attemptzeile wird als `reclaimed_expired` abgeschlossen;
- [x] verschlüsselte Payload sowie erfolgreiche und offene Recipientrefs bleiben
  erhalten;
- [x] Reclaimtoken ist one-shot und wird nicht in `response_json` gespeichert;
- [x] identischer tokenhaltiger Replay ergibt `idempotency_in_progress`;
- [x] leere Reclaimantworten sind tokenfrei und sicher cachebar;
- [x] kein Cross-Provider-Reclaim.

### TDD- und Gateevidenz

- [x] Test-only-Head `53b9a36d08f67af60fe69021a6cde7e51b5dc76a`
  rot verifiziert: sechs Reclaimtests scheiterten ausschließlich an der fehlenden
  Operation; Actions-Lauf `30585638088`;
- [x] Store-, API-, Socket-, one-shot- und Empty-Replay-Vertrag implementiert;
- [x] temporäre Patchinfrastruktur nach Anwendung entfernt;
- [x] vollständige Syntax-, Test- und Paketbuildkette auf Head
  `41bf2030600cc935b27afa82f2e4db9527ec0f17` grün; Actions-Lauf
  `30585978176`;
- [ ] Control-Protokoll, Providervertrag, README und Telegram-Addendum final
  pflegen;
- [ ] GitHub Actions, qlty und CodeRabbit auf finalem Dokumentationshead grün;
- [ ] alle Reviewthreads bearbeiten und lösen;
- [ ] PR #10 aus Draft nehmen und mit erwarteter Head-SHA mergen.

## Nach dem Reclaim-Merge

1. TeeBotus-Client und Fixture um `provider.v2.reclaim` erweitern;
2. verschlüsselte Spool-Envelopes um Target, Provider, Worker, Capability und
   vorherige Attemptnummer für einen sicheren Rebind ergänzen;
3. bei abgelaufenem Claim gezielt dieselbe Target-Delivery reclaimen;
4. Spoolatomar auf neuen Claimtoken, neue Attemptnummer und neue Request-ID
   umschreiben;
5. exakt den ursprünglichen Recipient-/Completioncallback replayen;
6. kein Telegram-Send im `reconciliation_only`-Pfad;
7. Crash-after-Accept-, langer Ausfall-, stale Rebind-, Cross-Provider- und
   Doppelversandtests grün machen;
8. TeeBotus PR #3 erst danach mergen.

## Nachfolgende Produktschnitte

- produktiver Config-v2-Writer und revisionsgesicherter Settingseditor;
- native Credentialprofile und write-only Secret-Service-Tokenoperationen;
- PR-HD-09-native-telegram-worker mit Bot-API, Formatter, Segmentierung,
  `retry_after`, Rate-Limit und systemd-Heartbeatloop;
- gemeinsamer Fault-Korpus und getrennte TeeBotus-/Native-Canaries;
- Cinnamon-Settingsschalter erst auf vollständig vorhandener Backendgrenze.

## Pflegevorgabe

Ein Haken wird nur gesetzt, wenn Code oder Dokumentation vorhanden, die
zugehörigen Tests grün und der GitHub-Nachweis im Pull Request nachvollziehbar
ist. Mergeabhängige Punkte bleiben bis zum tatsächlichen Merge offen.
