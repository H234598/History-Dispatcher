---
title: Native Telegram Credential Boundary Design
tags:
  - history-dispatcher
  - telegram
  - credentials
  - secret-service
  - security
type: design-spec
status: approved
created: 2026-07-31
date: 2026-07-31
aliases:
  - Native Telegram Credentials
  - Secret-Service Credential Boundary
---

# Native Telegram Credential Boundary Design

## 1. Status and approval basis

This design implements the already accepted next slice in
`docs/implementation-progress.md` and
`docs/implementation-plan-addendum-telegram.md`. The repository owner has
repeatedly instructed the plan to continue step by step without inserting a new
approval pause between already specified slices.

The slice ends before any Telegram Bot API network request or long-running
native worker.

## 2. Goals

The History-Dispatcher must be able to manage the two secret classes required
by a later native Telegram worker:

1. a bot token referenced by `routing.telegram.credential_ref`;
2. a raw Telegram chat ID referenced by each opaque
   `routing.telegram.recipient_refs` entry.

The public API is write-only for secret values. It may return only opaque
profile names, configured state, last-change timestamps, operation results and
bounded reason codes.

## 3. Non-goals

This slice does not:

- call Telegram;
- verify a token with `getMe`;
- send a test message;
- start a systemd worker;
- expose a token or chat ID through TOML, status, snapshot, audit or logs;
- activate the Cinnamon provider selector;
- change existing route plans.

Network validation follows with the native Bot API client so transport and
credential failure semantics are tested together.

## 4. Chosen architecture

### 4.1 Secret Service is the only secret-value store

Bot-token attributes:

```text
application=history-dispatcher
purpose=telegram-bot-token
profile=<opaque credential_ref>
```

Recipient-chat attributes:

```text
application=history-dispatcher
purpose=telegram-chat-id
profile=<opaque recipient_ref>
```

`secret-tool store` receives the secret through standard input. Secret values
never appear in argv, environment variables, exception messages or return
objects. There is no plaintext file, TOML, random-key or environment fallback.

### 4.2 Additive schema v4 stores metadata, not secrets

Schema v4 adds:

```text
telegram_secret_metadata
credential_audit
```

`telegram_secret_metadata` contains:

- `secret_kind = bot_token | chat_id`;
- HMAC-pseudonymized `profile_key` as the primary identity;
- `configured`;
- `last_changed`;
- `last_operation`.

It contains no raw profile, token, chat ID or value-derived fingerprint.

`credential_audit` contains:

- audit ID;
- HMAC-pseudonymized actor and profile keys;
- operation;
- secret kind;
- result and bounded reason code;
- UTC timestamp.

### 4.3 Explicit migration only

The credential API requires a verified schema-v4 database. It never creates or
migrates tables during a settings request. A separate dry-run-by-default
operator migration creates a private verified backup, runs one additive
transaction and verifies the result.

## 5. Secret provider boundary

A focused `NativeTelegramSecretStore` exposes internal methods:

```python
lookup_bot_token(profile_ref) -> str
lookup_chat_id(profile_ref) -> str
store_bot_token(profile_ref, token) -> None
store_chat_id(profile_ref, chat_id) -> None
clear_bot_token(profile_ref) -> bool
clear_chat_id(profile_ref) -> bool
```

Only the later native worker may use lookup methods. Socket handlers and public
status builders receive no lookup result.

Validation:

- bot token: bounded Telegram token syntax, no surrounding whitespace or
  controls;
- chat ID: signed decimal integer syntax with a strict length bound;
- profile: existing opaque Config-v2 profile normalization;
- subprocess timeout: five seconds;
- stdout/stderr from failed secret-tool writes are never surfaced verbatim.

## 6. Preview and apply contract

Additive Same-User operations:

```text
credential.get_status
credential.preview_apply
credential.apply
```

### 6.1 Status

`credential.get_status` is read-only and accepts an optional list of opaque
profiles constrained to the currently configured credential and recipient
profiles. It returns:

```json
{
  "schema_version": 1,
  "bot": {
    "profile_ref": "telegram_primary",
    "configured": true,
    "last_changed": "timestamp"
  },
  "recipients": [
    {
      "profile_ref": "status_admin_primary",
      "configured": true,
      "last_changed": "timestamp"
    }
  ]
}
```

No secret lookup result is included. Metadata is authoritative for the public
status; the later worker still resolves the actual secret and fails closed if
the keyring was modified externally.

### 6.2 Preview

`credential.preview_apply` requires a Request-ID and accepts exactly:

```json
{
  "action": "set | replace | delete",
  "secret_kind": "bot_token | chat_id",
  "profile_ref": "opaque_profile",
  "secret_value": "write-only value for set/replace"
}
```

The manager validates the value, stores it only in a bounded in-memory preview
entry and returns:

- schema version;
- action, kind and opaque profile;
- SHA-256 fingerprint over action/kind/profile plus an HMAC of the secret value;
- exact confirmation `CREDENTIAL <ACTION> <first-12-fingerprint>`;
- one-use preview token;
- 60-second expiry.

Neither the secret value nor its HMAC is returned or persisted.

### 6.3 Apply

`credential.apply` requires a Request-ID, preview token, fingerprint and exact
confirmation. The preview token is consumed before mutation. The apply response
is secret-free and durably request-idempotent.

## 7. Cross-store atomicity and rollback

Secret Service and SQLite cannot share one transaction. The manager therefore
uses compensation:

### Set or replace

1. read the previous secret internally into bounded memory;
2. write the new secret through stdin;
3. verify an internal lookup equals the submitted value using constant-time
   comparison;
4. commit metadata and audit in one SQLite transaction;
5. if step 3 or 4 fails, restore the previous secret or clear the newly created
   secret;
6. record a bounded rollback audit when possible.

### Delete

1. read the previous secret internally;
2. clear it;
3. commit `configured=false` metadata and audit;
4. if metadata/audit fails, restore the previous secret.

A rollback failure is terminal and explicitly reported as
`credential_rollback_failed`; no further mutation is attempted.

## 8. Idempotency and one-shot rules

`credential.preview_apply` is one-shot because the request body contains a
secret. Its response is never stored in `idempotency_results.response_json`.
Pure validation failures release the exact pending reservation.

`credential.apply` contains no secret value and is durably idempotent. An
identical replay returns the stored secret-free response. Reusing a consumed
preview under another Request-ID fails.

## 9. Status integration

Status v2 continues to expose only:

```json
{
  "configured": true,
  "last_changed": "timestamp"
}
```

The selected `credential_ref` determines the bot metadata row. No recipient
chat ID, profile key, secret kind, audit row or Secret-Service error text enters
the snapshot.

## 10. Testing strategy

Tests use an injected in-memory secret backend and never access the production
Secret Service.

Required red-green coverage:

- strict bot-token and chat-ID validation;
- no secret in argv, environment, response, SQLite, TOML, snapshot or logs;
- explicit schema-v4 dry run, apply, verify, backup and rollback;
- set, replace and delete for both secret kinds;
- one-use preview and durable apply replay;
- revision/profile authorization against current Config v2;
- Secret-Service timeout/failure;
- metadata failure restores the old secret;
- restore failure produces terminal rollback error;
- status uses only metadata and configured opaque profiles;
- legacy Config and Provider-v2 APIs remain unchanged.

## 11. Next slice

After this credential boundary merges, the native Telegram worker may consume
internal lookup methods and implement Bot API formatting, segmentation,
`retry_after`, transport reconciliation, systemd heartbeat and the shared fault
corpus. The network worker must not broaden the public credential API.
