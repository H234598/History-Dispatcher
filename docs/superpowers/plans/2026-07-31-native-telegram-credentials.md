---
title: Native Telegram Credentials Implementation Plan
tags:
  - history-dispatcher
  - telegram
  - credentials
  - secret-service
  - tdd
type: implementation-plan
status: active
created: 2026-07-31
date: 2026-07-31
aliases:
  - Native Credentials Plan
  - Telegram Secret-Service Plan
---

# Native Telegram Credentials Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [x]`) syntax for tracking.

**Goal:** Add a write-only native Telegram Secret-Service boundary for bot-token and recipient-chat-ID profiles, with explicit schema migration, preview/apply authorization, secret-free status and full rollback, without sending a Telegram request.

**Architecture:** Secret values live exclusively in Secret Service under opaque Config-v2 profile names. Additive schema v4 stores only HMAC-pseudonymized metadata and credential audit rows. A focused credential manager owns bounded one-use previews, write-only mutations and compensation across Secret Service and SQLite; the Same-User socket exposes status, preview and apply while never returning a secret.

**Tech Stack:** Python 3.13, `secret-tool`, `subprocess`, SQLite, frozen dataclasses, existing HMAC identifiers, Unix-socket protocol v1, pytest, GitHub Actions.

## Global Constraints

- No Telegram network request is made in this plan.
- No bot token or raw chat ID is stored in TOML, SQLite, status, snapshot, audit, log, argv or environment.
- Secret Service has no file, environment or random-key fallback.
- Bot-token attributes are `application=history-dispatcher`, `purpose=telegram-bot-token`, `profile=<opaque profile>`.
- Chat-ID attributes are `application=history-dispatcher`, `purpose=telegram-chat-id`, `profile=<opaque profile>`.
- Public APIs never expose an internal secret lookup result.
- Mutating credential operations require a non-empty Request-ID.
- Preview tokens expire after 60 seconds, are one-use and are never persisted in an idempotency response.
- Apply responses are secret-free and durably request-idempotent.
- Schema migration is explicit and dry-run by default; settings requests never auto-migrate.
- A failed metadata/audit commit restores the previous Secret-Service value; rollback failure is terminal.
- Existing Config-v2, Provider-v2, status-v1/v2 and legacy Config operations remain compatible.

---

### Task 1: Additive Credential Metadata Schema v4

**Files:**
- Create: `history_dispatcher/schema_v4.py`
- Create: `history_dispatcher/migrations/v4.py`
- Modify: `history_dispatcher/migrations/__init__.py`
- Create: `history_dispatcher/credential_migration_cli.py`
- Create: `scripts/migrate_credentials_v4.py`
- Test: `tests/test_migration_v4.py`
- Test: `tests/test_credential_migration_cli.py`

**Interfaces:**
- Consumes: `verify_database_v3()`, v2 backup helpers and `SecretServiceKeyProvider`.
- Produces: `DatabaseV4Migrator`, `MigrationV4Report`, `verify_database_v4()` and schema tables `telegram_secret_metadata`, `credential_audit`.

- [x] **Step 1: Write failing schema-v4 tests**

Create v3 fixtures and assert a write-free dry run reports:

```python
report = DatabaseV4Migrator(
    database,
    key_provider,
    backup_dir=tmp_path / "backups-v4",
).migrate(dry_run=True)
assert report.target_schema_version == 4
assert report.metadata_rows == 0
assert report.audit_rows == 0
assert not (tmp_path / "backups-v4").exists()
```

The real apply must create exactly:

```sql
CREATE TABLE telegram_secret_metadata (
    secret_kind TEXT NOT NULL CHECK(secret_kind IN ('bot_token','chat_id')),
    profile_key TEXT NOT NULL,
    configured INTEGER NOT NULL CHECK(configured IN (0,1)),
    last_changed TEXT NOT NULL,
    last_operation TEXT NOT NULL CHECK(last_operation IN ('set','replace','delete')),
    PRIMARY KEY(secret_kind, profile_key)
);

CREATE TABLE credential_audit (
    id TEXT PRIMARY KEY,
    actor_key TEXT NOT NULL,
    profile_key TEXT NOT NULL,
    operation TEXT NOT NULL,
    secret_kind TEXT NOT NULL CHECK(secret_kind IN ('bot_token','chat_id')),
    result TEXT NOT NULL,
    reason_code TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL
);
```

Also test backup mode `0600`, directory mode `0700`, active-claim rejection, idempotent second run, trigger/constraint enforcement, `quick_check`, foreign keys and no secret columns.

- [x] **Step 2: Run the focused migration tests**

```bash
python -m pytest tests/test_migration_v4.py tests/test_credential_migration_cli.py -q --tb=short
```

Expected: import failure because schema v4 and its CLI do not exist.

- [x] **Step 3: Implement schema and explicit migrator**

Set:

```python
DB_SCHEMA_VERSION = 4
V4_TABLES = ("telegram_secret_metadata", "credential_audit")
```

Require complete v3 verification and no active v1 or target-specific claims. Use the existing owner/symlink/integrity helpers, online backup and one `BEGIN IMMEDIATE` transaction. Insert only schema migration metadata; never inspect or create a secret.

- [x] **Step 4: Implement dry-run-by-default CLI**

Commands:

```text
preflight
migrate
verify
```

A real write requires:

```text
--apply --confirm MIGRATE-CREDENTIALS-V4
```

Emit compact finite JSON only.

- [x] **Step 5: Run migration and regression tests**

```bash
python -m pytest \
  tests/test_migration_v4.py \
  tests/test_credential_migration_cli.py \
  tests/test_migration_v3.py \
  -q --tb=short
```

Expected: PASS.

- [x] **Step 6: Commit**

```bash
git add history_dispatcher/schema_v4.py history_dispatcher/migrations \
  history_dispatcher/credential_migration_cli.py \
  scripts/migrate_credentials_v4.py tests/test_migration_v4.py \
  tests/test_credential_migration_cli.py
git commit -m "feat: add credential metadata schema v4"
```

---

### Task 2: Strict Secret-Service Telegram Store

**Files:**
- Create: `history_dispatcher/telegram_secrets.py`
- Test: `tests/test_telegram_secrets.py`

**Interfaces:**
- Produces: `TelegramSecretKind`, `TelegramSecretError`, `TelegramSecretBackend`, `SecretToolTelegramBackend` and `NativeTelegramSecretStore`.
- Internal lookup methods are consumed only by Task 3 and the later native worker.

- [x] **Step 1: Write failing validation and subprocess-boundary tests**

Test valid examples:

```python
store.validate_bot_token("123456789:ABCDEFGHIJKLMNOPQRSTUVWXYZabcdef")
store.validate_chat_id("-1001234567890")
```

Test rejection of whitespace, controls, malformed tokens, overlong values,
non-decimal chat IDs and empty profiles.

With an injected runner, assert `secret-tool store` argv contains only:

```text
secret-tool store --label=History-Dispatcher Telegram bot token
application history-dispatcher purpose telegram-bot-token profile telegram_primary
```

and the token appears only in `input`. Similarly assert `clear` and `lookup`
attributes for both secret kinds. Failed stdout/stderr must not appear in raised
messages.

- [x] **Step 2: Run tests and observe missing module**

```bash
python -m pytest tests/test_telegram_secrets.py -q --tb=short
```

Expected: module import failure.

- [x] **Step 3: Implement typed secret backend**

Define:

```python
class TelegramSecretKind(str, Enum):
    BOT_TOKEN = "bot_token"
    CHAT_ID = "chat_id"

class TelegramSecretBackend(Protocol):
    def lookup(self, kind: TelegramSecretKind, profile_ref: str) -> str | None: ...
    def store(self, kind: TelegramSecretKind, profile_ref: str, value: str) -> None: ...
    def clear(self, kind: TelegramSecretKind, profile_ref: str) -> bool: ...
```

`SecretToolTelegramBackend` uses `subprocess.run(check=False, capture_output=True, timeout=5)` and passes store values through `input=value.encode("utf-8")`. It never includes a value in argv or an exception.

- [x] **Step 4: Implement native internal store**

`NativeTelegramSecretStore` normalizes profiles with the existing Config-v2 opaque-profile helper and exposes:

```python
lookup_bot_token(profile_ref: str) -> str
lookup_chat_id(profile_ref: str) -> str
store_bot_token(profile_ref: str, token: str) -> None
store_chat_id(profile_ref: str, chat_id: str) -> None
clear_bot_token(profile_ref: str) -> bool
clear_chat_id(profile_ref: str) -> bool
```

Lookup raises `TelegramSecretError("... is unavailable")` without value or backend stderr.

- [x] **Step 5: Run tests**

```bash
python -m pytest tests/test_telegram_secrets.py -q --tb=short
```

Expected: PASS.

- [x] **Step 6: Commit**

```bash
git add history_dispatcher/telegram_secrets.py tests/test_telegram_secrets.py
git commit -m "feat: add strict Telegram Secret-Service store"
```

---

### Task 3: Credential Preview, Apply, Metadata and Compensation

**Files:**
- Create: `history_dispatcher/credential_manager.py`
- Test: `tests/test_credential_manager_preview.py`
- Test: `tests/test_credential_manager_apply.py`

**Interfaces:**
- Consumes: `NativeTelegramSecretStore`, schema-v4 metadata/audit, existing HMAC identifiers and Config-v2 profile authorization.
- Produces: `CredentialManager`, `CredentialPreview`, `CredentialApplyError`, `get_status()`, `preview_apply()` and `apply_preview()`.

- [x] **Step 1: Write failing preview tests**

Preview input:

```python
preview = manager.preview_apply(
    action="set",
    secret_kind="bot_token",
    profile_ref="telegram_primary",
    secret_value="123456789:ABCDEFGHIJKLMNOPQRSTUVWXYZabcdef",
)
assert preview.confirmation == (
    f"CREDENTIAL SET {preview.fingerprint[:12]}"
)
```

Test set/replace require a value, delete forbids a value, kind/profile must be currently authorized by Config v2, token/chat-ID values are validated, preview expires after 60 seconds, registry is capped at 128 and no secret is returned or stored in SQLite.

- [x] **Step 2: Run preview tests**

```bash
python -m pytest tests/test_credential_manager_preview.py -q --tb=short
```

Expected: missing `CredentialManager`.

- [x] **Step 3: Implement bounded in-memory previews**

Use a frozen entry containing action, kind, HMAC-pseudonymized profile key, raw profile for backend attributes, secret value only in memory, fingerprint, token hash and expiry. Fingerprint canonical JSON includes action/kind/profile and an HMAC of the secret value derived from the payload key; the HMAC is not returned separately.

- [x] **Step 4: Write failing apply/compensation tests**

Cover:

```text
set absent bot token
replace existing bot token
delete existing token
set and delete chat ID
expired/unknown/replayed preview
fingerprint/confirmation mismatch
profile no longer configured
Secret Service store/clear/lookup failure
metadata transaction failure restores old secret
rollback failure is terminal
successful apply writes metadata and one bounded audit row
identical Request-ID replay is handled later by service without second secret mutation
```

Assert database bytes never contain token, chat ID, raw profile or preview token.

- [x] **Step 5: Implement compensated apply**

Inside one manager lock:

1. consume preview;
2. verify expiry, fingerprint and exact confirmation with constant-time compare;
3. reload Config v2 and reauthorize profile/kind;
4. internally read the previous value;
5. perform store or clear;
6. for set/replace, lookup and constant-time verify the written value;
7. upsert metadata plus credential audit in one SQLite transaction;
8. on DB failure restore the previous value or clear the new value;
9. record a bounded rollback audit when possible;
10. raise `credential_rollback_failed` if compensation fails.

Public result:

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

- [x] **Step 6: Implement metadata status**

`get_status(config)` returns only the configured bot profile and currently configured recipient profiles. Missing rows return `configured=false`, `last_changed=null`. Never call internal secret lookup from the public status method.

- [x] **Step 7: Run focused tests**

```bash
python -m pytest \
  tests/test_credential_manager_preview.py \
  tests/test_credential_manager_apply.py \
  -q --tb=short
```

Expected: PASS.

- [x] **Step 8: Commit**

```bash
git add history_dispatcher/credential_manager.py \
  tests/test_credential_manager_preview.py tests/test_credential_manager_apply.py
git commit -m "feat: add compensated Telegram credential manager"
```

---

### Task 4: Same-User Credential API and Status Integration

**Files:**
- Modify: `history_dispatcher/service.py`
- Modify: `history_dispatcher/status_v2.py`
- Modify: `history_dispatcher/status_runtime_v2.py`
- Test: `tests/test_credential_service.py`
- Modify: `tests/test_architecture_contract.py`
- Modify: `tests/test_status_service_v2.py`

**Interfaces:**
- Produces operations `credential.get_status`, `credential.preview_apply`, `credential.apply`.
- Consumes `CredentialManager` and exposes no secret lookup method.

- [x] **Step 1: Write failing service/socket tests**

Test direct service and `ControlServer` flows:

```text
credential.get_status
credential.preview_apply
credential.apply
```

Verify:

- read-only status needs no Request-ID;
- preview/apply require Request-ID;
- preview response is one-shot and not cached;
- pure validation failure releases its exact reservation;
- apply response is durably replayable;
- consumed preview under another Request-ID fails;
- responses, status-v2 snapshot, TOML, SQLite and service error text contain no token or chat ID;
- legacy Config and Provider-v2 operations remain green.

- [x] **Step 2: Run tests and observe unknown operations**

```bash
python -m pytest tests/test_credential_service.py -q --tb=short
```

Expected: `unknown_operation` failures.

- [x] **Step 3: Integrate manager lazily**

Add operations:

```text
credential.get_status
credential.preview_apply
credential.apply
```

`credential.preview_apply` joins the sensitive one-shot set. `credential.apply` is a durable idempotent mutation. Validation errors release only the exact empty preview reservation.

The service creates `CredentialManager` lazily with current Config v2, schema-v4 database, payload key provider and `NativeTelegramSecretStore`.

- [x] **Step 4: Integrate status v2**

Populate the existing bot credential block from metadata for the current `credential_ref`. Preserve exactly:

```json
{"configured": true, "last_changed": "timestamp"}
```

Do not add recipient details or secret kinds to the public status snapshot.

- [x] **Step 5: Run service and regression tests**

```bash
python -m pytest \
  tests/test_credential_service.py \
  tests/test_status_service_v2.py \
  tests/test_architecture_contract.py \
  tests/test_config_service_v2.py \
  tests/test_provider_api_v2.py \
  -q --tb=short
```

Expected: PASS.

- [x] **Step 6: Commit**

```bash
git add history_dispatcher/service.py history_dispatcher/status_v2.py \
  history_dispatcher/status_runtime_v2.py tests/test_credential_service.py \
  tests/test_status_service_v2.py tests/test_architecture_contract.py
git commit -m "feat: expose write-only Telegram credential API"
```

---

### Task 5: Contracts, Plan Tracking and Full Verification

**Files:**
- Create: `docs/native-telegram-credentials.md`
- Modify: `docs/contracts/control-protocol-v1.md`
- Modify: `docs/implementation-progress.md`
- Modify: `docs/implementation-plan-addendum-telegram.md`
- Modify: `README.md`
- Test: complete repository

**Interfaces:**
- Consumes completed schema, store, manager and socket API.
- Produces the operator contract and exact boundary before the native network worker.

- [x] **Step 1: Document migration and credential operations**

Document schema-v4 dry run/apply/verify commands, Secret-Service attributes, preview/apply bodies, one-shot behavior, compensation, public status and deliberate absence of network validation.

- [x] **Step 2: Run full verification**

```bash
python -m compileall -q history_dispatcher scripts tests
python -m pytest -q
python -m build
```

Expected: all exit 0.

- [x] **Step 3: Inspect leak boundary**

Verify no production Config, schema, snapshot, audit fixture or log contains a token/chat-ID example outside negative tests and security prose. Inspect `git diff --check` and the full PR diff.

- [x] **Step 4: Update plan evidence**

Mark `TG-D-002` complete only after write-only API, status, migration, compensation and leak tests are green. Keep native Bot API, network test and worker checkboxes open.

- [x] **Step 5: Commit documentation**

```bash
git add README.md docs
git commit -m "docs: complete native Telegram credential boundary"
```

- [ ] **Step 6: Enforce merge gates**

Open or update the draft PR. Require GitHub Actions, qlty, CodeRabbit and zero unresolved review threads on the exact final Head SHA before marking ready and squash-merging.
