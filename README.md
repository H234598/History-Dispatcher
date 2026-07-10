# History-Dispatcher

Standalone, local-only encrypted history collection and dispatch service.

The control interface is a versioned Unix socket. The service does not expose an
IP listener and stores payloads encrypted with a dedicated Secret Service key.

## Development

    python3 -m venv .venv-py313
    .venv-py313/bin/python -m pip install -e '.[dev]'
    .venv-py313/bin/python -m history_dispatcher config check
    .venv-py313/bin/python -m history_dispatcher status --json

The production key is resolved with:

    secret-tool lookup application history-dispatcher purpose payload-key

The value must decode to exactly 32 bytes. Tests inject a static key and never
touch the production Secret Service.

## Runtime layout

The default configuration is `~/.config/history-dispatcher/config.toml`.
State is kept below `~/.local/state/history-dispatcher`; the owner-only control
socket and the bounded `status-v1.json` snapshot are below
`$XDG_RUNTIME_DIR/history-dispatcher`. The Codex collector scans only
`~/.codex/sessions` and `~/.codex-agents/*/sessions` by default.
`config.example.toml` contains a complete, strict configuration template for
the service and Cinnamon applet; replace its `USERNAME` and runtime UID
placeholders before installing it.

Render hardened user units with:

    python -m history_dispatcher.systemd --print

The service is deliberately fail-closed when the Secret Service key is absent
or malformed. `status` can still report queue health without decrypting a
payload; all payload operations require the real key.

## TeeBotus integration

TeeBotus keeps its Messenger adapters and can use the optional bridge by
setting `TEEBOTUS_HISTORY_DISPATCHER_MODE=bridge` and, when needed,
`HISTORY_DISPATCHER_SOCKET`. `shadow` mirrors newly created legacy summaries
without changing the legacy reader. Delivery callbacks that cannot reach the
Dispatcher are atomically spooled under TeeBotus state and retried later.

Install the standalone applet transactionally with:

    python scripts/install_cinnamon_applet.py --dry-run

The applet reads only the bounded snapshot and runs allowlisted actions through
the fixed `applet-action` CLI path. Destructive deletion requires a backend
preview token and the exact `LOESCHEN <Anzahl>` confirmation.

## Migration

For a legacy JSONL export, use `history-dispatcher migrate-legacy --dry-run`
first. TeeBotus also exposes `migrate_codex_history_to_dispatcher`, which
streams decrypted AccountStore records directly over the Unix socket and never
creates a plaintext staging file.

## Isolated Cinnamon verification

`scripts/run_isolated_cinnamon_applet.py` runs one or both applets inside an
unshared Bubblewrap environment and a rootless Xephyr display. It uses a
throw-away HOME, runtime directory, D-Bus, and dconf database; it must not be
run against the production Cinnamon display.
