# Reuse Ledger

**Stand:** erster Baseline-Schnitt  
**Regel:** Kein verbatim übernommener Referenzcode ohne bestätigte Lizenz, Quellcommit, Symbol und Paritätstest.

## In diesem Schnitt verwendete Quellen

| Reuse-ID | Quelle | Symbol/Vertrag | Art | Lizenzstatus | Nachweis |
|---|---|---|---|---|---|
| `REUSE-001` | History-Dispatcher `8f0bb05…` | Unix-Socket, `SO_PEERCRED`, Operation-Allowlist | vorhandenes Verhalten dokumentiert, nicht kopiert | Zielrepository MIT | Architekturvertragstest |
| `REUSE-002` | History-Dispatcher `8f0bb05…` | atomarer 64-KiB-Snapshot | vorhandenes Verhalten dokumentiert, nicht kopiert | Zielrepository MIT | Snapshotvertragstest |
| `REUSE-003` | History-Dispatcher `8f0bb05…` | AES-GCM/Secret-Service-Grenze | vorhandenes Verhalten dokumentiert, nicht kopiert | Zielrepository MIT | Kryptovertragstest |
| `REUSE-004` | History-Dispatcher `8f0bb05…` | Applet-Snapshot-/Action-Grenze | vorhandenes Verhalten dokumentiert, nicht kopiert | Zielrepository MIT | Appletvertragstest |

## Für spätere Schnitte vorgemerkte Referenzen

| Quelle | Vorgesehene Muster | Status vor Übernahme |
|---|---|---|
| `H234598/speed-of-cinnamon` | Settings-Widgets, Iconvorschau, Lifecycle- und Crash-Testmuster | Lizenz und Attribution je Datei vor verbatim Übernahme prüfen |
| `H234598/TeeBotus` | Telegramworker, Callback-Spool, gruppierte Menüs | Root-Lizenzlage erneut prüfen; bis dahin nur Verhalten neu implementieren |
| `H234598/codex-usage` | Safe Mode, Last-known-good, Health-Log, Runtime-Harness | Root-Lizenzlage erneut prüfen; bis dahin nur Verhalten neu implementieren |
| `openai/codex` | Rollout-/Session-/Sub-Agent-Protokollstrukturen | nur sanitisiert als Protokollreferenz/Fixture; Upstreamlizenz dokumentieren |

Dieser Baseline-PR enthält keine wörtliche Kopie aus den drei Referenzapplets oder aus `openai/codex`.
