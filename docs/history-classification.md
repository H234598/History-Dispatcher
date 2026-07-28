# Versionierte History-Klassifikation

**Stand:** 28. Juli 2026  
**Implementierungsschnitt:** `PR-HD-02-codex-fixtures-classifier`  
**Classifier-Schema:** `1`  
**Upstream-Protokollreferenz:** `openai/codex@8e271dc02b23d42827875019924be0f5005642b0`

## 1. Geltungsbereich dieses Schnitts

Dieser Schnitt führt einen **reinen, nebenwirkungsfreien Classifier** und ein
sanitisiertes JSONL-Fixture-Korpus ein. Er verändert noch nicht:

- den produktiven Collector;
- Cursor oder Source-Registry;
- SQLite-Schema oder bestehende Queueeinträge;
- Routing, Telegram, Vault oder lokales Archiv;
- Status-Snapshot oder Cinnamon-Applet.

Der bisherige `codex_run_summary`-Produktionspfad bleibt deshalb bis zum
separaten Collector-/Migrationsschnitt unverändert. Diese Trennung verhindert,
dass eine neue Semantik ohne Datenmodell-, Migration- und Routingvertrag
teilaktiv wird.

## 2. Stabile Taxonomie

| `history_kind` | Bedeutung | Primäre Evidenz | externe Dispatchfähigkeit im Classifier |
|---|---|---|---|
| `subagent_completion` | Abschluss einer eindeutig als Sub-Agent identifizierten Session | `parent_thread_id`, `thread_source=subagent` oder `source=subagent/thread_spawn` plus Turn-Abschluss | nur `authoritative`/`compatible`, bekannte Session und bekanntes Projekt |
| `intermediate_update` | sichtbare, nicht abschließende Assistant-Zwischenmeldung | Assistant-`response_item` mit `phase=commentary`; kompatibel auch `event_msg/agent_message` | nur bei bekannter Session/Projektidentität |
| `task_completion` | Abschluss eines Root-Turns | `task_complete`/`turn_complete` plus korrelierte finale Assistant-Antwort | nur `authoritative`/`compatible`, bekannte Session und bekanntes Projekt |
| `unknown` | unbekanntes, mehrdeutiges, internes oder unvollständiges Ereignis | fehlende/konfliktäre Evidenz oder zukünftiger Rollouttyp | immer `false` |

Zusatzfelder:

- `classification_schema_version = 1`;
- `classification_confidence` = `authoritative`, `compatible`, `legacy` oder
  `ambiguous`;
- stabiler `classification_reason_code`;
- `agent_context` = `root`, `subagent` oder `unknown`;
- `source_schema_family` = `codex_rollout_current`,
  `codex_rollout_legacy` oder `unknown`.

## 3. Verarbeitungsreihenfolge

1. Eine JSONL-Zeile wird vor dem Parse auf ein hartes Byte-Limit geprüft.
2. UTF-8, eindeutige JSON-Objektschlüssel und endliche JSON-Zahlen sind
   verpflichtend. Doppelkeys, `NaN`, `Infinity`, Arrays oder ungültige
   Envelopes werden als begrenzte Issues protokolliert.
3. `session_meta` setzt Session-, Parent-, Agent- und Projektkontext.
4. Interne Codex-Sessions oder Session-Metadaten ohne stabile ID erhalten
   `agent_context=unknown` und bleiben extern fail-closed.
5. Bei Sub-Agenten markiert `subagent_history_start_ordinal` den Beginn des
   eigenen Child-Verlaufs. Frühere `turn_context`, Messages und Completion-
   Events sind geerbter Parentkontext und werden nicht als Child-History
   ausgegeben.
6. Nur `response_item` vom Typ `message`, Rolle `assistant` und Contentteil
   `output_text` ist sichtbar. User-, System-, Developer-, Reasoning-, Tool-
   und Bildteile werden ausgeschlossen.
7. `commentary` erzeugt unmittelbar ein `intermediate_update`.
8. `final_answer` beziehungsweise eine kompatible phase-lose Assistant-
   Nachricht wird zunächst turnbezogen gepuffert.
9. `task_complete`/`turn_complete` korreliert den Turn und erzeugt je nach
   Agentkontext `task_completion`, `subagent_completion` oder `unknown`.
10. Ein Abschluss ohne explizites Completion-Event wird nur dann erzeugt, wenn
    der Aufrufer ausdrücklich `source_quiescent=True` setzt. Der spätere
    Collector muss die im Plan festgelegte Quiescence-Frist selbst beweisen.
11. Legacy-`event`/`phase=final` bleibt `confidence=legacy` und ist unabhängig
    vom Projektnamen nicht extern dispatchfähig.
12. Unbekannte zukünftige Top-Level-Typen erzeugen einen verschlüsselbar
    repräsentierbaren `unknown`-Event, ohne die Bedeutung zu erraten.

## 4. Opaque Korrelation und Datenschutz

Der öffentliche `ClassifiedEvent` enthält keine rohen Session-, Turn-, Parent-
oder Response-IDs. Diese Werte werden in stabile opaque Hash-Keys überführt:

```text
sess_<sha256-prefix>
turn_<sha256-prefix>
parent_<sha256-prefix>
resp_<sha256-prefix>
```

Projektidentität wird bevorzugt aus einer credential-frei normalisierten
Git-Remote gebildet; andernfalls aus dem lokalen Projektkontext. Ausgegeben
werden nur `project_id` und ein gekürztes, redigiertes Label. Absolute lokale
Pfade, Credentials und Remote-Userinfo werden nicht veröffentlicht.

Sichtbarer Text wird vor der Eventbildung normalisiert und redigiert. Entfernt
werden unter anderem:

- OpenAI- und Telegram-Tokenmuster;
- Bearer-/Secret-/Password-Zuweisungen;
- credential-tragende URLs;
- E-Mail-Adressen;
- typische absolute Linux-, macOS- und Windows-Privatpfade;
- C0-/C1-Steuerzeichen.

Das UTF-8-Ergebnis ist standardmäßig auf 512 KiB begrenzt und endet bei
Trunkierung mit einem eindeutigen Marker.

## 5. Deterministische Event- und Dedupe-Keys

Der vollständige Dedupe-Key ist SHA-256 über eine kanonische, durch `US`
(`0x1f`) getrennte Folge:

```text
source_schema_family
session_id
turn_id
parent_thread_id
history_kind
response_or_completion_identity
sha256(redacted_visible_text)
classification_schema_version
```

`event_id` ist `evt_` plus ein 24-stelliges Präfix dieses Dedupe-Keys. Die
Rohwerte erscheinen weder in `event_id` noch in der öffentlichen Eventansicht.
Doppelte Completionzeilen desselben Turns erzeugen denselben Key; zwei Turns
oder ein tatsächlich geänderter sichtbarer Inhalt bleiben unterscheidbar.

Eine spätere Reclassification mit neuer Schemaversion darf nicht automatisch
zu externem Neuversand führen. Das wird erst im Datenmodell-/Replan-Schnitt
festgelegt.

## 6. Sanitisiertes Fixture-Korpus

Das Korpus liegt unter `tests/fixtures/codex/` und besitzt ein gehashtes
`manifest.json`. Es deckt mindestens ab:

- Root-Commentary plus autoritativen Abschluss;
- phase-losen kompatiblen Abschluss;
- mehrere Turns in einer Session;
- Sub-Agent mit Parentpräfix und eigener Ordinalgrenze;
- Legacy-Finalevent;
- zukünftigen unbekannten Rollouttyp;
- beschädigte JSONL-Zeile.

Neue reale Beispiele dürfen nie roh committed werden. Vorgesehener Ablauf:

```bash
python scripts/sanitize_codex_fixture.py \
  /privater/pfad/rollout.jsonl \
  /tmp/sanitized-rollout.jsonl \
  --manifest /tmp/sanitized-manifest.json \
  --upstream-commit 8e271dc02b23d42827875019924be0f5005642b0 \
  --dry-run
```

Nach Sichtprüfung wird der Befehl ohne `--dry-run` wiederholt. Der Sanitizer:

- verarbeitet die Quelldatei streamingbasiert;
- lehnt ungültiges, nicht eindeutiges oder übergroßes JSON ab;
- pseudonymisiert IDs deterministisch;
- ersetzt Pfade, URLs, Namen, freien Text und unbekannte Strings;
- redigiert secretartige Schlüssel;
- schreibt atomar mit privaten Rechten;
- speichert im Manifest ausschließlich Hashreferenzen, Zeilenzahl,
  Schemaversion und Upstreamcommit.

Die private Quelldatei und ein Manifest mit lokalem Quellpfad dürfen nicht in
das Repository gelangen.

## 7. API

```python
from history_dispatcher.classification import CodexRolloutClassifier

report = CodexRolloutClassifier().classify_lines(
    rollout_file,
    source_quiescent=False,
)
```

`ClassificationReport` enthält immutable `events`, bounded `issues`,
`records_seen`, `records_ignored` und `unknown_records`. Der Classifier führt
keine I/O-, Datenbank-, Cursor-, Dispatch- oder Netzwerkoperation aus.

## 8. Abnahmeregeln für den nächsten Integrationsschnitt

Der Collector darf erst auf diesen Classifier umgestellt werden, wenn:

1. das Fixturemanifest und alle Classification-/Sanitizer-Tests grün sind;
2. die DB-v2-Schnittstelle die vier History-Typen und Confidence sicher
   aufnehmen kann;
3. unbekannte beziehungsweise Legacyevents extern fail-closed bleiben;
4. Cursor, Partial-Line-Recovery und verspätete Sub-Agent-Events separat
   getestet sind;
5. Migration und Replan keinen unbeabsichtigten Neuversand erzeugen.
