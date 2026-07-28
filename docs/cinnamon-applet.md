# Cinnamon-Applet: eingefrorene v1-Baseline

Das Applet `history-dispatcher@H234598` ist eine lokale Beobachtungs- und Kontrolloberfläche. Es ist ausdrücklich **nicht** der Collector, Router, Telegramclient oder Vaultworker.

## Datenzugriff

- Normalpfad: asynchrones Lesen von `status-v1.json`.
- Größenlimit: 64 KiB vor beziehungsweise unmittelbar nach dem Lesen.
- akzeptierte Schemaversion: `1`.
- direkte SQLite-, Telegram-, HTTP- oder Vaultzugriffe sind verboten.
- Fehler werden in der UI dargestellt; der letzte Backendzustand bleibt Quelle der Wahrheit.

## Mutierende Aktionen

Das Applet übergibt nur feste Aktionsnamen an:

```text
history-dispatcher --config <validierter Pfad> applet-action --action <allowlisteter Wert>
```

Die v1-Allowlist umfasst `collect`, `retry`, `service-start`, `service-stop` und `service-restart`. Die Löschfunktion nutzt einen separaten Backendvorschau- und Bestätigungspfad.

## Lifecycle

Der Removal-Hook:

1. markiert die Instanz als entfernt;
2. erhöht die Generation;
3. cancelt laufendes Gio-I/O;
4. entfernt den lokalen Timer;
5. zerstört das Menü.

Er führt keine Dienst-, Collector- oder Dispatchaktion aus. Ein entferntes oder kaputtes Applet darf daher ausschließlich seine Darstellung verlieren.

## Noch nicht Bestandteil dieser Baseline

Die folgenden, bereits geplanten Funktionen folgen in späteren Implementierungsschnitten:

- Status v2 und Last-known-good;
- vollständige Ressourcenregistry und bounded subprocess I/O;
- Circuit Breaker und Safe Mode;
- Backend-Routingeditor ohne dconf-Duplikate;
- zielgetrenntes Menü;
- mehrere Iconfamilien und scoped CSS;
- sequenzbasierte, deduplizierte Desktopbenachrichtigungen.

Der aktuelle Fortschritt wird in [`implementation-progress.md`](implementation-progress.md) gepflegt.
