# Isolierte Cinnamon-Abnahme

Host: Fedora, Cinnamon 6.6.7, X11. Die produktive Sitzung auf `DISPLAY=:0`
wurde nicht aktiviert, nicht reloadet und nicht belastet.

Runner:

```text
scripts/run_isolated_cinnamon_applet.py
Xephyr: /tmp/history-dispatcher-xephyr/usr/bin/Xephyr (rootless RPM-Extraktion)
bwrap: system/user/network namespace, eigenes HOME, eigener D-Bus, llvmpipe
```

Ergebnisse:

| Variante | Dauer | Ergebnis | Geladene UUIDs | JS-Ausnahmen |
| --- | ---: | --- | --- | --- |
| `--applets history-dispatcher` | 12 s | PASS | `history-dispatcher@H234598` | 0 |
| `--applets teebotus` | 12 s | PASS | `teebotus@H234598` | 0 |
| `--applets both` Lauf 1 | 20 s | PASS | beide | 0 |
| `--applets both` Lauf 2 | 20 s | PASS | beide | 0 |
| `--applets both` Lauf 3 | 20 s | PASS | beide | 0 |

Jeder Lauf endete erwartungsgemäß durch die Runner-Zeitbegrenzung mit
Cinnamon-Rückgabecode `-15`; während der Laufzeit blieb der Cinnamon-Prozess
bestehen. Die Logs enthielten keine `JS ERROR`, `TypeError`, `ReferenceError`,
`SyntaxError` oder `UnhandledPromise`-Zeilen.

Zusätzliche Gates:

```text
History-Dispatcher: 16 passed
TeeBotus-Applet: 172 passed
Node --check: beide Applets erfolgreich
```

