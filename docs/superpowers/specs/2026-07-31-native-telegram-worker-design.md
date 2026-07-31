---
title: Native Telegram Worker Design
type: design-spec
status: approved
date: 2026-07-31
scope: history-dispatcher
---

# Native Telegram Worker Design

## 1. Goal

Implement the first production-capable outbound Telegram worker that delivers
only route plans immutably bound to `provider=history_dispatcher`. It reuses the
existing provider-v2 claim, lease, recipient, completion, heartbeat, retry and
reconciliation contracts and resolves bot tokens and chat IDs only through the
internal Secret-Service boundary merged in PR #13.

The worker must never fall back to TeeBotus, never expose secrets, and never
turn an uncertain post-send state into an automatic resend.

## 2. Scope

This slice includes:

- a fixed-host HTTPS Telegram Bot API client;
- `sendMessage` and text-file `sendDocument` support;
- deterministic plain-text formatting and bounded attachment fallback;
- native claim processing through `ProviderApiV2` in-process;
- recipient-level partial results and `possible_duplicate` handling;
- Telegram `retry_after` propagation into the shared store backoff;
- a bounded heartbeat loop and dedicated systemd user worker unit;
- a native fault corpus for TLS/transport failures, 429, explicit API errors,
  oversized responses, malformed JSON and crash-after-accept ambiguity.

This slice deliberately excludes:

- incoming Telegram updates, polling and webhooks;
- public credential read operations;
- rich messages, Markdown, HTML or entity parsing;
- arbitrary URLs, local Bot API servers, HTTP proxies or redirects;
- photos, audio, video and arbitrary attachments;
- paid broadcasts;
- Cinnamon settings UI and live canary sends.

## 3. Approaches considered

### 3.1 `urllib.request`

Rejected for the production transport. Its default opener can consume proxy
environment variables and follows redirects unless those behaviors are
explicitly replaced. That is avoidable complexity around a secret-bearing URL.

### 3.2 Direct `http.client.HTTPSConnection` — selected

Use one fixed host, `api.telegram.org`, port 443, and
`ssl.create_default_context()`. The client constructs only allowlisted method
paths and never accepts a URL from configuration or payload data. The standard
TLS context performs CA and hostname verification. Direct `HTTPSConnection`
also introduces no proxy or redirect path.

### 3.3 Third-party HTTP client

Rejected for this slice. It would add an unnecessary dependency and supply-chain
surface to a client that needs only two bounded POST methods.

## 4. Components

### 4.1 `telegram_bot_api.py`

`TelegramBotApiClient` owns the complete external network boundary.

Constants:

```text
host = api.telegram.org
port = 443
connect/read timeout = 10 seconds
maximum JSON request = 64 KiB
maximum multipart request = 2 MiB
maximum response = 256 KiB
allowlisted methods = sendMessage | sendDocument | getMe
```

Transport rules:

- use `http.client.HTTPSConnection` with `ssl.create_default_context()`;
- connect explicitly before sending so pre-connect failures remain safely
  retryable;
- after a successful TLS connection, any exception while writing the request or
  waiting for the response is classified `possible_duplicate` because Telegram
  may have accepted the request;
- never follow redirects and treat every 3xx response as a terminal protocol
  error;
- close every connection after one request;
- never include the token, full URL, chat ID, payload body, Telegram description
  or raw response in an exception string;
- read at most `maximum response + 1` bytes and reject oversized responses;
- require UTF-8, a top-level JSON object and the Telegram `ok` Boolean.

Typed outcomes:

```python
TelegramApiSuccess(message_id: int)
TelegramApiRateLimited(retry_after_seconds: int)
TelegramApiRejected(reason_code: str, retryable: bool)
TelegramApiPossibleDuplicate(reason_code: str)
```

Explicit Bot API errors are mapped to bounded reason codes. HTTP 429 or a
Telegram error with `parameters.retry_after` becomes rate-limited. Explicit 5xx
responses are retryable because Telegram returned a negative API response.
401/403 and ordinary 400-series validation/chat errors are terminal. Transport
ambiguity after connection is always `possible_duplicate`.

### 4.2 `telegram_formatter.py`

The formatter accepts the decrypted classified-event mapping from a provider
claim and produces one deterministic UTF-8 representation.

Rules:

- plain text only; do not set `parse_mode` or entities;
- normalize line endings and Unicode NFC;
- run repository redaction before returning output;
- include stable fields only: history kind, project label, source, timestamp,
  summary and bounded payload details;
- cap individual field text and total rendered bytes;
- produce a short inline message when the complete text is at most 3900
  characters;
- otherwise produce exactly one UTF-8 `.txt` document plus a bounded caption;
- do not send several text segments for one recipient. A multi-request segment
  sequence would require durable per-segment state to prevent partial duplicate
  sends. The single-document fallback preserves the existing recipient-level
  atomicity model;
- reject output above 1 MiB with `payload_too_large`.

`FormattedTelegramDelivery` contains either:

```text
mode=text, text=<1..3900 chars>
```

or:

```text
mode=document, filename=history-<opaque-event-fragment>.txt,
document=<1..1 MiB>, caption=<0..900 chars>
```

No raw project path, Secret-Service value or Telegram identifier may enter the
filename.

### 4.3 `native_telegram_worker.py`

The worker uses `ProviderApiV2` in-process instead of bypassing or duplicating
its validation semantics.

Fixed identity:

```text
target_id = telegram
provider_id = history_dispatcher
capability_version = history-dispatcher-telegram-native-v1
```

Batch flow:

1. emit `starting` heartbeat;
2. claim a bounded batch through `provider.v2.claim`;
3. for every claim, verify provider, target and capability defensively;
4. reject any `reconciliation_only` claim before secret lookup or send;
5. format the payload once;
6. register the claim's open opaque recipient refs;
7. for each recipient not already successful:
   - renew the target claim;
   - resolve the current bot token and recipient chat ID from Secret Service;
   - pace the chat;
   - send one message or one document;
   - convert the Telegram message ID into an HMAC-derived opaque
     `message_ref_key`;
   - record the recipient outcome immediately;
8. complete the target with the shared store aggregation and the maximum
   `retry_after` observed for failed recipients;
9. emit a bounded `idle`, `degraded` or `blocked` heartbeat.

A successful recipient is never offered again. One recipient failure does not
prevent independent recipients from completing. There is no cross-provider
fallback.

### 4.4 Rate limiter

`TelegramRateLimiter` receives an injectable monotonic clock and sleeper.

- minimum 1.05 seconds between sends to the same recipient profile;
- minimum 0.04 seconds globally, keeping the serial worker below 25 messages per
  second;
- Telegram `retry_after` is authoritative and is passed to target completion;
- all values are capped to the existing seven-day store maximum;
- tests use a fake clock and never sleep in real time.

### 4.5 systemd worker

Render a separate `history-dispatcher-telegram-worker.service`.

- runs `python -m history_dispatcher ... telegram-worker`;
- depends on the main History-Dispatcher service;
- receives `AF_UNIX AF_FILE AF_INET AF_INET6`;
- the main service and collector retain their current network restrictions;
- `NoNewPrivileges`, `PrivateTmp`, `PrivateDevices`, `ProtectSystem=strict`,
  `ProtectHome=read-only`, `RestrictNamespaces`, `LockPersonality`,
  `MemoryDenyWriteExecute` and `UMask=0077` remain enabled;
- restart on failure with bounded delay;
- no token or chat ID is placed in the unit or environment.

## 5. Error and retry semantics

| Condition | Recipient outcome | Target behavior |
|---|---|---|
| explicit success | `delivered` | aggregate normally |
| HTTP/Bot API 429 | `failed` / `rate_limited` | retry using `retry_after` |
| explicit retryable 5xx | `failed` / `telegram_transient` | shared backoff |
| invalid chat / forbidden | `failed` / bounded terminal reason | terminal when aggregation decides |
| missing/invalid secret | `failed` / `credential_unavailable` | fail closed; no network send |
| connect/TLS failure before request | `failed` / `telegram_connect_failed` | shared backoff |
| failure after TLS connect while sending/reading | `possible_duplicate` | never automatic resend |
| malformed/oversized success response | `possible_duplicate` | never automatic resend |
| malformed explicit error response | `failed` / `telegram_protocol_error` | shared backoff unless acceptance is ambiguous |
| oversized formatted payload | `failed` / `payload_too_large` | terminal |

Error strings and heartbeat details contain only bounded reason codes and counts.

## 6. Testing strategy

### Client contract

- fixed host and port;
- secure default TLS context;
- no redirects or proxy lookup;
- token appears only in the private request path passed to the injected
  connection and never in errors/logs;
- bounded request and response bodies;
- success parsing and opaque message ID handoff;
- 400/401/403/429/5xx mapping;
- `retry_after` validation and capping;
- pre-connect retryable versus post-connect `possible_duplicate`;
- malformed UTF-8/JSON and oversized response handling;
- multipart document body contains no unbounded filename or metadata.

### Formatter contract

- deterministic output;
- NFC and line-ending normalization;
- plain text only;
- redaction of token/chat-ID/path-like markers;
- inline threshold;
- document fallback and 1 MiB hard bound;
- no secret or raw identifier in filename/caption.

### Worker contract

- native-only claims;
- no TeeBotus fallback;
- no send for reconciliation-only claims;
- secret lookup immediately before send;
- lease renewal before every network operation;
- successful recipient skip;
- partial recipients recorded before completion;
- 429 propagation;
- post-connect ambiguity becomes monotone `possible_duplicate`;
- identical batches cannot resend completed recipients;
- bounded heartbeat states;
- same semantic provider fixture used by TeeBotus and native tests where
  applicable.

### systemd contract

- only the native worker gains Internet address families;
- no credentials in units;
- hardening directives remain present;
- existing service and collector unit text stays backward compatible.

## 7. Definition of done

This slice is complete only when:

- Bot API client, formatter, worker and worker unit exist;
- all focused and full repository tests pass;
- leak scans find no token/chat-ID in logs, snapshots, database bytes, units or
  persisted responses;
- qlty and CodeRabbit are green with no unresolved threads;
- the implementation plan and central progress ledger contain exact test and
  merge evidence;
- the PR is squash-merged against the exact verified head SHA.

Live Telegram canaries and the Cinnamon provider selector remain separate,
explicit later gates.
