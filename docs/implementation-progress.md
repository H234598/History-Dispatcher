---
title: History-Dispatcher Implementierungsfortschritt
tags:
  - history-dispatcher
  - cinnamon
  - telegram
  - implementation
  - progress
type: implementation-progress
status: active
date: 2026-07-31
created: 2026-07-28
aliases:
  - Cinnamon-Applet-Ausbau Fortschritt
  - History-Dispatcher Roadmap Status
---

# Implementierungsfortschritt: Cinnamon-Applet-Ausbau

**Planquelle:** `HISTORY_DISPATCHER_CINNAMON_APPLET_IMPLEMENTIERUNGSPLAN`, SHA-256 `a1f52c11117a063702f4cff008c9d24646f8f33a7540cdd1bf48ab220053ba0c`  
**Telegram-Addendum:** `docs/implementation-plan-addendum-telegram.md`  
**Ausgangsbasis:** `main@8f0bb05a540942e61c979a51bbaeca32d4308eb1`  
**Aktueller History-Dispatcher-Main:** `bb335259f16797ec385b2eee13d0fcc49a931426`
**Aktueller TeeBotus-Main:** `36c75843a5910cc3b22ffdd9a5ec87eb1d5b2ea9`  
**Abgeschlossene Schnitte:** PR #13 native Telegram-Credentialgrenze und PR #14 Plan-Sync

**Aktiver Schnitt:** PR #15 `codex/native-telegram-worker`

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
| PR-HD-09-plan | Cross-Repository-Rollout und Reihenfolge | `c10623c24885618fbacdb4c84e6430359914a185` |
| PR-HD-08c | gezielter Reclaim abgelaufener Providerclaims | `0934e85e53ae03d97df57ef494cd1aec7d141ef3` |
| PR-HD-11-plan | Reclaim-/TeeBotus-Merge-SHAs synchronisiert | `7d3944bc1bf70114a4b0c381014eabbc3e84c30c` |
| PR-HD-12 | produktiver Config-v2-Writer, Preview/Apply, Audit und Same-User-API | `decd370f8359979beff59da0b4dbf81208fb044a` |
| PR-HD-13 | Secret-Service-Credentialgrenze, Schema v4, Kompensation und write-only Same-User-API | `cd35d5807cef1834e0c4d6d6f0a18e81b7e3cda4` |

## Gemergte TeeBotus-Schnitte

| Schnitt | Inhalt | Main-Commit |
|---|---|---|
| TB-HD-01 / PR-HD-08b | Provider-v2-Client, Lease-/Recipient-API und verschlüsselter Callback-Spool | `5989b5129808486a9be272324285e6b5a02e76ab` |
| TB-HD-02 | expliziter `provider_v2`-Cutover, Reclaim/Rebind und Fault-Härtung | `36c75843a5910cc3b22ffdd9a5ec87eb1d5b2ea9` |

## Abgeschlossene Routing-, Provider- und Configgrenze

- [x] zwei unveränderlich gebundene Telegramprovider `teebotus | history_dispatcher`;
- [x] kein automatischer Cross-Provider-Fallback;
- [x] target-/provider-/capability-/workergebundene Claims, Leases und Attempts;
- [x] monotone Recipientzustände, `possible_duplicate` und Partial-Reconciliation;
- [x] gezielter Reclaim abgelaufener Claims ausschließlich für Callback-Reconciliation;
- [x] verschlüsselter TeeBotus-Callback-Spool und atomarer Rebind ohne neuen Send;
- [x] produktives `[routing.telegram]`-TOML-Modell;
- [x] Config-v2 Validate/Preview/Apply mit Revision-CAS, Audit und Rollback;
- [x] Same-User-Socket-API und Status-v2-Provideraktualisierung;
- [x] PR #12 auf finalem Head `397749480896bd8a52a0ffef78d3bff2c581ff6a` vollständig grün und squash-gemergt;
- [x] keine Bot-Tokenwrites im Config-v2-Schnitt.

## Abgeschlossener Schnitt: native write-only Telegram-Credentials

### Architektur und TDD-Plan

- [x] Design unter `docs/superpowers/specs/2026-07-31-native-telegram-credentials-design.md` dokumentiert;
- [x] ausführbaren TDD-Plan unter `docs/superpowers/plans/2026-07-31-native-telegram-credentials.md` angelegt;
- [x] Secret Service als einzige Secretwert-Persistenz gewählt;
- [x] getrennte Secretarten für Bot-Token und Recipient-Chat-ID;
- [x] kein File-, Env- oder Zufallsfallback;
- [x] keine Telegram-Netzwerkoperation in diesem Schnitt.

### Schema v4 und Operator-Migration

- [x] additive Datenbankversion 4 implementiert;
- [x] secretfreie Tabelle `telegram_secret_metadata`;
- [x] secretfreie Tabelle `credential_audit`;
- [x] HMAC-pseudonymisierte Profil- und Actorkeys;
- [x] keine Token-, Chat-ID-, Secretwert- oder Klartextprofilspalte;
- [x] vollständige v3-Verifikation als Voraussetzung;
- [x] aktive v1-/Targetclaims blockieren Migration;
- [x] schreibfreier Dry Run;
- [x] owner-only verifiziertes Backup;
- [x] Apply nur mit `--apply --confirm MIGRATE-CREDENTIALS-V4`;
- [x] idempotenter zweiter Lauf und eigenständiges Verify;
- [x] Actions-Lauf `30626526124` vollständig grün.

### Strikter Secret-Service-Store

- [x] `secret-tool store` übergibt Secret ausschließlich via stdin;
- [x] exakte Attribute `application`, `purpose`, `profile`;
- [x] getrennte Purposes `telegram-bot-token` und `telegram-chat-id`;
- [x] fünf Sekunden Subprozess-Timeout;
- [x] stdout/stderr und Secretwerte werden nicht in Fehlern gespiegelt;
- [x] strikte Bot-Token- und Chat-ID-Validierung;
- [x] bestehende opaque Config-v2-Profilnormalisierung verwendet;
- [x] interne Lookupmethoden ausschließlich für Manager/späteren Worker;
- [x] vollständige Suite und Build auf Actions-Lauf `30626677611` grün.

### Credential Preview, Apply und Kompensation

- [x] Actions `set | replace | delete`;
- [x] Secretarten `bot_token | chat_id`;
- [x] Config-v2-Autorisierung für aktuelles Credential-/Recipientprofil;
- [x] Secretwert ausschließlich im begrenzten In-Memory-Preview;
- [x] 60-Sekunden-One-use-Previewtoken und maximal 128 Previews;
- [x] key-abgeleitete Secretwertidentität im Fingerprint, nicht separat ausgegeben;
- [x] exakte Bestätigung `CREDENTIAL <ACTION> <Fingerprint-Präfix>`;
- [x] Config unmittelbar vor Mutation neu geladen und reautorisiert;
- [x] `set` verlangt Abwesenheit, `replace/delete` verlangen vorhandenen Wert;
- [x] Post-Write-/Post-Delete-Verifikation;
- [x] Metadaten und Audit in einer SQLite-Transaktion;
- [x] vollständige Secret-Service-Kompensation bei DB-/Auditfehler;
- [x] terminaler Fehler `credential_rollback_failed` bei fehlgeschlagener Kompensation;
- [x] Status liest ausschließlich Metadaten und führt keinen Secretlookup aus;
- [x] Actions-Lauf `30627063391` vollständig grün.

### Same-User-API und Statusintegration

- [x] additive Read-only-Operation `credential.get_status`;
- [x] additive sensible One-shot-Operation `credential.preview_apply`;
- [x] additive dauerhaft idempotente Operation `credential.apply`;
- [x] Request-ID für Preview und Apply erzwungen;
- [x] Previewantwort nie im Idempotenz-Responsecache;
- [x] reine Validierungsfehler geben exakte leere Reservierung frei;
- [x] identischer Apply-Replay führt keine zweite Secretmutation aus;
- [x] verbrauchter Previewtoken unter anderer Request-ID wird abgewiesen;
- [x] Same-User-Unix-Socket-End-to-End-Test;
- [x] Status-v2 publiziert nur `configured` und `last_changed` des aktuellen Botprofils;
- [x] vor Schema v4 oder ohne Profil bleibt Status fail-closed `configured=false`;
- [x] Token und Chat-ID fehlen in API, TOML, SQLitebytes und Snapshot;
- [x] 297 Tests, Syntax und Paketbuild auf Actions-Lauf `30627562605` grün;
- [x] temporäre Patchskripte und Hilfsworkflows entfernt.

### Dokumentation und finale Gates

- [x] Betreiber-Runbook `docs/native-telegram-credentials.md` angelegt;
- [x] Control-Protokoll um Credentialoperationen und Idempotenzregeln erweitert;
- [x] Fortschrittsplan auf tatsächlichen Merge-/Teststand aktualisiert;
- [x] Telegram-Addendum und README final aktualisiert;
- [x] ausführbaren TDD-Plan mit belegter Evidenz abgeglichen;
- [x] repositoryweiten Leakscan durchgeführt; Funktionshead `60103e66d8785a79abe6a7dd3f90d3e116789cc1` mit 298 Tests, Syntax und Paketbuild grün;
- [x] GitHub Actions, qlty und CodeRabbit auf finalem Head `c8da7593d235af6e03c101bc0ee4242690c9a0f9` grün;
- [x] keine offenen Reviewthreads;
- [x] PR #13 gegen `c8da7593d235af6e03c101bc0ee4242690c9a0f9` squash-gemergt; Main-Commit `cd35d5807cef1834e0c4d6d6f0a18e81b7e3cda4`.

## Bewusste Schnittgrenze

Der gemergte PR #13 führt keine Telegram-Netzwerkoperation aus. Es gibt weder `getMe` noch
Testnachricht, Bot-API-Client, Formatter, Rate-Limit-Handling oder systemd-
Worker. Der öffentliche API-Vertrag bleibt write-only: Secretwerte werden nie
ausgelesen oder zurückgegeben.

Metadata `configured=true` bedeutet, dass ein erfolgreicher API-Apply den
Secretwert geschrieben und intern verifiziert hat. Der spätere Worker löst den
Wert dennoch bei jeder Nutzung fail-closed auf, da externe Keyringänderungen
nicht über den öffentlichen Status gespiegelt werden.

## Aktiver sequenzieller Schnitt

PR #15 implementiert den nativen Telegramworker:

1. interner Bot-Token- und Chat-ID-Lookup;
2. gehärteter Bot-API-Client mit TLS, Timeouts und bounded Antworten;
3. deterministische Formatierung und Segmentierung;
4. Telegram-`retry_after`, Backoff und Rate-Limit;
5. empfängerweise Resultate und Crash-after-Accept-Reconciliation;
6. systemd-User-Worker und Heartbeat;
7. gemeinsamer Fault-Korpus gegen TeeBotus und Native;
8. getrennte Canaries ohne Cross-Provider-Doppelversand.


### PR #15: belegter Fortschritt

- [x] Designspezifikation `docs/superpowers/specs/2026-07-31-native-telegram-worker-design.md` angelegt;
- [x] ausführbaren TDD-Plan `docs/superpowers/plans/2026-07-31-native-telegram-worker.md` angelegt;
- [x] festen HTTPS-Client für `api.telegram.org:443` ohne Proxy-, Redirect- oder konfigurierbaren URL-Pfad implementiert;
- [x] TLS-, Timeout-, Request-, Multipart- und Responsegrenzen getestet;
- [x] Telegram `retry_after` auf den gemeinsamen Backoffvertrag abgebildet;
- [x] Fehler vor dem Request retrybar und Fehler nach erfolgreichem Connect als `possible_duplicate` klassifiziert;
- [x] deterministischen Plain-Text-Formatter mit genau einem UTF-8-Textdokument-Fallback implementiert;
- [x] native Provider-v2-Claim-/Renew-/Recipient-/Complete-Lifecycle implementiert;
- [x] Recipientzustand vor jedem Send idempotent geprüft; `possible_duplicate` und andere terminale Empfänger werden nicht erneut gesendet;
- [x] terminalen Recipientstatus `failed_terminal` im gemeinsamen Telegramvertrag monotone ergänzt;
- [x] versionierten gemeinsamen Native-Fault-Korpus mit acht Szenarien angelegt;
- [x] CLI-Befehl `telegram-worker` und Signalstop implementiert;
- [x] separate gehärtete systemd-Workerunit implementiert; ausschließlich diese Unit erhält `AF_INET/AF_INET6`;
- [x] Workeraktivierung bleibt explizites Opt-in `--enable-telegram-worker`;
- [x] redigierte Status-v2-Providererkennung aus Heartbeatdetails implementiert;
- [x] Task-4-Abschlusshead auf Actions-Lauf `30635389842` mit Syntax, vollständiger Testsuite und Paketbuild grün;
- [ ] Betreiber-Runbook, README, Telegram-Addendum und finalen PR-Vertrag aktualisieren;
- [ ] vollständigen Leak-/Netzwerkgrenzenscan auf finalem Dokumentationshead durchführen;
- [ ] qlty und CodeRabbit auf finalem Head grün;
- [ ] keine offenen Reviewthreads;
- [ ] PR #15 gegen exakte geprüfte Head-SHA squash-mergen;
- [ ] Live-Canary ohne Cross-Provider-Doppelversand durchführen;
- [ ] Cinnamon-Providerauswahl aktivieren.

Der Cinnamon-Settingsschalter folgt erst nach vollständig grüner nativer
Credential- und Workergrenze.

## Pflegevorgabe

Ein Haken wird nur gesetzt, wenn Code oder Dokumentation vorhanden, die
zugehörigen Tests grün und der GitHub-Nachweis im Pull Request nachvollziehbar
ist. Mergeabhängige Punkte bleiben bis zum tatsächlichen Merge offen.
