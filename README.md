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
- [`docs/config-v2-api.md`](docs/config-v2-api.md) — productive Telegram routing
  config, revisioned preview/apply, audit and rollback;
- [`docs/native-telegram-credentials.md`](docs/native-telegram-credentials.md)
  — explicit schema-v4 migration and write-only Secret-Service boundary;
- [`docs/native-telegram-worker.md`](docs/native-telegram-worker.md)
  — fixed-host Bot API client, formatter, provider-v2 worker and hardened unit;
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

## Productive Config v2

Telegram routing is persisted in the real TOML config:

```toml
[routing.telegram]
provider = "teebotus"
credential_ref = ""
recipient_refs = []
```

Allowed providers are exactly:

```text
teebotus
history_dispatcher
```

`credential_ref` and `recipient_refs` are opaque profile names only. Bot tokens
and raw Telegram chat IDs are rejected by the config loader and patch API.

The additive Same-User-Socket flow is:

```text
config.get_redacted
config.validate_patch
config.preview_apply
config.apply
```

A productive apply requires the current revision, a 60-second one-use preview
token, the canonical fingerprint, confirmation
`APPLY <first-12-fingerprint-characters>` and a Request-ID.

The apply uses compare-and-swap, the private atomic TOML writer, post-write
reload verification, `config_audit`, and full rollback if write, reload or audit
fails. Its effect is always `new_route_plans_only`: existing route plans are not
mutated or replanned.

Legacy `config.get`, path-based `config.validate`, and flat safe-values
`config.apply` remain compatible. See
[`docs/config-v2-api.md`](docs/config-v2-api.md).

## Native Telegram credentials

Bot tokens and recipient chat IDs are stored only in Secret Service under the
opaque profiles selected by Config v2.

Bot-token attributes:

```text
application=history-dispatcher
purpose=telegram-bot-token
profile=<credential_ref>
```

Recipient-chat attributes:

```text
application=history-dispatcher
purpose=telegram-chat-id
profile=<recipient_ref>
```

`secret-tool store` receives the value through standard input. Secret values do
not appear in argv, environment variables, TOML, SQLite, status, snapshots,
audit rows or API responses. There is no plaintext-file, environment or random
fallback.

Additive Same-User-Socket operations:

```text
credential.get_status
credential.preview_apply
credential.apply
```

`credential.preview_apply` validates set/replace/delete, kind and Config-v2
profile authorization. It holds the write-only value only in a bounded
60-second in-memory preview. The response contains a fingerprint, confirmation
`CREDENTIAL <ACTION> <first-12-fingerprint-characters>` and a one-use token, but
never the secret.

`credential.apply` is durably request-idempotent and returns only action, kind,
opaque profile, configured state and timestamp. Secret-Service mutation is
verified before secret-free metadata and audit are committed. A DB/audit failure
restores the previous secret; compensation failure is terminal as
`credential_rollback_failed`.

Public status uses metadata only and exposes only:

```json
{"configured": true, "last_changed": "timestamp"}
```

See [`docs/native-telegram-credentials.md`](docs/native-telegram-credentials.md).

The credential API itself performs no Telegram network request. The separately
reviewed native worker consumes its internal lookup methods immediately before each
send and never exposes a public credential-read operation.

## Native Telegram worker

The native worker is fixed to `https://api.telegram.org:443`, uses the standard
verified TLS context, and internally allowlists only `getMe`, `sendMessage`, and
`sendDocument`. There is no configurable URL, proxy, redirect, HTTP fallback,
local Bot API server, rich formatting, inbound update path or TeeBotus fallback.

Short payloads are sent as one plain-text message. Longer payloads use exactly
one bounded UTF-8 text document rather than a multi-request segment sequence.
This preserves recipient-level atomicity after crashes.

Run interactively:

```bash
python -m history_dispatcher \
  --config ~/.config/history-dispatcher/config.toml \
  telegram-worker
```

The dedicated systemd unit is rendered but not enabled by default. Explicit
activation requires:

```bash
python -m history_dispatcher.systemd \
  --python /path/to/.venv-py313/bin/python \
  --config ~/.config/history-dispatcher/config.toml \
  --enable \
  --enable-telegram-worker
```

Only that unit receives `AF_INET/AF_INET6`; the main service and collector remain
restricted to local Unix/file sockets. See
[`docs/native-telegram-worker.md`](docs/native-telegram-worker.md).

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

The TeeBotus provider and the native History-Dispatcher worker both use this
contract. The native worker resolves opaque Secret-Service profiles per recipient,
renews claims before network access, records recipient outcomes immediately, maps
Telegram `retry_after` into the shared backoff contract, and preserves uncertain
post-connect outcomes as monotone `possible_duplicate`. Live canaries remain a
separate explicit gate.

## Migrations

### Database v2

```bash
python scripts/migrate_database_v2.py preflight
python scripts/migrate_database_v2.py migrate
```

A real write requires `--apply --confirm MIGRATE-V2`.

### Provider-bound delivery schema v3

```bash
python scripts/migrate_delivery_v3.py preflight
python scripts/migrate_delivery_v3.py migrate
python scripts/migrate_delivery_v3.py verify
```

A real write requires `--apply --confirm MIGRATE-V3`.

### Credential metadata schema v4

```bash
python scripts/migrate_credentials_v4.py preflight
python scripts/migrate_credentials_v4.py migrate
python scripts/migrate_credentials_v4.py verify
```

A real write requires:

```bash
python scripts/migrate_credentials_v4.py migrate \
  --apply \
  --confirm MIGRATE-CREDENTIALS-V4
```

All migrations default to write-free dry runs. None starts a network worker or
reactivates Legacy deliveries.

## Cinnamon applet

Install the current applet transactionally with:

```bash
python scripts/install_cinnamon_applet.py --dry-run
```

The Applet remains a bounded snapshot/socket client. It does not read
credentials, open Telegram connections or participate in delivery claims.

The later provider selector consumes Config-v2 and Credential preview/apply APIs;
it must not store provider decisions or credentials in dconf.
