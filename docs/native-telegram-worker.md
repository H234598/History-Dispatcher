---
title: Native Telegram Bot API Worker
type: operator-runbook
status: implemented
date: 2026-07-31
---

# Native Telegram Bot API Worker

## Purpose

The native worker delivers only Telegram target deliveries that were immutably
planned with:

```text
target_id=telegram
provider_id=history_dispatcher
capability_version=history-dispatcher-telegram-native-v1
```

It uses the existing Provider API v2 lifecycle and the write-only Secret-Service
profiles from Config v2. It never falls back to TeeBotus or another provider.

## Prerequisites

Before enabling the worker:

1. database migrations v2, v3 and v4 must be applied and verified;
2. `[routing.telegram]` must select `history_dispatcher`;
3. `credential_ref` and every `recipient_ref` must be opaque profile names;
4. the Bot token and every recipient chat ID must be configured through the
   write-only credential API;
5. the main History-Dispatcher service must be running.

The public status can confirm only secret-free metadata:

```json
{
  "configured": true,
  "last_changed": "timestamp"
}
```

The worker still resolves every secret immediately before each send and fails
closed when the keyring is unavailable or changed externally.

## Network boundary

The client is fixed to:

```text
host: api.telegram.org
port: 443
protocol: HTTPS
```

Internal method allowlist:

```text
getMe
sendMessage
sendDocument
```

Limits:

| Boundary | Limit |
|---|---:|
| connect/read timeout | 10 seconds |
| JSON request | 64 KiB |
| multipart request | 2 MiB |
| response | 256 KiB |
| inline text | 3900 characters |
| document payload | 1 MiB |
| document caption | 900 characters |
| retry_after | 604800 seconds |

The implementation uses `http.client.HTTPSConnection` and
`ssl.create_default_context()`. No configurable URL, proxy handler, redirect,
HTTP fallback, local Bot API server or paid broadcast path exists.

## Formatting

The worker sends plain text only. It does not set `parse_mode`, HTML entities or
Markdown entities.

Stable fields are rendered in this order:

```text
History-Dispatcher
Type
Projekt
Quelle
Zeit
Summary
Details
```

All values are Unicode-NFC normalized, line endings become LF, structures and
field lengths are bounded, and repository redaction is applied before
transport.

A payload up to 3900 characters is sent as exactly one `sendMessage` request.
A longer payload is sent as exactly one UTF-8 `.txt` document through
`sendDocument`. It is deliberately not split into several messages: a
multi-request sequence would require durable per-segment recipient state to
avoid partial duplicate sends after a crash.

Payloads above 1 MiB are rejected as `payload_too_large`.

## Claim lifecycle

For every batch the worker:

1. records a `starting` heartbeat;
2. claims only native Telegram deliveries through `provider.v2.claim`;
3. records an `active` heartbeat when at least one claim was returned;
4. validates target, provider, capability, worker and immutable binding;
5. rejects `reconciliation_only` claims before secret lookup or network access;
6. formats the payload once;
7. idempotently registers planned recipient profiles;
8. reads each returned recipient state;
9. skips terminal states, including `possible_duplicate` and
   `failed_terminal`;
10. renews the target claim before every network request;
11. resolves the Bot token and recipient chat ID from Secret Service;
12. applies global and per-recipient pacing;
13. sends one message or one document;
14. persists the recipient result immediately;
15. completes the target with the shared aggregation and maximum
    `retry_after`;
16. records an `idle`, `degraded` or `blocked` heartbeat.

The raw Telegram message ID is never persisted. A successful ID is transformed
into an HMAC-derived opaque `message_ref_key`.

## Recipient outcomes

| Telegram result | Stored recipient outcome | Retry behavior |
|---|---|---|
| explicit success | `delivered` | none |
| HTTP/Bot API 429 | `failed`, `rate_limited` | Telegram `retry_after` |
| explicit retryable 5xx | `failed`, `telegram_transient` | shared backoff |
| explicit invalid/forbidden chat | `failed_terminal` | no resend |
| missing/invalid secret | `failed`, `credential_unavailable` | fail closed |
| connect/TLS failure before request | `failed`, `telegram_connect_failed` | shared backoff |
| request/read failure after connect | `possible_duplicate` | never automatic resend |
| malformed/oversized success response | `possible_duplicate` | never automatic resend |
| oversized formatted payload | `failed_terminal`, `payload_too_large` | no resend |

Before every attempted send the worker re-registers the recipient profiles and
reads the authoritative stored state. A recipient already marked
`possible_duplicate`, delivered, terminal or skipped causes no secret lookup and
no network request.

## Rate limiting

The serial worker enforces:

```text
minimum 1.05 seconds between sends to the same recipient profile
minimum 0.04 seconds between any two sends
```

An explicit Telegram `retry_after` is authoritative for target retry scheduling
and is capped at seven days. Tests use fake clocks and never sleep or send real
messages.

## CLI

Run interactively:

```bash
python -m history_dispatcher \
  --config ~/.config/history-dispatcher/config.toml \
  telegram-worker
```

`SIGTERM` and `SIGINT` set a stop event. Startup failures are reported with a
bounded generic message and never echo Secret-Service or Telegram values.

## systemd user service

Render/install units:

```bash
python -m history_dispatcher.systemd \
  --python /path/to/.venv-py313/bin/python \
  --config ~/.config/history-dispatcher/config.toml
```

The worker unit is written but not enabled by default. Explicit activation:

```bash
python -m history_dispatcher.systemd \
  --python /path/to/.venv-py313/bin/python \
  --config ~/.config/history-dispatcher/config.toml \
  --enable \
  --enable-telegram-worker
```

The dedicated worker service receives:

```text
RestrictAddressFamilies=AF_UNIX AF_FILE AF_INET AF_INET6
```

The main service and collector retain:

```text
RestrictAddressFamilies=AF_UNIX AF_FILE
```

The unit contains no token, chat ID or secret environment variable. Existing
hardening remains enabled: `NoNewPrivileges`, `PrivateTmp`, `PrivateDevices`,
`ProtectSystem=strict`, `ProtectHome=read-only`, `RestrictNamespaces`,
`LockPersonality`, `MemoryDenyWriteExecute`, and `UMask=0077`.

## Status and diagnostics

The worker writes only bounded counts and the redacted provider identifier into
Provider API v2 heartbeats. Status v2 derives worker identity and state from the
existing `worker_heartbeats` table. No token, chat ID, raw Telegram response,
payload body or raw message ID is exposed.

## Functional fault corpus

The versioned fixture `tests/fixtures/provider-v2-contract.json` covers:

```text
success
terminal_chat_error
rate_limited
connect_failure
crash_after_accept
oversized_response
malformed_response
partial_recipients
```

Focused tests also cover fixed-host TLS, request/response limits, deterministic
formatting, document fallback, recipient-state resumption, credential failure,
lease renewal, systemd network isolation and CLI composition.

## Deliberately separate gates

This implementation does not perform a real Telegram call during tests or
installation. The following remain separate explicit work:

- native live canary with a dedicated test recipient;
- TeeBotus/native canary comparison without cross-provider duplicate delivery;
- Cinnamon provider selector and settings UX;
- incoming updates or webhooks;
- rich formatting and arbitrary media.
