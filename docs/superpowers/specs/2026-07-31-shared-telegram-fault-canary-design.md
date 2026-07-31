---
title: Shared Telegram Fault Contract and Canary Harness Design
type: design-spec
status: approved
date: 2026-07-31
scope: history-dispatcher-and-teebotus
---

# Shared Telegram Fault Contract and Canary Harness Design

## 1. Goal

Create one versioned, transport-neutral Telegram provider fault contract that is
consumed by both repositories:

```text
H234598/History-Dispatcher@a51906f2b05c46252eedcd1c7523b75f9fe28bf5
H234598/TeeBotus@36c75843a5910cc3b22ffdd9a5ec87eb1d5b2ea9
```

Then add a strictly opt-in operator canary harness that can prove, in an isolated
runtime, that:

1. native History-Dispatcher delivery works through the fixed-host Bot API worker;
2. TeeBotus delivery works through Provider API v2;
3. each immutable route plan is claimable only by its bound provider;
4. repeating either worker after completion does not create another Telegram send;
5. an uncertain post-connect result remains `possible_duplicate` and is never
   automatically resent;
6. no production database, production queue or non-canary recipient can be
   touched by the harness.

The implementation must not perform a real Telegram request in CI, during
installation, or merely by rendering a preview. A live send remains an explicit
operator action with multiple independent gates.

## 2. Current state and gap

History-Dispatcher now contains the native functional fixture:

```text
tests/fixtures/provider-v2-contract.json
```

Its cases are:

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

TeeBotus currently contains:

```text
tests/fixtures/provider-v2/contract.json
```

That file describes the Provider API v2 operation list, claim/reclaim request
shape, recipient references and two sample outcomes. It does not yet encode the
same eight fault semantics consumed by the native worker.

The gap is therefore not the Provider API itself. The gap is that both
repositories do not consume one byte-identical, hash-bound fault corpus and do
not yet expose one common secret-free evidence format for operator canaries.

## 3. Approaches considered

### 3.1 One canonical copied contract with a fixed digest — selected

History-Dispatcher owns the canonical JSON bytes. Both repositories vendor the
same file and validate the same SHA-256 digest in CI. Provider-specific adapters
map abstract transport results into the common normalized outcomes.

Advantages:

- no runtime or CI network dependency between repositories;
- exact drift detection;
- deterministic fixtures and reviewable updates;
- each repository can test locally and in GitHub Actions;
- provider-specific implementation remains isolated behind adapters.

Trade-off:

- contract changes require coordinated pull requests in both repositories.

This is accepted because contract updates are deliberate architecture changes,
not an independently evolving data feed.

### 3.2 Independent provider fixture copies

Rejected. Independent fixtures would continue the current semantic drift and
could both be green while disagreeing on retry, terminal and duplicate rules.

### 3.3 Fetch the other repository during CI

Rejected. Cross-repository network fetches make tests depend on availability,
branch movement, credentials and external mutable state. They also complicate
reproducible local verification.

## 4. Canonical fault contract

### 4.1 Ownership and paths

Canonical source in History-Dispatcher:

```text
contracts/provider-v2/telegram-fault-contract-v1.json
```

Vendored test copy in History-Dispatcher:

```text
tests/fixtures/provider-v2/telegram-fault-contract-v1.json
```

Vendored test copy in TeeBotus:

```text
tests/fixtures/provider-v2/telegram-fault-contract-v1.json
```

A small manifest in each repository records the same contract identity and
digest:

```text
contracts/provider-v2/telegram-fault-contract-v1.sha256
```

TeeBotus mirrors that digest under:

```text
tests/fixtures/provider-v2/telegram-fault-contract-v1.sha256
```

The canonical and vendored History-Dispatcher copies must be byte-identical.
The TeeBotus copy must be byte-identical to the canonical file. JSON is written
with UTF-8, LF line endings, two-space indentation, sorted object keys and one
trailing newline.

### 4.2 Top-level schema

```json
{
  "contract_id": "history-dispatcher.telegram-provider-faults",
  "contract_version": 1,
  "provider_api_schema_version": 2,
  "target_id": "telegram",
  "providers": {
    "history_dispatcher": {
      "capability_version": "history-dispatcher-telegram-native-v1"
    },
    "teebotus": {
      "capability_version": "history-dispatcher-telegram-v2"
    }
  },
  "cases": []
}
```

Only transport-neutral fields are permitted. The contract must contain no bot
token, raw chat ID, Telegram username, account secret, local path, socket path,
production hostname, payload body or real message ID.

### 4.3 Case schema

Every case contains exactly:

```text
name
transport_results
expected_recipient_outcomes
expected_target
safety
```

`transport_results` is an ordered list because `partial_recipients` contains more
than one independent recipient.

Allowed abstract result kinds:

```text
success
terminal_rejection
retryable_rejection
rate_limited
pre_connect_failure
post_connect_ambiguity
oversized_success_response
malformed_success_response
```

A result may contain only bounded contract values such as:

```text
reason_code
retry_after_seconds
opaque_message_seed
```

`opaque_message_seed` is test input only. It is not a Telegram message ID and
must never be copied into persisted evidence.

Every normalized recipient outcome contains exactly:

```text
status
possible_duplicate
reason_code
message_ref_required
```

Allowed normalized statuses:

```text
accepted
delivered
acknowledged
failed
failed_terminal
skipped
possible_duplicate
```

The target expectation contains:

```text
expected_state_class = success | retryable | terminal | partial
retry_after_seconds
error_class
```

The safety object contains booleans:

```text
must_not_auto_resend
requires_recipient_persistence_before_complete
requires_reconciliation_only_replay
```

### 4.4 Required cases

The first contract version contains exactly these cases in this order:

1. `success`
2. `terminal_chat_error`
3. `rate_limited`
4. `connect_failure`
5. `crash_after_accept`
6. `oversized_response`
7. `malformed_response`
8. `partial_recipients`

Semantics:

#### `success`

- one explicit success;
- successful recipient outcome;
- opaque message reference required;
- target success;
- no retry and no automatic resend.

#### `terminal_chat_error`

- explicit forbidden/invalid recipient result;
- `failed_terminal`;
- terminal target when no other recipient succeeds;
- never automatically resent.

#### `rate_limited`

- explicit 429 with `retry_after_seconds=17`;
- retryable recipient outcome with reason `rate_limited`;
- target retry delay exactly 17 seconds or greater only when the shared store
  backoff is larger;
- no duplicate flag.

#### `connect_failure`

- failure before request acceptance is possible;
- retryable recipient outcome `telegram_connect_failed` or the provider-specific
  equivalent mapped to the common reason;
- no duplicate flag.

#### `crash_after_accept`

- post-connect ambiguity;
- recipient outcome `possible_duplicate`;
- `must_not_auto_resend=true`;
- target is partial/blocking until operator reconciliation;
- no automatic provider fallback.

#### `oversized_response`

- an explicit success HTTP status with an oversized response body;
- acceptance is uncertain;
- same `possible_duplicate` safety behavior as crash-after-accept.

#### `malformed_response`

- an explicit success HTTP status with malformed UTF-8/JSON/envelope;
- acceptance is uncertain;
- same `possible_duplicate` safety behavior.

#### `partial_recipients`

- one success and one retryable or terminal failure;
- outcomes persisted independently before target completion;
- target classified partial;
- successful recipient must not be offered again;
- only the still-open recipient may participate in a later retry.

## 5. Provider adapters

### 5.1 History-Dispatcher adapter

History-Dispatcher keeps its existing typed Bot API results. A focused adapter
converts each abstract fixture result into:

```text
TelegramApiSuccess
TelegramApiRateLimited
TelegramApiRejected
TelegramApiPossibleDuplicate
```

The native worker consumes those values normally. Tests must validate the full
Provider API v2 lifecycle, not only call `_map_result()` directly:

```text
claim
register recipients
renew
send fake result
record recipient
complete target
heartbeat
```

The test reads the resulting recipient and target snapshots and compares them to
the common contract.

### 5.2 TeeBotus adapter

TeeBotus maps each abstract fixture result to the local dispatch result consumed
by:

```text
provider_v2_dispatch_result_to_outcome
```

Tests run the Provider-v2 batch worker against a fake bridge and fake sender. The
same normalized expectations are asserted after the adapter has produced
recipient callbacks and completion callbacks.

The TeeBotus test must additionally verify:

- callback spooling remains encrypted;
- callback replay never invokes the sender;
- reclaim claims are `reconciliation_only`;
- a `possible_duplicate` outcome cannot be downgraded;
- a successful recipient cannot be resent in a later batch.

### 5.3 Digest guard

Each repository contains a focused test that:

1. reads the vendored contract as bytes;
2. computes SHA-256;
3. compares it with the committed `.sha256` value;
4. parses JSON and rejects unknown top-level or case fields;
5. verifies the exact case order and allowed enums.

History-Dispatcher additionally verifies that canonical and test copies are
byte-identical.

No test fetches another repository or the Internet.

## 6. Canary architecture

### 6.1 Separation from production

The harness never points workers at the production database or production
control socket. It creates an isolated owner-only runtime under:

```text
$XDG_RUNTIME_DIR/history-dispatcher-canary/<run-id>/
```

The runtime contains:

```text
config.toml
control.sock
canary.sqlite3
status-v2.json
evidence.json
```

Permissions:

```text
directory 0700
files 0600
socket same-user only
```

The harness refuses paths outside this generated runtime and refuses symlinks.
It never copies the production database.

The isolated database is migrated through the normal v2, v3 and v4 migration
code, then seeded with canary-only events and immutable route plans.

### 6.2 Canary profiles

Every live canary requires exactly one recipient profile. Its opaque reference
must match:

```text
^canary_[a-z0-9_.-]{1,80}$
```

Native canary inputs:

```text
provider=history_dispatcher
credential_ref matching ^canary_
recipient_ref matching ^canary_
```

TeeBotus canary inputs:

```text
provider=teebotus
instance_ref matching ^canary_
recipient_ref matching ^canary_
```

The harness rejects ordinary production profile names even when those profiles
exist. Raw chat IDs and tokens are never accepted as arguments.

### 6.3 Commands

History-Dispatcher owns the orchestration CLI:

```text
python -m history_dispatcher.canary plan
python -m history_dispatcher.canary run
python -m history_dispatcher.canary verify
python -m history_dispatcher.canary cleanup
```

`plan` is always write-free with respect to Telegram and production state. It:

1. validates provider selection and `canary_` profiles;
2. validates required executables and repository versions;
3. creates no provider claim and performs no Secret-Service lookup;
4. renders a canonical preview;
5. produces a SHA-256 fingerprint and exact confirmation string.

The confirmation format is:

```text
SEND TELEGRAM CANARY <provider> <first-12-fingerprint-characters>
```

`run` requires all of:

```text
--apply
--plan-file <owner-only preview JSON>
--fingerprint <full SHA-256>
--confirm "SEND TELEGRAM CANARY <provider> <prefix>"
--run-id <new opaque id>
```

It rejects expired plans older than ten minutes, reused run IDs, changed
repository SHAs, changed profile references and mismatched fingerprints.

`verify` is network-free. It reads the isolated database and evidence file and
checks expected claims, attempts, outcomes, heartbeat states and resend probes.

`cleanup` removes only the generated runtime after verifying ownership, path,
run ID and symlink safety. Evidence may first be copied to an operator-selected
owner-only directory.

### 6.4 Provider-separated execution

The harness supports exactly:

```text
--provider history_dispatcher
--provider teebotus
```

There is no implicit `both` mode in version 1. Separate runs reduce accidental
double sends and produce independently reviewable evidence.

A cross-provider comparison command consumes two already completed evidence
files:

```text
python -m history_dispatcher.canary compare \
  --native-evidence native.json \
  --teebotus-evidence teebotus.json
```

`compare` performs no network call. It verifies:

- different run IDs and canary nonce text;
- same contract digest;
- correct immutable provider binding for each run;
- wrong-provider preflight claims returned zero deliveries;
- one successful or explicitly uncertain recipient outcome per provider;
- repeat-worker probe produced zero sends;
- no event or route plan was consumed by both providers.

### 6.5 Native live flow

For `history_dispatcher` the harness:

1. starts an isolated Dispatcher service;
2. seeds exactly one canary event and native route plan;
3. calls the TeeBotus-bound claim preflight and requires zero claims;
4. starts one native worker `run_once()`;
5. records the recipient result and target completion;
6. invokes a second native `run_once()` with a counting client wrapper;
7. requires zero additional network calls;
8. stops the isolated service;
9. writes secret-free evidence.

The real Telegram client is reachable only in step 4 after all confirmation
checks have succeeded.

### 6.6 TeeBotus live flow

For `teebotus` the harness:

1. starts an isolated Dispatcher service;
2. seeds exactly one canary event and TeeBotus route plan;
3. calls the native-bound claim preflight and requires zero claims;
4. invokes a dedicated TeeBotus canary entrypoint against the isolated socket;
5. requires the Provider-v2 callback lifecycle to finish or spool safely;
6. replays any spool without invoking a second send;
7. invokes a second batch poll and requires zero additional sends;
8. stops the isolated service;
9. writes secret-free evidence.

The TeeBotus entrypoint must not use the ordinary production outbox, instance
scheduler or production account scan. It receives exactly one `canary_`
recipient and one isolated socket path from the orchestrator.

## 7. Evidence format

Every completed run writes one canonical JSON object:

```text
schema_version
run_id
provider
contract_id
contract_sha256
history_dispatcher_commit
teebotus_commit
started_at
completed_at
canary_nonce_hash
recipient_profile
credential_profile_configured
wrong_provider_claim_count
claim_count
send_attempt_count
recipient_outcomes
target_state
repeat_probe_send_count
possible_duplicate
cleanup_state
```

Evidence must not contain:

```text
bot token
raw chat ID
Telegram username
raw Telegram message ID
request URL
payload body
Secret-Service output
local home path
socket path
claim token
```

`recipient_profile` is allowed because it is an opaque `canary_` reference.
`credential_profile_configured` is a Boolean only.

The canary text contains:

```text
History-Dispatcher Telegram Canary
provider=<provider>
run=<short opaque run id>
nonce=<short random marker>
```

The nonce is stored in evidence only as SHA-256. This lets the operator visually
match a message while avoiding message content in durable evidence.

## 8. Failure and cleanup semantics

### 8.1 Before Telegram acceptance is possible

Configuration, migration, socket, claim, Secret-Service and pre-connect failures
abort the run as `failed_safe`. No provider fallback occurs.

### 8.2 After Telegram acceptance may have occurred

Any post-connect ambiguity becomes `possible_duplicate`. The harness:

- records the uncertain state;
- does not invoke another send;
- still runs network-free verification;
- retains the isolated database and evidence for operator reconciliation;
- refuses automatic cleanup unless `--acknowledge-possible-duplicate` is given.

### 8.3 Interrupted runs

A run lock contains the run ID, process ID, start time and fingerprint. A second
process cannot reuse the runtime. On restart, the harness supports only:

```text
verify
cleanup
```

It does not resume or repeat a live send automatically.

### 8.4 Cleanup

Automatic cleanup is permitted only for outcomes proven not to require
reconciliation. For `possible_duplicate`, spool recovery failure, or an
incomplete callback, evidence and database remain owner-only until an operator
explicitly acknowledges the state.

## 9. Testing strategy

All automated tests use fake clients, fake Secret-Service stores, fake TeeBotus
senders, temporary SQLite databases, temporary Unix sockets, fake clocks and
injected subprocess runners.

Required History-Dispatcher tests:

- canonical/vendored byte identity and SHA guard;
- strict contract schema and enum validation;
- all eight cases through the complete native Provider-v2 lifecycle;
- canary `plan` never reads secrets or opens an IP socket;
- `run` without every confirmation gate cannot send;
- non-`canary_` profiles are rejected;
- production database/socket paths are rejected;
- wrong-provider preflight claim is empty;
- second worker run produces zero send calls;
- evidence redaction and owner-only permissions;
- possible-duplicate blocks resend and cleanup;
- compare command rejects provider overlap or differing contract digest.

Required TeeBotus tests:

- exact fixture digest and strict schema;
- all eight cases through Provider-v2 worker callbacks;
- callback spool encryption and secret-free metadata;
- reclaim/rebind replay without sender invocation;
- wrong-provider and reconciliation-only claims never enter the send callback;
- dedicated canary entrypoint rejects production scheduler/outbox paths;
- non-`canary_` recipients are rejected;
- repeat batch produces zero sender calls.

No GitHub Actions workflow receives Telegram or Secret-Service credentials. No
CI test performs DNS, HTTPS, Telegram, desktop keyring or production socket
access.

## 10. Repository and pull-request sequence

### PR-HD-17A — canonical contract and native consumer

Repository:

```text
H234598/History-Dispatcher
```

Scope:

- canonical contract, vendored copy and digest;
- strict parser/validator;
- full native lifecycle consumer tests;
- contract documentation;
- no canary live path yet.

### PR-TB-04 — TeeBotus contract sync and consumer

Repository:

```text
H234598/TeeBotus
```

Scope:

- exact contract and digest copy from merged PR-HD-17A;
- strict parser/validator;
- full Provider-v2 callback/spool consumer tests;
- no production mode change and no live send.

### PR-HD-17B — isolated canary orchestrator

Repository:

```text
H234598/History-Dispatcher
```

Scope:

- plan/run/verify/cleanup/compare CLI;
- isolated runtime and database;
- native fake and live-capable path;
- TeeBotus subprocess contract;
- all confirmation, locking, evidence and cleanup rules;
- live mode implemented but never executed by CI.

### PR-TB-05 — dedicated TeeBotus canary entrypoint

Repository:

```text
H234598/TeeBotus
```

Scope:

- one isolated-socket, one-recipient canary entrypoint;
- no account discovery or ordinary scheduler;
- fake-tested only in CI;
- exact request/result protocol consumed by PR-HD-17B.

### Operator gate — live canaries

After all four PRs are merged and their final SHAs are recorded:

1. operator creates dedicated `canary_` Secret-Service and TeeBotus profiles;
2. operator runs `plan` separately for Native and TeeBotus;
3. operator reviews fingerprints and exact message previews;
4. operator executes each provider in a separate confirmed run;
5. operator runs `verify` and `compare`;
6. evidence SHAs are recorded in a docs-only PR;
7. only then may `TG-H-001`, `TG-H-002` and the shared half of `TG-F-002b` be
   closed;
8. Cinnamon provider selection remains blocked until those merge-dependent
   evidence checks are complete.

## 11. Security boundaries

The following are permanent invariants:

- no automatic cross-provider fallback;
- no production DB or production socket in the canary harness;
- no live send without `--apply` and exact fingerprint confirmation;
- no raw secret or chat ID argument;
- no non-`canary_` recipient;
- no CI credentials;
- no environment-variable token fallback;
- no configurable Telegram host, proxy or redirect;
- no automatic retry after an uncertain accept;
- no cleanup of uncertain evidence without explicit acknowledgement;
- no Cinnamon UI activation in these implementation PRs.

## 12. Definition of done

The cross-repository implementation is complete only when:

- both repositories contain the exact same contract bytes and SHA-256 digest;
- all eight cases pass through the full native and TeeBotus provider lifecycles;
- each repository is green in its full test/build gates, qlty and CodeRabbit;
- all review threads are resolved;
- the isolated canary harness and TeeBotus entrypoint are merged;
- live runs are executed manually with dedicated `canary_` profiles;
- each provider produces one expected message or one explicitly reconciled
  uncertain state;
- wrong-provider claims and repeat-worker probes produce zero sends;
- comparison evidence proves no route plan or event was consumed by both
  providers;
- merge SHAs, contract digest and redacted evidence digests are recorded in the
  implementation progress ledger;
- only after that evidence may the Cinnamon provider selector proceed.
