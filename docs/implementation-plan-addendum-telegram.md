# Planaddendum: selbstständiger Telegram-Dispatch

**Datum:** 28. Juli 2026  
**Status:** verbindlich / umsetzungsreif  
**Auslöser:** Zusatzanforderung des Repositoryeigentümers im laufenden
Implementierungsvorhaben

## 1. Änderung gegenüber dem Ausgangsplan

Der Ausgangsplan sah Telegram ausschließlich über TeeBotus vor. Diese exklusive
Festlegung wird ersetzt. Der History-Dispatcher muss künftig zwei Transportwege
unter derselben zentralen Routing- und Delivery-Semantik unterstützen:

- Dispatch über TeeBotus;
- selbstständiger Dispatch durch den History-Dispatcher.

Unverändert bleiben die Sicherheitsgrenzen: Das Cinnamon-Applet ist kein
Netzwerkclient, besitzt keine Credentials und führt keine Dispatchschleife aus.
Alle akzeptierten Events werden zuerst verschlüsselt persistiert. Telegram ist
ein separates Target mit Empfänger-, Attempt-, Lease- und Auditstatus.

## 2. Neue verbindliche Requirements

- **`REQ-TG-001` – MUSS:** `routing.telegram.provider` besitzt genau die Werte
  `teebotus` und `history_dispatcher`.
- **`REQ-TG-002` – MUSS:** Der History-Dispatcher kann Telegram ohne laufenden
  TeeBotus-Prozess vollständig selbstständig ausliefern.
- **`REQ-TG-003` – MUSS:** Der gewählte Provider wird unveränderlich in jedem
  Route-Plan gespeichert und in dessen Hash einbezogen.
- **`REQ-TG-004` – MUSS:** Es gibt keinen automatischen Cross-Provider-Fallback.
- **`REQ-TG-005` – MUSS:** Beide Provider verwenden dieselben Idempotency-Keys,
  monotonen Empfängerzustände, Partial-Aggregation und Reconciliationregeln.
- **`REQ-TG-006` – MUSS:** Bot-Tokens und rohe Chat-IDs erscheinen nie in TOML,
  dconf, Route-Plan, Snapshot, Log, Diagnose oder Appletantwort.
- **`REQ-TG-007` – MUSS:** Der Backend-Routingeditor bietet einen Schalter
  „Über TeeBotus“ / „Direkt über History-Dispatcher“.
- **`REQ-TG-008` – MUSS:** Provideränderungen wirken standardmäßig nur auf neue
  Route-Pläne; rückwirkende Änderungen benötigen Preview, Token, Revision und
  exakte Bestätigung.
- **`REQ-TG-009` – MUSS:** Der native Worker übernimmt die bewährte TeeBotus-
  Semantik für routbare Empfänger, monotone Erfolgsränge, Retry-Ausschluss,
  Partial Results, `possible_duplicate`, Rate-Limit und Callback-Reconciliation.
- **`REQ-TG-010` – MUSS:** Beide Provider bestehen denselben versionierten
  Telegram-Contract- und Fehler-Injektionskorpus.

Das frühere `REQ-ROUTE-014` gilt in folgender Fassung weiter:

> Der Router bleibt zentral im History-Dispatcher. Telegram kann über den
> gewählten Provider TeeBotus oder History-Dispatcher ausgeliefert werden;
> Vault bleibt ein separater Worker.

## 3. Einstellungen

Neues Backendfeld:

```toml
[routing.telegram]
provider = "teebotus"
```

Default bleibt für die kompatible Einführung `teebotus`. Da sämtliche externen
History-Typ-Schalter weiterhin standardmäßig `false` sind, aktiviert der Default
keinen Versand.

Das Custom-Settings-Widget zeigt:

| Feld-ID | Widget | Default | Source of Truth | Apply |
|---|---|---|---|---|
| `telegram-dispatch-provider` | Combobox/Radio | `teebotus` | `routing.telegram.provider` | staged Validate/Preview/Apply |

Native Zusatzfelder werden nur bei `history_dispatcher` eingeblendet:

- Credentialprofil;
- Recipientprofile;
- Credentialstatus;
- write-only Token setzen/ersetzen;
- bestätigter Verbindungstest.

Keines dieser Felder wird als Bot-Token oder Chat-ID in dconf gespeichert.

## 4. Wiederverwendung aus TeeBotus

Quellstand für die erste Adaption:

```text
H234598/TeeBotus@aaa8c646ced7f9a818d18d3e11cae6859a258b25
```

Zu adaptierende Symbole und Verträge:

- `dispatch_codex_history_outbox`;
- `_dispatch_codex_history_outbox_via_dispatcher`;
- `_history_dispatcher_report_recipient_results`;
- `_history_dispatcher_inactive_failed_recipient_results`;
- `_codex_history_dispatch_routable_account_ids`;
- `_dispatch_codex_history_item_to_account`;
- `ProactiveSender` und private Routeauswahl;
- `HistoryDispatcherClient` und Callback-Spool.

Die erste Provider-/Merge-Implementierung wird lokal neu formuliert und mit
Quellcommit sowie Paritätstests attribuiert. Vor einer wörtlichen Übernahme
größerer Codeblöcke wird die Root-Lizenz des TeeBotus-Repositories explizit
festgelegt; aktuell ist dort keine Root-`LICENSE`-Datei vorhanden.

## 5. Überarbeitete PR-Reihenfolge

- **`PR-HD-03-db-v2-migration`** bleibt unverändert der sichere
  Persistenzschnitt.
- **`PR-HD-04-telegram-provider-contract`** ergänzt ADR-017, Providerenum,
  opaque Binding, Planfragment/Hash, Worker-Missmatch-Schutz und monotone
  Recipient-Merge-Semantik.
- **`PR-HD-05-route-planner-deliveries`** vervollständigt target- und
  provider-spezifische Claims, Leases, Attempts und Aggregation.
- **`PR-HD-06-config-v2-api`** ergänzt Providerfeld, Credentialprofile und
  revisionsgesicherte Konfigurationsoperationen.
- **`PR-HD-07-status-v2-health`** zeigt Provider und Workerzustand redigiert.
- **`PR-HD-08-teebotus-provider-v2`** stabilisiert den bestehenden
  Cross-Repository-Provider.
- **`PR-HD-09-native-telegram-worker`** implementiert Secret-Service-
  Credentialprovider, Bot-API-Client, Formatter, Batching, Rate-Limit und
  Reconciliation.
- Die nachfolgenden Applet-, Vault-, Quality- und Release-Schnitte verschieben
  sich entsprechend, ohne Anforderungen zu verlieren.

## 6. Sequenzielle Zusatz-Checkboxen

- [x] `TG-A-001` Exklusive ADR-007-Festlegung als historisch ersetzt markieren.
- [x] `TG-A-002` ADR-017 mit zwei Providern und No-Fallback-Regel anlegen.
- [x] `TG-A-003` neue Requirements und PR-Reihenfolge dokumentieren.
- [x] `TG-B-001` stabile Providerenum implementieren.
- [x] `TG-B-002` opaque Credential-/Recipient-Referenzen validieren.
- [x] `TG-B-003` Provider in Route-Plan-Fragment und Planhash binden.
- [x] `TG-B-004` Worker-/Plan-Provider-Missmatch fail-closed behandeln.
- [x] `TG-B-005` monotone Recipient-Merge-Semantik aus TeeBotus adaptieren.
- [x] `TG-B-006` Token-/Chat-ID-/Pfadnegative Tests ergänzen.
- [ ] `TG-C-001` Providerfeld in Route-Plan- und Store-API integrieren.
- [ ] `TG-C-002` target-/provider-spezifische Claims implementieren.
- [ ] `TG-C-003` TeeBotus-v2-Capability-Handschlag implementieren.
- [ ] `TG-D-001` Config-v2-Feld und staged Settingseditor implementieren.
- [ ] `TG-D-002` native Credentialprofile und write-only Tokenoperationen
  implementieren.
- [ ] `TG-E-001` gehärteten nativen Bot-API-Client implementieren.
- [ ] `TG-E-002` Formatter, Segmentierung und Attachmentfallback adaptieren.
- [ ] `TG-E-003` Retry-After, Backoff, Jitter und Max Attempts implementieren.
- [ ] `TG-E-004` Partial Results und `possible_duplicate` persistieren.
- [ ] `TG-E-005` Callback-/Attempt-Reconciliation implementieren.
- [ ] `TG-E-006` nativen systemd-Worker und Heartbeat implementieren.
- [ ] `TG-F-001` gemeinsames Contract-Fixture-Korpus beider Provider anlegen.
- [ ] `TG-F-002` Crash-after-Accept, Rate-Limit, Hänger, Oversize und
  Recipient-Partial-Tests für beide Provider grün machen.
- [ ] `TG-G-001` Appletsettings-Schalter mit Backendrevision verbinden.
- [ ] `TG-G-002` Providerstatus und Credentialstatus ohne Secrets anzeigen.
- [ ] `TG-H-001` TeeBotus- und Native-Canary getrennt durchführen.
- [ ] `TG-H-002` beweisen, dass kein Cross-Provider-Doppelversand entsteht.

## 7. Definition of Done des Zusatzes

- [ ] Native Telegramzustellung funktioniert bei gestopptem/nicht installiertem
  TeeBotus.
- [ ] TeeBotus-Zustellung funktioniert weiterhin unverändert über den
  versionierten Providervertrag.
- [ ] Der Settings-Schalter ändert nur neue Route-Pläne und zeigt die Wirkung in
  der Preview.
- [ ] Kein automatischer Fallback oder Doppelclaim ist möglich.
- [ ] Token und Chat-IDs sind ausschließlich in der Credentialgrenze vorhanden.
- [ ] Erfolgreiche Empfänger werden nie erneut gesendet.
- [ ] Unklare Accept-Fenster werden reconciliert oder als
  `possible_duplicate` blockiert.
- [ ] Beide Provider bestehen denselben Contract- und Fault-Korpus.
- [ ] Appletentfernung oder Safe Mode beeinflusst keinen der Telegramworker.
