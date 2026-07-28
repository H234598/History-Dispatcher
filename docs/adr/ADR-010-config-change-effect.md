# ADR-010: Wirkung von Konfigurationsänderungen

**Datum:** 28. Juli 2026  
**Status: Akzeptiert**

## Kontext

Würden geänderte Regeln automatisch auf alte Queueeinträge wirken, könnten bereits bewertete oder erfolgreiche Deliveries unerwartet erneut versendet werden.

## Entscheidung

Neue Regeln gelten standardmäßig nur für nach dem Apply erzeugte Route-Pläne. Bestehende Pläne bleiben immutable. Rückwirkende Änderungen erfolgen ausschließlich über bounded, preview-, token- und confirmgeschützte `replan`- beziehungsweise `backfill`-Operationen.

## Konsequenzen

- Erfolgreiche Empfängerzustände bleiben unveränderlich.
- Skipzustände werden nicht automatisch reaktiviert.
- Audit und Reproduzierbarkeit werden einfacher.

## Verifikation

Routingtests müssen nachweisen, dass Configänderung allein keinen bestehenden Plan ändert und Replan nie Success zurücksetzt.
