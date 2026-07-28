# ADR-001: Quelle der Wahrheit für Routing

**Datum:** 28. Juli 2026  
**Status: Akzeptiert**

## Kontext

Routing muss auch ohne laufendes Cinnamon funktionieren. In dconf gespiegelte Backendwerte können zwischen Applets und Dienst auseinanderlaufen und besitzen keinen ausreichenden Revisions- oder Auditvertrag.

## Entscheidung

Die versionierte Backendkonfiguration ist die einzige dauerhafte Quelle der Wahrheit. SQLite hält immutable Route-Pläne und Runtimezustände; dconf speichert ausschließlich lokale UI-Präferenzen und opaque Notification-Dedupe-Metadaten.

## Konsequenzen

- Das dedizierte Applet benötigt einen revisionsgesicherten Backendeditor.
- Andere Applets dürfen Routing nur read-only spiegeln.
- Konfiguration bleibt headless, atomar validierbar und auditierbar.

## Verifikation

Config-v2-Tests müssen nachweisen, dass Backendroutingkeys nicht im Cinnamon-Settings-Schema persistiert werden und Apply `expected_revision` verwendet.
