# ADR-014: Notification-Deduplizierung

**Datum:** 28. Juli 2026  
**Status: Akzeptiert**

## Kontext

Polling darf bei unverändertem Backlog oder nach Appletneustart keine Notification-Stürme auslösen. Gleichzeitig dürfen keine privaten History- oder Projektpfaddaten in dconf gespeichert werden.

## Entscheidung

Das Backend persistiert monotone `epoch`- und `event_sequence`-Werte. Das Applet speichert nur letzte Sequenz, opaque Alert-IDs, Severity und lokale Cooldownmetadaten in dconf. Alte Events werden beim ersten Start als Baseline behandelt.

## Konsequenzen

- Zustandswechsel und Severity-Eskalation sind die primären Trigger.
- Reminder verwenden einen begrenzten Cooldown.
- dconf enthält keine Historytexte, absoluten Pfade, Recipient- oder Secretwerte.

## Verifikation

Runtime-Tests müssen Eintritt, unveränderte Polls, Neustart, Cooldown, Resolve/Re-enter und beschädigten lokalen Dedupe-State abdecken.
