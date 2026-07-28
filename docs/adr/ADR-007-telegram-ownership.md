# ADR-007: Telegram-Eigentümerschaft

**Datum:** 28. Juli 2026  
**Status: Akzeptiert**

## Kontext

TeeBotus besitzt bereits Bot-Credentials, private Admin-/Accountrouten, Messengerformatierung und Callback-Spool. Eine zweite Implementierung im Applet oder Kerndienst würde Secrets und Transportlogik duplizieren.

## Entscheidung

Der History-Dispatcher entscheidet, ob ein Event zum Ziel `telegram` gehört. TeeBotus bleibt der autorisierte zielgebundene Telegramworker und löst die privaten Empfängerrouten auf.

## Konsequenzen

- Keine Tokens oder Chat-IDs in dconf, Snapshot oder History-Dispatcher-Applet.
- Ein versionierter Cross-Repository-Contract wird benötigt.
- Produktives Telegram v2 setzt eine kompatible TeeBotus-Version voraus.

## Verifikation

Contracttests beider Repositorys müssen target-spezifische Claims, Partial Recipient Results, Retry-After und Spool-Reconciliation abdecken.
