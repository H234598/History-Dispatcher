from __future__ import annotations

from .delivery_state import RecipientDeliveryState, TargetDeliveryState


DB_SCHEMA_VERSION = 2
ROUTING_SCHEMA_VERSION = 2
HISTORY_KINDS = (
    "subagent_completion",
    "intermediate_update",
    "task_completion",
    "unknown",
)
CLASSIFICATION_CONFIDENCES = (
    "authoritative",
    "compatible",
    "legacy",
    "ambiguous",
)
TARGET_IDS = ("local_archive", "telegram", "vault", "legacy_unknown")
V2_TABLES = (
    "history_events",
    "route_plans",
    "target_deliveries",
    "recipient_deliveries",
    "delivery_attempts",
    "local_archive_entries",
    "worker_heartbeats",
    "config_audit",
    "migration_journal",
)


def _quoted(values: tuple[str, ...]) -> str:
    return ",".join(f"'{value}'" for value in values)


_TARGET_STATES = tuple(state.value for state in TargetDeliveryState)
_RECIPIENT_STATES = tuple(state.value for state in RecipientDeliveryState)


V2_DDL = f"""
CREATE TABLE IF NOT EXISTS history_events (
    id TEXT PRIMARY KEY,
    legacy_item_id TEXT UNIQUE REFERENCES history_items(id) ON DELETE RESTRICT,
    source TEXT NOT NULL,
    source_instance TEXT NOT NULL DEFAULT '',
    dedupe_key TEXT NOT NULL UNIQUE,
    history_kind TEXT NOT NULL CHECK(history_kind IN ({_quoted(HISTORY_KINDS)})),
    classification_schema_version INTEGER NOT NULL CHECK(classification_schema_version >= 0),
    classification_confidence TEXT NOT NULL CHECK(classification_confidence IN ({_quoted(CLASSIFICATION_CONFIDENCES)})),
    classification_reason_code TEXT NOT NULL DEFAULT '',
    session_key TEXT NOT NULL DEFAULT '',
    turn_key TEXT NOT NULL DEFAULT '',
    parent_thread_key TEXT NOT NULL DEFAULT '',
    project_id TEXT NOT NULL DEFAULT '',
    project_label TEXT NOT NULL DEFAULT '',
    encrypted_payload BLOB NOT NULL,
    payload_hash TEXT NOT NULL,
    operational_state TEXT NOT NULL CHECK(operational_state IN ('ready','legacy_hold','terminal','quarantined')),
    legacy_status TEXT NOT NULL DEFAULT '',
    legacy_hold INTEGER NOT NULL DEFAULT 0 CHECK(legacy_hold IN (0,1)),
    created_at TEXT NOT NULL,
    collected_at TEXT NOT NULL,
    terminal_at TEXT NOT NULL DEFAULT ''
);
CREATE INDEX IF NOT EXISTS idx_history_events_kind_state
    ON history_events(history_kind, operational_state, created_at);
CREATE INDEX IF NOT EXISTS idx_history_events_project
    ON history_events(project_id, created_at);

CREATE TABLE IF NOT EXISTS route_plans (
    id TEXT PRIMARY KEY,
    event_id TEXT NOT NULL REFERENCES history_events(id) ON DELETE CASCADE,
    config_revision TEXT NOT NULL,
    routing_schema_version INTEGER NOT NULL CHECK(routing_schema_version > 0),
    planner_version TEXT NOT NULL,
    plan_hash TEXT NOT NULL UNIQUE,
    plan_state TEXT NOT NULL CHECK(plan_state IN ('active','legacy_migrated','superseded')),
    created_at TEXT NOT NULL,
    UNIQUE(event_id, plan_hash)
);
CREATE INDEX IF NOT EXISTS idx_route_plans_event
    ON route_plans(event_id, created_at);

CREATE TABLE IF NOT EXISTS target_deliveries (
    id TEXT PRIMARY KEY,
    route_plan_id TEXT NOT NULL REFERENCES route_plans(id) ON DELETE CASCADE,
    target_id TEXT NOT NULL CHECK(target_id IN ({_quoted(TARGET_IDS)})),
    state TEXT NOT NULL CHECK(state IN ({_quoted(_TARGET_STATES)})),
    legacy_outcome TEXT NOT NULL DEFAULT '',
    skip_reason TEXT NOT NULL DEFAULT '',
    blocked_reason TEXT NOT NULL DEFAULT '',
    claim_worker_id TEXT NOT NULL DEFAULT '',
    claim_token_hash TEXT NOT NULL DEFAULT '',
    claim_expires_at TEXT NOT NULL DEFAULT '',
    attempt_count INTEGER NOT NULL DEFAULT 0 CHECK(attempt_count >= 0),
    next_attempt_at TEXT NOT NULL DEFAULT '',
    last_error_class TEXT NOT NULL DEFAULT '',
    idempotency_key TEXT NOT NULL UNIQUE,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    terminal_at TEXT NOT NULL DEFAULT '',
    UNIQUE(route_plan_id, target_id)
);
CREATE INDEX IF NOT EXISTS idx_target_deliveries_dispatch
    ON target_deliveries(target_id, state, next_attempt_at, created_at);
CREATE INDEX IF NOT EXISTS idx_target_deliveries_claim
    ON target_deliveries(target_id, claim_expires_at);

CREATE TABLE IF NOT EXISTS recipient_deliveries (
    id TEXT PRIMARY KEY,
    target_delivery_id TEXT NOT NULL REFERENCES target_deliveries(id) ON DELETE CASCADE,
    recipient_key TEXT NOT NULL,
    state TEXT NOT NULL CHECK(state IN ({_quoted(_RECIPIENT_STATES)})),
    legacy_outcome TEXT NOT NULL DEFAULT '',
    external_message_ref_key TEXT NOT NULL DEFAULT '',
    idempotency_key TEXT NOT NULL UNIQUE,
    attempt_count INTEGER NOT NULL DEFAULT 0 CHECK(attempt_count >= 0),
    possible_duplicate INTEGER NOT NULL DEFAULT 0 CHECK(possible_duplicate IN (0,1)),
    last_error_class TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    terminal_at TEXT NOT NULL DEFAULT '',
    UNIQUE(target_delivery_id, recipient_key)
);
CREATE INDEX IF NOT EXISTS idx_recipient_deliveries_state
    ON recipient_deliveries(target_delivery_id, state, updated_at);

CREATE TABLE IF NOT EXISTS delivery_attempts (
    id TEXT PRIMARY KEY,
    target_delivery_id TEXT NOT NULL REFERENCES target_deliveries(id) ON DELETE CASCADE,
    recipient_delivery_id TEXT REFERENCES recipient_deliveries(id) ON DELETE CASCADE,
    worker_id TEXT NOT NULL,
    attempt_no INTEGER NOT NULL CHECK(attempt_no > 0),
    started_at TEXT NOT NULL,
    completed_at TEXT NOT NULL DEFAULT '',
    outcome TEXT NOT NULL DEFAULT '',
    error_class TEXT NOT NULL DEFAULT '',
    retry_after_seconds INTEGER NOT NULL DEFAULT 0 CHECK(retry_after_seconds >= 0),
    UNIQUE(target_delivery_id, recipient_delivery_id, attempt_no)
);
CREATE INDEX IF NOT EXISTS idx_delivery_attempts_target
    ON delivery_attempts(target_delivery_id, started_at);

CREATE TABLE IF NOT EXISTS local_archive_entries (
    event_id TEXT PRIMARY KEY REFERENCES history_events(id) ON DELETE CASCADE,
    archive_schema_version INTEGER NOT NULL CHECK(archive_schema_version > 0),
    encrypted_document BLOB NOT NULL,
    content_hash TEXT NOT NULL,
    created_at TEXT NOT NULL,
    expires_at TEXT NOT NULL DEFAULT ''
);

CREATE TABLE IF NOT EXISTS worker_heartbeats (
    worker_id TEXT PRIMARY KEY,
    target_id TEXT NOT NULL DEFAULT '',
    capability_version TEXT NOT NULL DEFAULT '',
    state TEXT NOT NULL,
    last_heartbeat_at TEXT NOT NULL,
    details_json TEXT NOT NULL DEFAULT '{{}}'
);

CREATE TABLE IF NOT EXISTS config_audit (
    id TEXT PRIMARY KEY,
    actor_key TEXT NOT NULL,
    operation TEXT NOT NULL,
    revision_before TEXT NOT NULL DEFAULT '',
    revision_after TEXT NOT NULL DEFAULT '',
    preview_token_hash TEXT NOT NULL DEFAULT '',
    result TEXT NOT NULL,
    affected_count INTEGER NOT NULL DEFAULT 0 CHECK(affected_count >= 0),
    reason_code TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS migration_journal (
    id TEXT PRIMARY KEY,
    migration_version INTEGER NOT NULL,
    phase TEXT NOT NULL CHECK(phase IN ('planned','applied','verified','failed','restored')),
    source_schema_version INTEGER NOT NULL,
    target_schema_version INTEGER NOT NULL,
    backup_name TEXT NOT NULL DEFAULT '',
    backup_sha256 TEXT NOT NULL DEFAULT '',
    report_json TEXT NOT NULL DEFAULT '{{}}',
    created_at TEXT NOT NULL,
    completed_at TEXT NOT NULL DEFAULT ''
);
CREATE INDEX IF NOT EXISTS idx_migration_journal_version
    ON migration_journal(migration_version, created_at);

CREATE TRIGGER IF NOT EXISTS trg_history_events_immutable_payload
BEFORE UPDATE OF source, source_instance, dedupe_key, history_kind,
    classification_schema_version, classification_confidence,
    classification_reason_code, session_key, turn_key, parent_thread_key,
    project_id, project_label, encrypted_payload, payload_hash, created_at
ON history_events
BEGIN
    SELECT RAISE(ABORT, 'history event immutable fields cannot be changed');
END;

CREATE TRIGGER IF NOT EXISTS trg_route_plans_immutable
BEFORE UPDATE ON route_plans
BEGIN
    SELECT RAISE(ABORT, 'route plans are immutable');
END;

CREATE TRIGGER IF NOT EXISTS trg_target_delivery_state_transition
BEFORE UPDATE OF state ON target_deliveries
WHEN OLD.state <> NEW.state AND NOT (
    (OLD.state='pending' AND NEW.state IN ('claimed','skipped_disabled','skipped_filtered','skipped_unknown','failed_terminal','quarantined','legacy_hold')) OR
    (OLD.state='claimed' AND NEW.state IN ('pending','delivered','partial','failed_retryable','failed_terminal','quarantined')) OR
    (OLD.state='partial' AND NEW.state IN ('delivered','failed_retryable','failed_terminal','quarantined')) OR
    (OLD.state='failed_retryable' AND NEW.state IN ('pending','claimed','failed_terminal','quarantined'))
)
BEGIN
    SELECT RAISE(ABORT, 'invalid target delivery state transition');
END;

CREATE TRIGGER IF NOT EXISTS trg_recipient_delivery_state_transition
BEFORE UPDATE OF state ON recipient_deliveries
WHEN OLD.state <> NEW.state AND NOT (
    (OLD.state='pending' AND NEW.state IN ('claimed','accepted','delivered','acknowledged','failed_retryable','failed_terminal','quarantined','skipped','possible_duplicate','legacy_hold')) OR
    (OLD.state='claimed' AND NEW.state IN ('pending','accepted','delivered','acknowledged','failed_retryable','failed_terminal','quarantined','skipped','possible_duplicate')) OR
    (OLD.state='failed_retryable' AND NEW.state IN ('pending','claimed','failed_terminal','quarantined','possible_duplicate')) OR
    (OLD.state='possible_duplicate' AND NEW.state IN ('accepted','delivered','acknowledged','failed_terminal','quarantined')) OR
    (OLD.state='accepted' AND NEW.state IN ('delivered','acknowledged')) OR
    (OLD.state='delivered' AND NEW.state='acknowledged')
)
BEGIN
    SELECT RAISE(ABORT, 'invalid recipient delivery state transition');
END;
"""
