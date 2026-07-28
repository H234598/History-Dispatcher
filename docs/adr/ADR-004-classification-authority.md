# ADR-004: Klassifikationsautorität und Legacyfallback

**Datum:** 28. Juli 2026  
**Status: Akzeptiert**

## Kontext

Aktuelle Codex-Rollouts besitzen explizite Session-, Turn-, Phase- und Sub-Agent-Metadaten; ältere Exporte sind unvollständiger. Nur eine Quelle zu akzeptieren wäre entweder unsicher oder inkompatibel.

## Entscheidung

Die Klassifikation ist gestuft: aktuelle Metadaten und Completion-Events sind autoritativ, ein dokumentierter Quiescence-Fallback ist kompatibel, Legacyheuristiken bleiben niedrig vertraut. `legacy` und `ambiguous` werden standardmäßig nicht extern versandt.

## Konsequenzen

- Parser und Classifier müssen unbekannte Typen sichtbar zählen.
- Confidence ist Bestandteil des gespeicherten Ergebnisses.
- Externe Ziele prüfen nicht nur Kind, sondern auch Dispatchfähigkeit.

## Verifikation

Classifier-Tests müssen fehlende Phase, unbekannte Rollouttypen, verspätete Sub-Agenten und Legacyformate fail-closed abdecken.
