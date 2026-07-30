from __future__ import annotations

from pathlib import Path


STORE = Path("history_dispatcher/delivery_store.py")
API = Path("history_dispatcher/provider_api_v2.py")
SERVICE = Path("history_dispatcher/service.py")
ARCHITECTURE = Path("tests/test_architecture_contract.py")
FIXTURE = Path("tests/fixtures/provider-v2/contract.json")


def replace_once(source: str, old: str, new: str, *, label: str) -> str:
    count = source.count(old)
    if count != 1:
        raise SystemExit(f"{label}: expected one match, found {count}")
    return source.replace(old, new, 1)


def patch_store() -> None:
    source = STORE.read_text(encoding="utf-8")
    marker = """        return tuple(claims)

    def _validated_binding(self, row: sqlite3.Row) -> dict[str, Any]:
"""
    method = """        return tuple(claims)

    def reclaim_target_delivery(
        self,
        *,
        target_delivery_id: str,
        provider_id: str,
        worker_id: str,
        capability_version: str,
        previous_attempt_no: int,
        lease_seconds: int = 120,
    ) -> TargetDeliveryClaim | None:
        \"\"\"Reclaim one expired target for callback reconciliation only.\"\"\"

        target_delivery_id = self._normalize_identifier(
            target_delivery_id,
            field="target_delivery_id",
        )
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
        if isinstance(previous_attempt_no, bool):
            raise DeliveryStoreError("previous_attempt_no must be an integer")
        try:
            expected_attempt = int(previous_attempt_no)
        except (TypeError, ValueError) as exc:
            raise DeliveryStoreError("previous_attempt_no must be an integer") from exc
        if expected_attempt < 1:
            raise DeliveryStoreError("previous_attempt_no must be positive")

        now_dt = self._now()
        now = self._format_time(now_dt)
        expires = self._format_time(
            now_dt + timedelta(seconds=max(10, min(int(lease_seconds), 1800)))
        )
        with self._db() as db:
            try:
                db.execute("BEGIN IMMEDIATE")
                row = db.execute(
                    "SELECT td.*,rp.event_id,rp.plan_state,he.legacy_hold,"
                    "he.encrypted_payload,b.provider_id,b.provider_schema_version,"
                    "b.binding_json,b.binding_hash "
                    "FROM target_deliveries td "
                    "JOIN route_plans rp ON rp.id=td.route_plan_id "
                    "JOIN history_events he ON he.id=rp.event_id "
                    "JOIN target_delivery_bindings b ON b.target_delivery_id=td.id "
                    "WHERE td.id=?",
                    (target_delivery_id,),
                ).fetchone()
                if row is None:
                    db.commit()
                    return None
                binding = self._validated_binding(row)
                if str(row["provider_id"]) != provider_id:
                    db.commit()
                    return None
                required_capability = self._required_capability(provider_id, binding)
                if not required_capability or capability_version != required_capability:
                    db.commit()
                    return None
                if str(row["plan_state"]) != "active" or int(row["legacy_hold"]):
                    db.commit()
                    return None
                if int(row["attempt_count"]) != expected_attempt:
                    db.commit()
                    return None
                state = str(row["state"])
                if state == "claimed":
                    if self._parse_time(str(row["claim_expires_at"])) > now_dt:
                        db.commit()
                        return None
                elif state not in {"pending", "failed_retryable", "partial"}:
                    db.commit()
                    return None

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
                except Exception as exc:
                    raise DeliveryStoreError("target payload is unavailable") from exc

                token = self._token_factory()
                if not isinstance(token, str) or len(token) < 32:
                    raise DeliveryStoreError("claim token factory returned an unsafe token")
                attempt_no = expected_attempt + 1
                updated = db.execute(
                    "UPDATE target_deliveries SET state='claimed',"
                    "claim_worker_id=?,claim_token_hash=?,claim_expires_at=?,"
                    "attempt_count=?,next_attempt_at='',last_error_class='',"
                    "updated_at=?,terminal_at='' "
                    "WHERE id=? AND attempt_count=? AND ("
                    "(state='claimed' AND claim_expires_at<=?) OR "
                    "state IN ('pending','failed_retryable','partial'))",
                    (
                        worker_id,
                        self._claim_token_hash(token),
                        expires,
                        attempt_no,
                        now,
                        target_delivery_id,
                        expected_attempt,
                        now,
                    ),
                ).rowcount
                if updated != 1:
                    db.rollback()
                    return None
                db.execute(
                    "UPDATE delivery_attempts SET completed_at=?,"
                    "outcome='reclaimed_expired',"
                    "error_class='claim_expired_reconciliation' "
                    "WHERE target_delivery_id=? AND recipient_delivery_id IS NULL "
                    "AND attempt_no=? AND completed_at=''",
                    (now, target_delivery_id, expected_attempt),
                )
                attempt_id = persistent_opaque_id(
                    self.key_provider,
                    "delivery-attempt",
                    f"{target_delivery_id}|{attempt_no}",
                    prefix="attempt",
                )
                db.execute(
                    "INSERT INTO delivery_attempts("
                    "id,target_delivery_id,recipient_delivery_id,worker_id,"
                    "attempt_no,started_at"
                    ") VALUES (?,?,NULL,?,?,?)",
                    (
                        attempt_id,
                        target_delivery_id,
                        worker_id,
                        attempt_no,
                        now,
                    ),
                )
                successful, open_refs = self._recipient_ref_sets_locked(
                    db,
                    target_delivery_id,
                )
                claim = TargetDeliveryClaim(
                    target_delivery_id=target_delivery_id,
                    route_plan_id=str(row["route_plan_id"]),
                    event_id=event_id,
                    target_id=str(row["target_id"]),
                    provider_id=provider_id,
                    provider_schema_version=int(row["provider_schema_version"]),
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
                db.commit()
                return claim
            except Exception:
                db.rollback()
                raise

    def _validated_binding(self, row: sqlite3.Row) -> dict[str, Any]:
"""
    STORE.write_text(replace_once(source, marker, method, label="delivery reclaim method"), encoding="utf-8")


def patch_api() -> None:
    source = API.read_text(encoding="utf-8")
    source = replace_once(
        source,
        '    "provider.v2.claim",\n    "provider.v2.renew",\n',
        '    "provider.v2.claim",\n    "provider.v2.reclaim",\n    "provider.v2.renew",\n',
        label="provider operation tuple",
    )
    source = replace_once(
        source,
        '        if operation == "provider.v2.claim":\n            return self._claim(body)\n        if operation == "provider.v2.renew":\n',
        '        if operation == "provider.v2.claim":\n            return self._claim(body)\n'
        '        if operation == "provider.v2.reclaim":\n            return self._reclaim(body)\n'
        '        if operation == "provider.v2.renew":\n',
        label="provider dispatch branch",
    )
    source = replace_once(
        source,
        """        return {
            "ok": True,
            "schema_version": PROVIDER_API_SCHEMA_VERSION,
            "claims": [_claim_dict(claim) for claim in claims],
        }

    def _renew(self, body: Mapping[str, Any]) -> dict[str, Any]:
""",
        """        return {
            "ok": True,
            "schema_version": PROVIDER_API_SCHEMA_VERSION,
            "claims": [_claim_dict(claim) for claim in claims],
        }

    def _reclaim(self, body: Mapping[str, Any]) -> dict[str, Any]:
        _only(
            body,
            frozenset(
                {
                    "target_delivery_id",
                    "provider_id",
                    "worker_id",
                    "capability_version",
                    "previous_attempt_no",
                    "lease_seconds",
                }
            ),
        )
        claim = self.store.reclaim_target_delivery(
            target_delivery_id=_identifier(body, "target_delivery_id"),
            provider_id=_identifier(body, "provider_id"),
            worker_id=_identifier(body, "worker_id"),
            capability_version=_identifier(body, "capability_version"),
            previous_attempt_no=_integer(
                body,
                "previous_attempt_no",
                default=0,
                minimum=1,
                maximum=2**31 - 1,
            ),
            lease_seconds=_integer(
                body,
                "lease_seconds",
                default=120,
                minimum=10,
                maximum=1800,
            ),
        )
        claims: list[dict[str, Any]] = []
        if claim is not None:
            rendered = _claim_dict(claim)
            rendered["reconciliation_only"] = True
            claims.append(rendered)
        return {
            "ok": True,
            "schema_version": PROVIDER_API_SCHEMA_VERSION,
            "claims": claims,
        }

    def _renew(self, body: Mapping[str, Any]) -> dict[str, Any]:
""",
        label="provider reclaim handler",
    )
    API.write_text(source, encoding="utf-8")


def patch_service() -> None:
    source = SERVICE.read_text(encoding="utf-8")
    source = replace_once(
        source,
        'ONE_SHOT_SENSITIVE_OPERATIONS = frozenset({"provider.v2.claim"})',
        'ONE_SHOT_SENSITIVE_OPERATIONS = frozenset({'
        '"provider.v2.claim", "provider.v2.reclaim"})',
        label="one-shot operations",
    )
    SERVICE.write_text(source, encoding="utf-8")


def patch_contracts() -> None:
    source = ARCHITECTURE.read_text(encoding="utf-8")
    source = replace_once(
        source,
        '        "provider.v2.claim",\n        "provider.v2.renew",\n',
        '        "provider.v2.claim",\n        "provider.v2.reclaim",\n        "provider.v2.renew",\n',
        label="architecture operation tuple",
    )
    ARCHITECTURE.write_text(source, encoding="utf-8")

    fixture = FIXTURE.read_text(encoding="utf-8")
    fixture = replace_once(
        fixture,
        '    "provider.v2.claim",\n    "provider.v2.renew",\n',
        '    "provider.v2.claim",\n    "provider.v2.reclaim",\n    "provider.v2.renew",\n',
        label="fixture operation tuple",
    )
    FIXTURE.write_text(fixture, encoding="utf-8")


def main() -> None:
    patch_store()
    patch_api()
    patch_service()
    patch_contracts()


if __name__ == "__main__":
    main()
