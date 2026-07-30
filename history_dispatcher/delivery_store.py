from __future__ import annotations

import hashlib
import hmac
import json
import math
import re
import secrets
import sqlite3
import unicodedata
from collections.abc import Callable, Iterable, Mapping
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Iterator

from .classification_types import ClassifiedEvent
from .crypto import SecretServiceKeyProvider, decrypt_json, encrypt_json
from .delivery_state import TargetDeliveryState, target_state_is_terminal
from .identifiers import persistent_opaque_id
from .migrations.v3 import verify_database_v3
from .redaction import redact_text
from .routing import RoutePlan, RouteTargetDecision
from .schema_v3 import PROVIDER_IDS
from .telegram_provider import (
    MAX_NATIVE_RECIPIENT_REFS,
    TEEBOTUS_CAPABILITY_V2,
    TelegramDispatchProvider,
    TelegramRecipientOutcome,
    merge_recipient_outcomes,
)


NATIVE_TELEGRAM_CAPABILITY_V1 = "history-dispatcher-telegram-native-v1"
LOCAL_ARCHIVE_CAPABILITY_V1 = "history-dispatcher-local-archive-v1"
VAULT_CAPABILITY_V1 = "history-dispatcher-vault-v1"
MAX_CLAIM_BATCH = 100
MAX_HEARTBEAT_DETAILS_BYTES = 4096
_SUCCESS_RECIPIENT_STATES = frozenset({"accepted", "delivered", "acknowledged"})
_TERMINAL_RECIPIENT_STATES = frozenset(
    {
        "accepted",
        "delivered",
        "acknowledged",
        "failed_terminal",
        "quarantined",
        "skipped",
        "legacy_hold",
    }
)
_IDENTIFIER_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}$")
_REASON_RE = re.compile(r"^[a-z][a-z0-9_]{0,95}$")


class DeliveryStoreError(RuntimeError):
    pass


class DeliverySchemaUnavailable(DeliveryStoreError):
    pass


class DeliveryClaimRejected(DeliveryStoreError):
    pass


class DeliveryIdempotencyConflict(DeliveryStoreError):
    pass


@dataclass(frozen=True)
class TargetDeliveryClaim:
    target_delivery_id: str
    route_plan_id: str
    event_id: str
    target_id: str
    provider_id: str
    provider_schema_version: int
    binding: Mapping[str, Any]
    attempt_no: int
    worker_id: str
    capability_version: str
    claim_token: str
    claim_expires_at: str
    payload: Mapping[str, Any]
    successful_recipient_refs: tuple[str, ...]
    open_recipient_refs: tuple[str, ...]


@dataclass(frozen=True)
class RecipientDeliverySnapshot:
    recipient_delivery_id: str
    recipient_ref: str
    state: str
    possible_duplicate: bool
    message_ref_key: str
    last_error_class: str
    attempt_count: int


@dataclass(frozen=True)
class EventDeliverySummary:
    event_id: str
    aggregate_state: str
    operational_state: str
    counts: Mapping[str, int]


class DeliveryStore:
    def __init__(
        self,
        database_path: Path,
        key_provider: SecretServiceKeyProvider,
        *,
        clock: Callable[[], datetime] | None = None,
        token_factory: Callable[[], str] | None = None,
    ) -> None:
        self.database_path = Path(database_path).expanduser().absolute()
        self.key_provider = key_provider
        self._clock = clock or (lambda: datetime.now(timezone.utc))
        self._token_factory = token_factory or (lambda: secrets.token_urlsafe(32))
        verification = verify_database_v3(self.database_path)
        if not verification["ok"]:
            raise DeliverySchemaUnavailable(
                "database must pass schema-v3 verification before delivery access"
            )

    @contextmanager
    def _db(self) -> Iterator[sqlite3.Connection]:
        connection = sqlite3.connect(
            self.database_path,
            timeout=30,
            isolation_level=None,
            check_same_thread=False,
        )
        try:
            connection.row_factory = sqlite3.Row
            connection.execute("PRAGMA foreign_keys=ON")
            connection.execute("PRAGMA busy_timeout=30000")
            yield connection
        finally:
            connection.close()

    def _now(self) -> datetime:
        value = self._clock()
        if value.tzinfo is None:
            value = value.replace(tzinfo=timezone.utc)
        return value.astimezone(timezone.utc)

    @staticmethod
    def _format_time(value: datetime) -> str:
        return value.astimezone(timezone.utc).isoformat(timespec="seconds")

    @staticmethod
    def _parse_time(value: str) -> datetime:
        try:
            parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        except ValueError as exc:
            raise DeliveryStoreError("stored timestamp is invalid") from exc
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        return parsed.astimezone(timezone.utc)

    @staticmethod
    def _canonical_json(value: object) -> str:
        return json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        )

    @staticmethod
    def _normalize_identifier(value: Any, *, field: str) -> str:
        if not isinstance(value, str):
            raise DeliveryStoreError(f"{field} must be a string")
        normalized = unicodedata.normalize("NFC", value.strip())
        if not _IDENTIFIER_RE.fullmatch(normalized):
            raise DeliveryStoreError(f"{field} is invalid")
        return normalized

    @staticmethod
    def _normalize_reason(value: Any, *, field: str = "reason_code") -> str:
        if value in (None, ""):
            return ""
        normalized = unicodedata.normalize("NFC", str(value).strip()).casefold()
        if not _REASON_RE.fullmatch(normalized):
            raise DeliveryStoreError(f"{field} is invalid")
        return normalized

    @staticmethod
    def _normalize_recipient_ref(value: Any) -> str:
        if not isinstance(value, str):
            raise DeliveryStoreError("recipient_ref must be a string")
        return TelegramRecipientOutcome(
            recipient_ref=value,
            status="failed",
        ).recipient_ref

    @staticmethod
    def _claim_token_hash(token: str) -> str:
        return hashlib.sha256(token.encode("utf-8")).hexdigest()

    @staticmethod
    def _required_capability(
        provider_id: str,
        binding: Mapping[str, Any],
    ) -> str:
        if provider_id == "teebotus":
            capability = str(binding.get("bridge_capability") or "")
            return capability or TEEBOTUS_CAPABILITY_V2
        if provider_id == "history_dispatcher":
            return NATIVE_TELEGRAM_CAPABILITY_V1
        if provider_id == "local_archive":
            return LOCAL_ARCHIVE_CAPABILITY_V1
        if provider_id == "vault":
            return VAULT_CAPABILITY_V1
        return ""

    def append_classified_event(self, event: ClassifiedEvent) -> str:
        payload_text = self._canonical_json(event.as_dict())
        payload = payload_text.encode("utf-8")
        payload_hash = hashlib.sha256(payload).hexdigest()
        encrypted = encrypt_json(
            payload,
            self.key_provider,
            aad=event.event_id.encode("utf-8"),
        )
        now = self._format_time(self._now())
        created_at = str(event.timestamp or now)
        with self._db() as db:
            try:
                db.execute("BEGIN IMMEDIATE")
                db.execute(
                    "INSERT INTO history_events("
                    "id,legacy_item_id,source,source_instance,dedupe_key,history_kind,"
                    "classification_schema_version,classification_confidence,"
                    "classification_reason_code,session_key,turn_key,parent_thread_key,"
                    "project_id,project_label,encrypted_payload,payload_hash,"
                    "operational_state,legacy_status,legacy_hold,created_at,collected_at,"
                    "terminal_at"
                    ") VALUES (?,NULL,?,?,?,?,?,?,?,?,?,?,?,?,?,?,'ready','',0,?,?,'')",
                    (
                        event.event_id,
                        event.source_schema_family,
                        event.source_schema_family,
                        event.dedupe_key,
                        event.history_kind.value,
                        event.classification_schema_version,
                        event.confidence.value,
                        event.reason_code,
                        event.session_key,
                        event.turn_key,
                        event.parent_thread_key,
                        event.project_id,
                        event.project_label,
                        encrypted,
                        payload_hash,
                        created_at,
                        now,
                    ),
                )
                db.commit()
                return event.event_id
            except sqlite3.IntegrityError as exc:
                db.rollback()
                existing = db.execute(
                    "SELECT id,dedupe_key,payload_hash FROM history_events "
                    "WHERE id=? OR dedupe_key=?",
                    (event.event_id, event.dedupe_key),
                ).fetchone()
                if (
                    existing is not None
                    and str(existing["dedupe_key"]) == event.dedupe_key
                    and str(existing["payload_hash"]) == payload_hash
                ):
                    return str(existing["id"])
                raise DeliveryIdempotencyConflict(
                    "classified event identity conflicts with stored payload"
                ) from exc

    def create_route_plan(self, plan: RoutePlan) -> str:
        now = self._format_time(self._now())
        route_plan_id = persistent_opaque_id(
            self.key_provider,
            "route-plan",
            f"{plan.event_id}|{plan.plan_hash}",
            prefix="route",
        )
        with self._db() as db:
            try:
                db.execute("BEGIN IMMEDIATE")
                event = db.execute(
                    "SELECT id,legacy_hold FROM history_events WHERE id=?",
                    (plan.event_id,),
                ).fetchone()
                if event is None:
                    raise DeliveryStoreError("route plan event does not exist")
                if int(event["legacy_hold"]):
                    raise DeliveryStoreError("legacy-hold events require explicit replan")
                existing = db.execute(
                    "SELECT id,event_id FROM route_plans WHERE plan_hash=?",
                    (plan.plan_hash,),
                ).fetchone()
                if existing is not None:
                    if str(existing["event_id"]) != plan.event_id:
                        raise DeliveryIdempotencyConflict(
                            "route plan hash belongs to a different event"
                        )
                    db.commit()
                    return str(existing["id"])
                active = db.execute(
                    "SELECT id FROM route_plans "
                    "WHERE event_id=? AND plan_state='active'",
                    (plan.event_id,),
                ).fetchone()
                if active is not None:
                    raise DeliveryIdempotencyConflict(
                        "event already has a different active route plan"
                    )
                db.execute(
                    "INSERT INTO route_plans("
                    "id,event_id,config_revision,routing_schema_version,"
                    "planner_version,plan_hash,plan_state,created_at"
                    ") VALUES (?,?,?,?,?,?,'active',?)",
                    (
                        route_plan_id,
                        plan.event_id,
                        plan.config_revision,
                        plan.routing_schema_version,
                        plan.planner_version,
                        plan.plan_hash,
                        now,
                    ),
                )
                for target in plan.targets:
                    self._insert_target_locked(
                        db,
                        plan=plan,
                        route_plan_id=route_plan_id,
                        target=target,
                        now=now,
                    )
                self._aggregate_event_locked(db, plan.event_id, now=now)
                db.commit()
                return route_plan_id
            except Exception:
                db.rollback()
                raise

    def _insert_target_locked(
        self,
        db: sqlite3.Connection,
        *,
        plan: RoutePlan,
        route_plan_id: str,
        target: RouteTargetDecision,
        now: str,
    ) -> str:
        target_delivery_id = persistent_opaque_id(
            self.key_provider,
            "target-delivery",
            f"{route_plan_id}|{target.target_id}",
            prefix="target",
        )
        idempotency_key = persistent_opaque_id(
            self.key_provider,
            "target-idempotency",
            f"{plan.event_id}|{plan.plan_hash}|{target.target_id}",
            prefix="idem",
            length=48,
        )
        terminal_at = (
            now if target_state_is_terminal(target.initial_state) else ""
        )
        db.execute(
            "INSERT INTO target_deliveries("
            "id,route_plan_id,target_id,state,skip_reason,idempotency_key,"
            "created_at,updated_at,terminal_at"
            ") VALUES (?,?,?,?,?,?,?,?,?)",
            (
                target_delivery_id,
                route_plan_id,
                target.target_id,
                target.initial_state.value,
                target.reason_code,
                idempotency_key,
                now,
                now,
                terminal_at,
            ),
        )
        db.execute(
            "INSERT INTO target_delivery_bindings("
            "target_delivery_id,provider_id,provider_schema_version,binding_json,"
            "binding_hash,created_at"
            ") VALUES (?,?,?,?,?,?)",
            (
                target_delivery_id,
                target.provider_id,
                int(target.provider_schema_version),
                target.binding_json,
                target.binding_hash,
                now,
            ),
        )
        if (
            target.target_id == "telegram"
            and target.provider_id == TelegramDispatchProvider.HISTORY_DISPATCHER.value
        ):
            recipient_refs = target.binding.get("recipient_refs", [])
            if not isinstance(recipient_refs, list):
                raise DeliveryStoreError("native Telegram binding recipients are invalid")
            initial_state = (
                "pending"
                if target.initial_state is TargetDeliveryState.PENDING
                else "skipped"
            )
            for recipient_ref in recipient_refs:
                self._insert_recipient_locked(
                    db,
                    event_id=plan.event_id,
                    target_delivery_id=target_delivery_id,
                    recipient_ref=self._normalize_recipient_ref(recipient_ref),
                    initial_state=initial_state,
                    now=now,
                )
        return target_delivery_id

    def _insert_recipient_locked(
        self,
        db: sqlite3.Connection,
        *,
        event_id: str,
        target_delivery_id: str,
        recipient_ref: str,
        initial_state: str,
        now: str,
    ) -> str:
        recipient_key = persistent_opaque_id(
            self.key_provider,
            "recipient",
            recipient_ref,
            prefix="recipient",
        )
        recipient_delivery_id = persistent_opaque_id(
            self.key_provider,
            "recipient-delivery",
            f"{target_delivery_id}|{recipient_ref}",
            prefix="delivery",
        )
        idempotency_key = persistent_opaque_id(
            self.key_provider,
            "recipient-idempotency",
            f"{event_id}|{target_delivery_id}|{recipient_ref}",
            prefix="idem",
            length=48,
        )
        terminal_at = now if initial_state == "skipped" else ""
        db.execute(
            "INSERT OR IGNORE INTO recipient_deliveries("
            "id,target_delivery_id,recipient_key,state,idempotency_key,"
            "created_at,updated_at,terminal_at"
            ") VALUES (?,?,?,?,?,?,?,?)",
            (
                recipient_delivery_id,
                target_delivery_id,
                recipient_key,
                initial_state,
                idempotency_key,
                now,
                now,
                terminal_at,
            ),
        )
        db.execute(
            "INSERT OR IGNORE INTO recipient_delivery_bindings("
            "recipient_delivery_id,target_delivery_id,recipient_ref,"
            "recipient_ref_hash,created_at"
            ") VALUES (?,?,?,?,?)",
            (
                recipient_delivery_id,
                target_delivery_id,
                recipient_ref,
                hashlib.sha256(recipient_ref.encode("utf-8")).hexdigest(),
                now,
            ),
        )
        existing = db.execute(
            "SELECT recipient_ref FROM recipient_delivery_bindings "
            "WHERE recipient_delivery_id=?",
            (recipient_delivery_id,),
        ).fetchone()
        if existing is None or str(existing["recipient_ref"]) != recipient_ref:
            raise DeliveryIdempotencyConflict("recipient binding identity conflict")
        return recipient_delivery_id

    def claim_target_deliveries(
        self,
        *,
        target_id: str,
        provider_id: str,
        worker_id: str,
        capability_version: str,
        limit: int = 20,
        lease_seconds: int = 120,
        max_attempts: int = 8,
        base_backoff_seconds: int = 5,
        max_backoff_seconds: int = 3600,
        jitter_ratio: float = 0.20,
    ) -> tuple[TargetDeliveryClaim, ...]:
        target_id = self._normalize_identifier(target_id, field="target_id").casefold()
        provider_id = self._normalize_identifier(
            provider_id,
            field="provider_id",
        ).casefold()
        if provider_id not in PROVIDER_IDS or provider_id == "legacy_unknown":
            raise DeliveryClaimRejected("provider is not claimable")
        worker_id = self._normalize_identifier(worker_id, field="worker_id")
        capability_version = self._normalize_identifier(
            capability_version,
            field="capability_version",
        )
        safe_limit = max(1, min(int(limit), MAX_CLAIM_BATCH))
        safe_lease = max(10, min(int(lease_seconds), 1800))
        now_dt = self._now()
        now = self._format_time(now_dt)
        expires = self._format_time(now_dt + timedelta(seconds=safe_lease))
        claims: list[TargetDeliveryClaim] = []
        with self._db() as db:
            try:
                db.execute("BEGIN IMMEDIATE")
                self._release_expired_locked(
                    db,
                    now_dt=now_dt,
                    max_attempts=max_attempts,
                    base_backoff_seconds=base_backoff_seconds,
                    max_backoff_seconds=max_backoff_seconds,
                    jitter_ratio=jitter_ratio,
                )
                candidates = db.execute(
                    "SELECT td.*,rp.event_id,rp.plan_state,he.encrypted_payload,"
                    "b.provider_id,b.provider_schema_version,b.binding_json,"
                    "b.binding_hash "
                    "FROM target_deliveries td "
                    "JOIN route_plans rp ON rp.id=td.route_plan_id "
                    "JOIN history_events he ON he.id=rp.event_id "
                    "JOIN target_delivery_bindings b "
                    "ON b.target_delivery_id=td.id "
                    "WHERE td.target_id=? AND b.provider_id=? "
                    "AND rp.plan_state='active' AND he.legacy_hold=0 "
                    "AND (td.state IN ('pending','failed_retryable') OR "
                    "(td.state='partial' AND (td.target_id<>'telegram' OR EXISTS ("
                    "SELECT 1 FROM recipient_deliveries rd "
                    "WHERE rd.target_delivery_id=td.id "
                    "AND rd.state IN ('pending','failed_retryable')"
                    ")))) "
                    "AND (td.next_attempt_at='' OR td.next_attempt_at<=?) "
                    "ORDER BY td.created_at,td.id LIMIT ?",
                    (target_id, provider_id, now, safe_limit),
                ).fetchall()
                for row in candidates:
                    binding = self._validated_binding(row)
                    required_capability = self._required_capability(
                        provider_id,
                        binding,
                    )
                    if not required_capability or capability_version != required_capability:
                        continue
                    event_id = str(row["event_id"])
                    try:
                        raw = decrypt_json(
                            bytes(row["encrypted_payload"]),
                            self.key_provider,
                            aad=event_id.encode("utf-8"),
                        )
                        payload = json.loads(raw.decode("utf-8"))
                        if not isinstance(payload, dict):
                            raise ValueError("payload is not an object")
                    except Exception:
                        db.execute(
                            "UPDATE target_deliveries SET state='quarantined',"
                            "last_error_class='payload_unavailable',updated_at=?,"
                            "terminal_at=? WHERE id=?",
                            (now, now, str(row["id"])),
                        )
                        self._aggregate_event_locked(db, event_id, now=now)
                        continue
                    token = self._token_factory()
                    if not isinstance(token, str) or len(token) < 32:
                        raise DeliveryStoreError("claim token factory returned an unsafe token")
                    attempt_no = int(row["attempt_count"]) + 1
                    updated = db.execute(
                        "UPDATE target_deliveries SET state='claimed',"
                        "claim_worker_id=?,claim_token_hash=?,claim_expires_at=?,"
                        "attempt_count=?,next_attempt_at='',updated_at=? "
                        "WHERE id=? AND state=?",
                        (
                            worker_id,
                            self._claim_token_hash(token),
                            expires,
                            attempt_no,
                            now,
                            str(row["id"]),
                            str(row["state"]),
                        ),
                    ).rowcount
                    if updated != 1:
                        continue
                    attempt_id = persistent_opaque_id(
                        self.key_provider,
                        "delivery-attempt",
                        f"{row['id']}|{attempt_no}",
                        prefix="attempt",
                    )
                    db.execute(
                        "INSERT INTO delivery_attempts("
                        "id,target_delivery_id,recipient_delivery_id,worker_id,"
                        "attempt_no,started_at"
                        ") VALUES (?,?,NULL,?,?,?)",
                        (
                            attempt_id,
                            str(row["id"]),
                            worker_id,
                            attempt_no,
                            now,
                        ),
                    )
                    successful, open_refs = self._recipient_ref_sets_locked(
                        db,
                        str(row["id"]),
                    )
                    claims.append(
                        TargetDeliveryClaim(
                            target_delivery_id=str(row["id"]),
                            route_plan_id=str(row["route_plan_id"]),
                            event_id=event_id,
                            target_id=target_id,
                            provider_id=provider_id,
                            provider_schema_version=int(
                                row["provider_schema_version"]
                            ),
                            binding=binding,
                            attempt_no=attempt_no,
                            worker_id=worker_id,
                            capability_version=capability_version,
                            claim_token=token,
                            claim_expires_at=expires,
                            payload=payload,
                            successful_recipient_refs=successful,
                            open_recipient_refs=open_refs,
                        )
                    )
                db.commit()
            except Exception:
                db.rollback()
                raise
        return tuple(claims)

    def _validated_binding(self, row: sqlite3.Row) -> dict[str, Any]:
        rendered = str(row["binding_json"])
        if hashlib.sha256(rendered.encode("utf-8")).hexdigest() != str(
            row["binding_hash"]
        ):
            raise DeliveryStoreError("target binding hash mismatch")
        try:
            value = json.loads(rendered)
        except json.JSONDecodeError as exc:
            raise DeliveryStoreError("target binding JSON is invalid") from exc
        if not isinstance(value, dict):
            raise DeliveryStoreError("target binding must be an object")
        if str(value.get("provider") or "") != str(row["provider_id"]):
            raise DeliveryStoreError("target binding provider mismatch")
        return value

    def _recipient_ref_sets_locked(
        self,
        db: sqlite3.Connection,
        target_delivery_id: str,
    ) -> tuple[tuple[str, ...], tuple[str, ...]]:
        rows = db.execute(
            "SELECT rb.recipient_ref,rd.state FROM recipient_deliveries rd "
            "JOIN recipient_delivery_bindings rb "
            "ON rb.recipient_delivery_id=rd.id "
            "WHERE rd.target_delivery_id=? ORDER BY rd.created_at,rd.id",
            (target_delivery_id,),
        ).fetchall()
        successful = tuple(
            str(row["recipient_ref"])
            for row in rows
            if str(row["state"]) in _SUCCESS_RECIPIENT_STATES
        )
        open_refs = tuple(
            str(row["recipient_ref"])
            for row in rows
            if str(row["state"]) in {"pending", "claimed", "failed_retryable"}
        )
        return successful, open_refs

    def renew_claim(
        self,
        *,
        target_delivery_id: str,
        worker_id: str,
        claim_token: str,
        lease_seconds: int = 120,
        max_claim_lifetime_seconds: int = 1800,
    ) -> str:
        worker_id = self._normalize_identifier(worker_id, field="worker_id")
        now_dt = self._now()
        now = self._format_time(now_dt)
        with self._db() as db:
            try:
                db.execute("BEGIN IMMEDIATE")
                row, _binding = self._verify_claim_locked(
                    db,
                    target_delivery_id=target_delivery_id,
                    worker_id=worker_id,
                    claim_token=claim_token,
                    now_dt=now_dt,
                )
                attempt = db.execute(
                    "SELECT started_at FROM delivery_attempts "
                    "WHERE target_delivery_id=? AND recipient_delivery_id IS NULL "
                    "AND attempt_no=?",
                    (target_delivery_id, int(row["attempt_count"])),
                ).fetchone()
                if attempt is None:
                    raise DeliveryClaimRejected("claim attempt record is missing")
                started = self._parse_time(str(attempt["started_at"]))
                maximum = started + timedelta(
                    seconds=max(30, min(int(max_claim_lifetime_seconds), 86400))
                )
                proposed = now_dt + timedelta(
                    seconds=max(10, min(int(lease_seconds), 1800))
                )
                new_expiry = min(proposed, maximum)
                if new_expiry <= now_dt:
                    raise DeliveryClaimRejected("claim maximum lifetime has elapsed")
                rendered = self._format_time(new_expiry)
                db.execute(
                    "UPDATE target_deliveries SET claim_expires_at=?,updated_at=? "
                    "WHERE id=?",
                    (rendered, now, target_delivery_id),
                )
                db.commit()
                return rendered
            except Exception:
                db.rollback()
                raise

    def register_recipients(
        self,
        *,
        target_delivery_id: str,
        worker_id: str,
        claim_token: str,
        recipient_refs: Iterable[str],
    ) -> tuple[RecipientDeliverySnapshot, ...]:
        refs = tuple(dict.fromkeys(self._normalize_recipient_ref(ref) for ref in recipient_refs))
        if not refs or len(refs) > MAX_NATIVE_RECIPIENT_REFS:
            raise DeliveryStoreError("recipient list is empty or exceeds the limit")
        now_dt = self._now()
        now = self._format_time(now_dt)
        with self._db() as db:
            try:
                db.execute("BEGIN IMMEDIATE")
                row, binding = self._verify_claim_locked(
                    db,
                    target_delivery_id=target_delivery_id,
                    worker_id=worker_id,
                    claim_token=claim_token,
                    now_dt=now_dt,
                )
                if str(row["target_id"]) != "telegram":
                    raise DeliveryClaimRejected("only Telegram targets have recipients")
                provider_id = str(row["provider_id"])
                if provider_id == TelegramDispatchProvider.HISTORY_DISPATCHER.value:
                    allowed = binding.get("recipient_refs", [])
                    if not isinstance(allowed, list):
                        raise DeliveryStoreError("native recipient binding is invalid")
                    allowed_refs = {
                        self._normalize_recipient_ref(value) for value in allowed
                    }
                    if not set(refs) <= allowed_refs:
                        raise DeliveryClaimRejected(
                            "native worker attempted an unplanned recipient"
                        )
                elif provider_id != TelegramDispatchProvider.TEEBOTUS.value:
                    raise DeliveryClaimRejected("Telegram provider is not routable")
                for recipient_ref in refs:
                    self._insert_recipient_locked(
                        db,
                        event_id=str(row["event_id"]),
                        target_delivery_id=target_delivery_id,
                        recipient_ref=recipient_ref,
                        initial_state="pending",
                        now=now,
                    )
                snapshots = self._recipient_snapshots_locked(db, target_delivery_id)
                db.commit()
                return snapshots
            except Exception:
                db.rollback()
                raise

    def record_recipient_outcomes(
        self,
        *,
        target_delivery_id: str,
        worker_id: str,
        claim_token: str,
        outcomes: Iterable[TelegramRecipientOutcome | Mapping[str, Any]],
    ) -> tuple[RecipientDeliverySnapshot, ...]:
        normalized = tuple(
            outcome
            if isinstance(outcome, TelegramRecipientOutcome)
            else TelegramRecipientOutcome(**dict(outcome))
            for outcome in outcomes
        )
        if not normalized:
            return ()
        self.register_recipients(
            target_delivery_id=target_delivery_id,
            worker_id=worker_id,
            claim_token=claim_token,
            recipient_refs=(outcome.recipient_ref for outcome in normalized),
        )
        now_dt = self._now()
        now = self._format_time(now_dt)
        with self._db() as db:
            try:
                db.execute("BEGIN IMMEDIATE")
                target, _binding = self._verify_claim_locked(
                    db,
                    target_delivery_id=target_delivery_id,
                    worker_id=worker_id,
                    claim_token=claim_token,
                    now_dt=now_dt,
                )
                attempt_no = int(target["attempt_count"])
                for outcome in normalized:
                    row = db.execute(
                        "SELECT rd.*,rb.recipient_ref FROM recipient_deliveries rd "
                        "JOIN recipient_delivery_bindings rb "
                        "ON rb.recipient_delivery_id=rd.id "
                        "WHERE rd.target_delivery_id=? AND rb.recipient_ref=?",
                        (target_delivery_id, outcome.recipient_ref),
                    ).fetchone()
                    if row is None:
                        raise DeliveryStoreError("recipient registration disappeared")
                    existing = self._stored_recipient_outcome(row)
                    merged = (
                        merge_recipient_outcomes((existing,), (outcome,))[0]
                        if existing is not None
                        else outcome
                    )
                    state = (
                        "failed_retryable"
                        if merged.status == "failed"
                        else merged.status
                    )
                    terminal_at = (
                        now if state in _TERMINAL_RECIPIENT_STATES else ""
                    )
                    db.execute(
                        "UPDATE recipient_deliveries SET state=?,"
                        "external_message_ref_key=?,possible_duplicate=?,"
                        "last_error_class=?,attempt_count=MAX(attempt_count,?),"
                        "updated_at=?,terminal_at=? WHERE id=?",
                        (
                            state,
                            merged.message_ref_key,
                            int(merged.possible_duplicate),
                            merged.reason_code,
                            attempt_no,
                            now,
                            terminal_at,
                            str(row["id"]),
                        ),
                    )
                    attempt_id = persistent_opaque_id(
                        self.key_provider,
                        "recipient-attempt",
                        f"{row['id']}|{attempt_no}",
                        prefix="attempt",
                    )
                    db.execute(
                        "INSERT INTO delivery_attempts("
                        "id,target_delivery_id,recipient_delivery_id,worker_id,"
                        "attempt_no,started_at,completed_at,outcome,error_class"
                        ") VALUES (?,?,?,?,?,?,?,?,?) "
                        "ON CONFLICT(target_delivery_id,recipient_delivery_id,attempt_no) "
                        "DO UPDATE SET completed_at=excluded.completed_at,"
                        "outcome=excluded.outcome,error_class=excluded.error_class",
                        (
                            attempt_id,
                            target_delivery_id,
                            str(row["id"]),
                            worker_id,
                            attempt_no,
                            now,
                            now,
                            state,
                            merged.reason_code,
                        ),
                    )
                snapshots = self._recipient_snapshots_locked(db, target_delivery_id)
                db.commit()
                return snapshots
            except Exception:
                db.rollback()
                raise

    @staticmethod
    def _stored_recipient_outcome(
        row: sqlite3.Row,
    ) -> TelegramRecipientOutcome | None:
        state = str(row["state"])
        if state in {"pending", "claimed"}:
            return None
        outcome_status = (
            "failed"
            if state in {
                "failed_retryable",
                "failed_terminal",
                "quarantined",
                "legacy_hold",
            }
            else state
        )
        return TelegramRecipientOutcome(
            recipient_ref=str(row["recipient_ref"]),
            status=outcome_status,
            possible_duplicate=bool(row["possible_duplicate"]),
            message_ref_key=str(row["external_message_ref_key"]),
            reason_code=str(row["last_error_class"]),
        )

    def complete_target(
        self,
        *,
        target_delivery_id: str,
        worker_id: str,
        claim_token: str,
        outcome: str | None = None,
        error_class: str = "",
        retry_after_seconds: int = 0,
        max_attempts: int = 8,
        base_backoff_seconds: int = 5,
        max_backoff_seconds: int = 3600,
        jitter_ratio: float = 0.20,
    ) -> str:
        now_dt = self._now()
        now = self._format_time(now_dt)
        error_class = self._normalize_reason(error_class, field="error_class")
        with self._db() as db:
            try:
                db.execute("BEGIN IMMEDIATE")
                target, _binding = self._verify_claim_locked(
                    db,
                    target_delivery_id=target_delivery_id,
                    worker_id=worker_id,
                    claim_token=claim_token,
                    now_dt=now_dt,
                )
                if outcome is None:
                    state, derived_error = self._derive_target_state_locked(
                        db,
                        target_delivery_id,
                    )
                    error_class = error_class or derived_error
                else:
                    state = TargetDeliveryState(outcome)
                    if state not in {
                        TargetDeliveryState.DELIVERED,
                        TargetDeliveryState.FAILED_RETRYABLE,
                        TargetDeliveryState.FAILED_TERMINAL,
                        TargetDeliveryState.QUARANTINED,
                        TargetDeliveryState.SKIPPED_DISABLED,
                        TargetDeliveryState.SKIPPED_FILTERED,
                        TargetDeliveryState.SKIPPED_UNKNOWN,
                    }:
                        raise DeliveryStoreError("unsupported target completion state")
                attempt_no = int(target["attempt_count"])
                if (
                    state
                    in {
                        TargetDeliveryState.FAILED_RETRYABLE,
                        TargetDeliveryState.PARTIAL,
                    }
                    and attempt_no >= max(1, int(max_attempts))
                ):
                    state = TargetDeliveryState.QUARANTINED
                    error_class = error_class or "max_attempts_exceeded"
                next_attempt_at = ""
                retry_delay = 0
                if state in {
                    TargetDeliveryState.FAILED_RETRYABLE,
                    TargetDeliveryState.PARTIAL,
                }:
                    retry_delay = max(
                        int(retry_after_seconds),
                        self.compute_backoff_seconds(
                            target_delivery_id,
                            attempt_no,
                            base_seconds=base_backoff_seconds,
                            max_seconds=max_backoff_seconds,
                            jitter_ratio=jitter_ratio,
                        ),
                    )
                    next_attempt_at = self._format_time(
                        now_dt + timedelta(seconds=retry_delay)
                    )
                terminal_at = now if target_state_is_terminal(state) else ""
                skip_reason = (
                    error_class
                    if state
                    in {
                        TargetDeliveryState.SKIPPED_DISABLED,
                        TargetDeliveryState.SKIPPED_FILTERED,
                        TargetDeliveryState.SKIPPED_UNKNOWN,
                    }
                    else ""
                )
                blocked_reason = (
                    error_class if state is TargetDeliveryState.PARTIAL else ""
                )
                db.execute(
                    "UPDATE target_deliveries SET state=?,skip_reason=?,"
                    "blocked_reason=?,claim_worker_id='',claim_token_hash='',"
                    "claim_expires_at='',next_attempt_at=?,last_error_class=?,"
                    "updated_at=?,terminal_at=? WHERE id=?",
                    (
                        state.value,
                        skip_reason,
                        blocked_reason,
                        next_attempt_at,
                        error_class,
                        now,
                        terminal_at,
                        target_delivery_id,
                    ),
                )
                db.execute(
                    "UPDATE delivery_attempts SET completed_at=?,outcome=?,"
                    "error_class=?,retry_after_seconds=? "
                    "WHERE target_delivery_id=? AND recipient_delivery_id IS NULL "
                    "AND attempt_no=?",
                    (
                        now,
                        state.value,
                        error_class,
                        retry_delay,
                        target_delivery_id,
                        attempt_no,
                    ),
                )
                self._aggregate_event_locked(
                    db,
                    str(target["event_id"]),
                    now=now,
                )
                db.commit()
                return state.value
            except Exception:
                db.rollback()
                raise

    def _derive_target_state_locked(
        self,
        db: sqlite3.Connection,
        target_delivery_id: str,
    ) -> tuple[TargetDeliveryState, str]:
        rows = db.execute(
            "SELECT state FROM recipient_deliveries "
            "WHERE target_delivery_id=? ORDER BY id",
            (target_delivery_id,),
        ).fetchall()
        if not rows:
            return TargetDeliveryState.FAILED_RETRYABLE, "no_routable_recipients"
        states = [str(row["state"]) for row in rows]
        success = sum(state in _SUCCESS_RECIPIENT_STATES for state in states)
        skipped = sum(state == "skipped" for state in states)
        possible_duplicate = any(state == "possible_duplicate" for state in states)
        retryable = any(
            state in {"pending", "claimed", "failed_retryable"}
            for state in states
        )
        terminal_failure = any(
            state in {"failed_terminal", "quarantined", "legacy_hold"}
            for state in states
        )
        if possible_duplicate:
            return TargetDeliveryState.PARTIAL, "possible_duplicate"
        if success and (retryable or terminal_failure):
            return TargetDeliveryState.PARTIAL, "recipient_partial_failure"
        if success and success + skipped == len(states):
            return TargetDeliveryState.DELIVERED, ""
        if skipped == len(states):
            return TargetDeliveryState.SKIPPED_FILTERED, "no_active_recipient"
        if retryable:
            return TargetDeliveryState.FAILED_RETRYABLE, "recipient_retryable_failure"
        return TargetDeliveryState.FAILED_TERMINAL, "recipient_terminal_failure"

    def release_expired_claims(
        self,
        *,
        max_attempts: int = 8,
        base_backoff_seconds: int = 5,
        max_backoff_seconds: int = 3600,
        jitter_ratio: float = 0.20,
    ) -> int:
        now_dt = self._now()
        with self._db() as db:
            try:
                db.execute("BEGIN IMMEDIATE")
                count = self._release_expired_locked(
                    db,
                    now_dt=now_dt,
                    max_attempts=max_attempts,
                    base_backoff_seconds=base_backoff_seconds,
                    max_backoff_seconds=max_backoff_seconds,
                    jitter_ratio=jitter_ratio,
                )
                db.commit()
                return count
            except Exception:
                db.rollback()
                raise

    def _release_expired_locked(
        self,
        db: sqlite3.Connection,
        *,
        now_dt: datetime,
        max_attempts: int,
        base_backoff_seconds: int,
        max_backoff_seconds: int,
        jitter_ratio: float,
    ) -> int:
        now = self._format_time(now_dt)
        rows = db.execute(
            "SELECT td.*,rp.event_id FROM target_deliveries td "
            "JOIN route_plans rp ON rp.id=td.route_plan_id "
            "WHERE td.state='claimed' AND td.claim_expires_at<=? "
            "ORDER BY td.claim_expires_at,td.id",
            (now,),
        ).fetchall()
        for row in rows:
            attempt_no = int(row["attempt_count"])
            if attempt_no >= max(1, int(max_attempts)):
                state = TargetDeliveryState.QUARANTINED
                next_attempt_at = ""
                terminal_at = now
                error_class = "claim_expired_max_attempts"
            else:
                state = TargetDeliveryState.FAILED_RETRYABLE
                delay = self.compute_backoff_seconds(
                    str(row["id"]),
                    attempt_no,
                    base_seconds=base_backoff_seconds,
                    max_seconds=max_backoff_seconds,
                    jitter_ratio=jitter_ratio,
                )
                next_attempt_at = self._format_time(
                    now_dt + timedelta(seconds=delay)
                )
                terminal_at = ""
                error_class = "claim_expired"
            db.execute(
                "UPDATE target_deliveries SET state=?,claim_worker_id='',"
                "claim_token_hash='',claim_expires_at='',next_attempt_at=?,"
                "last_error_class=?,updated_at=?,terminal_at=? WHERE id=?",
                (
                    state.value,
                    next_attempt_at,
                    error_class,
                    now,
                    terminal_at,
                    str(row["id"]),
                ),
            )
            db.execute(
                "UPDATE delivery_attempts SET completed_at=?,outcome=?,"
                "error_class=? WHERE target_delivery_id=? "
                "AND recipient_delivery_id IS NULL AND attempt_no=?",
                (
                    now,
                    state.value,
                    error_class,
                    str(row["id"]),
                    attempt_no,
                ),
            )
            self._aggregate_event_locked(
                db,
                str(row["event_id"]),
                now=now,
            )
        return len(rows)

    @staticmethod
    def compute_backoff_seconds(
        delivery_id: str,
        attempt_no: int,
        *,
        base_seconds: int = 5,
        max_seconds: int = 3600,
        jitter_ratio: float = 0.20,
    ) -> int:
        attempt = max(1, int(attempt_no))
        base = max(1, int(base_seconds))
        maximum = max(base, int(max_seconds))
        raw = min(maximum, base * (2 ** min(attempt - 1, 20)))
        jitter = max(0.0, min(float(jitter_ratio), 0.50))
        digest = hashlib.sha256(
            f"{delivery_id}|{attempt}".encode("utf-8")
        ).digest()
        unit = int.from_bytes(digest[:8], "big") / float((1 << 64) - 1)
        factor = 1.0 + jitter * ((2.0 * unit) - 1.0)
        return max(1, min(maximum, int(math.ceil(raw * factor))))

    def heartbeat(
        self,
        *,
        worker_id: str,
        target_id: str,
        provider_id: str,
        capability_version: str,
        state: str,
        details: Mapping[str, Any] | None = None,
    ) -> None:
        worker_id = self._normalize_identifier(worker_id, field="worker_id")
        target_id = self._normalize_identifier(target_id, field="target_id").casefold()
        provider_id = self._normalize_identifier(
            provider_id,
            field="provider_id",
        ).casefold()
        capability_version = self._normalize_identifier(
            capability_version,
            field="capability_version",
        )
        state = self._normalize_identifier(state, field="state").casefold()
        safe_details: dict[str, Any] = {"provider_id": provider_id}
        for index, (key, value) in enumerate((details or {}).items()):
            if index >= 16:
                break
            normalized_key = self._normalize_reason(key, field="detail key")
            if isinstance(value, bool | int):
                safe_details[normalized_key] = value
            elif isinstance(value, str):
                safe_details[normalized_key] = redact_text(
                    value,
                    max_chars=120,
                    max_bytes=480,
                )
        rendered = self._canonical_json(safe_details)
        if len(rendered.encode("utf-8")) > MAX_HEARTBEAT_DETAILS_BYTES:
            raise DeliveryStoreError("heartbeat details exceed the byte limit")
        now = self._format_time(self._now())
        with self._db() as db:
            db.execute(
                "INSERT INTO worker_heartbeats("
                "worker_id,target_id,capability_version,state,last_heartbeat_at,"
                "details_json"
                ") VALUES (?,?,?,?,?,?) "
                "ON CONFLICT(worker_id) DO UPDATE SET "
                "target_id=excluded.target_id,"
                "capability_version=excluded.capability_version,"
                "state=excluded.state,"
                "last_heartbeat_at=excluded.last_heartbeat_at,"
                "details_json=excluded.details_json",
                (
                    worker_id,
                    target_id,
                    capability_version,
                    state,
                    now,
                    rendered,
                ),
            )

    def event_delivery_summary(self, event_id: str) -> EventDeliverySummary:
        with self._db() as db:
            event = db.execute(
                "SELECT operational_state FROM history_events WHERE id=?",
                (event_id,),
            ).fetchone()
            if event is None:
                raise DeliveryStoreError("event does not exist")
            rows = db.execute(
                "SELECT td.state,COUNT(*) AS count FROM target_deliveries td "
                "JOIN route_plans rp ON rp.id=td.route_plan_id "
                "WHERE rp.event_id=? AND rp.plan_state='active' "
                "GROUP BY td.state",
                (event_id,),
            ).fetchall()
            counts = {str(row["state"]): int(row["count"]) for row in rows}
            aggregate = self._aggregate_state_from_counts(counts)
            return EventDeliverySummary(
                event_id=event_id,
                aggregate_state=aggregate,
                operational_state=str(event["operational_state"]),
                counts=counts,
            )

    def _aggregate_event_locked(
        self,
        db: sqlite3.Connection,
        event_id: str,
        *,
        now: str,
    ) -> str:
        event = db.execute(
            "SELECT legacy_hold FROM history_events WHERE id=?",
            (event_id,),
        ).fetchone()
        if event is None:
            raise DeliveryStoreError("event does not exist")
        if int(event["legacy_hold"]):
            return "legacy_hold"
        rows = db.execute(
            "SELECT td.state,COUNT(*) AS count FROM target_deliveries td "
            "JOIN route_plans rp ON rp.id=td.route_plan_id "
            "WHERE rp.event_id=? AND rp.plan_state='active' "
            "GROUP BY td.state",
            (event_id,),
        ).fetchall()
        counts = {str(row["state"]): int(row["count"]) for row in rows}
        aggregate = self._aggregate_state_from_counts(counts)
        if aggregate in {"pending", "partial"}:
            operational = "ready"
            terminal_at = ""
        elif aggregate == "failed":
            operational = "quarantined"
            terminal_at = now
        else:
            operational = "terminal"
            terminal_at = now
        db.execute(
            "UPDATE history_events SET operational_state=?,terminal_at=? WHERE id=?",
            (operational, terminal_at, event_id),
        )
        return aggregate

    @staticmethod
    def _aggregate_state_from_counts(counts: Mapping[str, int]) -> str:
        if not counts:
            return "pending"
        active = sum(
            counts.get(state, 0)
            for state in ("pending", "claimed", "failed_retryable")
        )
        partial = counts.get("partial", 0)
        delivered = counts.get("delivered", 0)
        failures = counts.get("failed_terminal", 0) + counts.get("quarantined", 0)
        skipped = sum(
            counts.get(state, 0)
            for state in (
                "skipped_disabled",
                "skipped_filtered",
                "skipped_unknown",
                "legacy_hold",
            )
        )
        total = sum(counts.values())
        if active:
            return "partial" if partial else "pending"
        if partial:
            return "partial"
        if failures:
            return "partial" if delivered else "failed"
        if delivered:
            return "delivered"
        if skipped == total:
            return "skipped"
        return "pending"

    def _verify_claim_locked(
        self,
        db: sqlite3.Connection,
        *,
        target_delivery_id: str,
        worker_id: str,
        claim_token: str,
        now_dt: datetime,
    ) -> tuple[sqlite3.Row, dict[str, Any]]:
        row = db.execute(
            "SELECT td.*,rp.event_id,b.provider_id,b.provider_schema_version,"
            "b.binding_json,b.binding_hash FROM target_deliveries td "
            "JOIN route_plans rp ON rp.id=td.route_plan_id "
            "JOIN target_delivery_bindings b ON b.target_delivery_id=td.id "
            "WHERE td.id=?",
            (target_delivery_id,),
        ).fetchone()
        if row is None or str(row["state"]) != "claimed":
            raise DeliveryClaimRejected("target delivery is not actively claimed")
        if str(row["claim_worker_id"]) != worker_id:
            raise DeliveryClaimRejected("claim belongs to another worker")
        expected = str(row["claim_token_hash"])
        actual = self._claim_token_hash(str(claim_token))
        if not hmac.compare_digest(expected, actual):
            raise DeliveryClaimRejected("claim token is invalid")
        if self._parse_time(str(row["claim_expires_at"])) <= now_dt:
            raise DeliveryClaimRejected("claim has expired")
        return row, self._validated_binding(row)

    def _recipient_snapshots_locked(
        self,
        db: sqlite3.Connection,
        target_delivery_id: str,
    ) -> tuple[RecipientDeliverySnapshot, ...]:
        rows = db.execute(
            "SELECT rd.*,rb.recipient_ref FROM recipient_deliveries rd "
            "JOIN recipient_delivery_bindings rb "
            "ON rb.recipient_delivery_id=rd.id "
            "WHERE rd.target_delivery_id=? ORDER BY rd.created_at,rd.id",
            (target_delivery_id,),
        ).fetchall()
        return tuple(
            RecipientDeliverySnapshot(
                recipient_delivery_id=str(row["id"]),
                recipient_ref=str(row["recipient_ref"]),
                state=str(row["state"]),
                possible_duplicate=bool(row["possible_duplicate"]),
                message_ref_key=str(row["external_message_ref_key"]),
                last_error_class=str(row["last_error_class"]),
                attempt_count=int(row["attempt_count"]),
            )
            for row in rows
        )
