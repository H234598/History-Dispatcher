# Status-Snapshot v2

**Status:** additiver Vertrag  
**Schema:** `status.schema_version = 2`  
**Envelope:** `version = 2`

## Pfad und Rechte

```text
$XDG_RUNTIME_DIR/history-dispatcher/status-v2.json
```

- Runtimeverzeichnis: Modus `0700`;
- Snapshot: Modus `0600`;
- UTF-8 JSON, kompakt und mit sortierten Schlüsseln;
- maximales Dateilimit: 65.536 Byte;
- atomarer Replace aus einer privaten temporären Datei;
- Datei- und Verzeichnisinhalt werden vor Veröffentlichung synchronisiert.

`status-v1.json` bleibt parallel bestehen und behält Schema v1.

## Envelope

```json
{
  "version": 2,
  "status": {
    "schema_version": 2,
    "generated_at": "2026-07-30T17:00:00Z",
    "telegram": {
      "provider": "teebotus",
      "credential": {
        "configured": false,
        "last_changed": null
      }
    },
    "workers": [],
    "queue": {},
    "deliveries": {}
  }
}
```

## Erlaubte Inhalte

- ausgewählter Telegram-Provider;
- boolescher Credentialzustand und optionaler Änderungszeitpunkt;
- höchstens 64 Workerzeilen mit Worker-ID, Target, Provider, Capability,
  redigiertem Zustand und Heartbeat;
- aggregierte Queue- und Target-Delivery-Zähler.

## Verbotene Inhalte

- History- oder Eventpayloads;
- verschlüsselte Payloadblobs;
- Bot-Tokens, Passwörter oder sonstige Secrets;
- rohe Chat-IDs;
- Recipient- oder Message-Referenzen;
- private Pfade, E-Mail-Adressen oder Credential-URLs.

Die Ausgabe wird vor dem Schreiben rekursiv geprüft. Verbotene Feldnamen,
bekannte sensible Stringmuster, nicht endliche JSON-Werte, mehr als zwölf
Verschachtelungsebenen, mehr als 4096 Werte oder ein Überschreiten des Limits
brechen fail-closed ab. Eine bereits bestehende Snapshotdatei wird bei einem
Validierungsfehler nicht ersetzt.

## Runtime-Datenquelle

- Queuezähler stammen aus dem v1-Storestatus;
- Worker und Deliveryzähler werden read-only aus den additiven Tabellen gelesen;
- fehlen die Tabellen vor einer Migration, bleiben diese optionalen Abschnitte
  leer;
- malformed Heartbeat-Details werden auf `unknown` reduziert;
- strukturell ungültige Workerzeilen werden ausgelassen;
- die Statusabfrage erzeugt oder verändert keine Datenbankdatei.
