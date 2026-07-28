# ADR-015: Safe Mode und Poll-/Worker-Eigentümerschaft

**Datum:** 28. Juli 2026  
**Status: Akzeptiert**

## Kontext

Wiederholte GJS-, Snapshot- oder Renderefehler dürfen das Panel nicht dauerhaft unbedienbar machen. Das Poll-Owner-Muster anderer Applets darf aber nicht dazu führen, dass das Applet Collector oder Dispatcher übernimmt.

## Entscheidung

Last-known-good, Circuit Breaker und Safe-Mode-Minimalmenü werden konzeptionell übernommen. Collection, Routing und Dispatch bleiben immer Backendaufgaben. Der Applet-Timer liest ausschließlich Snapshots.

## Konsequenzen

- Safe Mode kann nur Darstellung und lokale Pollfrequenz reduzieren.
- Appletremoval oder Circuit-Open stoppt keine Unit.
- Manuelle Recovery schließt den Circuit erst nach erfolgreichem Read und Render.

## Verifikation

Runtime- und isolierte Cinnamon-Tests injizieren invaliden Snapshot, Hänger, Renderexception und Removal während Callback und prüfen Backend-Liveness.
