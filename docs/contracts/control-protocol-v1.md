# Control-Protokoll v1

**Status:** eingefrorene Baseline mit sicherheitsrelevanter Präzisierung  
**Protokollwert:** `protocol_version = 1`

## Transport

- lokaler Unix-Stream-Socket;
- keine TCP-/UDP-Bindung;
- Socketdatei mit Modus `0600`;
- Server prüft Linux-`SO_PEERCRED` und akzeptiert nur `uid == os.getuid()`;
- Server-Timeout pro Verbindung: 30 Sekunden.

Der authentifizierte Client-Scope für Idempotenz ist die effektive UID des owner-only Socketdienstes zusammen mit seiner lokalen Dispatcher-Datenbank. Andere UIDs werden vor dem Requesthandling verworfen.

## Framing

Jede Nachricht besteht aus:

1. einem unsigned 4-Byte-Big-Endian-Längenfeld;
2. exakt so vielen UTF-8-Bytes mit einem JSON-Dokument.

Frames mit Länge `0`, einer Länge oberhalb des konfigurierten Limits, abgeschnittenem Inhalt, ungültigem UTF-8 oder ungültigem JSON werden verworfen.

## Request

```json
{
  "protocol_version": 1,
  "request_id": "opaque-id",
  "operation": "status.get",
  "body": {}
}
```

- `operation` muss in der festen Allowlist stehen;
- `request_id` ist für idempotente Mutationen auf 128 Zeichen begrenzt und darf keine Steuerzeichen enthalten;
- ein fehlendes `body` entspricht `{}`;
- ein vorhandenes `body` muss ein JSON-Objekt sein; Arrays, Strings, Zahlen, Boolesche Werte und `null` werden mit einem begrenzten Fehler `invalid_request` abgewiesen;
- nicht endliche JSON-Zahlen, die nicht kanonisch serialisiert werden können, werden ebenfalls mit `invalid_request` abgewiesen.

## Response

Erfolg:

```json
{"ok": true, "data": {}}
```

Fehler:

```json
{
  "ok": false,
  "error": {
    "code": "operation_failed",
    "message": "begrenzte Fehlermeldung"
  }
}
```

Interne Tracebacks werden an der API-Grenze nicht ausgegeben. Fehlercodes sind auf 96 Zeichen, Fehlermeldungen auf 500 Zeichen begrenzt.

## Operation-Allowlist

```text
protocol.describe
health.get
status.get
report.get
history.append
history.query
dispatch.claim
dispatch.complete
dispatch.retry
delivery.record
config.get
config.validate
config.apply
collector.collect
admin.preview
admin.execute
audit.query
migration.import_legacy
maintenance.prune
```

## Idempotente Mutationen

Der v1-Dienst kann Antworten für folgende Operationen anhand von `request_id` wiederverwenden:

```text
history.append
dispatch.claim
dispatch.complete
dispatch.retry
delivery.record
config.apply
collector.collect
admin.execute
migration.import_legacy
maintenance.prune
```

Für jede solche Request-ID gilt:

1. Die ID ist innerhalb des authentifizierten Same-User-Scopes und der zugehörigen Dispatcher-Datenbank eindeutig.
2. Vor der Mutation reserviert der Dienst die ID transaktional.
3. Gespeichert wird ein SHA-256-Fingerabdruck der kanonischen Struktur `{operation, body}`. JSON-Objektschlüssel werden sortiert und kompakt UTF-8-kodiert; die Reihenfolge von JSON-Arrays bleibt semantisch erhalten.
4. Dieselbe ID mit identischer Operation und identischem Body liefert die dauerhaft gespeicherte Antwort zurück.
5. Dieselbe ID mit abweichender Operation oder abweichendem Body wird mit `idempotency_conflict` abgewiesen und führt keine Mutation aus.
6. Eine reservierte ID ohne durable Antwort wird mit `idempotency_in_progress` abgewiesen. Das verhindert einen blinden Wiederholungsversuch nach einem Crash zwischen Mutation und Antwortpersistenz.
7. Kann die Antwort nach ausgeführter Mutation nicht persistiert werden, bleibt die Reservierung absichtlich offen und der Client erhält `idempotency_persist_failed`.
8. Idempotenzdatensätze werden mindestens für `audit_retention_days` aufbewahrt und ausschließlich durch `maintenance.prune` entfernt. Damit besitzt die Schutzfrist dieselbe operatorseitig dokumentierte Retention wie der Auditbestand.
9. Alte v1-Cachezeilen ohne Fingerabdruck werden beim sicheren Initialisieren verworfen, weil sie nicht vertrauenswürdig gegen Operation und Body geprüft werden können. Queue-, Delivery- und Auditdaten werden dabei nicht verändert.

## Evolutionsregel

Neue inkompatible Request-/Responseformen benötigen eine neue Protokoll-Majorversion. Ein alter Client darf eine unbekannte Majorversion nicht erraten. Übergangsoperationen werden explizit dokumentiert und capability-basiert aktiviert.
