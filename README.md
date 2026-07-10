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

