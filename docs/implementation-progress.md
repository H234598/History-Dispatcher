# Implementierungsfortschritt: Cinnamon-Applet-Ausbau

**Planquelle:** `HISTORY_DISPATCHER_CINNAMON_APPLET_IMPLEMENTIERUNGSPLAN`, SHA-256 `a1f52c11117a063702f4cff008c9d24646f8f33a7540cdd1bf48ab220053ba0c`  
**Telegram-Addendum:** `docs/implementation-plan-addendum-telegram.md`  
**Ausgangsbasis:** `main@8f0bb05a540942e61c979a51bbaeca32d4308eb1`  
**Aktueller History-Dispatcher-Main:** `7d3944bc1bf70114a4b0c381014eabbc3e84c30c`  
**Aktueller TeeBotus-Main:** `36c75843a5910cc3b22ffdd9a5ec87eb1d5b2ea9`  
**Aktiver Schnitt:** PR #12 `codex/config-v2-writer`  
**Nächster separat reviewbarer Schnitt:** native write-only Secret-Service-Credentialgrenze

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
| PR-HD-11-plan | Reclaim-/TeeBotus-Merge-SHAs und nächste Reihenfolge synchronisiert | `7d3944bc1bf70114a4b0c381014eabbc3e84c30c` |

## Gemergte TeeBotus-Schnitte

| Schnitt | Inhalt | Main-Commit |
|---|---|---|
| TB-HD-01 / PR-HD-08b | Provider-v2-Client, Claim-/Lease-/Recipient-API und verschlüsselter Callback-Spool | `5989b5129808486a9be272324285e6b5a02e76ab` |
| TB-HD-02 | expliziter `provider_v2`-Cutover, Batchworker, Reclaim/Rebind und Fault-Härtung | `36c75843a5910cc3b22ffdd9a5ec87eb1d5b2ea9` |

## Abgeschlossene Provider-v2- und Reclaimgrenze

- [x] Provider-v2-Claim, Renew, Recipient-, Completion- und Heartbeat-API;
- [x] tokenhaltige Claims one-shot und tokenfreie leere Polls replaybar;
- [x] gezielter Reclaim exakt einer abgelaufenen Target-Delivery;
- [x] Provider-, Capability-, Binding-, Attempt- und Terminalprüfung;
- [x] `reconciliation_only=true` und Defense-in-depth gegen neuen Send;
- [x] verschlüsselter TeeBotus-Callback-Spool und atomarer Token-/Attempt-Rebind;
- [x] kein Cross-Provider-Fallback und kein Doppelversand;
- [x] vollständige TeeBotus Core-, Benchmark-, Audit-, Plan2-, qlty- und
  CodeRabbit-Gates.

## Aktiver Schnitt: produktiver Config-v2-Writer

### Produktives TOML-Modell

- [x] `[routing.telegram]` in der echten Config implementiert;
- [x] Provider exakt `teebotus | history_dispatcher`;
- [x] opaque `credential_ref` und maximal 32 opaque `recipient_refs`;
- [x] stabile Deduplizierung und TOML-Roundtrip;
- [x] Tokens, rohe Chat-IDs, Pfade, Steuerzeichen und unbekannte Keys abgewiesen;
- [x] native Profile im TeeBotus-Modus abgewiesen;
- [x] Routingwerte in `config_revision()` aufgenommen.

### Patch, Preview und Compare-and-Swap

- [x] kanonische, endliche und auf 64 KiB begrenzte Patches;
- [x] deterministische SHA-256-Fingerprints;
- [x] 60 Sekunden gültige One-use-Previewtokens;
- [x] höchstens 128 aktive Previeweinträge;
- [x] exakte Bestätigung `APPLY <erste 12 Fingerprint-Zeichen>`;
- [x] Wirkung hart als `new_route_plans_only` ausgewiesen;
- [x] Revision vor Preview und unmittelbar vor Apply geprüft;
- [x] Previewtoken vor jeder Mutation verbraucht;
- [x] Fingerprint und Bestätigung konstantzeitverglichen.

### Write, Audit und Rollback

- [x] bestehender owner-only atomarer TOML-Writer verwendet;
- [x] Post-Write-Reload und erwartete neue Revision verifiziert;
- [x] HMAC-pseudonymisierter Configactor;
- [x] bounded `config_audit` ohne Patchwerte, Recipientrefs oder Token;
- [x] fehlende Audittabelle fail-closed;
- [x] abgewiesene Revisionen und Autorisierungsfehler auditiert;
- [x] vollständiger Dateirückbau bei Write-, Reload- oder Auditfehler;
- [x] In-Memory-Config nach Rollback auf vorherigen Stand zurückgeführt.

### Same-User-Socket und Legacykompatibilität

- [x] additive Operation `config.get_redacted`;
- [x] additive request-idempotente Operation `config.validate_patch`;
- [x] additive one-shot Operation `config.preview_apply` ohne Token im
  Idempotenz-Responsecache;
- [x] previewgestütztes request-idempotentes `config.apply`;
- [x] Request-ID für neue Config-v2-Mutationen erzwungen;
- [x] identischer Apply-Replay liefert dieselbe sichere Antwort;
- [x] verbrauchter Previewtoken unter anderer Request-ID abgewiesen;
- [x] Same-User-Unix-Socket-End-to-End-Test;
- [x] `config.get`, path-basiertes `config.validate` und flaches Legacy-
  `config.apply` unverändert;
- [x] Legacy-Apply synchronisiert einen bereits erzeugten Config-v2-Manager;
- [x] Status-v2 veröffentlicht nach Apply den aktuellen Provider;
- [x] Previewtoken, Bot-Token und rohe Chat-ID fehlen im Snapshot.

### TDD- und Gateevidenz

- [x] Task 1 rot wegen fehlendem `[routing]` reproduziert, danach vollständige
  Suite und Build grün;
- [x] Task 2 rot wegen fehlendem `ConfigManagerV2` reproduziert, danach grün;
- [x] Task 3 rot wegen fehlendem Applypfad reproduziert, danach Actions-Lauf
  `30591377648` vollständig grün;
- [x] Task 4 rot mit exakt drei `unknown_operation`-Fehlern und 247 grünen
  Bestandstests reproduziert;
- [x] Task 4 anschließend mit vollständiger Suite und Paketbuild grün;
- [x] temporäre Patchworkflows und Hilfsskripte vollständig entfernt;
- [ ] finale Dokumentationshead-Actions, qlty und CodeRabbit grün;
- [ ] keine offenen Reviewthreads;
- [ ] PR #12 aus Draft genommen und gegen exakte Head-SHA gemergt.

## Bewusste Schnittgrenze

PR #12 schreibt und liest keinen Telegram-Bot-Token. `credential_ref` ist nur
ein opaque Profilname. Der Status meldet weiterhin keinen geheimen
Credentialwert. Der Config-v2-Apply verändert ausschließlich zukünftige
Route-Pläne und führt keine Migration, Neuplanung oder Providerfallbacks aus.

## Noch offene Telegram-Arbeit

- [ ] native write-only Secret-Service-Operationen zum Setzen, Ersetzen und
  Löschen eines Bot-Tokens;
- [ ] Credentialstatus und bestätigter Credentialtest ohne Secretwert;
- [ ] native Recipientprofile mit Secret-/owner-only Auflösung der Chat-IDs;
- [ ] nativer Telegram-Bot-API-Client, Formatter und Segmentierung;
- [ ] Telegram-`retry_after`, Rate-Limit und Transport-Reconciliation;
- [ ] nativer systemd-Worker und Heartbeatloop;
- [ ] vollständiger gemeinsamer Fault-Korpus beider Provider;
- [ ] getrennte Canaries;
- [ ] Cinnamon-Settingsschalter gegen die vollständige Backend- und
  Credentialgrenze.

## Nächster sequenzieller Schnitt

Nach Merge von PR #12 folgt ein eigener Credential-PR:

1. Secret-Service-Attribute für opaque Credentialprofile;
2. write-only Setzen/Ersetzen/Löschen des Bot-Tokens;
3. Tokenformat- und Secret-Service-Fehlergrenzen;
4. Credentialstatus `configured` und `last_changed` ohne Tokenwert;
5. bestätigter Verbindungstest;
6. Audit-, API-, TOML-, Snapshot-, Log- und dconf-Leaktests.

Erst danach folgt der native History-Dispatcher-Telegramworker.

## Pflegevorgabe

Ein Haken wird nur gesetzt, wenn Code oder Dokumentation vorhanden, die
zugehörigen Tests grün und der GitHub-Nachweis im Pull Request nachvollziehbar
ist. Mergeabhängige Punkte bleiben bis zum tatsächlichen Merge offen.
