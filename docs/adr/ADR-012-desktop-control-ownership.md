# ADR-012: Eigentümerschaft der Desktop-Control-Plane

**Datum:** 28. Juli 2026  
**Status: Akzeptiert**

## Kontext

Das dedizierte History-Dispatcher-Applet und das TeeBotus-Applet können v1-Backendwerte unabhängig spiegeln und verändern. Zwei Writer erzeugen Drift und schwer erklärbare Revisionen.

## Entscheidung

Das dedizierte History-Dispatcher-Applet ist die einzige schreibende Desktopoberfläche. TeeBotus zeigt den Dispatcherstatus read-only und verlinkt auf die dedizierten Einstellungen.

## Konsequenzen

- Server und Config-API dürfen veraltete TeeBotus-Writepfade nach der Übergangsphase ablehnen.
- Der Telegramworker in TeeBotus bleibt unabhängig von der UI-Eigentümerschaft bestehen.
- Dual-Applet-Tests müssen konkurrierende Writes ausschließen.

## Verifikation

Der gemeinsame Cinnamon-Test prüft, dass beide Applets laden, aber nur das dedizierte Applet Configapply anbietet.
