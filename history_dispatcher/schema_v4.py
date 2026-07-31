from __future__ import annotations


DB_SCHEMA_VERSION = 4
SECRET_KINDS = ("bot_token", "chat_id")
V4_TABLES = ("telegram_secret_metadata", "credential_audit")


def _quoted(values: tuple[str, ...]) -> str:
    return ",".join(f"'{value}'" for value in values)


V4_DDL = f"""
CREATE TABLE IF NOT EXISTS telegram_secret_metadata (
    secret_kind TEXT NOT NULL CHECK(secret_kind IN ({_quoted(SECRET_KINDS)})),
    profile_key TEXT NOT NULL,
    configured INTEGER NOT NULL CHECK(configured IN (0,1)),
    last_changed TEXT NOT NULL,
    last_operation TEXT NOT NULL CHECK(last_operation IN ('set','replace','delete')),
    PRIMARY KEY(secret_kind, profile_key)
);
CREATE INDEX IF NOT EXISTS idx_telegram_secret_metadata_changed
    ON telegram_secret_metadata(last_changed, secret_kind);

CREATE TABLE IF NOT EXISTS credential_audit (
    id TEXT PRIMARY KEY,
    actor_key TEXT NOT NULL,
    profile_key TEXT NOT NULL,
    operation TEXT NOT NULL,
    secret_kind TEXT NOT NULL CHECK(secret_kind IN ({_quoted(SECRET_KINDS)})),
    result TEXT NOT NULL,
    reason_code TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_credential_audit_created
    ON credential_audit(created_at, operation);
"""
