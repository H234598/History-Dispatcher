# Planaddendum: selbstständiger Telegram-Dispatch

**Datum:** 28. Juli 2026  
**Stand:** 30. Juli 2026  
**Status:** verbindlich / in sequenzieller Umsetzung

## 1. Zieländerung

Der History-Dispatcher unterstützt künftig zwei explizit auswählbare
Telegram-Transportwege unter derselben zentralen Routing- und Delivery-Semantik:

- Dispatch über TeeBotus;
- selbstständiger Dispatch durch den History-Dispatcher.

Das Cinnamon-Applet bleibt reiner Same-User-Client ohne Netzwerkzugriff oder
Credentials. Alle Events werden vor Routing verschlüsselt persistiert.

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

`REQ-ROUTE-014` lautet damit: Der Router bleibt zentral im
History-Dispatcher; Telegram wird über den gewählten Provider ausgeliefert,
Vault bleibt ein separater Worker.

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

## 4. Wiederverwendung aus TeeBotus

Referenzstand:

```text
H234598/TeeBotus@aaa8c646ced7f9a818d18d3e11cae6859a258b25
```

Referenzierte Verträge/Symbole:

- `dispatch_codex_history_outbox`;
- `_dispatch_codex_history_outbox_via_dispatcher`;
- `_history_dispatcher_report_recipient_results`;
- `_history_dispatcher_inactive_failed_recipient_results`;
- `_codex_history_dispatch_routable_account_ids`;
- `_dispatch_codex_history_item_to_account`;
- `ProactiveSender`, private Routeauswahl und Callback-Spool.

Erfolgsrang, Retry-Ausschluss, Skip-/Reconciliation- und Recipient-Semantik
wurden lokal neu formuliert und attribuiert. Größere wörtliche Übernahmen
bleiben bis zu einer expliziten Root-Lizenzfestlegung vermieden.

## 5. PR-Reihenfolge

- [x] **PR-HD-03** – DB-v2-Migration;
- [x] **PR-HD-04** – dualer Providervertrag;
- [x] **PR-HD-05** – Route Planner, target-/provider-spezifische Claims,
  Leases, Attempts und Aggregation;
- [x] **PR-HD-06** – Config-v2-Vertrags- und Previewgrenze;
- [ ] **PR-HD-07** – redigierte Status-v2-API und Snapshot;
- [ ] **PR-HD-08** – TeeBotus-Provider v2 gegen den gemeinsamen Storevertrag;
- [ ] **PR-HD-09** – nativer Telegramworker mit Secret Service, Bot-API,
  Formatter, Batching, Rate-Limit und Reconciliation.

## 6. Sequenzielle Zusatz-Checkboxen

- [x] `TG-A-001..003` ADR- und Planänderung dokumentiert.
- [x] `TG-B-001..006` Providervertrag, opaque Referenzen, Planhash,
  No-Fallback und monotone Merge-Semantik implementiert.
- [x] `TG-C-001` Providerbindung in Route-Plan und Store integriert.
- [x] `TG-C-002` target-/provider-spezifische Claims implementiert.
- [x] `TG-C-003` TeeBotus-/Native-Capability-Handschlag implementiert.
- [x] `TG-C-004` immutable Target-/Recipientbindings persistiert.
- [x] `TG-C-005` Claimtoken, Lease, Heartbeat und Expiry-Recovery implementiert.
- [x] `TG-C-006` Konkurrenz- und Zielisolationstests implementiert.
- [ ] `TG-D-001` produktives Config-v2-Feld und staged Settingseditor.
- [ ] `TG-D-002` native Credentialprofile und write-only Tokenoperationen.
- [ ] `TG-E-001` nativer Bot-API-Client.
- [ ] `TG-E-002` Formatter, Segmentierung und Attachmentfallback.
- [ ] `TG-E-003` Telegram-`retry_after` im echten Adapter; Store-Backoff,
  Jitter und Max Attempts sind vorhanden.
- [x] `TG-E-004` Partial Results und `possible_duplicate` im Store persistiert.
- [ ] `TG-E-005` Transport-Callback-/Attempt-Reconciliation.
- [ ] `TG-E-006` nativer systemd-Worker und Heartbeatloop.
- [ ] `TG-F-001` gemeinsamer Provider-Contract-Fixture-Korpus.
- [ ] `TG-F-002` Crash-after-Accept, Rate-Limit, Hänger, Oversize und
  Recipient-Partial-Tests beider echten Provider.
- [ ] `TG-G-001` Appletsettings-Schalter mit Backendrevision.
- [x] `TG-G-002` redigierter Provider-, Credential- und Workerstatus als
  Backend-API und Snapshot; Appletdarstellung folgt separat.
- [ ] `TG-H-001` getrennte TeeBotus-/Native-Canaries.
- [ ] `TG-H-002` Canarynachweis ohne Cross-Provider-Doppelversand.

## 7. Definition of Done

- [ ] Native Telegramzustellung funktioniert ohne TeeBotus.
- [ ] TeeBotus-Zustellung funktioniert über den versionierten Providervertrag.
- [ ] Der Settings-Schalter ändert nur neue Route-Pläne und zeigt eine Preview.
- [x] Store und Planner erlauben keinen automatischen Fallback oder Doppelclaim.
- [ ] Tokens und Chat-IDs existieren ausschließlich in der Credentialgrenze.
- [x] Erfolgreiche Empfänger werden nicht erneut angeboten oder zurückgestuft.
- [x] Unklare Accept-Fenster bleiben blockierend `possible_duplicate`.
- [ ] Beide echten Provider bestehen denselben Contract- und Fault-Korpus.
- [ ] Appletentfernung oder Safe Mode beeinflusst keinen Telegramworker.
