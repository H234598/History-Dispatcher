# ADR-012: Eigentümerschaft der Desktop-Control-Plane

**Datum:** 28. Juli 2026  
**Status: Akzeptiert**

## Kontext

Das dedizierte History-Dispatcher-Applet und das TeeBotus-Applet können v1-Backendwerte unabhängig spiegeln und verändern. Zwei Writer erzeugen Drift und schwer erklärbare Revisionen.

## Entscheidung

Das dedizierte History-Dispatcher-Applet ist die einzige schreibende Desktopoberfläche. TeeBotus zeigt den Dispatcherstatus read-only und verlinkt auf die dedizierten Einstellungen.

Der Kompatibilitätsgrenzpunkt ist die frühestmögliche Produktversion `0.3.0`: Alle `0.2.x`-Releases behalten den v1/v2-Dualwriter und akzeptieren den dokumentierten Legacy-TeeBotus-Übergangspfad. Die Grenze darf erst aktiviert werden, wenn eine veröffentlichte TeeBotus-Version den v2-Workervertrag und den read-only Desktopspiegel unterstützt und 20 aufeinanderfolgende Dual-Applet-Kompatibilitätsläufe ohne Vertrags- oder JavaScriptfehler grün waren.

## Konsequenzen

- Der Server und die Config-API dürfen Legacy-TeeBotus-Writepfade frühestens an exakt diesem `0.3.0`-Grenzpunkt ablehnen; vorher werden sie nur als Übergangspfad dokumentiert und gemessen.
- Der Telegramworker in TeeBotus bleibt unabhängig von der UI-Eigentümerschaft bestehen.
- Dual-Applet-Tests müssen konkurrierende Writes ausschließen.
- Wird eine der beiden messbaren Vorbedingungen nicht erfüllt, verschiebt sich die Ablehnung auf ein späteres Release; sie wird nicht allein durch Zeitablauf aktiviert.

## Verifikation

Der gemeinsame Cinnamon-Test prüft, dass beide Applets laden, aber nur das dedizierte Applet Configapply anbietet. Release- und Contracttests prüfen zusätzlich die TeeBotus-Mindestversion und den Nachweis der 20 aufeinanderfolgenden grünen Dual-Applet-Läufe vor einer `0.3.0`-Aktivierung.
