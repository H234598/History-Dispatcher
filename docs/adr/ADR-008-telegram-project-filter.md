# ADR-008: Telegram-Projektfilter

**Datum:** 28. Juli 2026  
**Status: Akzeptiert**

## Kontext

Freie Pfade, Anzeigenamen, Globs oder Regex würden uneindeutige und potenziell gefährliche Routingentscheidungen erzeugen.

## Entscheidung

Der Telegramfilter verwendet kanonische stabile `project_id`-Werte, Unicode-NFC, Trim und case-sensitive exakten Match. Es gibt nur `blacklist` und `whitelist`; keine Globs, Regex oder Teilstrings. Eine leere Whitelist blockiert alles, eine leere Blacklist nichts. Unbekannte Projekte werden für Telegram geskippt.

## Konsequenzen

- Displaynamen sind nur UI-Hilfe.
- Liste, Zeilenlänge und Gesamtgröße werden begrenzt.
- Der Filter gilt ausschließlich für Telegram.

## Verifikation

Truth-Table-Tests müssen Leerlisten, Unicode, Duplikate, Steuerzeichen, Case- und Substringfälle abdecken.
