# Status-Snapshot v1

**Status:** eingefrorene Baseline  
**Schemavert:** `schema_version = 1`

## Zweck

Der Snapshot ist die redigierte, begrenzte Desktopansicht des Backends. Er ist keine Queuequelle und enthält keine entschlüsselten History-Payloads.

## Datei- und Schreibvertrag

- Standardname: `status-v1.json` im privaten Runtimeverzeichnis;
- reguläre owner-only Datei, Modus `0600`;
- UTF-8-JSON;
- hartes Gesamtbudget: höchstens **65.536 Byte**;
- Writer schreibt zunächst eine temporäre Datei im Zielverzeichnis;
- temporäre Datei wird geflusht und per `fsync` gesichert;
- Veröffentlichung erfolgt atomar mit `os.replace`.

Ein Directory-`fsync` und weitergehende Symlinkprüfungen sind für den v2-Writer vorgesehen und werden hier nicht fälschlich als bereits umgesetzt dokumentiert.

## Kernfelder

```text
schema_version
service
version
ok
generated_at
started_at
last_operation
last_error
last_collection
last_delivery
queue_preview
collector
dispatch
capabilities
```

Zusätzlich enthält der Snapshot die vom Store gelieferten aggregierten Queuefelder, beispielsweise `total`, `queued`, `failed` und `oldest_queued_at`.

## Queuevorschau

Die Vorschau ist auf 20 Einträge im Writer und 10 sichtbare Einträge im aktuellen Applet begrenzt. Pro Eintrag werden nur folgende Felder veröffentlicht:

```text
id
status
kind
created_at
last_error (maximal 160 Zeichen)
```

Keine Payload, kein Empfängertoken und kein Secret-Service-Wert darf in die Vorschau gelangen.

## Appletvalidierung

Das aktuelle Applet:

- prüft die Dateigröße vor dem Laden;
- verwirft Inhalte oberhalb 64 KiB;
- verlangt ein JSON-Objekt mit `schema_version === 1`;
- markiert einen Snapshot nach 120 Sekunden als veraltet;
- verwendet Generation und `Gio.Cancellable`, um verspätete Reads nach Entfernung zu verwerfen.

## Evolutionsregel

Status v2 wird unter einem eigenen Dateinamen eingeführt. Während der definierten Übergangsphase schreibt das Backend v1 und v2 parallel. Das v2-Applet darf v1 nur read-only als Kompatibilitätsmodus verwenden.
