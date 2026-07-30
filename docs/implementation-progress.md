# Implementierungsfortschritt: Cinnamon-Applet-Ausbau

**Planquelle:** `HISTORY_DISPATCHER_CINNAMON_APPLET_IMPLEMENTIERUNGSPLAN`, SHA-256 `a1f52c11117a063702f4cff008c9d24646f8f33a7540cdd1bf48ab220053ba0c`  
**Telegram-Addendum:** `docs/implementation-plan-addendum-telegram.md`  
**Ausgangsbasis:** `main@8f0bb05a540942e61c979a51bbaeca32d4308eb1`  
**Aktuelle PR-Basis:** `main@2efc7c7f68225936c79d06745ef0645cb3ec5999`  
**Aktueller Schnitt:** `PR-HD-08a-provider-v2-api`  
**Branch:** `codex/teebotus-provider-v2`

## Gemergte Schnitte

| Schnitt | Inhalt | Main-Commit |
|---|---|---|
| PR-HD-01 | Baseline, ADRs, Sicherheitsverträge | `4ff947aba6da390dcff7adaea41e9e4871132eef` |
| PR-HD-02 | Codex-Fixtures, Sanitizer, Classifier | `d6b9fccdce5d429d07e182b1fff985c0fd1c8c40` |
| PR-HD-03 | transaktionale DB-v2-Migration | `ec3acf360cabc793835ecf3a8106fd1501897ba4` |
| PR-HD-04 | dualer Telegram-Providervertrag | `9d3f9420805986720e458d18876539962eab893f` |
| PR-HD-06 | Config-v2-Vertrags- und Previewgrenze | `278f9a3198a54cde7495b1a3ce4fb0c85dabc246` |
| PR-HD-05 | providergebundener Route-/Delivery-Store | `74cec04ef6f06edf3ea3e5826f9fd4f3e5a1afc3` |
| PR-HD-07 | redigierte Status-v2-API und Snapshot | `2efc7c7f68225936c79d06745ef0645cb3ec5999` |

## Status PR-HD-08a

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

### TDD- und Gateevidenz

- [x] Test-only-Head `0458352b26fa1a2b9820c6a3732c0597226d5e4c`
  erwartungsgemäß rot wegen fehlendem `provider_api_v2`;
- [x] erster vollständiger Providerpfad implementiert und grün gemacht;
- [x] zusätzliche one-shot-/empty-poll-Tests zunächst rot reproduziert;
- [x] Funktionshead `7b1ef3111bb516bb5d21bfacdd656d28b9f3a590`:
  Syntax, vollständige Tests und Paketbuild grün, Actions-Lauf `30578039473`;
- [x] CodeRabbit auf dem Funktionshead grün;
- [ ] GitHub Actions, qlty und CodeRabbit auf dem finalen Dokumentationshead grün;
- [ ] alle finalen Reviewthreads bearbeitet und gelöst;
- [ ] PR #8 aus Draft genommen und mit erwarteter Head-SHA gemergt.

## Bewusste Schnittgrenze

PR-HD-08a sendet keine Telegramnachricht. Er definiert und implementiert nur
den sicheren Worker-/Storevertrag. TeeBotus bleibt bis zum gepaarten Adapter-PR
auf seinem bisherigen Legacy-/Bridgepfad. Der native Telegramworker und seine
Secret-Service-Credentials bleiben PR-HD-09.

## Nächste Schritte

1. finale Gates und Merge von PR-HD-08a;
2. gepaarter TeeBotus-PR `TB-HD-01-provider-v2-adapter`;
3. TeeBotus nutzt Claimtoken, Lease, dynamische opaque Accountrefs,
   Recipientresultate, Completion, Heartbeat und Callback-Spool;
4. derselbe Fixture-Korpus läuft in beiden Repositorys;
5. danach PR-HD-09 für den nativen Telegramworker.

## Pflegevorgabe

Ein Haken wird nur gesetzt, wenn Code oder Dokumentation vorhanden, die
zugehörigen Tests grün und der GitHub-Nachweis im Pull Request nachvollziehbar
ist. Mergeabhängige Punkte bleiben bis zum tatsächlichen Merge offen.
