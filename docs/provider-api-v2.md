# Provider-v2-Worker-API

**Stand:** 30. Juli 2026  
**Implementierungsschnitt:** `PR-HD-08-teebotus-provider-v2`  
**Schema:** `2`  
**Transport:** owner-only Same-User-Unix-Socket, `protocol_version = 1`

## 1. Zweck

Die Provider-v2-API verbindet externe Transportworker mit dem zentralen,
providergebundenen Delivery-Store des History-Dispatchers. Der erste echte
Client ist TeeBotus; der spätere native Telegramworker verwendet denselben
Storevertrag, aber eine andere Provider-ID und Capability.

Der History-Dispatcher bleibt Eigentümer von:

- Event und verschlüsselter Payload;
- Route-Plan und unveränderlicher Providerbindung;
- Target- und Recipient-Delivery;
- Claim, Lease und Attempt;
- Idempotenz, Retry, Backoff und Aggregation;
- Reconciliation- und `possible_duplicate`-Zuständen.

Der Worker besitzt nur den konkreten Transport und meldet Ergebnisse zurück.
Es gibt keinen automatischen Cross-Provider-Fallback.

## 2. Operationen

```text
provider.v2.claim
provider.v2.renew
provider.v2.register_recipients
provider.v2.record_recipients
provider.v2.complete
provider.v2.heartbeat
```

Alle Operationen sind mutierend und verlangen eine nicht leere `request_id`.
Der Body wird gegen eine feste Feldallowlist, endliches JSON und maximal 256 KiB
geprüft.

## 3. Claim

### 3.1 Request

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

Optionale, begrenzte Felder:

```text
max_attempts
base_backoff_seconds
max_backoff_seconds
jitter_ratio
```

Provider- und Capability-Missmatches liefern keine fremde Delivery und lösen
keinen Fallback aus.

### 3.2 Antwort mit Claim

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

`claim_token` wird genau einmal an den erfolgreichen Claimer zurückgegeben. In
der Datenbank wird nur SHA-256 des Tokens gespeichert.

### 3.3 One-shot-Idempotenz

Eine Claimantwort mit mindestens einem Claim enthält einen geheimen Token und
wird deshalb **nicht** in `idempotency_results.response_json` gespeichert.

Für dieselbe Request-ID gilt danach:

- identischer Body → `idempotency_in_progress`;
- anderer Body oder andere Operation → `idempotency_conflict`;
- kein zweiter Attempt und kein zweiter Claimtoken.

Eine erfolgreiche leere Pollantwort ist tokenfrei:

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

Sie wird normal im Idempotenzcache gespeichert und kann sicher identisch
wiederholt werden.

Reine Validierungsfehler finden vor einer Deliverymutation statt. Ihre noch
leere Reservierung wird exakt freigegeben, sodass ein korrigierter Request mit
derselben Request-ID erneut versucht werden kann. Eine abgeschlossene Antwort
kann über diesen Pfad niemals gelöscht werden.

## 4. Leaseverlängerung

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
maximale Lebensdauer des Attempts kann nicht durch wiederholte Renew-Aufrufe
überschritten werden.

## 5. Recipientregistrierung

### TeeBotus

TeeBotus löst seine privaten Admin-/Accountrouten selbst auf und registriert
unter dem aktiven Claim ausschließlich opaque Referenzen, beispielsweise:

```text
status_admin_primary
status_admin_secondary
```

Bot-Token, Chat-ID, private Accountobjekte oder Message-IDs werden nicht an den
History-Dispatcher übertragen.

### Nativer Worker

Der native Worker darf nur Recipientprofile verwenden, die bereits im
unveränderlichen Route-Plan gebunden wurden. Ungeplante Recipientrefs werden
abgewiesen.

## 6. Recipientresultate

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

Die zentrale Merge-Semantik verhindert Downgrades von `accepted`, `delivered`
und `acknowledged`. Bereits erfolgreiche Empfänger werden in späteren Claims
unter `successful_recipient_refs` ausgewiesen und nicht erneut angeboten.

Ein unklarer Absturz nach externem Accept wird `possible_duplicate`. Dieser
Empfänger ist kein normal retrybarer Recipient und bleibt bis zur
Reconciliation blockiert.

## 7. Targetcompletion

`provider.v2.complete` kann den Zielzustand aus Recipientresultaten ableiten oder
explizit einen erlaubten terminalen/retrybaren Zustand melden.

Unterstützte Retryparameter:

```text
retry_after_seconds
max_attempts
base_backoff_seconds
max_backoff_seconds
jitter_ratio
```

Ein explizites `retry_after_seconds` hat Vorrang vor dem deterministischen
exponentiellen Backoff, wenn es länger ist. Nach `max_attempts` folgt
Quarantäne; bereits erfolgreiche Recipientzustände bleiben erhalten.

## 8. Heartbeat

`provider.v2.heartbeat` speichert nur begrenzte Betriebsmetadaten:

```text
worker_id
target_id
provider_id
capability_version
state
details
```

`details` besitzt höchstens 16 formatgeprüfte Felder. Strings werden vor der
Persistenz redigiert. Tokens, Chat-IDs, Payloads und private Pfade sind kein
zulässiger Heartbeatinhalt.

## 9. Sicherheitsgarantien

- Same-User-`SO_PEERCRED` bleibt Transportgrenze;
- jede Provideroperation verlangt eine Request-ID;
- Claimtokens werden nie im Status, Snapshot oder Idempotenz-Responsecache
  gespeichert;
- rohe Telegramtokens und Chat-IDs sind keine Contractfelder;
- unbekannte Felder werden fail-closed abgewiesen;
- Provider und Capability werden exakt geprüft;
- `legacy_unknown` bleibt unclaimbar;
- keine automatische Providerumschaltung;
- keine erneute Zustellung bereits erfolgreicher Empfänger;
- keine zweite Mutation bei Request-Replay.

## 10. Gemeinsamer Fixture-Korpus

Der erste versionierte Contract-Fixture liegt unter:

```text
tests/fixtures/provider-v2/contract.json
```

Er enthält ausschließlich künstliche opaque Referenzen. Der gepaarte
TeeBotus-Adapter muss denselben Operationssatz, dieselbe Capability und dieselben
Recipient-/Outcome-Beispiele konsumieren. Erst wenn beide Repositorys denselben
Korpus bestehen, gilt `TG-F-001` vollständig als erledigt.
