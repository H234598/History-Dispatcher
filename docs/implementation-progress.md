# Implementierungsfortschritt: Cinnamon-Applet-Ausbau

**Planquelle:** `HISTORY_DISPATCHER_CINNAMON_APPLET_IMPLEMENTIERUNGSPLAN`, SHA-256 `a1f52c11117a063702f4cff008c9d24646f8f33a7540cdd1bf48ab220053ba0c`  
**Telegram-Addendum:** `docs/implementation-plan-addendum-telegram.md`  
**Ausgangsbasis:** `main@8f0bb05a540942e61c979a51bbaeca32d4308eb1`  
**Aktueller Main-Stand:** `01c791c252547c3766edfae97f2628a5c3cf6183`  
**Aktiver Cross-Repository-Schnitt:** `PR-HD-08b / TB-HD-01-provider-v2-adapter-foundation`  
**Folgeschnitt:** `TB-HD-02-provider-v2-cutover`

## Gemergte History-Dispatcher-Schnitte

| Schnitt | Inhalt | Main-Commit |
|---|---|---|
| PR-HD-01 | Baseline, ADRs, Sicherheitsverträge | `4ff947aba6da390dcff7adaea41e9e4871132eef` |
| PR-HD-02 | Codex-Fixtures, Sanitizer, Classifier | `d6b9fccdce5d429d07e182b1fff985c0fd1c8c40` |
| PR-HD-03 | transaktionale DB-v2-Migration | `ec3acf360cabc793835ecf3a8106fd1501897ba4` |
| PR-HD-04 | dualer Telegram-Providervertrag | `9d3f9420805986720e458d18876539962eab893f` |
| PR-HD-06 | Config-v2-Vertrags- und Previewgrenze | `278f9a3198a54cde7495b1a3ce4fb0c85dabc246` |
| PR-HD-05 | providergebundener Route-/Delivery-Store | `74cec04ef6f06edf3ea3e5826f9fd4f3e5a1afc3` |
| PR-HD-07 | redigierte Status-v2-API und Snapshot | `2efc7c7f68225936c79d06745ef0645cb3ec5999` |
| PR-HD-08a | versionierte Provider-v2-Worker-API | `01c791c252547c3766edfae97f2628a5c3cf6183` |

## Abgeschlossener Schnitt PR-HD-08a

### Gemeinsamer Contract-Fixture-Korpus

- [x] `tests/fixtures/provider-v2/contract.json` angelegt;
- [x] Schema-Version `2`, Provider `teebotus`, Target `telegram` und Capability
  `history-dispatcher-telegram-v2` eingefroren;
- [x] künstliche opaque Recipient-/Message-Referenzen verwendet;
- [x] Token- und Chat-ID-Leaknegative Tests ergänzt;
- [x] Operationsreihenfolge für beide Repositoryadapter festgelegt.

### ProviderApiV2

- [x] `provider.v2.claim` implementiert;
- [x] `provider.v2.renew` implementiert;
- [x] `provider.v2.register_recipients` implementiert;
- [x] `provider.v2.record_recipients` implementiert;
- [x] `provider.v2.complete` implementiert;
- [x] `provider.v2.heartbeat` implementiert;
- [x] strikte Feldallowlists, Body-/Array-/Zahlen-/Jittergrenzen und endliches
  JSON implementiert;
- [x] Provider-/Capability-Mismatch ohne Fallback getestet;
- [x] alle Provideroperationen in die feste Same-User-Socket-Allowlist
  aufgenommen und Request-ID-pflichtig gemacht.

### Idempotenz- und Tokengrenze

- [x] normale Provider-Mutationen dauerhaft idempotent gecacht;
- [x] `IdempotencyStore.release()` für exakt passende, noch leere
  Reservierungen implementiert;
- [x] abgeschlossene Antworten gegen Release geschützt;
- [x] Claimantworten mit Token niemals in `response_json` persistiert;
- [x] identischer tokenhaltiger Claim-Replay ergibt `idempotency_in_progress`;
- [x] abweichender Replay ergibt `idempotency_conflict`;
- [x] kein zweiter Attempt bei Replay;
- [x] Claimtoken nicht in den SQLite-Dateibytes vorhanden;
- [x] reine Validierungsfehler geben die Reservierung für korrigierten Request
  frei;
- [x] erfolgreiche leere Claimantworten tokenfrei gecacht und sicher replaybar.

### Gate- und Mergeevidenz

- [x] Test-only-Head `0458352b26fa1a2b9820c6a3732c0597226d5e4c`
  erwartungsgemäß rot wegen fehlendem `provider_api_v2`;
- [x] one-shot-/empty-poll-Härtung zunächst rot reproduziert;
- [x] Funktionshead `7b1ef3111bb516bb5d21bfacdd656d28b9f3a590`:
  Syntax, vollständige Tests und Paketbuild grün, Actions-Lauf `30578039473`;
- [x] finaler Head `a31b8d01bee2214ad7031182353906af9e9148a8`:
  GitHub Actions, qlty und CodeRabbit grün; keine offenen Reviewthreads;
- [x] PR #8 per Squash mit erwarteter Head-SHA gemergt;
- [x] Main-Commit `01c791c252547c3766edfae97f2628a5c3cf6183`.

## Aktiver Cross-Repository-Schnitt PR-HD-08b / TB-HD-01

Repository: `H234598/TeeBotus`  
PR: `#2 feat: add History-Dispatcher provider v2 adapter foundation`  
Branch: `codex/history-dispatcher-provider-v2`

### Adaptergrundlage

- [x] semantisch identischen, secretfreien Provider-v2-Fixture-Korpus in
  TeeBotus angelegt;
- [x] explizite Request-IDs im Unix-Socket-Client implementiert;
- [x] Claimresponse auf Schema, Provider, Target, Capability, Worker, Binding,
  Token, Payload und Recipientlisten fail-closed validiert;
- [x] Renew, dynamische opaque Recipientregistrierung, Recipientresultate,
  Completion und Heartbeat implementiert;
- [x] separaten verschlüsselten `ProviderCallbackSpool` implementiert;
- [x] AES-256-GCM, separaten per-instance Secret-Purpose, Instanzbindung als
  AAD, owner-only Dateien und atomaren Replayvertrag umgesetzt;
- [x] Claimtoken im Spool nicht im Klartext gespeichert;
- [x] bestehende Legacy-Bridge-Methoden und Legacy-Callback-Spool unverändert
  kompatibel gehalten;
- [x] fokussierten Bridge-/Provider-v2-Lauf `30579312585` grün gemacht;
- [x] Provider-Test in das vollständige Plan2-Testinventar aufgenommen;
- [x] unabhängige one-shot-FD-Reuse-Fixture im Runtime-Maintenance-Test
  deterministisch korrigiert;
- [x] qlty und CodeRabbit auf dem bereinigten finalen Head grün;
- [ ] vollständigen TeeBotus-Gesamtlauf `30580563598` grün abschließen;
- [ ] PR #2 aus Draft nehmen und gegen exakte Head-SHA mergen.

## Gestapelter Folgeschnitt TB-HD-02-provider-v2-cutover

Repository: `H234598/TeeBotus`  
PR: `#3 test: define provider v2 dispatch worker cutover`  
Branch: `codex/history-dispatcher-provider-v2-cutover`

### Provider-v2-Batchworker

- [x] Callback-Spool vor jedem neuen Claim flushen;
- [x] bei unresolved Callback-Spool alle neuen Claims und Sends blockieren;
- [x] ohne routbare Recipientrefs keinen Claim anfordern;
- [x] dynamische Recipientrefs registrieren;
- [x] bereits erfolgreiche Recipientrefs auslassen;
- [x] Lease vor jedem offenen Transport verlängern;
- [x] Transportfehler als Recipientresultat melden statt Prozessabbruch;
- [x] Recipientresultate vor Targetcompletion persistieren;
- [x] gespulte Recipientresultate und gespulte Completion fail-closed blockieren;
- [x] stabile phasen-/Target-/Attempt-gebundene Request-IDs verwenden;
- [x] Workerheartbeats vor und nach dem Batch senden;
- [x] `possible_duplicate` niemals erneut senden;
- [x] fokussierten Bridge-/Worker-/Legacy-Kompatibilitätslauf
  `30580145725` grün gemacht;
- [ ] Foundation-PR #2 mergen und Cutover-Branch sauber auf TeeBotus-`main`
  neu aufbauen;
- [ ] Worker-/Fault-Tests in das vollständige Plan2-Testinventar aufnehmen;
- [ ] tatsächlichen `codex-history`-Dispatchloop in einem expliziten
  Provider-v2-Modus anbinden;
- [ ] private Route vor Claim, Sendadapter, Claim-Rebind und
  Crash-after-Accept-Reconciliation vollständig testen;
- [ ] qlty, CodeRabbit und vollständige TeeBotus-Actions grün;
- [ ] Cutover-PR mergen.

## Bewusste Schnittgrenze

Der History-Dispatcher-Providervertrag ist produktiv vorhanden, sendet aber
selbst keine Telegramnachricht. TeeBotus besitzt bereits die sichere
Adaptergrundlage, der bestehende `legacy`/`shadow`/`bridge`-Betrieb bleibt jedoch
bis zum vollständigen Cutover-/Fault-Korpus unverändert.

Es gibt weiterhin:

- keinen automatischen Cross-Provider-Fallback;
- keinen Klartext-Claimtoken im Spool;
- keinen erneuten Send für erfolgreiche oder `possible_duplicate`-Recipients;
- keinen nativen Bot-API-Client im History-Dispatcher;
- keinen Appletzugriff auf Claims oder Credentials.

## Nächste Schritte

1. TeeBotus-Foundation-Gesamtlauf abschließen und PR #2 mergen;
2. gestapelten Cutover-PR auf den gemergten TeeBotus-Mainstand neu aufbauen;
3. `dispatch_codex_history_outbox` über den getesteten Provider-v2-Worker
   anbinden, ohne Legacy-Fallback;
4. Crash-after-Accept, Claimablauf/Rebind, Hänger, Rate-Limit, Oversize und
   Recipient-Partial-Fault-Korpus grün machen;
5. TeeBotus-Cutover mergen;
6. anschließend PR-HD-09 für den nativen History-Dispatcher-Telegramworker mit
   Secret-Service-Credentials, Bot-API, Formatter und Rate-Limit beginnen.

## Pflegevorgabe

Ein Haken wird nur gesetzt, wenn Code oder Dokumentation vorhanden, die
zugehörigen Tests grün und der GitHub-Nachweis im Pull Request nachvollziehbar
ist. Mergeabhängige Punkte bleiben bis zum tatsächlichen Merge offen.
