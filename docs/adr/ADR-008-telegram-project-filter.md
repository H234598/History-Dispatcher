# ADR-008: Telegram-Projektfilter

**Datum:** 28. Juli 2026  
**Status: Akzeptiert**

## Kontext

Freie Pfade, Anzeigenamen, Globs oder Regex würden uneindeutige und potenziell gefährliche Routingentscheidungen erzeugen.

## Entscheidung

Der Telegramfilter verwendet ausschließlich kanonische stabile `project_id`-Werte. Jeder Konfigurationseintrag wird getrimmt und per Unicode-NFC normalisiert; identische kanonische Werte werden deterministisch dedupliziert. Einträge mit C0-/C1-Steuerzeichen oder `DEL`, leere Einträge nach dem Trim, Globs, Regex und Teilstringregeln werden abgelehnt. Der Match ist case-sensitive und exakt.

Es gibt nur `blacklist` und `whitelist`. Eine leere Whitelist blockiert alles, eine leere Blacklist blockiert nichts. Unbekannte Projekte werden für Telegram geskippt.

## Konsequenzen

- Displaynamen sind nur UI-Hilfe und niemals autoritative Filterwerte.
- Liste, Zeilenlänge und Gesamtgröße werden begrenzt.
- Die gespeicherte Reihenfolge folgt der ersten kanonischen Nennung; spätere Duplikate werden entfernt.
- Ein einziger ungültiger Eintrag macht den gesamten Patch ungültig; es gibt keine stille Teilübernahme.
- Der Filter gilt ausschließlich für Telegram.

## Verifikation

Truth-Table-Tests müssen Leerlisten, Unicode-NFC, Trim, deterministische Deduplizierung, Ablehnung von Steuerzeichen, Case-, Exact-Match-, Glob-, Regex- und Substringfälle abdecken.
