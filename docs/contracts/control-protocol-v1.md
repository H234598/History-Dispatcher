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

Jede Nachricht besteht aus einem unsigned 4-Byte-Big-Endian-Längenfeld und exakt
so vielen UTF-8-Bytes mit einem JSON-Dokument. Leere, übergroße, abgeschnittene
oder ungültige Frames werden verworfen.

## Request

```json
{
  "protocol_version": 1,
  "request_id": "opaque-id",
  "operation": "config.preview_apply",
  "body": {}
}
```

- `operation` muss in der festen Allowlist stehen;
- `request_id` ist für idempotente Mutationen auf 128 Zeichen begrenzt und darf
  keine Steuerzeichen enthalten;
- alle `provider.v2.*`-Operationen verlangen eine nicht leere Request-ID;
- `config.validate_patch` und `config.preview_apply` verlangen eine nicht leere
  Request-ID;
- previewgestütztes Config-v2-`config.apply` verlangt eine nicht leere
  Request-ID;
- Legacy-`config.apply` mit flachem `values`-Objekt bleibt kompatibel und darf
  weiterhin ohne Request-ID aufgerufen werden;
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
config.get_redacted
config.validate
config.validate_patch
config.preview_apply
config.apply
collector.collect
admin.preview
admin.execute
audit.query
migration.import_legacy
maintenance.prune
provider.v2.claim
provider.v2.reclaim
provider.v2.renew
provider.v2.register_recipients
provider.v2.record_recipients
provider.v2.complete
provider.v2.heartbeat
```

`status.get_redacted` ist additive Read-only-Operation. Sie liefert
`{ "version": 2, "status": { ... } }`; die v1-Statusoperationen bleiben
unverändert.

Die Config-v2-Operationen sind additive Same-User-Settingsoperationen:

- `config.get_redacted` liefert ausschließlich Routingrevision und opaque
  Telegramprofilnamen;
- `config.validate_patch` validiert und kanonisiert einen Patch;
- `config.preview_apply` erzeugt einen 60 Sekunden gültigen One-use-Preview;
- previewgestütztes `config.apply` führt Revision-CAS, atomaren Write, Audit und
  Rollback aus;
- Provideränderungen gelten ausschließlich für neue Route-Pläne.

Der vollständige Vertrag steht in `docs/config-v2-api.md`.

Die Provider-v2-Operationen sind additive Same-User-Workeroperationen. Ihr
vollständiger Body-/Responsevertrag steht in `docs/provider-api-v2.md`.

## Dauerhaft idempotente Mutationen

```text
history.append
dispatch.claim
dispatch.complete
dispatch.retry
delivery.record
config.validate_patch
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

Für previewgestütztes Config-v2-`config.apply` enthält die dauerhaft gespeicherte
Antwort niemals Previewtoken oder Patchwerte. Derselbe Request-ID-Replay liefert
die sichere Applyantwort; derselbe verbrauchte Previewtoken mit einer anderen
Request-ID wird abgewiesen.

## Sensible One-shot-Mutationen

```text
provider.v2.claim
provider.v2.reclaim
config.preview_apply
```

### Providerclaims

Eine erfolgreiche Antwort mit mindestens einem Claim enthält einen geheimen
`claim_token`. Sie wird nie in `idempotency_results.response_json` gespeichert.
Der identische Replay ergibt `idempotency_in_progress`; ein abweichender Replay
`idempotency_conflict`. Dadurch entstehen weder zweiter Attempt noch zweiter
Token.

Eine erfolgreiche Antwort mit `claims: []` ist tokenfrei und wird dauerhaft
gecached. Reine Validierungsfehler geben ihre exakte noch leere Reservierung
frei; abgeschlossene Antworten können dadurch nicht gelöscht werden.

`provider.v2.reclaim` ist zusätzlich auf reine Callback-/Completion-
Reconciliation begrenzt. Ein erfolgreicher Eintrag trägt
`reconciliation_only=true`, bindet exakt eine Target-Delivery und darf von einem
Transportworker nicht als Autorisierung für einen neuen Send interpretiert
werden.

### Configpreview

`config.preview_apply` liefert einen kurzlebigen geheimen Previewtoken. Die
Antwort wird nie in `idempotency_results.response_json` gespeichert. Ein
identischer Request-ID-Replay ergibt `idempotency_in_progress`; ein abweichender
Replay `idempotency_conflict`.

Reine Patch-/Revisionsvalidierungsfehler geben ihre exakte noch leere
Reservierung frei. Der Previewtoken selbst wird ausschließlich gehasht im
begrenzten In-Memory-Previewregister gehalten und erscheint weder in TOML,
Status, Snapshot noch Audit.

## Config-v2-Bestätigung und Wirkung

Ein produktiver Apply verlangt exakt:

```text
expected_revision
preview_token
fingerprint
confirmation = APPLY <erste 12 Fingerprint-Zeichen>
```

Die Wirkung ist hart als `new_route_plans_only` ausgewiesen. Der Apply ändert
keine bestehenden Route-Pläne und führt keinen Cross-Provider-Fallback aus.

## Evolutionsregel

Neue inkompatible Request-/Responseformen benötigen eine neue Majorversion.
Additive Operationen dürfen innerhalb von v1 ergänzt werden, wenn alte
Operationen semantisch und strukturell unverändert bleiben und der neue
Operationsvertrag separat versioniert ist.
