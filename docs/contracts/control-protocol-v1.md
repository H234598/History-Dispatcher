# Control-Protokoll v1

**Status:** eingefrorene Baseline  
**Protokollwert:** `protocol_version = 1`

## Transport

- lokaler Unix-Stream-Socket;
- keine TCP-/UDP-Bindung;
- Socketdatei mit Modus `0600`;
- Server prüft Linux-`SO_PEERCRED` und akzeptiert nur `uid == os.getuid()`;
- Server-Timeout pro Verbindung: 30 Sekunden.

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
- `body` ist ein JSON-Objekt; andere Werte werden als leeres Objekt behandelt.

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

Interne Tracebacks werden an der API-Grenze nicht ausgegeben.

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

## Evolutionsregel

Neue inkompatible Request-/Responseformen benötigen eine neue Protokoll-Majorversion. Ein alter Client darf eine unbekannte Majorversion nicht erraten. Übergangsoperationen werden explizit dokumentiert und capability-basiert aktiviert.
