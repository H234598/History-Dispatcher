# ADR-017: Zwei auswählbare Telegram-Provider

**Datum:** 28. Juli 2026  
**Status: Akzeptiert**

## Kontext

Der Implementierungsplan sah Telegram zunächst ausschließlich über TeeBotus
vor. Die neue verbindliche Anforderung verlangt zusätzlich, dass der
History-Dispatcher Telegram selbstständig ausliefern kann und dass die
Einstellungen zwischen beiden Wegen umschalten können.

Ein unkontrollierter Laufzeit-Fallback wäre gefährlich: Wenn ein Provider die
Nachricht extern bereits angenommen hat, aber der lokale Abschluss fehlt,
könnte ein zweiter Provider dieselbe Nachricht erneut senden.

## Entscheidung

`routing.telegram.provider` ist eine versionierte Enum mit genau zwei Werten:

- `teebotus`
- `history_dispatcher`

Der Provider wird gemeinsam mit Config-Revision, Credential-/Routenreferenzen
und Planner-Version unveränderlich im Route-Plan gespeichert und ist Teil des
Planhashes. Ein Worker darf nur Deliveries bedienen, deren Provider mit seiner
Capability übereinstimmt.

Es gibt **keinen automatischen Cross-Provider-Fallback**. Eine Änderung gilt
standardmäßig nur für neue Events. Bereits geplante, noch nicht erfolgreiche
Deliveries wechseln den Provider ausschließlich über eine explizite
Replan-Vorschau mit Revision, Token und exakter Bestätigung. Erfolgreiche
Empfänger bleiben unveränderlich.

Im Modus `teebotus` bleiben Bot-Credentials, private Account-Routen,
Formatierung und Callback-Spool Eigentum von TeeBotus. Im Modus
`history_dispatcher` betreibt der History-Dispatcher einen eigenen gehärteten
Telegramworker. Bot-Token und rohe Chat-IDs werden ausschließlich über Secret
Service beziehungsweise eine gleichwertige owner-only Credentialgrenze
aufgelöst. In Config, Route-Plan, Status, dconf und Logs stehen nur opaque
Referenzen.

## Konsequenzen

- Der zentrale Target-/Recipient-State-Vertrag ist für beide Provider identisch.
- Beide Provider verwenden dieselben stabilen Idempotency-Keys und monotonen
  Empfängerzustände.
- Der native Worker übernimmt beziehungsweise adaptiert TeeBotus-Muster für
  Route-Preflight, Erfolgsrang, Ausschluss bereits erfolgreicher Empfänger,
  Partial-Ergebnisse, `possible_duplicate`, Retry-After, Batching, Redaction und
  Reconciliation.
- Der Settings-Schalter ist Backendkonfiguration und kein dconf-Routingwert.
- Native Credentials werden niemals zurück an das Applet gelesen; die UI sieht
  nur `configured=true/false` und opaque Profilnamen.
- Das bestehende TeeBotus-Cross-Repository-Protokoll bleibt ein eigener,
  getesteter Providervertrag.

## Verifikation

- Providerwerte und Provider-Schema sind stabil getestet.
- Der Provider ist im Route-Plan-Fragment und Planhash enthalten.
- Ein Worker mit falschem Provider wird fail-closed abgewiesen.
- Token-, Chat-ID-, Pfad- und Kontrollzeichenwerte können nicht als opaque
  Referenz gespeichert werden.
- Empfängererfolge können durch spätere Fehler nicht zurückgestuft werden.
- Native und TeeBotus-Worker bestehen denselben Contract-Fixture-Korpus.
- Integrationstests injizieren Crash nach externem Accept, Rate-Limit und
  partielle Empfängerfehler für beide Provider.
