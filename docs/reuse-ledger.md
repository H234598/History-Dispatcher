# Reuse Ledger

**Stand:** vierter Implementierungsschnitt / Telegram-Providervertrag  
**Regel:** Jede Übernahme nennt Quellcommit, Symbol, Adaptionsgrad, Lizenzstatus
und Paritätstest. Größere wörtliche Übernahmen setzen eine explizit geklärte
Lizenz- beziehungsweise Rechtefreigabe voraus.

## Verwendete Quellen und Verträge

| Reuse-ID | Quelle | Symbol/Vertrag | Art | Lizenz-/Rechtestatus | Nachweis |
|---|---|---|---|---|---|
| `REUSE-001` | History-Dispatcher `8f0bb05…` | Unix-Socket, `SO_PEERCRED`, Operation-Allowlist | vorhandenes Verhalten dokumentiert und erweitert | Zielrepository MIT | Architekturvertragstest |
| `REUSE-002` | History-Dispatcher `8f0bb05…` | atomarer 64-KiB-Snapshot | vorhandenes Verhalten dokumentiert | Zielrepository MIT | Snapshotvertragstest |
| `REUSE-003` | History-Dispatcher `8f0bb05…` | AES-GCM/Secret-Service-Grenze | erhalten und um schlüsselgebundene IDs ergänzt | Zielrepository MIT | Kryptovertragstest, `tests/test_identifiers.py` |
| `REUSE-004` | History-Dispatcher `8f0bb05…` | Applet-Snapshot-/Action-Grenze | vorhandenes Verhalten dokumentiert | Zielrepository MIT | Appletvertragstest |
| `REUSE-005` | `openai/codex@8e271dc02b23d42827875019924be0f5005642b0` | aktuelle Rollout-/Session-/Sub-Agent-Protokolltypen | Protokollstruktur gelesen; Pythonparser und Fixtures eigenständig formuliert | Apache-2.0 im Upstreamroot verifiziert | Fixturemanifest und Classifiertests |
| `REUSE-006` | `H234598/TeeBotus@aaa8c646ced7f9a818d18d3e11cae6859a258b25` | `HISTORY_DISPATCHER_RECIPIENT_STATUS_RANKS`, `_history_dispatcher_report_recipient_results` | monotone Recipient-Merge-Semantik lokal neu formuliert | Repository gehört demselben Eigentümer und Übernahme wurde ausdrücklich beauftragt; Root-`LICENSE` fehlt, daher noch keine größere verbatim Übernahme | `tests/test_telegram_provider.py` |
| `REUSE-007` | `H234598/TeeBotus@aaa8c646ced7f9a818d18d3e11cae6859a258b25` | `_history_dispatcher_inactive_failed_recipient_results`, `_codex_history_dispatch_routable_account_ids` | terminales Skip-/Route-Preflight-Verhalten als verbindlicher nativer Workercontract adaptiert | wie `REUSE-006` | Planaddendum, spätere Contracttests |
| `REUSE-008` | `H234598/TeeBotus@aaa8c646ced7f9a818d18d3e11cae6859a258b25` | `dispatch_codex_history_outbox`, `_dispatch_codex_history_outbox_via_dispatcher`, Callback-Spool | Muster für Claim, Partial Results, Ausschluss von Erfolgen und Reconciliation vorgemerkt | wie `REUSE-006`; vor direkter Codeübernahme Lizenzdatei/Attribution festlegen | `TG-E-*`, `TG-F-*` |
| `REUSE-009` | `H234598/TeeBotus@aaa8c646ced7f9a818d18d3e11cae6859a258b25` | `ProactiveSender`, private Routeauswahl, Redactionmuster | Transport- und Sicherheitsmuster für nativen Worker vorgemerkt | wie `REUSE-006` | native Worker-/Formatter-/Leaktests |

## Für spätere Schnitte vorgemerkte Referenzen

| Quelle | Vorgesehene Muster | Status vor Übernahme |
|---|---|---|
| `H234598/speed-of-cinnamon` | Settings-Widgets, Iconvorschau, Lifecycle- und Crash-Testmuster | Lizenz und Attribution je Datei vor verbatim Übernahme prüfen |
| `H234598/TeeBotus` | Bot-API-Transport, Formatter, Rate-Limit, Callback-Spool, gruppierte Menüs | Herkunft ist fixiert; Root-Lizenz vor größerer wörtlicher Übernahme ergänzen oder Verhalten lokal neu formulieren |
| `H234598/codex-usage` | Safe Mode, Last-known-good, Health-Log, Runtime-Harness | Root-Lizenzlage erneut prüfen; bis dahin Verhalten neu implementieren |

## Herkunfts- und Datenschutzregeln

- Raw Codex-Rollouts, Bot-Tokens, Chat-IDs, Message-Refs, private Account-IDs
  und absolute Pfade werden niemals als Fixture oder Dokumentationsbeispiel
  übernommen.
- Telegram-Fixtures verwenden ausschließlich `example.invalid`, opaque
  Recipient-/Credentialreferenzen und künstliche Message-Ref-Keys.
- Der native Telegramworker darf TeeBotus-Semantik übernehmen, aber keine
  TeeBotus-Credentialdatei oder private Accountdaten importieren.
- Beide Provider teilen ausschließlich versionierte Contract-Fixtures und den
  History-Dispatcher-Storevertrag; sie besitzen keine gemeinsame
  Laufzeitbibliothek.
- `openai/codex` bleibt Protokoll-/Fixture-Referenz und keine Runtimeabhängigkeit.
