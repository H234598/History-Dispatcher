# ADR-005: Router- und Worker-Topologie

**Datum:** 28. Juli 2026  
**Status: Akzeptiert**

## Kontext

Ein monolithischer Prozess würde Telegramcredentials in den Kern ziehen; vollständig dezentrale Worker könnten Routingregeln unterschiedlich interpretieren.

## Entscheidung

Der History-Dispatcher erstellt zentral einen immutable Route-Plan. Zielgebundene Worker claimen ausschließlich ihre Deliveries: lokales Archiv im Kern, Telegram über TeeBotus und Vault über einen separaten Worker.

## Konsequenzen

- Ziele besitzen getrennte Leases, Backoff- und Fehlerzustände.
- Ein Telegramausfall blockiert Vault und Archiv nicht.
- Das Applet besitzt keinen Workerloop.

## Verifikation

Integrationstests müssen unabhängige Claims und Crash-Recovery pro Ziel nachweisen.
