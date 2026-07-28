# ADR-007: Telegram-Eigentümerschaft

**Datum:** 28. Juli 2026  
**Status: Akzeptiert; durch ADR-017 erweitert und in der exklusiven Form ersetzt**

## Kontext

TeeBotus besitzt Bot-Credentials, private Admin-/Accountrouten,
Messengerformatierung und Callback-Spool. Die ursprüngliche Entscheidung sah
TeeBotus deshalb als einzigen autorisierten Telegramworker vor.

Am 28. Juli 2026 wurde die verbindliche Zusatzanforderung aufgenommen, dass der
History-Dispatcher Telegram auch ohne TeeBotus selbstständig ausliefern können
muss. Die bestehende TeeBotus-Integration bleibt erhalten, ist aber nicht mehr
der einzige Transportweg.

## Entscheidung

Der weiterhin gültige Teil dieser ADR lautet: Das Cinnamon-Applet enthält keine
Telegram-Credentials, Chat-IDs, Netzwerkclients oder Dispatchschleifen. Der
History-Dispatcher entscheidet bei der Route-Plan-Erstellung, ob ein Event zum
Ziel `telegram` gehört.

Die exklusive Festlegung auf TeeBotus ist durch ADR-017 ersetzt. Der konkrete
Provider wird nun unveränderlich je Route-Plan auf `teebotus` oder
`history_dispatcher` gebunden.

## Konsequenzen

- Keine Tokens oder Chat-IDs in dconf, Snapshot oder Applet.
- TeeBotus bleibt ein vollwertiger, auswählbarer Provider.
- Der History-Dispatcher erhält zusätzlich einen eigenen Telegramworker.
- Es gibt keinen automatischen Provider-Fallback nach Erstellung eines
  Route-Plans.

## Verifikation

ADR-017, der Providervertrag und die zugehörigen Tests müssen beweisen, dass
Providerwechsel den Planhash ändern, falsche Worker einen Claim nicht bedienen
können und erfolgreiche Empfängerzustände transportübergreifend nicht
zurückgestuft werden.
