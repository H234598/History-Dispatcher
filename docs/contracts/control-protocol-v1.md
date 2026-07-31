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
  "operation": "credential.preview_apply",
  "body": {}
}
```

- `operation` muss in der festen Allowlist stehen;
- `request_id` ist für idempotente Mutationen auf 128 Zeichen begrenzt und darf
  keine Steuerzeichen enthalten;
- alle `provider.v2.*`-Operationen verlangen eine nicht leere Request-ID;
- `config.validate_patch`, `config.preview_apply` und previewgestütztes
  `config.apply` verlangen eine nicht leere Request-ID;
- `credential.preview_apply` und `credential.apply` verlangen eine nicht leere
  Request-ID;
- `credential.get_status` ist read-only und benötigt keine Request-ID;
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

Interne Tracebacks, Secret-Service-stdout/-stderr, Bot-Tokens und Chat-IDs werden
nicht ausgegeben. Fehlercodes sind auf 96 Zeichen, Fehlermeldungen auf 500
Zeichen begrenzt.

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
credential.get_status
credential.preview_apply
credential.apply
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

## Config-v2-Operationen

- `config.get_redacted` liefert ausschließlich Routingrevision und opaque
  Telegramprofilnamen;
- `config.validate_patch` validiert und kanonisiert einen Patch;
- `config.preview_apply` erzeugt einen 60 Sekunden gültigen One-use-Preview;
- previewgestütztes `config.apply` führt Revision-CAS, atomaren Write, Audit und
  Rollback aus;
- Provideränderungen gelten ausschließlich für neue Route-Pläne.

Der vollständige Vertrag steht in `docs/config-v2-api.md`.

## Credential-Operationen

### `credential.get_status`

Read-only, Body exakt `{}`. Die Antwort enthält ausschließlich aktuell durch
Config v2 autorisierte opaque Profile und secretfreie Metadaten:

```json
{
  "schema_version": 1,
  "bot": {
    "profile_ref": "telegram_primary",
    "configured": false,
    "last_changed": null
  },
  "recipients": []
}
```

Die Operation führt keinen Secret-Service-Lookup aus.

### `credential.preview_apply`

Sensible One-shot-Mutation. Erlaubte Felder:

```text
action = set | replace | delete
secret_kind = bot_token | chat_id
profile_ref = opaque Config-v2 profile
secret_value = write-only, nur bei set/replace
```

Die Antwort enthält Fingerprint, exakte Bestätigung, 60-Sekunden-One-use-Token,
Action, Kind und opaque Profil, aber niemals den Secretwert. Der Secretwert lebt
nur im begrenzten In-Memory-Previewregister.

### `credential.apply`

Dauerhaft idempotente Mutation mit exakt:

```text
preview_token
fingerprint
confirmation = CREDENTIAL <ACTION> <erste 12 Fingerprint-Zeichen>
```

Die Antwort ist secretfrei und enthält nur Action, Kind, opaque Profil,
`configured` und `last_changed`. Secret-Service-Mutation, Post-Write-Prüfung,
Metadaten/Audit und kompensierender Rollback sind in
`docs/native-telegram-credentials.md` beschrieben.

## Provider-v2-Operationen

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
credential.apply
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

Previewgestütztes Config-v2- und Credential-`apply` speichern ausschließlich
secretfreie Antworten. Derselbe Request-ID-Replay liefert dieselbe Antwort;
ein verbrauchter Previewtoken unter einer anderen Request-ID wird abgewiesen.

## Sensible One-shot-Mutationen

```text
provider.v2.claim
provider.v2.reclaim
config.preview_apply
credential.preview_apply
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
`reconciliation_only=true` und darf nie als Autorisierung für einen neuen Send
interpretiert werden.

### Configpreview

`config.preview_apply` liefert einen kurzlebigen geheimen Previewtoken. Die
Antwort wird nie im Idempotenz-Responsecache gespeichert. Reine
Patch-/Revisionsvalidierungsfehler geben die exakte leere Reservierung frei.

### Credentialpreview

`credential.preview_apply` enthält im Request einen Secretwert und liefert einen
kurzlebigen Previewtoken. Weder Requestbody noch Antwort werden als
Idempotenzantwort gespeichert; gespeichert werden ausschließlich Operation und
Requestfingerprint. Ein identischer Replay ergibt `idempotency_in_progress`.

Reine Format-, Action-, Kind-, Profil- oder Configautorisierungsfehler geben die
exakte leere Reservierung frei. Ein operationaler Secret-Service- oder
Schemafehler bleibt pending, damit eine unbekannte Mutation nicht blind
wiederholt wird.

## Bestätigungen und Wirkung

Config-v2:

```text
APPLY <erste 12 Fingerprint-Zeichen>
```

Credential:

```text
CREDENTIAL <SET|REPLACE|DELETE> <erste 12 Fingerprint-Zeichen>
```

Config-v2 wirkt ausschließlich auf neue Route-Pläne. Credentialoperationen
ändern ausschließlich den Secret-Service-Wert und dessen secretfreie Metadaten;
sie senden keine Telegramnachricht und verändern keinen Route-Plan.

## Evolutionsregel

Neue inkompatible Request-/Responseformen benötigen eine neue Majorversion.
Additive Operationen dürfen innerhalb von v1 ergänzt werden, wenn alte
Operationen semantisch und strukturell unverändert bleiben und der neue
Operationsvertrag separat versioniert ist.
