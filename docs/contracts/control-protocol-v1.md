# Control-Protokoll v1

**Status:** eingefrorene Baseline mit additiven, rückwärtskompatiblen Operationen  
**Protokollwert:** `protocol_version = 1`

## Transport

- lokaler Unix-Stream-Socket;
- keine TCP-/UDP-Bindung;
- Socketdatei mit Modus `0600`;
- Server prüft Linux-`SO_PEERCRED` und akzeptiert nur `uid == os.getuid()`;
- Server-Timeout pro Verbindung: 30 Sekunden.

Der authentifizierte Client-Scope für Idempotenz ist die effektive UID des
owner-only Socketdienstes zusammen mit seiner lokalen Dispatcher-Datenbank.
Andere UIDs werden vor dem Requesthandling verworfen.

## Framing

Jede Nachricht besteht aus:

1. einem unsigned 4-Byte-Big-Endian-Längenfeld;
2. exakt so vielen UTF-8-Bytes mit einem JSON-Dokument.

Frames mit Länge `0`, einer Länge oberhalb des konfigurierten Limits,
abgeschnittenem Inhalt, ungültigem UTF-8 oder ungültigem JSON werden verworfen.

## Request

```json
{
  "protocol_version": 1,
  "request_id": "opaque-id",
  "operation": "status.get_redacted",
  "body": {}
}
```

- `operation` muss in der festen Allowlist stehen;
- `request_id` ist für idempotente Mutationen auf 128 Zeichen begrenzt und darf
  keine Steuerzeichen enthalten;
- ein fehlendes `body` entspricht `{}`;
- ein vorhandenes `body` muss ein JSON-Objekt sein;
- nicht endliche JSON-Zahlen werden mit `invalid_request` abgewiesen.

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

Interne Tracebacks werden nicht ausgegeben. Fehlercodes sind auf 96 Zeichen,
Fehlermeldungen auf 500 Zeichen begrenzt.

## Operation-Allowlist

```text
protocol.describe
health.get
status.get
status.get_redacted
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

`status.get_redacted` ist eine additive Read-only-Operation. Sie liefert eine
Antwort der Form `{ "version": 2, "status": { ... } }`. `status.get`,
`health.get` und `report.get` behalten während des Applet-Cutovers ihre
v1-Antwort unverändert.

## Idempotente Mutationen

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

1. Die ID ist innerhalb des Same-User-Scopes und der zugehörigen Datenbank
   eindeutig.
2. Vor der Mutation reserviert der Dienst die ID transaktional.
3. Gespeichert wird SHA-256 über die kanonische Struktur `{operation, body}`.
4. Dieselbe ID mit identischer Operation und identischem Body liefert die
   dauerhaft gespeicherte Antwort.
5. Eine abweichende Wiederverwendung wird mit `idempotency_conflict` abgewiesen.
6. Eine Reservierung ohne durable Antwort wird mit `idempotency_in_progress`
   abgewiesen.
7. Kann die Antwort nach einer Mutation nicht persistiert werden, bleibt die
   Reservierung offen und der Client erhält `idempotency_persist_failed`.
8. Retention erfolgt ausschließlich über `maintenance.prune`.

## Evolutionsregel

Neue inkompatible Request-/Responseformen benötigen eine neue Majorversion.
Additive Read-only-Operationen dürfen innerhalb von v1 ergänzt werden, wenn alte
Operationen semantisch und strukturell unverändert bleiben.
