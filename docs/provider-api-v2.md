# Provider-v2-Worker-API

**Stand:** 30. Juli 2026  
**Implementierungsschnitte:** `PR-HD-08a-provider-v2-api`, `PR-HD-08c-provider-v2-target-reclaim`  
**Schema:** `2`  
**Transport:** owner-only Same-User-Unix-Socket, `protocol_version = 1`

## 1. Zweck

Die Provider-v2-API verbindet externe Transportworker mit dem zentralen,
providergebundenen Delivery-Store des History-Dispatchers. Der erste echte
Client ist TeeBotus; der spätere native Telegramworker verwendet denselben
Storevertrag mit eigener Provider-ID und Capability.

Der History-Dispatcher bleibt Eigentümer von Event, verschlüsselter Payload,
Route-Plan, Providerbindung, Target-/Recipient-Delivery, Claim, Lease, Attempt,
Idempotenz, Retry, Aggregation und Reconciliation. Der Worker besitzt nur den
konkreten Transport. Es gibt keinen automatischen Cross-Provider-Fallback.

## 2. Operationen

```text
provider.v2.claim
provider.v2.reclaim
provider.v2.renew
provider.v2.register_recipients
provider.v2.record_recipients
provider.v2.complete
provider.v2.heartbeat
```

Alle Operationen sind mutierend, verlangen eine nicht leere `request_id` und
werden gegen feste Feldallowlists, endliches JSON und maximal 256 KiB geprüft.

## 3. Normaler Claim

### Request

```json
{
  "protocol_version": 1,
  "request_id": "opaque-request-id",
  "operation": "provider.v2.claim",
  "body": {
    "target_id": "telegram",
    "provider_id": "teebotus",
    "worker_id": "teebotus-worker",
    "capability_version": "history-dispatcher-telegram-v2",
    "limit": 20,
    "lease_seconds": 120
  }
}
```

Optionale begrenzte Felder:

```text
max_attempts
base_backoff_seconds
max_backoff_seconds
jitter_ratio
```

Provider- und Capability-Missmatches liefern keine fremde Delivery und lösen
keinen Fallback aus.

### Antwort mit Claim

```json
{
  "ok": true,
  "data": {
    "ok": true,
    "schema_version": 2,
    "claims": [
      {
        "target_delivery_id": "target_opaque",
        "route_plan_id": "route_opaque",
        "event_id": "evt_opaque",
        "target_id": "telegram",
        "provider_id": "teebotus",
        "provider_schema_version": 1,
        "binding": {
          "schema_version": 1,
          "provider": "teebotus",
          "bridge_capability": "history-dispatcher-telegram-v2"
        },
        "attempt_no": 1,
        "worker_id": "teebotus-worker",
        "capability_version": "history-dispatcher-telegram-v2",
        "claim_token": "one-shot-secret",
        "claim_expires_at": "timestamp",
        "payload": {},
        "successful_recipient_refs": [],
        "open_recipient_refs": []
      }
    ]
  }
}
```

Der Token wird genau einmal zurückgegeben; in der Datenbank wird nur sein
SHA-256 gespeichert.

## 4. Gezielter Reclaim für Reconciliation

`provider.v2.reclaim` bindet nach Ablauf einer alten Claim-Lease exakt dieselbe
Target-Delivery erneut. Der Pfad dient ausschließlich dazu, bereits entstandene
Recipient- oder Completioncallbacks aus einem verschlüsselten Spool mit einem
neuen Token zu replayen.

### Request

```json
{
  "protocol_version": 1,
  "request_id": "reclaim-target-attempt-1",
  "operation": "provider.v2.reclaim",
  "body": {
    "target_delivery_id": "target_opaque",
    "provider_id": "teebotus",
    "worker_id": "teebotus-worker",
    "capability_version": "history-dispatcher-telegram-v2",
    "previous_attempt_no": 1,
    "lease_seconds": 120
  }
}
```

### Bedingungen

- Target, Route-Plan und Providerbinding müssen existieren und aktiv sein;
- Event darf nicht auf `legacy_hold` stehen;
- Provider und Capability müssen exakt zur unveränderlichen Binding passen;
- `previous_attempt_no` muss dem aktuellen Attempt entsprechen;
- ein noch aktiver Claim wird nicht gestohlen;
- terminale Zustände werden nicht geöffnet;
- stale Reclaims nach einem bereits erfolgten Rebind liefern `claims: []`;
- Cross-Provider-Reclaim liefert `claims: []`.

### Erfolgreiche Antwort

Der neue Claim besitzt einen neuen Attempt und einen neuen One-shot-Token:

```json
{
  "ok": true,
  "data": {
    "ok": true,
    "schema_version": 2,
    "claims": [
      {
        "target_delivery_id": "target_opaque",
        "attempt_no": 2,
        "claim_token": "new-one-shot-secret",
        "reconciliation_only": true,
        "payload": {},
        "successful_recipient_refs": [],
        "open_recipient_refs": []
      }
    ]
  }
}
```

Der vorherige offene Target-Attempt wird als `reclaimed_expired` mit
`claim_expired_reconciliation` abgeschlossen. Payload, Binding und
Recipientzustände werden nicht verändert.

`reconciliation_only=true` ist eine harte Workergrenze: Der Token darf für
`record_recipients`, `complete` und nötige Leaseverlängerung verwendet werden,
aber niemals einen neuen Telegram-Send autorisieren.

## 5. One-shot-Idempotenz

`provider.v2.claim` und `provider.v2.reclaim` sind sensible One-shot-
Operationen.

Eine Antwort mit mindestens einem Claim enthält einen geheimen Token und wird
nicht in `idempotency_results.response_json` gespeichert:

- identischer Body → `idempotency_in_progress`;
- anderer Body oder andere Operation → `idempotency_conflict`;
- kein zweiter Attempt und kein zweiter Token.

Eine erfolgreiche leere Antwort ist tokenfrei:

```json
{
  "ok": true,
  "data": {
    "ok": true,
    "schema_version": 2,
    "claims": []
  }
}
```

Sie wird dauerhaft gecached und sicher identisch replayt. Reine
Validierungsfehler geben die exakte noch leere Reservierung frei. Abgeschlossene
Antworten können über diesen Pfad niemals gelöscht werden.

## 6. Leaseverlängerung

`provider.v2.renew` verlangt:

```text
target_delivery_id
worker_id
claim_token
```

Optional:

```text
lease_seconds
max_claim_lifetime_seconds
```

Worker, Token, Target und Ablaufzeit müssen zum aktiven Claim passen. Die harte
maximale Lebensdauer eines Attempts kann nicht durch wiederholte Renew-Aufrufe
überschritten werden.

## 7. Recipientregistrierung

TeeBotus löst private Admin-/Accountrouten selbst auf und registriert unter dem
aktiven Claim ausschließlich opaque Referenzen, beispielsweise:

```text
status_admin_primary
status_admin_secondary
```

Bot-Token, Chat-ID, private Accountobjekte oder rohe Message-IDs werden nicht an
den History-Dispatcher übertragen. Der native Worker darf nur bereits im
Route-Plan gebundene Recipientprofile verwenden.

## 8. Recipientresultate

`provider.v2.record_recipients` meldet pro Empfänger:

```text
accepted
delivered
acknowledged
failed
skipped
possible_duplicate
```

Optionale Felder:

```text
message_ref_key
reason_code
possible_duplicate
```

Die zentrale Merge-Semantik verhindert Downgrades erfolgreicher Zustände.
Erfolgreiche Empfänger werden in späteren Claims unter
`successful_recipient_refs` ausgewiesen und nicht erneut angeboten.
`possible_duplicate` ist nicht normal retrybar und bleibt bis zur
Reconciliation blockiert.

## 9. Targetcompletion

`provider.v2.complete` kann den Zielzustand aus Recipientresultaten ableiten oder
einen erlaubten Zustand explizit melden. Unterstützte Retryparameter:

```text
retry_after_seconds
max_attempts
base_backoff_seconds
max_backoff_seconds
jitter_ratio
```

Ein längeres `retry_after_seconds` hat Vorrang vor dem deterministischen
Backoff. Nach `max_attempts` folgt Quarantäne; erfolgreiche Recipientzustände
bleiben erhalten.

## 10. Heartbeat

`provider.v2.heartbeat` speichert nur begrenzte Betriebsmetadaten:

```text
worker_id
target_id
provider_id
capability_version
state
details
```

`details` besitzt höchstens 16 formatgeprüfte Felder. Strings werden redigiert.
Tokens, Chat-IDs, Payloads und private Pfade sind unzulässig.

## 11. Sicherheitsgarantien

- Same-User-`SO_PEERCRED` bleibt Transportgrenze;
- jede Provideroperation verlangt eine Request-ID;
- Claimtokens stehen nie in Status, Snapshot oder Idempotenz-Responsecache;
- rohe Telegramtokens und Chat-IDs sind keine Contractfelder;
- unbekannte Felder werden fail-closed abgewiesen;
- Provider und Capability werden exakt geprüft;
- `legacy_unknown` bleibt unclaimbar;
- keine automatische Providerumschaltung;
- keine erneute Zustellung erfolgreicher oder `possible_duplicate`-Empfänger;
- aktive Claims werden durch Reclaim nicht gestohlen;
- terminale Targets werden nicht wieder geöffnet;
- keine zweite Mutation bei Request-Replay.

## 12. Gemeinsamer Fixture-Korpus

Der versionierte Fixture liegt unter:

```text
tests/fixtures/provider-v2/contract.json
```

Er enthält ausschließlich künstliche opaque Referenzen. Der TeeBotus-Adapter
konsumiert denselben Operationssatz, dieselbe Capability und dieselben
Recipient-/Outcome-Beispiele. Mit `provider.v2.reclaim` wird der Fixture-Korpus
im TeeBotus-Cutover erweitert, bevor der lange Claimablauf-/Callback-Rebind-Test
als abgeschlossen gilt.
