# ADR-002: Bedeutung von „Dispatch in/zu DB“

**Datum:** 28. Juli 2026  
**Status: Akzeptiert**

## Kontext

Die verschlüsselte Betriebsdatenbank ist Voraussetzung für Crashsicherheit und externen Dispatch. Ein UI-Schalter darf diese Persistenz nicht abschalten.

## Entscheidung

DB-Schalter steuern ein optionales logisches Langzeitarchiv innerhalb derselben verschlüsselten Datenbank. Die Betriebsqueue bleibt immer aktiv. Im Pflichtumfang existieren Archivschalter nur für `subagent_completion` und `intermediate_update`.

## Konsequenzen

- Kein Klartext- oder zweites unkoordiniertes DB-File.
- `task_completion` bleibt im normalen abgeschlossenen Betriebsbestand gemäß Retention.
- Archivfehler bilden ein eigenes Ziel und rollen Ingress nicht zurück.

## Verifikation

Routingtests müssen zeigen, dass alle Zielschalter aus sein können, während das Event weiterhin verschlüsselt in der Betriebsdatenbank persistiert wird.
