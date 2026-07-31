---
title: Native Telegram Credential Boundary
tags:
  - history-dispatcher
  - telegram
  - credentials
  - secret-service
  - security
type: runbook
status: implemented
date: 2026-07-31
created: 2026-07-31
aliases:
  - Telegram Secret-Service Runbook
  - Native Telegram Credentials
---

# Native Telegram Credential Boundary

## 1. Scope

This boundary manages the secret values required by the later native
History-Dispatcher Telegram worker without exposing them through Config, SQLite,
status, snapshots, audit, logs or API responses.

Supported secret kinds:

```text
bot_token
chat_id
```

This slice does **not** contact Telegram, call `getMe`, send a test message or
start a worker. Network validation belongs to the later native Bot API client so
transport and credential failure semantics are tested together.

## 2. Secret Service attributes

Bot token:

```text
application=history-dispatcher
purpose=telegram-bot-token
profile=<routing.telegram.credential_ref>
```

Recipient chat ID:

```text
application=history-dispatcher
purpose=telegram-chat-id
profile=<one routing.telegram.recipient_refs entry>
```

The secret value is supplied to `secret-tool store` through standard input. It
never appears in argv, environment variables, a temporary file or an exception
message. There is no environment, plaintext-file or random-value fallback.

Internal lookup methods exist for the future native worker, but no public socket
operation returns a lookup result.

## 3. Credential metadata schema v4

Schema v4 adds only secret-free metadata:

```text
telegram_secret_metadata
credential_audit
```

`telegram_secret_metadata` contains:

- `secret_kind`;
- HMAC-pseudonymized `profile_key`;
- `configured`;
- `last_changed`;
- `last_operation`.

`credential_audit` contains:

- audit ID;
- HMAC-pseudonymized actor and profile keys;
- operation and secret kind;
- result and bounded reason code;
- UTC timestamp.

Neither table contains a raw profile, token, chat ID, secret value or
value-derived plaintext fingerprint.

## 4. Explicit migration v3 → v4

The service never migrates during a settings request.

### 4.1 Preflight

```bash
python scripts/migrate_credentials_v4.py preflight
```

Requires:

- complete schema-v3 verification;
- owner-controlled regular database and backup paths without symlinks;
- available payload key;
- clean SQLite and foreign-key checks;
- no active v1 or target-specific claims.

### 4.2 Write-free dry run

```bash
python scripts/migrate_credentials_v4.py migrate
```

Without `--apply`, no backup directory, table or schema version is written.

### 4.3 Apply

```bash
python scripts/migrate_credentials_v4.py migrate \
  --apply \
  --confirm MIGRATE-CREDENTIALS-V4
```

The real migration:

1. runs the complete preflight;
2. creates a verified owner-only SQLite backup;
3. starts `BEGIN IMMEDIATE`;
4. rechecks active claims;
5. creates the two additive tables and indices;
6. runs integrity verification;
7. records migration version 4 and its journal entry;
8. commits and independently verifies the result.

Backup directory mode is `0700`; backup file mode is `0600`.

### 4.4 Verify

```bash
python scripts/migrate_credentials_v4.py verify
```

## 5. Same-User socket API

Additive operations:

```text
credential.get_status
credential.preview_apply
credential.apply
```

### 5.1 Status

Request:

```json
{
  "protocol_version": 1,
  "request_id": "",
  "operation": "credential.get_status",
  "body": {}
}
```

Response shape:

```json
{
  "schema_version": 1,
  "bot": {
    "profile_ref": "telegram_primary",
    "configured": false,
    "last_changed": null
  },
  "recipients": [
    {
      "profile_ref": "status_admin_primary",
      "configured": false,
      "last_changed": null
    }
  ]
}
```

Only profiles currently authorized by Config v2 are listed. This method reads
metadata only and never calls Secret Service lookup.

### 5.2 Preview

`credential.preview_apply` requires a Request-ID.

Set/replace example:

```json
{
  "action": "set",
  "secret_kind": "bot_token",
  "profile_ref": "telegram_primary",
  "secret_value": "<write-only value>"
}
```

Delete example:

```json
{
  "action": "delete",
  "secret_kind": "chat_id",
  "profile_ref": "status_admin_primary"
}
```

The response contains no secret:

```json
{
  "schema_version": 1,
  "action": "set",
  "secret_kind": "bot_token",
  "profile_ref": "telegram_primary",
  "fingerprint": "sha256",
  "confirmation": "CREDENTIAL SET 0123456789ab",
  "preview_token": "one-use-token",
  "expires_in_seconds": 60
}
```

The secret exists only in the bounded in-memory preview entry. The fingerprint
contains a key-derived opaque value identity; that identity is not returned
separately or persisted.

The preview token:

- expires after 60 seconds;
- is consumed before mutation;
- is internally held only as SHA-256;
- is never persisted in an idempotency response;
- makes identical Request-ID replay return `idempotency_in_progress`;
- is released only after a pure validation failure before a preview exists.

### 5.3 Apply

`credential.apply` requires a Request-ID and exactly:

```json
{
  "preview_token": "one-use-token",
  "fingerprint": "sha256",
  "confirmation": "CREDENTIAL SET 0123456789ab"
}
```

A successful, secret-free response is durably request-idempotent:

```json
{
  "ok": true,
  "schema_version": 1,
  "action": "set",
  "secret_kind": "bot_token",
  "profile_ref": "telegram_primary",
  "configured": true,
  "last_changed": "timestamp"
}
```

Reusing the consumed preview under another Request-ID is rejected.

## 6. Authorization

Credential operations are available only when Config v2 currently selects:

```text
routing.telegram.provider = history_dispatcher
```

A bot-token operation must target exactly the configured
`credential_ref`. A chat-ID operation must target one current
`recipient_refs` entry. Config is reloaded and reauthorized immediately before
mutation; a profile removed after preview cannot be changed.

## 7. Set, replace and delete semantics

- `set` requires no existing secret;
- `replace` requires an existing secret;
- `delete` requires an existing secret;
- set/replace require and validate `secret_value`;
- delete forbids `secret_value`.

Bot-token validation permits only bounded Telegram token syntax. Chat IDs must
be bounded signed decimal integers. Surrounding whitespace, controls, malformed
values and oversized values are rejected before Secret Service mutation.

## 8. Compensation and rollback

Secret Service and SQLite cannot share a transaction. Apply therefore uses
compensation:

1. read the previous value internally;
2. perform store or clear;
3. verify the new Secret-Service state;
4. commit metadata and audit in one SQLite transaction;
5. on database failure restore the previous secret or clear the newly created
   secret;
6. best-effort record a bounded rollback audit.

If compensation itself fails, apply terminates with:

```text
credential_rollback_failed
```

No further mutation is attempted.

## 9. Public status integration

Status v2 continues to publish only:

```json
{
  "configured": true,
  "last_changed": "timestamp"
}
```

It uses metadata for the currently selected bot credential profile. It does not
publish recipient status, profile keys, secret kinds, audit rows, tokens or chat
IDs. Before schema v4 or without a selected credential profile, status remains
fail-closed as `configured=false`.

## 10. Leak boundary

The following are forbidden outside Secret Service and transient process
memory:

- bot-token value;
- raw Telegram chat ID;
- Secret-Service stderr;
- preview token;
- raw profile in SQLite metadata/audit;
- secret-derived plaintext fingerprint.

Tests assert absence from:

- TOML;
- SQLite database bytes;
- status-v2 snapshot;
- API responses;
- audit rows;
- subprocess argv and environment;
- bounded service errors.

## 11. Next slice

The next slice may implement the native Telegram Bot API worker using the
internal lookup methods. It must add:

- Bot API client and TLS/timeouts;
- formatting and deterministic segmentation;
- `retry_after` handling;
- transport reconciliation and crash-after-accept tests;
- systemd user worker and heartbeat;
- shared provider fault corpus;
- no expansion of the public credential API.
