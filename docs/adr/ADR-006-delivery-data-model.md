# ADR-006: Delivery-Datenmodell

**Datum:** 28. Juli 2026  
**Status: Akzeptiert**

## Kontext

Das v1-Modell claimt global pro History-Eintrag und trennt Empfängerresultate nicht dauerhaft vom Ziel. Mehrere gleichzeitige Ziele wären dadurch race- und resendanfällig.

## Entscheidung

Schema v2 trennt `history_events`, `route_plans`, `target_deliveries`, `recipient_deliveries` und `delivery_attempts`. Zustandsübergänge sind monoton; erfolgreiche Empfänger werden nie zurückgestuft.

## Konsequenzen

- Claims benötigen Ziel, Worker, Lease und Token.
- Partielle Zustellung ist ein erstklassiger Zustand.
- Migration muss bestehende Erfolge erhalten und uneindeutige Results in einen Legacyhold legen.

## Verifikation

DB- und Concurrencytests müssen doppelte aktive Leases, fremde Completion und Success-Downgrade verhindern.
