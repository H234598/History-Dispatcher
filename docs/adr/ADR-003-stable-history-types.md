# ADR-003: Stabile History-Typen

**Datum:** 28. Juli 2026  
**Status: Akzeptiert**

## Kontext

Der v1-Typ `codex_run_summary` unterscheidet weder Sub-Agent-Abschluss, sichtbaren Zwischenstand noch Gesamtabschluss.

## Entscheidung

Classifier v1 verwendet die stabilen Typen `subagent_completion`, `intermediate_update`, `task_completion` und `unknown`. Zusätzlich werden Klassifikationsversion, Confidence, Reason-Code und Agentkontext gespeichert.

## Konsequenzen

- Die Typen sind ereignisorientiert statt quell- oder agentenorientiert benannt.
- Unbekannte Formate bleiben intern verschlüsselt und extern standardmäßig gesperrt.
- Legacybestand benötigt explizites Mapping und darf nicht still umgedeutet werden.

## Verifikation

Ein sanitisiertes Fixture-Korpus muss positive und negative Fälle für alle vier Typen deterministisch abdecken.
