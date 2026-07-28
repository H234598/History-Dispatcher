# Reuse Ledger

**Stand:** zweiter Implementierungsschnitt  
**Regel:** Kein verbatim übernommener Referenzcode ohne bestätigte Lizenz, Quellcommit, Symbol und Paritätstest.

## Verwendete Quellen und Verträge

| Reuse-ID | Quelle | Symbol/Vertrag | Art | Lizenzstatus | Nachweis |
|---|---|---|---|---|---|
| `REUSE-001` | History-Dispatcher `8f0bb05…` | Unix-Socket, `SO_PEERCRED`, Operation-Allowlist | vorhandenes Verhalten dokumentiert, nicht kopiert | Zielrepository MIT | Architekturvertragstest |
| `REUSE-002` | History-Dispatcher `8f0bb05…` | atomarer 64-KiB-Snapshot | vorhandenes Verhalten dokumentiert, nicht kopiert | Zielrepository MIT | Snapshotvertragstest |
| `REUSE-003` | History-Dispatcher `8f0bb05…` | AES-GCM/Secret-Service-Grenze | vorhandenes Verhalten dokumentiert, nicht kopiert | Zielrepository MIT | Kryptovertragstest |
| `REUSE-004` | History-Dispatcher `8f0bb05…` | Applet-Snapshot-/Action-Grenze | vorhandenes Verhalten dokumentiert, nicht kopiert | Zielrepository MIT | Appletvertragstest |
| `REUSE-005` | `openai/codex@8e271dc02b23d42827875019924be0f5005642b0` | `RolloutLine`, `SessionMeta`, `SessionSource`, `ThreadSource`, `SubAgentSource`, `ResponseItem::Message`, `MessagePhase`, `EventMsg`-Aliases und `TurnCompleteEvent` | öffentliche Protokollstruktur gelesen; Fixtures und Pythonparser eigenständig neu formuliert; kein Rust-Code kopiert | Apache-2.0 im Upstreamroot verifiziert | Fixturemanifest, `tests/test_classification.py`, `tests/test_fixture_sanitizer.py` |

## Für spätere Schnitte vorgemerkte Referenzen

| Quelle | Vorgesehene Muster | Status vor Übernahme |
|---|---|---|
| `H234598/speed-of-cinnamon` | Settings-Widgets, Iconvorschau, Lifecycle- und Crash-Testmuster | Lizenz und Attribution je Datei vor verbatim Übernahme prüfen |
| `H234598/TeeBotus` | Telegramworker, Callback-Spool, gruppierte Menüs | Root-Lizenzlage erneut prüfen; bis dahin nur Verhalten neu implementieren |
| `H234598/codex-usage` | Safe Mode, Last-known-good, Health-Log, Runtime-Harness | Root-Lizenzlage erneut prüfen; bis dahin nur Verhalten neu implementieren |

## Fixture- und Codeherkunft dieses Schnitts

- Alle eingecheckten JSONL-Fixtures sind handgefertigte, sanitiserte
  Protokollbeispiele mit künstlichen IDs, relativen Fixturepfaden und
  `example.invalid`-URLs.
- Es wurde keine reale Codex-Sessiondatei und kein Upstream-Testfixture kopiert.
- Der Sanitizer erzeugt für spätere lokale Beispiele deterministische
  Pseudonyme und ein Hashmanifest; private Quelldateien bleiben außerhalb des
  Repositorys.
- `openai/codex` ist ausschließlich Protokoll-/Fixture-Referenz und keine
  Runtime- oder Buildabhängigkeit.
