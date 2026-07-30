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
  "operation": "provider.v2.claim",
  "body": {}
}
```

- `operation` muss in der festen Allowlist stehen;
- `request_id` ist für idempotente Mutationen auf 128 Zeichen begrenzt und darf
  keine Steuerzeichen enthalten;
- alle `provider.v2.*`-Operationen verlangen eine nicht leere Request-ID;
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
provider.v2.claim
provider.v2.renew
provider.v2.register_recipients
provider.v2.record_recipients
provider.v2.complete
provider.v2.heartbeat
```

`status.get_redacted` ist additive Read-only-Operation. Sie liefert
`{ "version": 2, "status": { ... } }`; die v1-Statusoperationen bleiben
unverändert.

Die Provider-v2-Operationen sind additive Same-User-Workeroperationen. Ihr
vollständiger Body-/Responsevertrag steht in `docs/provider-api-v2.md`.

## Dauerhaft idempotente Mutationen

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
provider.v2.renew
provider.v2.register_recipients
provider.v2.record_recipients
provider.v2.complete
provider.v2.heartbeat
```

Für jede solche Request-ID gilt:

1. Die ID ist innerhalb des Same-User-Scopes und der zugehörigen Datenbank
   eindeutig.
2. Vor der Mutation reserviert der Dienst die ID transaktional.
3. Gespeichert wird SHA-256 über die kanonische Struktur `{operation, body}`.
4. Dieselbe ID mit identischer Operation und identischem Body liefert die
   dauerhaft gespeicherte Antwort.
5. Abweichende Wiederverwendung ergibt `idempotency_conflict`.
6. Reservierung ohne durable Antwort ergibt `idempotency_in_progress`.
7. Kann die Antwort nach der Mutation nicht persistiert werden, bleibt die
   Reservierung offen und der Client erhält `idempotency_persist_failed`.
8. Retention erfolgt ausschließlich über `maintenance.prune`.

## Sensible One-shot-Mutation `provider.v2.claim`

Ein erfolgreicher Claim kann einen geheimen `claim_token` enthalten. Eine solche
Antwort wird nie in `response_json` gespeichert. Der identische Replay ergibt
`idempotency_in_progress`; ein abweichender Replay `idempotency_conflict`.
Dadurch entstehen weder zweiter Attempt noch zweiter Token.

Eine erfolgreiche Antwort mit `claims: []` ist tokenfrei und wird normal
dauerhaft gecacht. Reine Validierungsfehler geben ihre exakte noch leere
Reservierung frei; abgeschlossene Antworten können dadurch nicht gelöscht
werden.

## Evolutionsregel

Neue inkompatible Request-/Responseformen benötigen eine neue Majorversion.
Additive Operationen dürfen innerhalb von v1 ergänzt werden, wenn alte
Operationen semantisch und strukturell unverändert bleiben und der neue
Operationsvertrag separat versioniert ist.
