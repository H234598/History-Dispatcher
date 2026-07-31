---
title: Planaddendum selbstständiger Telegram-Dispatch
tags:
  - history-dispatcher
  - telegram
  - teebotus
  - native-provider
  - roadmap
type: implementation-plan-addendum
status: active
date: 2026-07-31
created: 2026-07-28
aliases:
  - Telegram Provider Addendum
  - Native Telegram Rollout Plan
---

# Planaddendum: selbstständiger Telegram-Dispatch

## 1. Zieländerung

Der History-Dispatcher unterstützt zwei explizit auswählbare Telegramwege unter
demselben zentralen Routing-, Claim-, Recipient-, Attempt- und
Reconciliationvertrag:

- Dispatch über TeeBotus;
- selbstständiger Dispatch durch den History-Dispatcher.

Das Cinnamon-Applet bleibt reiner Same-User-Client ohne Netzwerkzugriff,
Claims, Bot-Tokens oder Chat-IDs. Events werden vor Routing verschlüsselt
persistiert.

## 2. Verbindliche Anforderungen

- **`REQ-TG-001` – MUSS:** `routing.telegram.provider` besitzt genau
  `teebotus | history_dispatcher`.
- **`REQ-TG-002` – MUSS:** Der native Weg funktioniert ohne laufenden TeeBotus.
- **`REQ-TG-003` – MUSS:** Provider und opaque Binding sind unveränderlicher
  Bestandteil jedes Route-Plans und seines Hashes.
- **`REQ-TG-004` – MUSS:** Kein automatischer Cross-Provider-Fallback.
- **`REQ-TG-005` – MUSS:** Beide Provider teilen Idempotenz, monotone
  Recipientzustände, Partial-Aggregation und Reconciliation.
- **`REQ-TG-006` – MUSS:** Tokens und rohe Chat-IDs erscheinen nie in TOML,
  dconf, Route-Plan, Snapshot, Log, Diagnose oder Appletantwort.
- **`REQ-TG-007` – MUSS:** Der Backendeditor bietet „Über TeeBotus“ und
  „Direkt über History-Dispatcher“.
- **`REQ-TG-008` – MUSS:** Provideränderungen wirken standardmäßig nur auf neue
  Route-Pläne; rückwirkende Änderungen benötigen Preview, Token, Revision und
  exakte Bestätigung.
- **`REQ-TG-009` – MUSS:** Der native Worker übernimmt TeeBotus-Semantik für
  routbare Empfänger, Erfolgsränge, Retry-Ausschluss, Partial Results,
  `possible_duplicate`, Rate-Limit und Reconciliation.
- **`REQ-TG-010` – MUSS:** Beide Provider bestehen denselben versionierten
  Contract- und Fault-Korpus.
- **`REQ-TG-011` – MUSS:** Ein nach externem Accept gespulter Callback muss nach
  Ablauf der ursprünglichen Claim-Lease gezielt an dieselbe Target-Delivery und
  deren aktuellen Attempt neu gebunden werden können, ohne einen neuen
  Telegram-Send auszulösen.
- **`REQ-TG-012` – MUSS:** Target-Reclaim prüft unveränderlichen Provider,
  Capability, vorherige Attemptnummer und Terminalzustand; aktive Claims dürfen
  nicht gestohlen und stale Rebinds nicht akzeptiert werden.
- **`REQ-TG-013` – MUSS:** Native Bot-Tokens und Recipient-Chat-IDs existieren
  ausschließlich in Secret Service unter opaque Config-v2-Profilnamen.
- **`REQ-TG-014` – MUSS:** Credentialoperationen sind öffentlich write-only;
  Status, Audit und API geben nie einen Secretwert oder eine rohe Chat-ID aus.
- **`REQ-TG-015` – MUSS:** Secret-Service-Mutation und Metadaten/Audit werden
  kompensiert; ein DB-/Auditfehler stellt den vorherigen Secretzustand wieder
  her oder endet terminal als `credential_rollback_failed`.

`REQ-ROUTE-014` lautet: Der Router bleibt zentral im History-Dispatcher;
Telegram wird über den gewählten Provider ausgeliefert, Vault bleibt ein
separater Worker.

## 3. Produktive Routingkonfiguration

```toml
[routing.telegram]
provider = "teebotus"
credential_ref = ""
recipient_refs = []
```

Default ist kompatibel `teebotus`; alle externen History-Typ-Schalter bleiben
standardmäßig `false`.

`credential_ref` und `recipient_refs` sind opaque Profilnamen. Bot-Tokens und
rohe Chat-IDs werden von Configloader und Patch-API abgewiesen.

| Feld-ID | Widget | Default | Source of Truth | Apply |
|---|---|---|---|---|
| `telegram-dispatch-provider` | Combobox/Radio | `teebotus` | `routing.telegram.provider` | Validate/Preview/Apply |

Die produktive Backendschnittstelle ist gemergt:

```text
config.get_redacted
config.validate_patch
config.preview_apply
config.apply
```

Ein Apply benötigt Revision, 60-Sekunden-One-use-Previewtoken, kanonischen
Fingerprint, exakte Bestätigung und Request-ID. Die Wirkung ist ausschließlich
`new_route_plans_only`.

## 4. Native Credentialgrenze

Secret-Service-Attribute:

```text
application=history-dispatcher
purpose=telegram-bot-token
profile=<credential_ref>
```

```text
application=history-dispatcher
purpose=telegram-chat-id
profile=<recipient_ref>
```

Der Secretwert wird über stdin an `secret-tool store` übergeben. Es gibt keinen
Datei-, Environment- oder Zufallsfallback.

Additive Backendoperationen:

```text
credential.get_status
credential.preview_apply
credential.apply
```

- `credential.get_status` liest ausschließlich secretfreie Schema-v4-Metadaten;
- `credential.preview_apply` hält den Secretwert nur im RAM und liefert einen
  60-Sekunden-One-use-Token;
- `credential.apply` ist secretfrei und dauerhaft request-idempotent;
- `set` verlangt Abwesenheit;
- `replace` und `delete` verlangen einen vorhandenen Wert;
- Config wird unmittelbar vor Mutation neu geladen und das Profil reautorisiert;
- Metadaten und Audit speichern nur HMAC-pseudonymisierte Profil-/Actorkeys;
- bei DB-/Auditfehler wird der vorherige Secret-Service-Wert wiederhergestellt;
- Status v2 veröffentlicht ausschließlich `configured` und `last_changed` des
  aktuell ausgewählten Botprofils.

Der sichtbare Cinnamon-Schalter bleibt bis zur vollständigen nativen
Workergrenze deaktiviert. dconf wird nicht zur Routing- oder Credentialquelle.

## 5. Gemergte Cross-Repository-Referenzen

History-Dispatcher-Reclaim:

```text
H234598/History-Dispatcher@0934e85e53ae03d97df57ef494cd1aec7d141ef3
```

Produktiver Config-v2-Writer:

```text
H234598/History-Dispatcher@decd370f8359979beff59da0b4dbf81208fb044a
```

TeeBotus-Adaptergrundlage:

```text
H234598/TeeBotus@5989b5129808486a9be272324285e6b5a02e76ab
```

TeeBotus-Provider-v2-Cutover:

```text
H234598/TeeBotus@36c75843a5910cc3b22ffdd9a5ec87eb1d5b2ea9
```

## 6. PR-Reihenfolge

- [x] **PR-HD-03** – DB-v2-Migration;
- [x] **PR-HD-04** – dualer Providervertrag;
- [x] **PR-HD-05** – Route Planner, Claims, Leases, Attempts und Aggregation;
- [x] **PR-HD-06** – Config-v2-Vertrags- und Previewgrenze;
- [x] **PR-HD-07** – redigierte Status-v2-API und Snapshot;
- [x] **PR-HD-08a** – History-Dispatcher Provider-v2-Socket/API-Vertrag;
- [x] **PR-HD-08b / TB-HD-01** – TeeBotus-Adaptergrundlage und verschlüsselter
  Provider-Callback-Spool;
- [x] **PR-HD-08c** – gezielter Reclaim abgelaufener Providerclaims;
- [x] **TB-HD-02** – produktiver TeeBotus-Provider-v2-Cutover;
- [x] **PR-HD-12** – produktive revisionsgesicherte Routingconfig, Audit und
  Same-User-API;
- [x] **PR-HD-13** – Secret-Service-Credentialgrenze, Schema v4, Kompensation und write-only Same-User-API; gemergt als `cd35d5807cef1834e0c4d6d6f0a18e81b7e3cda4`;
- [ ] **PR-HD-15 / PR-HD-Native-Telegram** – nativer Telegramworker mit
  fixed-host Bot API, Formatter, Provider-v2-Lifecycle, Rate-Limit und
  Reconciliation; funktional grün, finale Gates und Merge offen.

## 7. Sequenzielle Zusatz-Checkboxen

- [x] `TG-A-001..003` ADR- und Planänderung dokumentiert.
- [x] `TG-B-001..006` Providervertrag, opaque Referenzen, Planhash,
  No-Fallback und monotone Merge-Semantik implementiert.
- [x] `TG-C-001..006` Providerbindung, Claims, Capability, Bindings, Lease,
  Heartbeat, Recovery und Konkurrenztests implementiert.
- [x] `TG-D-001a` produktives Config-v2-TOML-Feld und strikter Roundtrip.
- [x] `TG-D-001b` revisionsgesicherte Backendkette
  `get_redacted → validate → preview → apply` mit Audit und Rollback.
- [x] `TG-D-002a` additive secretfreie Metadaten-/Audittabellen und explizite
  Schema-v4-Migration.
- [x] `TG-D-002b` strikter Secret-Service-Store ohne Fallback oder argv-Leak.
- [x] `TG-D-002c` write-only Credential-Preview/Apply mit Kompensation.
- [x] `TG-D-002d` secretfreier Credentialstatus und Same-User-Socket-API.
- [x] `TG-E-001` nativer fixed-host Bot-API-Client mit TLS-, Timeout- und Größenlimits.
- [x] `TG-E-002` deterministischer Plain-Text-Formatter und atomarer Ein-Dokument-Fallback.
- [x] `TG-E-003` Telegram-`retry_after` im nativen Adapter an den gemeinsamen Store-Backoff übergeben.
- [x] `TG-E-004` Partial Results und `possible_duplicate` im Store persistiert.
- [x] `TG-E-005a` Provider-v2-Recipient-/Completioncallbacks und verschlüsselten
  Replay-Spool implementiert.
- [x] `TG-E-005b` gezielten History-Dispatcher-Reclaim implementiert.
- [x] `TG-E-005c` TeeBotus-Spool atomar regebunden und Callback ohne Send replayt.
- [x] `TG-E-006` nativer CLI-/systemd-Worker und redigierter Heartbeatloop; Aktivierung explizit opt-in.
- [x] `TG-F-001a` gemeinsames Provider-v2-Fixture im History-Dispatcher.
- [x] `TG-F-001b` denselben Fixture-Korpus im TeeBotus-Adapter konsumiert.
- [x] `TG-F-002a` TeeBotus-Crash-after-Accept, Reclaim/Rebind und
  Doppelversand-Schutz getestet.
- [x] `TG-F-002b-native` Rate-Limit, Connect-/Read-Hänger, Oversize, malformed Response und Recipient-Partial-Fälle für Native getestet.
- [ ] `TG-F-002b-shared` erweiterten vollständigen Fault-Korpus erneut gegen TeeBotus und Native gemeinsam abnehmen.
- [ ] `TG-G-001` Cinnamon-Settingsschalter gegen Backendrevision und vollständige
  Credential-/Workergrenze.
- [x] `TG-G-002` redigierter Provider-, Credential- und Workerstatus als
  Backend-API und Snapshot.
- [ ] `TG-H-001` getrennte TeeBotus-/Native-Canaries.
- [ ] `TG-H-002` Canarynachweis ohne Cross-Provider-Doppelversand.

## 8. Abgeschlossener Reclaim-/Rebindvertrag

`provider.v2.reclaim` bindet exakt eine abgelaufene Target-Delivery neu und
liefert `reconciliation_only=true`. TeeBotus schreibt das verschlüsselte
Callback-Envelope atomar auf neuen Token, neuen Attempt und neue Request-ID um
und replayt ausschließlich den ursprünglichen Recipient- oder
Completioncallback. Transportadapter und Batchworker blockieren zusätzlich
jedes `reconciliation_only`-Flag vor einem neuen Send.

## 9. Bewusste Grenze des gemergten PR #13

PR #13 führt keine Telegram-Netzwerkoperation aus. Es gibt keinen Bot-API-Client,
kein `getMe`, keine Testnachricht, keine Formatierung, kein Rate-Limit und keinen
systemd-Worker.

Metadata `configured=true` bedeutet, dass ein erfolgreicher API-Apply den
Secretwert geschrieben und intern verifiziert hat. Der spätere Worker löst den
Wert bei jeder Nutzung erneut fail-closed auf, da externe Keyringänderungen
nicht in den öffentlichen Status zurückgespiegelt werden.

## 10. Aktiver Schnitt: nativer Telegramworker

PR #15 hat funktional umgesetzt:

1. internen Bot-Token- und Chat-ID-Lookup unmittelbar vor jedem Send;
2. fixed-host Bot-API-Client mit TLS, Timeouts und bounded Antworten;
3. deterministische Plain-Text-Formatierung mit Ein-Dokument-Fallback;
4. Telegram-`retry_after`, Backoff und Rate-Limit;
5. empfängerweise Resultate und Crash-after-Accept-`possible_duplicate`;
6. explizit opt-in-fähigen systemd-User-Worker und redigierte Heartbeats;
7. versionierten nativen Fault-Korpus.

Offen bleiben Merge-Gates, getrennte Live-Canaries ohne Cross-Provider-
Doppelversand und danach die Cinnamon-Providerauswahl.

## 11. Definition of Done

- [ ] Native Telegramzustellung funktioniert ohne TeeBotus.
- [ ] TeeBotus-Live-Canary bestätigt Zustellung über den versionierten Vertrag.
- [ ] Der Cinnamon-Settingsschalter ändert nur neue Route-Pläne und zeigt eine
  Preview.
- [x] Das Backend persistiert die Providerwahl ausschließlich über Revision,
  Preview und Audit.
- [x] Bot-Token und rohe Chat-IDs können ausschließlich über die write-only
  Secret-Service-Grenze gesetzt, ersetzt oder gelöscht werden.
- [x] Status, Audit, TOML, Snapshot und API geben keinen Secretwert aus.
- [x] Store und Planner erlauben keinen automatischen Fallback oder Doppelclaim.
- [x] Erfolgreiche Empfänger werden nicht erneut angeboten oder zurückgestuft.
- [x] Unklare Accept-Fenster bleiben blockierend `possible_duplicate`.
- [x] Gespulte TeeBotus-Callbacks können nach Leaseablauf sicher regebunden und
  ohne erneuten Telegram-Send abgeschlossen werden.
- [ ] Beide echten Provider bestehen den vollständigen gemeinsamen Contract- und
  Fault-Korpus.
- [ ] Appletentfernung oder Safe Mode beeinflusst keinen Telegramworker.
