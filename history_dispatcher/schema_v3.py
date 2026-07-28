from __future__ import annotations


DB_SCHEMA_VERSION = 3
ROUTING_SCHEMA_VERSION = 3
PROVIDER_IDS = (
    "local_archive",
    "vault",
    "teebotus",
    "history_dispatcher",
    "legacy_unknown",
)
V3_TABLES = (
    "target_delivery_bindings",
    "recipient_delivery_bindings",
)


def _quoted(values: tuple[str, ...]) -> str:
    return ",".join(f"'{value}'" for value in values)


V3_DDL = f"""
CREATE TABLE IF NOT EXISTS target_delivery_bindings (
    target_delivery_id TEXT PRIMARY KEY
        REFERENCES target_deliveries(id) ON DELETE CASCADE,
    provider_id TEXT NOT NULL
        CHECK(provider_id IN ({_quoted(PROVIDER_IDS)})),
    provider_schema_version INTEGER NOT NULL
        CHECK(provider_schema_version >= 0),
    binding_json TEXT NOT NULL,
    binding_hash TEXT NOT NULL,
    created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_target_delivery_bindings_provider
    ON target_delivery_bindings(provider_id, created_at);

CREATE TABLE IF NOT EXISTS recipient_delivery_bindings (
    recipient_delivery_id TEXT PRIMARY KEY
        REFERENCES recipient_deliveries(id) ON DELETE CASCADE,
    target_delivery_id TEXT NOT NULL
        REFERENCES target_deliveries(id) ON DELETE CASCADE,
    recipient_ref TEXT NOT NULL,
    recipient_ref_hash TEXT NOT NULL,
    created_at TEXT NOT NULL,
    UNIQUE(target_delivery_id, recipient_ref)
);
CREATE INDEX IF NOT EXISTS idx_recipient_delivery_bindings_target
    ON recipient_delivery_bindings(target_delivery_id, created_at);

CREATE TRIGGER IF NOT EXISTS trg_target_delivery_bindings_immutable
BEFORE UPDATE ON target_delivery_bindings
BEGIN
    SELECT RAISE(ABORT, 'target delivery bindings are immutable');
END;

CREATE TRIGGER IF NOT EXISTS trg_recipient_delivery_bindings_immutable
BEFORE UPDATE ON recipient_delivery_bindings
BEGIN
    SELECT RAISE(ABORT, 'recipient delivery bindings are immutable');
END;

CREATE TRIGGER IF NOT EXISTS trg_recipient_binding_target_match
BEFORE INSERT ON recipient_delivery_bindings
WHEN NOT EXISTS (
    SELECT 1 FROM recipient_deliveries rd
    WHERE rd.id=NEW.recipient_delivery_id
      AND rd.target_delivery_id=NEW.target_delivery_id
)
BEGIN
    SELECT RAISE(ABORT, 'recipient binding does not belong to target delivery');
END;

DROP TRIGGER IF EXISTS trg_target_delivery_state_transition;
CREATE TRIGGER trg_target_delivery_state_transition
BEFORE UPDATE OF state ON target_deliveries
WHEN OLD.state <> NEW.state AND NOT (
    (OLD.state='pending' AND NEW.state IN (
        'claimed','skipped_disabled','skipped_filtered','skipped_unknown',
        'failed_terminal','quarantined','legacy_hold'
    )) OR
    (OLD.state='claimed' AND NEW.state IN (
        'pending','delivered','partial','failed_retryable','failed_terminal',
        'quarantined','skipped_disabled','skipped_filtered','skipped_unknown'
    )) OR
    (OLD.state='partial' AND NEW.state IN (
        'claimed','delivered','failed_retryable','failed_terminal','quarantined'
    )) OR
    (OLD.state='failed_retryable' AND NEW.state IN (
        'pending','claimed','failed_terminal','quarantined'
    ))
)
BEGIN
    SELECT RAISE(ABORT, 'invalid target delivery state transition');
END;

DROP TRIGGER IF EXISTS trg_recipient_delivery_state_transition;
CREATE TRIGGER trg_recipient_delivery_state_transition
BEFORE UPDATE OF state ON recipient_deliveries
WHEN OLD.state <> NEW.state AND NOT (
    (OLD.state='pending' AND NEW.state IN (
        'claimed','accepted','delivered','acknowledged','failed_retryable',
        'failed_terminal','quarantined','skipped','possible_duplicate','legacy_hold'
    )) OR
    (OLD.state='claimed' AND NEW.state IN (
        'pending','accepted','delivered','acknowledged','failed_retryable',
        'failed_terminal','quarantined','skipped','possible_duplicate'
    )) OR
    (OLD.state='failed_retryable' AND NEW.state IN (
        'pending','claimed','accepted','delivered','acknowledged',
        'failed_terminal','quarantined','skipped','possible_duplicate'
    )) OR
    (OLD.state='possible_duplicate' AND NEW.state IN (
        'accepted','delivered','acknowledged','failed_terminal','quarantined'
    )) OR
    (OLD.state='accepted' AND NEW.state IN ('delivered','acknowledged')) OR
    (OLD.state='delivered' AND NEW.state='acknowledged') OR
    (OLD.state IN ('failed_terminal','quarantined','skipped','legacy_hold')
        AND NEW.state IN ('accepted','delivered','acknowledged'))
)
BEGIN
    SELECT RAISE(ABORT, 'invalid recipient delivery state transition');
END;

CREATE TRIGGER IF NOT EXISTS trg_target_delivery_claim_fields_insert
BEFORE INSERT ON target_deliveries
WHEN (
    NEW.state='claimed' AND (
        NEW.claim_worker_id='' OR NEW.claim_token_hash='' OR
        NEW.claim_expires_at=''
    )
) OR (
    NEW.state<>'claimed' AND (
        NEW.claim_worker_id<>'' OR NEW.claim_token_hash<>'' OR
        NEW.claim_expires_at<>''
    )
)
BEGIN
    SELECT RAISE(ABORT, 'target delivery claim fields do not match state');
END;

CREATE TRIGGER IF NOT EXISTS trg_target_delivery_claim_fields_update
BEFORE UPDATE OF state, claim_worker_id, claim_token_hash, claim_expires_at
ON target_deliveries
WHEN (
    NEW.state='claimed' AND (
        NEW.claim_worker_id='' OR NEW.claim_token_hash='' OR
        NEW.claim_expires_at=''
    )
) OR (
    NEW.state<>'claimed' AND (
        NEW.claim_worker_id<>'' OR NEW.claim_token_hash<>'' OR
        NEW.claim_expires_at<>''
    )
)
BEGIN
    SELECT RAISE(ABORT, 'target delivery claim fields do not match state');
END;
"""
