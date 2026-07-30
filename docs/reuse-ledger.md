# Reuse Ledger

**Stand:** achter Implementierungsschnitt / Provider-v2-Reclaim  
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
| `REUSE-005` | `openai/codex@8e271dc02b23d42827875019924be0f5005642b0` | aktuelle Rollout-/Session-/Sub-Agent-Protokolltypen | Protokollstruktur gelesen; Parser und Fixtures eigenständig formuliert | Apache-2.0 im Upstreamroot verifiziert | Fixturemanifest und Classifiertests |
| `REUSE-006` | `H234598/TeeBotus@aaa8c646ced7f9a818d18d3e11cae6859a258b25` | `HISTORY_DISPATCHER_RECIPIENT_STATUS_RANKS`, `_history_dispatcher_report_recipient_results` | monotone Recipient-Merge-Semantik lokal neu formuliert | gleicher Repositoryeigentümer und ausdrücklicher Auftrag; Root-`LICENSE` fehlt, daher keine größere verbatim Übernahme | `tests/test_telegram_provider.py` |
| `REUSE-007` | gleicher TeeBotus-Stand | `_history_dispatcher_inactive_failed_recipient_results`, `_codex_history_dispatch_routable_account_ids` | terminales Skip-/Route-Preflight-Verhalten adaptiert | wie `REUSE-006` | Route-/Providervertragstests |
| `REUSE-008` | gleicher TeeBotus-Stand | `dispatch_codex_history_outbox`, `_dispatch_codex_history_outbox_via_dispatcher`, Callback-Spool | Muster für Claim, Partial Results, Erfolgsausschluss und Reconciliation | wie `REUSE-006`; lokal neu formuliert | `tests/test_provider_api_v2.py`, TeeBotus-Adaptertests |
| `REUSE-009` | gleicher TeeBotus-Stand | `ProactiveSender`, private Routeauswahl, Redactionmuster | Transport-/Sicherheitsmuster für nativen Worker vorgemerkt | wie `REUSE-006` | spätere native Worker-/Formatter-/Leaktests |
| `REUSE-010` | `H234598/TeeBotus@5989b5129808486a9be272324285e6b5a02e76ab` | `HistoryDispatcherClient`, Provider-v2-Bridge, AES-GCM-`ProviderCallbackSpool` | gemergte Adaptergrundlage und semantisch gleicher Fixture-Korpus als Cross-Repository-Referenz | gleicher Repositoryeigentümer; keine verbatim Übernahme in History-Dispatcher | Provider-v2-Fixture, Bridge- und Spooltests |
| `REUSE-011` | `H234598/TeeBotus` PR #3 / Head `ea44a025176ddef92154f37e64340048e6baf18c` | fail-closed Batchworker, private Route vor Claim, `possible_duplicate`-Sendverbot und Callbackblockade | aktiver Cutover als Fault- und Rebind-Referenz; Reclaimvertrag im History-Dispatcher eigenständig implementiert | wie `REUSE-006` | `tests/test_provider_api_v2_reclaim.py`, TeeBotus-Cutovertests |

## Für spätere Schnitte vorgemerkte Referenzen

| Quelle | Vorgesehene Muster | Status vor Übernahme |
|---|---|---|
| `H234598/speed-of-cinnamon` | Settings-Widgets, Iconvorschau, Lifecycle- und Crash-Testmuster | Lizenz und Attribution je Datei vor verbatim Übernahme prüfen |
| `H234598/TeeBotus` | Bot-API-Transport, Formatter, Rate-Limit und gruppierte Menüs | Herkunft ist fixiert; Root-Lizenz vor größerer wörtlicher Übernahme ergänzen oder Verhalten lokal neu formulieren |
| `H234598/codex-usage` | Safe Mode, Last-known-good, Health-Log, Runtime-Harness | Root-Lizenzlage erneut prüfen; bis dahin Verhalten neu implementieren |

## Herkunfts- und Datenschutzregeln

- Raw Codex-Rollouts, Bot-Tokens, Chat-IDs, Message-Refs, private Account-IDs
  und absolute Pfade werden niemals als Fixture oder Dokumentationsbeispiel
  übernommen.
- Telegram-Fixtures verwenden ausschließlich opaque Recipient-/Credentialrefs
  und künstliche Message-Ref-Keys.
- Der native Telegramworker darf TeeBotus-Semantik übernehmen, aber keine
  TeeBotus-Credentialdatei oder private Accountdaten importieren.
- Beide Provider teilen ausschließlich versionierte Contract-Fixtures und den
  History-Dispatcher-Storevertrag; sie besitzen keine gemeinsame
  Laufzeitbibliothek.
- Der Reclaimvertrag transportiert keine Telegram-Credentials und autorisiert
  ausschließlich Callback-/Completion-Reconciliation, keinen neuen Send.
- `openai/codex` bleibt Protokoll-/Fixture-Referenz und keine Runtimeabhängigkeit.
