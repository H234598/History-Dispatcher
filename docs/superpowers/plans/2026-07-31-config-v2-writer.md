# Productive Config v2 Writer Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Persist `routing.telegram.provider`, opaque credential profile names, and opaque recipient profile names through a revisioned, previewed, audited, atomic Config-v2 API without exposing secrets or changing existing route plans.

**Architecture:** Extend the immutable `DispatcherConfig` and strict TOML loader with one nested `[routing.telegram]` section. Add a focused `ConfigManagerV2` that owns patch validation, short-lived one-use previews, compare-and-swap apply, atomic writer invocation, and `config_audit` persistence. Expose additive read/validate/preview operations and route preview-backed requests through the existing idempotent `config.apply`, while preserving the legacy flat safe-values path.

**Tech Stack:** Python 3.13, `tomllib`, frozen dataclasses, SQLite, Unix-socket protocol v1, existing Secret-Service-backed persistent IDs, pytest, GitHub Actions.

## Global Constraints

- Provider values are exactly `teebotus | history_dispatcher`.
- Provider changes affect new route plans only; no existing plan is mutated or replanned.
- Bot tokens and raw chat IDs are never accepted by Config v2.
- Stored native references are opaque profile names only.
- Default provider remains `teebotus`.
- Preview tokens expire after 60 seconds, are one-use, and are never written to TOML or status snapshots.
- Every successful Config-v2 apply requires matching `expected_revision`, patch fingerprint, preview token, and exact confirmation `APPLY <first-12-fingerprint-characters>`.
- Every successful or rejected apply attempt writes a bounded `config_audit` row when schema v2+ is available.
- New Config-v2 operations require a non-empty Request-ID and use the existing durable idempotency store.
- Existing `config.get`, legacy `config.validate`, and legacy flat `config.apply` remain backward compatible.
- No native Secret-Service token write occurs in this plan; that is the next separately reviewed plan.

---

### Task 1: Productive Telegram Routing Config Model and TOML Round Trip

**Files:**
- Modify: `history_dispatcher/config.py`
- Test: `tests/test_config_v2_writer_model.py`

**Interfaces:**
- Consumes: `TelegramDispatchProvider` from `history_dispatcher.telegram_provider`.
- Produces: `DispatcherConfig.telegram_provider: TelegramDispatchProvider`, `telegram_credential_ref: str`, `telegram_recipient_refs: tuple[str, ...]`, and a strict `[routing.telegram]` TOML round trip.

- [ ] **Step 1: Write failing strict-loader and round-trip tests**

```python
from history_dispatcher.config import load_config, write_config
from history_dispatcher.telegram_provider import TelegramDispatchProvider


def test_routing_telegram_round_trip(tmp_path):
    path = tmp_path / "config.toml"
    path.write_text(
        '[routing.telegram]\n'
        'provider = "history_dispatcher"\n'
        'credential_ref = "telegram_primary"\n'
        'recipient_refs = ["status_admin_primary", "ops_admin"]\n',
        encoding="utf-8",
    )
    config = load_config(path)
    assert config.telegram_provider is TelegramDispatchProvider.HISTORY_DISPATCHER
    assert config.telegram_credential_ref == "telegram_primary"
    assert config.telegram_recipient_refs == (
        "status_admin_primary",
        "ops_admin",
    )
    write_config(config)
    assert load_config(path) == config
```

Also test:

```python
@pytest.mark.parametrize(
    "toml",
    [
        '[routing.telegram]\nprovider="automatic"\n',
        '[routing.telegram]\nbot_token="secret"\n',
        '[routing.telegram]\nchat_id="-1001234567890"\n',
        '[routing.telegram]\nrecipient_refs=["-1001234567890"]\n',
        '[routing.telegram]\ncredential_ref="../token"\n',
    ],
)
def test_routing_telegram_rejects_unsafe_values(tmp_path, toml): ...
```

- [ ] **Step 2: Run tests and verify the missing fields/section fail**

Run:

```bash
python -m pytest tests/test_config_v2_writer_model.py -q --tb=short
```

Expected: failures because `DispatcherConfig` and `load_config()` do not yet support `[routing.telegram]`.

- [ ] **Step 3: Implement opaque reference normalization and config fields**

Add focused helpers in `config.py`:

```python
_OPAQUE_PROFILE_RE = re.compile(r"^[a-z][a-z0-9_.-]{0,95}$")


def _opaque_profile(value: object, name: str, *, allow_empty: bool) -> str:
    if value in (None, "") and allow_empty:
        return ""
    if not isinstance(value, str):
        raise ValueError(f"{name} must be an opaque profile name")
    normalized = unicodedata.normalize("NFC", value.strip()).casefold()
    if not _OPAQUE_PROFILE_RE.fullmatch(normalized):
        raise ValueError(f"{name} is invalid")
    return normalized
```

Extend `DispatcherConfig`:

```python
telegram_provider: TelegramDispatchProvider = TelegramDispatchProvider.TEEBOTUS
telegram_credential_ref: str = ""
telegram_recipient_refs: tuple[str, ...] = ()
```

Parse only:

```text
routing.telegram.provider
routing.telegram.credential_ref
routing.telegram.recipient_refs
```

Deduplicate recipient refs in stable order and cap them at 32. Reject numeric chat IDs, token-like values, paths, control characters, unknown fields, and a credential/recipient profile without provider `history_dispatcher`.

- [ ] **Step 4: Extend redacted public config and atomic TOML writer**

`public_config()` must add:

```python
"routing": {
    "telegram": {
        "provider": config.telegram_provider.value,
        "credential_ref": config.telegram_credential_ref,
        "recipient_refs": list(config.telegram_recipient_refs),
    }
}
```

`write_config()` must render:

```toml
[routing.telegram]
provider = "teebotus"
credential_ref = ""
recipient_refs = []
```

The existing temp-file, `fsync`, mode `0600`, backup, and atomic replace behavior remains.

- [ ] **Step 5: Run focused and existing config tests**

```bash
python -m pytest \
  tests/test_config_v2_writer_model.py \
  tests/test_config.py \
  tests/test_config_v2_contract.py \
  tests/test_config_v2_api.py \
  tests/test_config_v2_integration.py \
  -q --tb=short
```

Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add history_dispatcher/config.py tests/test_config_v2_writer_model.py
git commit -m "feat: persist strict Telegram routing config"
```

---

### Task 2: Patch Validation and Canonical Preview Contract

**Files:**
- Create: `history_dispatcher/config_manager_v2.py`
- Modify: `history_dispatcher/config_v2_api.py`
- Test: `tests/test_config_manager_v2_preview.py`

**Interfaces:**
- Consumes: `DispatcherConfig`, `config_revision()`, `apply_safe_values()`, productive Telegram routing fields.
- Produces: `ConfigPatchV2`, `ConfigPreviewV2`, `ConfigManagerV2.get_redacted()`, `validate_patch()`, and `preview_apply()`.

- [ ] **Step 1: Write failing patch and preview tests**

Cover:

```python
patch = {
    "routing": {
        "telegram": {
            "provider": "history_dispatcher",
            "credential_ref": "telegram_primary",
            "recipient_refs": ["status_admin_primary"],
        }
    }
}
validated = manager.validate_patch(patch)
preview = manager.preview_apply(
    expected_revision=current_revision,
    patch=patch,
)
assert preview.effect == "new_route_plans_only"
assert preview.confirmation == f"APPLY {preview.fingerprint[:12]}"
assert preview.token
```

Also assert rejection of:

```text
bot_token
chat_id
secret
unknown nested keys
non-object routing/telegram sections
provider-native fields while provider=teebotus
more than 32 recipients
patches above 64 KiB
non-finite JSON
```

- [ ] **Step 2: Run tests and verify `ConfigManagerV2` is absent**

```bash
python -m pytest tests/test_config_manager_v2_preview.py -q --tb=short
```

Expected: import failure or missing class.

- [ ] **Step 3: Implement canonical typed patch**

Use frozen dataclasses:

```python
@dataclass(frozen=True)
class TelegramPatchV2:
    provider: TelegramDispatchProvider
    credential_ref: str
    recipient_refs: tuple[str, ...]

@dataclass(frozen=True)
class ConfigPatchV2:
    telegram: TelegramPatchV2

    def canonical_dict(self) -> dict[str, object]: ...
    def fingerprint(self, *, expected_revision: str) -> str: ...
```

The fingerprint is SHA-256 over canonical JSON:

```python
{
    "expected_revision": expected_revision,
    "patch": patch.canonical_dict(),
    "schema_version": 2,
}
```

- [ ] **Step 4: Implement in-memory preview registry**

`ConfigManagerV2` receives injectable `clock` and `token_factory`. Store only:

```python
@dataclass(frozen=True)
class _PreviewEntry:
    token_hash: str
    fingerprint: str
    expected_revision: str
    expires_at: float
```

Keep entries keyed by SHA-256 of the token, cap the registry at 128 entries, prune expired entries on every preview/apply, and use a lock.

`preview_apply()` returns a token once and the public preview:

```python
{
    "schema_version": 2,
    "expected_revision": revision,
    "fingerprint": fingerprint,
    "confirmation": f"APPLY {fingerprint[:12]}",
    "effect": "new_route_plans_only",
    "changes": {...},
    "preview_token": token,
    "expires_in_seconds": 60,
}
```

- [ ] **Step 5: Verify deterministic fingerprints and bounded previews**

```bash
python -m pytest tests/test_config_manager_v2_preview.py -q --tb=short
```

Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add history_dispatcher/config_manager_v2.py history_dispatcher/config_v2_api.py tests/test_config_manager_v2_preview.py
git commit -m "feat: add revisioned Config v2 previews"
```

---

### Task 3: Compare-and-Swap Apply, Atomic Write, and Config Audit

**Files:**
- Modify: `history_dispatcher/config_manager_v2.py`
- Test: `tests/test_config_manager_v2_apply.py`

**Interfaces:**
- Consumes: preview registry and typed patch from Task 2, existing `write_config()`.
- Produces: `ConfigManagerV2.apply_preview()` and bounded `config_audit` rows.

- [ ] **Step 1: Write failing apply tests**

Test successful apply:

```python
result = manager.apply_preview(
    expected_revision=revision,
    preview_token=preview.preview_token,
    fingerprint=preview.fingerprint,
    confirmation=preview.confirmation,
    actor="uid:1000",
)
assert result["provider"] == "history_dispatcher"
assert load_config(path).telegram_provider.value == "history_dispatcher"
```

Test failures:

```text
revision changed after preview
fingerprint mismatch
confirmation mismatch
expired token
token replay
unknown token
TOML write failure
post-write reload mismatch
missing config_audit table
```

Verify rejected attempts do not mutate the file. Verify successful apply writes exactly one audit row with operation `config.apply_v2`, revision before/after, preview-token hash, result, affected count, reason code, and UTC timestamp. Verify no token, raw recipient value, or secret-like string appears in the audit row.

- [ ] **Step 2: Run tests and verify apply is missing**

```bash
python -m pytest tests/test_config_manager_v2_apply.py -q --tb=short
```

Expected: failures because `apply_preview()` is not implemented.

- [ ] **Step 3: Implement exact one-use compare-and-swap**

Inside one manager lock:

1. hash and look up the token;
2. remove it before any mutation;
3. verify expiry, expected revision, and fingerprint using `hmac.compare_digest`;
4. require exact confirmation;
5. reload current config from disk and compare `config_revision`;
6. build the candidate frozen config;
7. call the existing atomic writer;
8. reload and verify the expected post-write revision;
9. insert the audit row transactionally.

Use `persistent_opaque_id(key_provider, "config-actor", actor, prefix="actor")` for `actor_key`. Audit `affected_count` is the number of changed leaf fields; no patch values are stored in `config_audit`.

If audit persistence fails after the file replace, restore the existing `.bak` atomically, reload the old config, and raise `ConfigApplyError`. The test must prove file and in-memory config return to the prior revision.

- [ ] **Step 4: Implement bounded audit helper**

Add private methods:

```python
def _audit_apply(
    *,
    actor_key: str,
    revision_before: str,
    revision_after: str,
    preview_token_hash: str,
    result: str,
    affected_count: int,
    reason_code: str,
) -> None: ...
```

Require an existing `config_audit` table; do not auto-migrate a production database from the settings path.

- [ ] **Step 5: Run focused tests**

```bash
python -m pytest \
  tests/test_config_manager_v2_preview.py \
  tests/test_config_manager_v2_apply.py \
  -q --tb=short
```

Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add history_dispatcher/config_manager_v2.py tests/test_config_manager_v2_apply.py
git commit -m "feat: apply Config v2 with audit and rollback"
```

---

### Task 4: Same-User Socket API and Legacy Compatibility

**Files:**
- Modify: `history_dispatcher/service.py`
- Modify: `docs/contracts/control-protocol-v1.md`
- Test: `tests/test_config_service_v2.py`
- Modify: `tests/test_architecture_contract.py`

**Interfaces:**
- Consumes: `ConfigManagerV2` from Tasks 2–3.
- Produces: `config.get_redacted`, `config.validate_patch`, `config.preview_apply`, and preview-backed `config.apply`.

- [ ] **Step 1: Write failing service and socket tests**

Add operations to the expected allowlist and test:

```python
get_response = service.handle(request("config.get_redacted", {}))
validate_response = service.handle(
    request("config.validate_patch", {"patch": patch})
)
preview_response = service.handle(
    request(
        "config.preview_apply",
        {"expected_revision": revision, "patch": patch},
    )
)
apply_response = service.handle(
    request(
        "config.apply",
        {
            "expected_revision": revision,
            "preview_token": preview["preview_token"],
            "fingerprint": preview["fingerprint"],
            "confirmation": preview["confirmation"],
        },
    )
)
```

Verify the same calls through `ControlServer` and `call_socket()`.

Also verify:

- missing Request-ID for new Config-v2 mutations is rejected;
- legacy `config.get`, path-based `config.validate`, and flat `config.apply` still work;
- Config-v2 `config.apply` is request-idempotent;
- preview-token replay under a different Request-ID fails;
- responses and `status-v2.json` contain no `preview_token`, bot token, raw chat ID, or secret field after apply.

- [ ] **Step 2: Run tests and verify operations are absent**

```bash
python -m pytest tests/test_config_service_v2.py -q --tb=short
```

Expected: `unknown_operation` and missing manager failures.

- [ ] **Step 3: Integrate manager lazily**

Add:

```python
CONFIG_V2_MUTATIONS = frozenset(
    {"config.validate_patch", "config.preview_apply"}
)
```

Require Request-ID for preview and apply. `config.get_redacted` remains read-only. Instantiate `ConfigManagerV2` lazily with the current `config`, database path, and key provider.

`config.apply` behavior:

```python
if "preview_token" in body:
    result = manager.apply_preview(...)
    self.config = load_config(self.config.config_path)
    self._config_v2_manager.replace_config(self.config)
    return result
# otherwise preserve the existing legacy flat safe-values path
```

- [ ] **Step 4: Update protocol contract and architecture allowlist**

Document the additive operations, one-use preview rules, exact confirmation, new-route-plans-only effect, and absence of credentials.

- [ ] **Step 5: Run service, architecture, and snapshot tests**

```bash
python -m pytest \
  tests/test_config_service_v2.py \
  tests/test_architecture_contract.py \
  tests/test_status_service_v2.py \
  -q --tb=short
```

Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add history_dispatcher/service.py docs/contracts/control-protocol-v1.md tests/test_config_service_v2.py tests/test_architecture_contract.py
git commit -m "feat: expose staged Config v2 socket API"
```

---

### Task 5: Documentation, Plan Tracking, and Full Verification

**Files:**
- Modify: `docs/config-v2-api.md`
- Modify: `docs/implementation-progress.md`
- Modify: `docs/implementation-plan-addendum-telegram.md`
- Modify: `README.md`
- Test: all tests

**Interfaces:**
- Consumes: completed Config-v2 writer/API.
- Produces: accurate operator contract and next-step boundary for write-only credentials.

- [ ] **Step 1: Update documentation**

Record:

- actual `[routing.telegram]` TOML fields;
- exact API request/response sequence;
- one-use preview token and confirmation syntax;
- audit/rollback behavior;
- backward-compatible legacy operations;
- new-route-plans-only effect;
- deliberate absence of actual bot-token writes;
- next slice: native credential provider and write-only Secret-Service operations.

- [ ] **Step 2: Run complete verification**

```bash
python -m compileall -q history_dispatcher scripts tests
python -m pytest -q
python -m build
```

Expected: all commands exit 0.

- [ ] **Step 3: Inspect leak boundary**

```bash
grep -RInE 'bot_token|chat_id|123456789:|-1001234567890' \
  config.example.toml docs tests/fixtures history_dispatcher \
  --exclude='test_*'
```

Expected: no production Config-v2 field or fixture exposes a token or raw chat ID; any documentation mentions are negative security statements only.

- [ ] **Step 4: Update plan checkboxes only with evidence**

Mark productive Config-v2 persistence, preview/apply, audit, and API complete. Keep `TG-D-002` unchecked because Secret-Service write-only credential operations are intentionally the next plan.

- [ ] **Step 5: Commit**

```bash
git add README.md docs
git commit -m "docs: complete productive Config v2 writer"
```

- [ ] **Step 6: Open PR and enforce gates**

Create a draft PR titled:

```text
feat: add productive Config v2 writer
```

Require GitHub Actions, qlty, CodeRabbit, and zero unresolved review threads before marking ready and squash-merging against the exact final Head SHA.
