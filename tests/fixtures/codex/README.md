# Sanitisiertes Codex-Rollout-Fixture-Korpus

Dieses Korpus ist die bindende, datenschutzbereinigte Kompatibilitätsbasis des
versionierten History-Classifiers. Es enthält keine echten Session-IDs,
Benutzernamen, Repository-Credentials, Chat-IDs, Tokens oder privaten Pfade.

## Protokollreferenz

- Upstream: `openai/codex`
- verifizierter Commit: `8e271dc02b23d42827875019924be0f5005642b0`
- relevante Rollouttypen: `session_meta`, `response_item`, `turn_context`,
  `event_msg`
- relevante Metadaten: `parent_thread_id`, `thread_source`, `source`,
  `agent_path`, `agent_role`, `subagent_history_start_ordinal`
- relevante Phasen: `commentary`, `final_answer`
- Abschlussaliases: `task_complete`, `turn_complete`

Der Upstreamcommit ist eine Protokoll- und Fixture-Referenz, keine
Laufzeitabhängigkeit.

## Fixtures

- `current-main/root-turn.jsonl`: sichtbarer Zwischenstand plus autoritativer
  Root-Abschluss; Reasoning bleibt ausgeschlossen.
- `current-main/phase-missing-complete.jsonl`: expliziter Turn-Abschluss mit
  finaler Assistant-Antwort ohne Phase; Confidence `compatible`.
- `current-main/multi-turn.jsonl`: zwei getrennte Turns in einer Session.
- `current-main/future-type.jsonl`: unbekannter zukünftiger Rollouttyp;
  externes Routing bleibt gesperrt.
- `subagents/subagent-late.jsonl`: geerbter Parentpräfix, eigener
  Sub-Agent-Zwischenstand und verspäteter Child-Abschluss.
- `legacy/final-event.jsonl`: dokumentierter Legacyfallback mit
  Confidence `legacy`, extern fail-closed.
- `malformed/invalid-json.jsonl`: parsebarer erster Datensatz plus beschädigte
  Folgezeile zur Fehlerisolation.

`manifest.json` bindet Dateihashes, Zeilenzahlen, erwartete History-Typen und
den Upstreamcommit. `scripts/sanitize_codex_fixture.py` ist der einzige
vorgesehene Weg, zusätzliche lokale reale Beispiele in dieses Korpus zu
überführen.
