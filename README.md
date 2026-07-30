# History-Dispatcher

Standalone, local-only encrypted history collection and dispatch service.

The control interface is a versioned same-user Unix socket. The service exposes
no IP listener and stores History payloads encrypted with a dedicated Secret
Service key.

## Architecture and implementation tracking

- [`docs/architecture.md`](docs/architecture.md) — components and failure domains;
- [`docs/contracts/`](docs/contracts/) — control, status and security contracts;
- [`docs/adr/`](docs/adr/) — accepted architecture decisions;
- [`docs/history-classification.md`](docs/history-classification.md) — Codex
  classifier, redaction and fixture contract;
- [`docs/migration-v2.md`](docs/migration-v2.md) — explicit DB-v2 migration;
- [`docs/delivery-store-v3.md`](docs/delivery-store-v3.md) — provider-bound
  routes, targets, recipients, claims, leases and attempts;
- [`docs/provider-api-v2.md`](docs/provider-api-v2.md) — external worker API,
  one-shot tokens, targeted callback reclaim and shared provider fixture;
- [`docs/status-v2-health.md`](docs/status-v2-health.md) — redacted Health API;
- [`docs/contracts/status-snapshot-v2.md`](docs/contracts/status-snapshot-v2.md)
  — owner-only additive status snapshot;
- [`docs/implementation-plan-addendum-telegram.md`](docs/implementation-plan-addendum-telegram.md)
  — standalone Telegram plan extension;
- [`docs/implementation-progress.md`](docs/implementation-progress.md) — current
  sequential implementation status;
- [`docs/reuse-ledger.md`](docs/reuse-ledger.md) — source and parity tracking.

## Development

```bash
python3 -m venv .venv-py313
.venv-py313/bin/python -m pip install -e '.[dev]'
.venv-py313/bin/python -m history_dispatcher config check
.venv-py313/bin/python -m history_dispatcher status --json
```

The production payload key is resolved with:

```bash
secret-tool lookup application history-dispatcher purpose payload-key
```

It must decode to exactly 32 bytes. Tests inject a static key and never touch
the production Secret Service.

## Runtime layout

- config: `~/.config/history-dispatcher/config.toml`;
- state: `~/.local/state/history-dispatcher`;
- control socket: `$XDG_RUNTIME_DIR/history-dispatcher/control.sock`;
- compatibility snapshot: `status-v1.json`;
- additive redacted snapshot: `status-v2.json`.

The read-only socket operation `status.get_redacted` returns the same v2
envelope as the new snapshot. Existing v1 status operations remain unchanged.

## Codex classification fixtures

Never commit a raw Codex rollout. Sanitize local examples first:

```bash
python scripts/sanitize_codex_fixture.py \
  /private/path/rollout.jsonl \
  /tmp/sanitized-rollout.jsonl \
  --manifest /tmp/sanitized-manifest.json \
  --upstream-commit 8e271dc02b23d42827875019924be0f5005642b0 \
  --dry-run
```

The classifier remains isolated from the production collector until the later
cursor/cutover slice.

## Telegram providers

The route contract supports exactly:

```text
teebotus
history_dispatcher
```

Provider selection is immutable per Route-Plan. There is no automatic fallback.
The store supports target-specific claims, leases, recipient results, attempts,
backoff and reconciliation.

The additive provider-v2 Same-User-Socket operations are:

```text
provider.v2.claim
provider.v2.reclaim
provider.v2.renew
provider.v2.register_recipients
provider.v2.record_recipients
provider.v2.complete
provider.v2.heartbeat
```

All require a Request-ID. Token-bearing normal and reconciliation claims are
one-shot and never cached; token-free empty polls are safely replayable.

`provider.v2.reclaim` targets exactly one expired delivery and returns
`reconciliation_only=true`. It exists so an encrypted Recipient- or
Completioncallback can be rebound to a new token after a long outage. A worker
must never use such a claim for a new Telegram send. See
[`docs/provider-api-v2.md`](docs/provider-api-v2.md).

A native Bot-API worker and write-only Secret-Service credential operations are
later slices. The current status API therefore exposes no token and reports the
native credential as not configured.

## Migrations

Database v2 defaults to a write-free dry run:

```bash
python scripts/migrate_database_v2.py preflight
python scripts/migrate_database_v2.py migrate
```

A real write requires `--apply --confirm MIGRATE-V2`.

Provider-bound delivery schema v3 also defaults to dry run:

```bash
python scripts/migrate_delivery_v3.py preflight
python scripts/migrate_delivery_v3.py migrate
python scripts/migrate_delivery_v3.py verify
```

A real write requires `--apply --confirm MIGRATE-V3`. Neither migration starts a
network worker or reactivates Legacy deliveries.

## Cinnamon applet

Install the current applet transactionally with:

```bash
python scripts/install_cinnamon_applet.py --dry-run
```

The Applet remains a bounded snapshot/socket client. It does not read
credentials, open Telegram connections or participate in delivery claims.
