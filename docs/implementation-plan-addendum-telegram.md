# Planaddendum: selbstständiger Telegram-Dispatch

**Datum:** 28. Juli 2026  
**Stand:** 31. Juli 2026, Europe/Berlin  
**Status:** verbindlich / in sequenzieller Umsetzung

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

`REQ-ROUTE-014` lautet: Der Router bleibt zentral im History-Dispatcher;
Telegram wird über den gewählten Provider ausgeliefert, Vault bleibt ein
separater Worker.

## 3. Einstellungen

```toml
[routing.telegram]
provider = "teebotus"
```

Default ist kompatibel `teebotus`; alle externen History-Typ-Schalter bleiben
standardmäßig `false`.

| Feld-ID | Widget | Default | Source of Truth | Apply |
|---|---|---|---|---|
| `telegram-dispatch-provider` | Combobox/Radio | `teebotus` | `routing.telegram.provider` | Validate/Preview/Apply |

Native Zusatzfelder:

- opaque Credentialprofil;
- opaque Recipientprofile;
- Credentialstatus;
- write-only Token setzen/ersetzen;
- bestätigter Verbindungstest.

Der Schalter wird erst aktiviert, wenn produktiver Config-v2-Writer,
Revision/Audit und native Credentialgrenze existieren.

## 4. Gemergte Cross-Repository-Referenzen

History-Dispatcher-Reclaim:

```text
H234598/History-Dispatcher@0934e85e53ae03d97df57ef494cd1aec7d141ef3
```

TeeBotus-Adaptergrundlage:

```text
H234598/TeeBotus@5989b5129808486a9be272324285e6b5a02e76ab
```

TeeBotus-Provider-v2-Cutover:

```text
H234598/TeeBotus@36c75843a5910cc3b22ffdd9a5ec87eb1d5b2ea9
```

Verwendete Verträge/Symbole:

- `HistoryDispatcherClient` und Same-User-Socketframing;
- `HistoryDispatcherBridge`;
- verschlüsselter `ProviderCallbackSpool`;
- `dispatch_provider_v2_batch`;
- `dispatch_codex_history_outbox`;
- `_history_dispatcher_report_recipient_results`;
- `_history_dispatcher_inactive_failed_recipient_results`;
- `_codex_history_dispatch_routable_account_ids`;
- `_dispatch_codex_history_item_to_account`;
- `ProactiveSender` und private Routeauswahl.

Erfolgsrang, Retry-Ausschluss, Skip-/Reconciliation- und Recipient-Semantik
wurden lokal neu formuliert und attribuiert. Größere wörtliche Übernahmen
bleiben bis zu einer expliziten Root-Lizenzfestlegung vermieden.

## 5. PR-Reihenfolge

- [x] **PR-HD-03** – DB-v2-Migration;
- [x] **PR-HD-04** – dualer Providervertrag;
- [x] **PR-HD-05** – Route Planner, Claims, Leases, Attempts und Aggregation;
- [x] **PR-HD-06** – Config-v2-Vertrags- und Previewgrenze;
- [x] **PR-HD-07** – redigierte Status-v2-API und Snapshot;
- [x] **PR-HD-08a** – History-Dispatcher Provider-v2-Socket/API-Vertrag;
- [x] **PR-HD-08b / TB-HD-01** – TeeBotus-Adaptergrundlage und verschlüsselter
  Provider-Callback-Spool;
- [x] **PR-HD-08c** – gezielter Reclaim abgelaufener Providerclaims für reine
  Callback-Reconciliation;
- [x] **TB-HD-02** – produktiver TeeBotus-Provider-v2-Cutover mit Rebind und
  Crash-after-Accept-Härtung;
- [ ] **PR-HD-Config-v2-Writer** – produktive, revisionsgesicherte Routingconfig
  und native write-only Credentialgrenze;
- [ ] **PR-HD-Native-Telegram** – nativer Telegramworker mit Bot-API, Formatter,
  Batching, Rate-Limit und Reconciliation.

## 6. Sequenzielle Zusatz-Checkboxen

- [x] `TG-A-001..003` ADR- und Planänderung dokumentiert.
- [x] `TG-B-001..006` Providervertrag, opaque Referenzen, Planhash,
  No-Fallback und monotone Merge-Semantik implementiert.
- [x] `TG-C-001..006` Providerbindung, Claims, Capability, Bindings, Lease,
  Heartbeat, Recovery und Konkurrenztests implementiert.
- [ ] `TG-D-001` produktives Config-v2-Feld und staged Settingseditor.
- [ ] `TG-D-002` native Credentialprofile und write-only Tokenoperationen.
- [ ] `TG-E-001` nativer Bot-API-Client.
- [ ] `TG-E-002` Formatter, Segmentierung und Attachmentfallback.
- [ ] `TG-E-003` Telegram-`retry_after` im echten Adapter; Store-Backoff,
  Jitter und Max Attempts sind vorhanden.
- [x] `TG-E-004` Partial Results und `possible_duplicate` im Store persistiert.
- [x] `TG-E-005a` Provider-v2-Recipient-/Completioncallbacks und verschlüsselten
  Replay-Spool implementiert.
- [x] `TG-E-005b` gezielten History-Dispatcher-Reclaim für abgelaufene Claims
  implementiert und aktive, terminale, stale und Cross-Provider-Fälle getestet.
- [x] `TG-E-005c` TeeBotus-Spool atomar auf neuen Reclaimtoken/Attempt
  umgeschrieben und ursprünglichen Callback ohne Send replayt.
- [ ] `TG-E-006` nativer systemd-Worker und Heartbeatloop.
- [x] `TG-F-001a` versioniertes gemeinsames Provider-v2-Fixture im
  History-Dispatcher angelegt.
- [x] `TG-F-001b` denselben semantischen Fixture-Korpus im TeeBotus-Adapter
  konsumiert.
- [x] `TG-F-002a` TeeBotus-Crash-after-Accept, langer Ausfall, Reclaim/Rebind,
  stale/leerer Reclaim und Doppelversand-Schutz getestet.
- [ ] `TG-F-002b` Rate-Limit, Hänger, Oversize und vollständige
  Recipient-Partial-Tests für beide echten Provider abschließen.
- [ ] `TG-G-001` Appletsettings-Schalter mit Backendrevision.
- [x] `TG-G-002` redigierter Provider-, Credential- und Workerstatus als
  Backend-API und Snapshot; Appletdarstellung folgt separat.
- [ ] `TG-H-001` getrennte TeeBotus-/Native-Canaries.
- [ ] `TG-H-002` Canarynachweis ohne Cross-Provider-Doppelversand.

## 7. Abgeschlossener Reclaim-/Rebindvertrag

Additive Operation:

```text
provider.v2.reclaim
```

Der History-Dispatcher bindet exakt eine abgelaufene Target-Delivery neu und
liefert bei Erfolg:

```json
{
  "reconciliation_only": true
}
```

TeeBotus speichert Callbackoperation, Target, Provider, Worker, Capability und
vorherige Attemptnummer AES-GCM-verschlüsselt. Bei eindeutigen Claimablauf-
Fehlern reclaiment der Worker dieselbe Delivery, schreibt das Envelope atomar
auf neuen Token, neuen Attempt und neue Request-ID um und replayt ausschließlich
den ursprünglichen Recipient- oder Completioncallback.

Transportadapter und Batchworker blockieren zusätzlich jedes
`reconciliation_only`-Flag im normalen Sendpfad vor Registrierung oder
Telegram-Send. Damit existieren sowohl Server- als auch Clientseitige
Defense-in-depth-Grenzen gegen Doppelversand.

## 8. Nächster Schnitt: produktive Config-v2- und Credentialgrenze

Der bereits dokumentierte Configvertrag ist noch nicht vollständig produktiv
integriert. Vor dem nativen Bot-API-Worker folgen deshalb:

1. striktes Schema für `routing.telegram.provider` in der echten TOML;
2. revisionsgesicherte `get_redacted → validate → preview → apply`-Operationen;
3. atomare Backups, Compare-and-Swap und `config_audit`;
4. opaque Credential- und Recipientprofile;
5. write-only Secret-Service-Operationen für Bot-Tokens;
6. Credentialstatus ohne Secretwerte;
7. Leaktests für TOML, dconf, Status, Snapshot, Logs und API-Antworten.

## 9. Definition of Done

- [ ] Native Telegramzustellung funktioniert ohne TeeBotus.
- [ ] TeeBotus-Live-Canary bestätigt Zustellung über den versionierten
  Providervertrag.
- [ ] Der Settings-Schalter ändert nur neue Route-Pläne und zeigt eine Preview.
- [x] Store und Planner erlauben keinen automatischen Fallback oder Doppelclaim.
- [ ] Tokens und Chat-IDs existieren ausschließlich in der Credentialgrenze.
- [x] Erfolgreiche Empfänger werden nicht erneut angeboten oder zurückgestuft.
- [x] Unklare Accept-Fenster bleiben blockierend `possible_duplicate`.
- [x] Ein gespulter TeeBotus-Callback kann nach Leaseablauf sicher regebunden und
  ohne erneuten Telegram-Send abgeschlossen werden.
- [ ] Beide echten Provider bestehen den vollständigen gemeinsamen Contract- und
  Fault-Korpus.
- [ ] Appletentfernung oder Safe Mode beeinflusst keinen Telegramworker.
