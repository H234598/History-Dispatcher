# ADR-013: Statusvertrag und Rückwärtskompatibilität

**Datum:** 28. Juli 2026  
**Status: Akzeptiert**

## Kontext

Status v2 benötigt Ziel-, Typ-, Heartbeat-, Alert- und Configrevisiondaten. TeeBotus und das bestehende Applet lesen jedoch `status-v1.json`.

## Entscheidung

Status v2 erhält den eigenen Dateinamen `status-v2.json`. Das neue Applet bevorzugt v2 und verwendet v1 nur read-only mit deutlich sichtbarem Kompatibilitätsmodus.

Der Kompatibilitätsgrenzpunkt ist die frühestmögliche Produktversion `0.3.0`: Alle `0.2.x`-Releases behalten den v1/v2-Dualwriter und akzeptieren den dokumentierten Legacy-TeeBotus-Übergangspfad. Die Grenze darf erst aktiviert werden, wenn eine veröffentlichte TeeBotus-Version den v2-Workervertrag und den read-only Desktopspiegel unterstützt und 20 aufeinanderfolgende Dual-Applet-Kompatibilitätsläufe ohne Vertrags- oder JavaScriptfehler grün waren.

## Konsequenzen

- Zielgetrennte Mutationen sind im v1-Fallback deaktiviert.
- v1 wird in keinem `0.2.x`-Release abgeschaltet.
- Die frühestmögliche Entfernung des v1-Writers ist `0.3.0` und bleibt an beide messbaren Exitbedingungen gebunden.
- Ein gemeinsamer Aggregator verhindert Countdrift.
- Werden TeeBotus-v2-Kompatibilität oder 20 grüne Läufe nicht nachgewiesen, bleibt der Dualwriter auch über `0.3.0` hinaus aktiv oder die Produktversion wird nicht als kompatibler Grenzrelease freigegeben.

## Verifikation

Contracttests vergleichen v1-/v2-Kernzähler; Major-Inkompatibilität führt im Applet zu read-only Safe Mode. Das Release-Gate prüft vor Abschaltung des v1-Writers die veröffentlichte kompatible TeeBotus-Version und die 20 aufeinanderfolgenden grünen Dual-Applet-Kompatibilitätsberichte.
