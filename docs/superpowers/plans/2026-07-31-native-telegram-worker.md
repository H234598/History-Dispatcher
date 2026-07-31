---
title: Native Telegram Worker Implementation Plan
type: implementation-plan
status: active
date: 2026-07-31
---

# Native Telegram Worker Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Deliver provider-bound History-Dispatcher Telegram targets through a native, secret-safe, retry-aware Bot API worker without TeeBotus fallback or duplicate sends after ambiguous acceptance.

**Architecture:** Use a fixed-host `http.client.HTTPSConnection` Bot API client, a deterministic plain-text formatter with a single text-document fallback, and an in-process worker that consumes the existing `ProviderApiV2` contract. Keep the current recipient-level atomicity model by sending exactly one Telegram request per recipient, propagate `retry_after` into shared target backoff, and classify post-connect transport ambiguity as `possible_duplicate`.

**Tech Stack:** Python 3.13 standard library (`http.client`, `ssl`, `json`, `email.generator`-free bounded multipart rendering), existing Secret-Service store, Provider API v2, SQLite delivery store, pytest, systemd user units, GitHub Actions.

## Global Constraints

- Only `https://api.telegram.org:443` is allowed.
- Only `getMe`, `sendMessage`, and `sendDocument` are allowlisted internally.
- No proxy, redirect, local Bot API server, configurable URL, HTTP fallback, or paid broadcast.
- TLS uses `ssl.create_default_context()` with hostname and CA validation.
- Connect/read timeout is 10 seconds.
- JSON request bodies are at most 64 KiB.
- Multipart request bodies are at most 2 MiB.
- Responses are at most 256 KiB.
- `sendMessage` output is 1–3900 characters; longer content uses one UTF-8 text document, never a multi-request segment sequence.
- Document payload is at most 1 MiB and caption at most 900 characters.
- Bot token and chat ID are resolved only through `NativeTelegramSecretStore` immediately before sending.
- Token, chat ID, request URL, raw Telegram response, raw message ID, payload body, and Telegram description never appear in logs, exceptions, status, audit, snapshots, units, argv or persisted idempotency responses.
- Claims are exclusively `target_id=telegram`, `provider_id=history_dispatcher`, `capability_version=history-dispatcher-telegram-native-v1`.
- No cross-provider fallback.
- Post-connect request/read ambiguity becomes `possible_duplicate` and is never automatically resent.
- Telegram `retry_after` is authoritative and capped at 604800 seconds.
- Worker tests use injected connections, clocks and sleepers; they perform no real Telegram or Secret-Service calls.

---

### Task 1: Fixed-Host Telegram Bot API Client

**Files:**
- Create: `history_dispatcher/telegram_bot_api.py`
- Test: `tests/test_telegram_bot_api.py`

**Interfaces:**
- Consumes: validated bot token and chat ID strings from `NativeTelegramSecretStore`.
- Produces:
  - `TelegramApiSuccess(message_id: int)`
  - `TelegramApiRateLimited(retry_after_seconds: int)`
  - `TelegramApiRejected(reason_code: str, retryable: bool)`
  - `TelegramApiPossibleDuplicate(reason_code: str)`
  - `TelegramBotApiClient.send_message(token: str, chat_id: str, text: str) -> TelegramApiResult`
  - `TelegramBotApiClient.send_document(token: str, chat_id: str, filename: str, document: bytes, caption: str) -> TelegramApiResult`
  - `TelegramBotApiClient.get_me(token: str) -> TelegramApiResult`

- [ ] **Step 1: Write failing transport and response tests**

Create an injected fake HTTPS connection and cover:

```python
client = TelegramBotApiClient(connection_factory=factory)
result = client.send_message(token, chat_id, "hello")
assert result == TelegramApiSuccess(message_id=42)
assert factory.calls[0].host == "api.telegram.org"
assert factory.calls[0].port == 443
assert factory.calls[0].timeout == 10
```

Also assert:

- TLS context has `check_hostname=True` and `verify_mode=ssl.CERT_REQUIRED`;
- connection is explicit before request;
- POST path is exactly `/bot<token>/sendMessage` or `/bot<token>/sendDocument`;
- request headers/body are bounded;
- client never uses proxy or redirect handlers;
- 429 with `parameters.retry_after=17` returns `TelegramApiRateLimited(17)`;
- retry_after values below 1 or above 604800 are rejected/capped safely;
- explicit 401/403/400 maps to terminal bounded reasons;
- explicit 5xx maps to retryable `telegram_transient`;
- connect failure maps to retryable `telegram_connect_failed`;
- request/getresponse/read failures after connection map to `TelegramApiPossibleDuplicate`;
- oversized, malformed UTF-8, malformed JSON and malformed success responses never leak token/chat ID/description;
- success message IDs must be positive integers;
- 3xx is a terminal `telegram_redirect_forbidden`;
- multipart filename is normalized and the body stays below 2 MiB.

- [ ] **Step 2: Run the focused test and verify RED**

```bash
python -m pytest tests/test_telegram_bot_api.py -q --tb=short
```

Expected: collection fails because `history_dispatcher.telegram_bot_api` does not exist.

- [ ] **Step 3: Implement the minimal fixed-host client**

Implement:

```python
TELEGRAM_API_HOST = "api.telegram.org"
TELEGRAM_API_PORT = 443
TELEGRAM_API_TIMEOUT_SECONDS = 10
MAX_JSON_REQUEST_BYTES = 64 * 1024
MAX_MULTIPART_REQUEST_BYTES = 2 * 1024 * 1024
MAX_RESPONSE_BYTES = 256 * 1024
MAX_RETRY_AFTER_SECONDS = 7 * 24 * 3600
```

Use `http.client.HTTPSConnection` and `ssl.create_default_context()`. Connect before calling `request()`. Read `MAX_RESPONSE_BYTES + 1`, close in `finally`, parse a bounded Telegram envelope, and return typed outcomes without raising a message containing private data.

Build multipart bodies manually from a fixed ASCII boundary generated by an injectable factory. Fields are exactly `chat_id`, optional `caption`, and `document`; the filename is a bounded ASCII-safe `.txt` basename.

- [ ] **Step 4: Run focused and secret-store tests**

```bash
python -m pytest \
  tests/test_telegram_bot_api.py \
  tests/test_telegram_secrets.py \
  -q --tb=short
```

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add history_dispatcher/telegram_bot_api.py tests/test_telegram_bot_api.py
git commit -m "feat: add fixed-host Telegram Bot API client"
```

---

### Task 2: Deterministic Formatter and Single-Document Fallback

**Files:**
- Create: `history_dispatcher/telegram_formatter.py`
- Test: `tests/test_telegram_formatter.py`

**Interfaces:**
- Consumes: one decrypted claim `payload: Mapping[str, Any]` and opaque `event_id`.
- Produces:
  - `FormattedTelegramDelivery(mode: Literal["text", "document"], text: str, filename: str, document: bytes, caption: str)`
  - `format_telegram_delivery(payload: Mapping[str, Any], *, event_id: str) -> FormattedTelegramDelivery`

- [ ] **Step 1: Write failing formatter tests**

Cover:

```python
formatted = format_telegram_delivery(payload, event_id="evt_123")
assert formatted.mode == "text"
assert 1 <= len(formatted.text) <= 3900
assert formatted.filename == ""
assert formatted.document == b""
```

Also assert:

- deterministic output for identical input;
- Unicode NFC and `\n` line endings;
- stable field order: type, project, source, timestamp, summary, details;
- no `parse_mode`, Markdown or HTML escaping assumptions;
- redaction removes token-like, raw-chat-ID and private-path markers;
- field values and collection counts are bounded;
- output above 3900 characters becomes one text document;
- document filename is `history-<opaque-fragment>.txt` and contains no raw event ID/path/secret;
- document caption is at most 900 characters;
- output above 1 MiB raises `TelegramFormattingError("payload_too_large")`;
- non-object payloads, non-finite JSON values and unsupported deeply nested structures fail with bounded reasons.

- [ ] **Step 2: Run the focused test and verify RED**

```bash
python -m pytest tests/test_telegram_formatter.py -q --tb=short
```

Expected: import failure because the formatter module is absent.

- [ ] **Step 3: Implement bounded deterministic rendering**

Normalize supported scalar/list/dict values into a bounded plain-text tree. Reuse `redact_text` on every final field and the final rendering. Use SHA-256 of the normalized event ID for the filename fragment. Emit text mode at `<=3900` characters and document mode otherwise. Reject document bytes above `1 * 1024 * 1024`.

- [ ] **Step 4: Run formatter and privacy tests**

```bash
python -m pytest \
  tests/test_telegram_formatter.py \
  tests/test_classification_privacy.py \
  tests/test_redaction.py \
  -q --tb=short
```

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add history_dispatcher/telegram_formatter.py tests/test_telegram_formatter.py
git commit -m "feat: format bounded native Telegram deliveries"
```

---

### Task 3: Native Provider-v2 Worker and Rate Limiter

**Files:**
- Create: `history_dispatcher/native_telegram_worker.py`
- Test: `tests/test_native_telegram_worker.py`
- Test: `tests/test_native_telegram_worker_faults.py`
- Modify: `tests/fixtures/provider-v2-contract.json`

**Interfaces:**
- Consumes:
  - `ProviderApiV2.dispatch(operation: str, body: Mapping[str, Any])`
  - `NativeTelegramSecretStore.lookup_bot_token(profile_ref)`
  - `NativeTelegramSecretStore.lookup_chat_id(profile_ref)`
  - `TelegramBotApiClient`
  - `format_telegram_delivery()`
- Produces:
  - `TelegramRateLimiter.wait(recipient_ref: str) -> None`
  - `NativeTelegramWorker.run_once() -> NativeTelegramWorkerReport`
  - `NativeTelegramWorker.run_forever(stop_event) -> None`

- [ ] **Step 1: Write failing worker-flow tests**

Build a fake `ProviderApiV2`, secret store, client, clock and sleeper. Verify:

```python
report = worker.run_once()
assert report.claimed == 1
assert report.delivered == 1
assert provider.operations == [
    "provider.v2.heartbeat",
    "provider.v2.claim",
    "provider.v2.register_recipients",
    "provider.v2.renew",
    "provider.v2.record_recipients",
    "provider.v2.complete",
    "provider.v2.heartbeat",
]
```

Also cover:

- fixed native target/provider/capability claim body;
- claim batch, lease, max attempts and backoff bounds;
- defensive rejection of wrong provider/target/capability;
- `reconciliation_only` blocks before secret lookup/send;
- payload formatted once per claim;
- successful recipient refs are skipped;
- recipient refs are resolved from the immutable claim binding/open refs only;
- bot token and chat ID are looked up immediately before each send;
- lease renewal precedes every network request;
- text/document client selection;
- successful Telegram message ID becomes an HMAC-derived opaque message_ref_key;
- recipient outcome is recorded before target completion;
- one recipient failure does not block independent recipients;
- maximum retry_after is passed to completion;
- explicit terminal failures remain `failed` with bounded reason;
- post-connect ambiguity becomes `possible_duplicate` and is not resent in a later batch;
- credential failures produce no network call;
- no TeeBotus operation/fallback occurs;
- worker report and heartbeat details contain counts/reason codes only.

- [ ] **Step 2: Write failing rate-limit and fault tests**

Verify fake-clock behavior:

```python
limiter.wait("status_admin_primary")
limiter.wait("status_admin_primary")
assert sleeper.calls == [pytest.approx(1.05)]
```

Cover global 0.04-second pacing, per-recipient 1.05-second pacing, 429 retry_after propagation, connect failure, explicit 5xx, oversized response, malformed response, request ambiguity, repeated run, completed-recipient skip and bounded stop-event loop.

Extend the shared provider fixture with native cases for:

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

- [ ] **Step 3: Run worker tests and verify RED**

```bash
python -m pytest \
  tests/test_native_telegram_worker.py \
  tests/test_native_telegram_worker_faults.py \
  -q --tb=short
```

Expected: import failure because the worker module is absent.

- [ ] **Step 4: Implement the minimal worker**

Use `ProviderApiV2` for every claim lifecycle mutation. The worker must never call `DeliveryStore` directly for claim/recipient/completion state. Validate every returned claim defensively, format once, resolve secrets per recipient, pace, renew, send, record immediately, then complete with shared aggregation.

Use `persistent_opaque_id(key_provider, "telegram-message-ref", f"{recipient_ref}|{message_id}", prefix="message")`. Never persist the raw Telegram message ID.

`run_forever()` sleeps an injectable bounded idle interval and exits when the stop event is set. It emits `starting`, `active`, `idle`, `degraded` and `blocked` heartbeats with at most 16 bounded fields.

- [ ] **Step 5: Run focused, provider and store tests**

```bash
python -m pytest \
  tests/test_native_telegram_worker.py \
  tests/test_native_telegram_worker_faults.py \
  tests/test_provider_api_v2.py \
  tests/test_provider_api_v2_one_shot.py \
  tests/test_delivery_store.py \
  tests/test_delivery_store_concurrency.py \
  -q --tb=short
```

Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add history_dispatcher/native_telegram_worker.py \
  tests/test_native_telegram_worker.py \
  tests/test_native_telegram_worker_faults.py \
  tests/fixtures/provider-v2-contract.json
git commit -m "feat: add native Telegram provider worker"
```

---

### Task 4: CLI, Dedicated systemd Unit and Status Contract

**Files:**
- Modify: `history_dispatcher/cli.py`
- Modify: `history_dispatcher/systemd.py`
- Modify: `history_dispatcher/status_runtime_v2.py`
- Modify: `history_dispatcher/status_v2.py`
- Test: `tests/test_native_telegram_cli.py`
- Test: `tests/test_systemd.py`
- Test: `tests/test_status_runtime_v2.py`

**Interfaces:**
- Consumes: `NativeTelegramWorker` and existing config/credential/status contracts.
- Produces:
  - CLI command `history-dispatcher telegram-worker`
  - `history-dispatcher-telegram-worker.service`
  - redacted native worker status derived from existing heartbeat metadata

- [ ] **Step 1: Write failing CLI/systemd/status tests**

Verify:

```python
units = render_units(...)
worker_unit = units["history-dispatcher-telegram-worker.service"]
assert "telegram-worker" in worker_unit
assert "RestrictAddressFamilies=AF_UNIX AF_FILE AF_INET AF_INET6" in worker_unit
```

Also assert:

- main service and collector keep `AF_UNIX AF_FILE` only;
- worker unit contains no token, chat ID, credential value or environment secret;
- hardening directives remain present;
- worker service depends on `history-dispatcher.service`;
- CLI constructs the worker with config, key provider, secret store, client and provider API;
- SIGTERM/SIGINT set a stop event and do not expose internals;
- missing schema/credential/network prerequisites fail with bounded redacted errors;
- status reports native worker heartbeat state/counts without secrets;
- existing CLI and status-v1/v2 tests remain unchanged.

- [ ] **Step 2: Run focused tests and verify RED**

```bash
python -m pytest \
  tests/test_native_telegram_cli.py \
  tests/test_systemd.py \
  tests/test_status_runtime_v2.py \
  -q --tb=short
```

Expected: failures because command, unit and native worker status are absent.

- [ ] **Step 3: Implement CLI and unit integration**

Add a bounded `telegram-worker` subcommand. Construct `DeliveryStore`, `ProviderApiV2`, `NativeTelegramSecretStore`, `TelegramBotApiClient` and `NativeTelegramWorker`. Install signal handlers that set a `threading.Event` and call `run_forever()`.

Extend `render_units()` with a dedicated worker unit while preserving existing unit text byte-for-byte except for the returned additional mapping entry. Enable the worker only when an explicit `--enable-telegram-worker` installer flag is supplied; do not silently enable network delivery for existing installations.

Expose only heartbeat-derived native worker state in status.

- [ ] **Step 4: Run CLI/systemd/status and architecture tests**

```bash
python -m pytest \
  tests/test_native_telegram_cli.py \
  tests/test_systemd.py \
  tests/test_status_runtime_v2.py \
  tests/test_status_service_v2.py \
  tests/test_architecture_contract.py \
  -q --tb=short
```

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add history_dispatcher/cli.py history_dispatcher/systemd.py \
  history_dispatcher/status_runtime_v2.py history_dispatcher/status_v2.py \
  tests/test_native_telegram_cli.py tests/test_systemd.py \
  tests/test_status_runtime_v2.py
git commit -m "feat: run native Telegram worker as hardened user service"
```

---

### Task 5: Contracts, Plan Tracking, Full Verification and Merge Gates

**Files:**
- Create: `docs/native-telegram-worker.md`
- Modify: `docs/implementation-progress.md`
- Modify: `docs/implementation-plan-addendum-telegram.md`
- Modify: `docs/contracts/control-protocol-v1.md`
- Modify: `README.md`
- Modify: `docs/superpowers/plans/2026-07-31-native-telegram-worker.md`
- Test: complete repository

**Interfaces:**
- Consumes completed client, formatter, worker, CLI and unit.
- Produces operator runbook, exact fault semantics and next canary/UI boundary.

- [ ] **Step 1: Document the worker contract**

Record:

- fixed Telegram host/method/timeout/size limits;
- plain-text and text-document behavior;
- Secret-Service lookup timing;
- provider-v2 claim lifecycle;
- rate-limit and `retry_after` behavior;
- possible-duplicate semantics;
- systemd installation/enable commands;
- no proxy, redirect, fallback, rich formatting, inbound updates or live canary in this slice;
- exact separation between functional tests and later live canaries.

- [ ] **Step 2: Run complete verification**

```bash
python -m compileall -q history_dispatcher scripts tests
node --check files/history-dispatcher@H234598/applet.js
node --test tests/applet_contract.test.js
python -m pytest -q
python -m build
```

Expected: all commands exit 0.

- [ ] **Step 3: Inspect leak and network boundaries**

Inspect the full PR diff and verify:

- no concrete bot token/chat ID outside negative tests;
- no token/chat ID in exception strings, status, heartbeat, units or fixtures;
- no configurable URL/proxy/redirect/local-server path;
- only the worker unit gains `AF_INET/AF_INET6`;
- no raw Telegram message ID is persisted;
- `git diff --check` is clean.

- [ ] **Step 4: Update plan and roadmap evidence**

Mark `TG-E-001`, `TG-E-002`, `TG-E-003`, `TG-E-006` and the native half of `TG-F-002b` complete only with green evidence. Keep live canaries and Cinnamon UI unchecked.

- [ ] **Step 5: Commit documentation**

```bash
git add README.md docs
git commit -m "docs: complete native Telegram worker contract"
```

- [ ] **Step 6: Enforce hard merge gates**

Create or update a draft PR titled:

```text
feat: add native Telegram Bot API worker
```

Require GitHub Actions, qlty, CodeRabbit and zero unresolved review threads on the exact final head SHA. Mark ready and squash-merge only against that SHA. Add a post-merge docs-only plan sync if merge-dependent checkboxes require the resulting main commit.
