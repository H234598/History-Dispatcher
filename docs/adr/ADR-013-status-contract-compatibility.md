# ADR-013: Statusvertrag und Rückwärtskompatibilität

**Datum:** 28. Juli 2026  
**Status: Akzeptiert**

## Kontext

Status v2 benötigt Ziel-, Typ-, Heartbeat-, Alert- und Configrevisiondaten. TeeBotus und das bestehende Applet lesen jedoch `status-v1.json`.

## Entscheidung

Status v2 erhält den eigenen Dateinamen `status-v2.json`. Das Backend schreibt während mindestens einer definierten Übergangsrelease v1 und v2 parallel. Das neue Applet bevorzugt v2 und verwendet v1 nur read-only mit deutlich sichtbarem Kompatibilitätsmodus.

## Konsequenzen

- Zielgetrennte Mutationen sind im v1-Fallback deaktiviert.
- v1 wird nicht im Einführungsrelease abgeschaltet.
- Ein gemeinsamer Aggregator verhindert Countdrift.

## Verifikation

Contracttests vergleichen v1-/v2-Kernzähler; Major-Inkompatibilität führt im Applet zu read-only Safe Mode.
