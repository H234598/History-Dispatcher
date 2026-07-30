# Status v2 und redigierte Health-API

**Stand:** 30. Juli 2026  
**Implementierungsschnitt:** `PR-HD-07-status-v2-health`  
**Schema:** `status-v2` / API-Version `2`

## 1. Zweck

Status v2 bildet die sichere, applet- und CLI-fähige Betriebsansicht für:

- den ausgewählten Telegram-Provider;
- den reinen Credentialzustand ohne Credentialwert;
- Worker-Heartbeats;
- Queue- und Delivery-Zähler;
- einen späteren eigenständigen Telegramworker des History-Dispatchers.

Der Status enthält keine History-Payloads, Recipientrouten, Chat-IDs,
Message-Refs, Tokens, Passwörter oder privaten Dateipfade.

## 2. Versionierung und Kompatibilität

Die bestehende Operation `status.get` und `status-v1.json` bleiben während des
Applet-Cutovers unverändert. PR-HD-07 ergänzt additiv:

- Operation `status.get_redacted`;
- Snapshot `status-v2.json`;
- Antwortform `{ "version": 2, "status": { ... } }`.

Damit wird kein bestehender v1-Client still auf ein neues Schema umgestellt.

## 3. Telegramstatus

Der Provider besitzt ausschließlich die Werte:

```text
teebotus
history_dispatcher
```

Der Credentialstatus besitzt nur:

```json
{
  "configured": false,
  "last_changed": null
}
```

Der spätere native Credentialprovider darf ausschließlich diese Metadaten
liefern. Der Tokenwert und rohe Chat-IDs sind keine Statusfelder.

## 4. Workerstatus

Jeder Workerstatus ist begrenzt auf:

```text
worker_id
target
provider
capability
state
heartbeat
```

Es werden höchstens 64 Workerzeilen ausgegeben. Freitextzustände werden vor der
Ausgabe durch die zentrale Redaction geführt.

## 5. Leak- und Größenprüfung

Die gesamte Ausgabe wird rekursiv geprüft:

- verbotene Feldnamen wie `token`, `secret`, `chat_id`, `recipient_id`,
  `recipient_ref`, `message_ref` und `payload`;
- bekannte Token-, Credential-, E-Mail- und Privatpfadmuster in Stringwerten;
- maximal zwölf Verschachtelungsebenen;
- maximal 4096 Werte;
- ausschließlich endliche JSON-Werte;
- maximal 64 KiB UTF-8.

Ein Verstoß erzeugt keine teilweise Statusantwort, sondern schlägt
fail-closed fehl.

## 6. Nächster Integrationsschritt

Der nächste TDD-Zyklus bindet die neue Antwort additiv an den bestehenden
Unix-Socket und schreibt `status-v2.json` atomar mit Modus `0600`, während
`status-v1.json` unverändert bestehen bleibt.
