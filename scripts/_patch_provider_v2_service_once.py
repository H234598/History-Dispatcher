from __future__ import annotations

from pathlib import Path


IDEMPOTENCY = Path("history_dispatcher/idempotency.py")
SERVICE = Path("history_dispatcher/service.py")
ARCHITECTURE_TEST = Path("tests/test_architecture_contract.py")


def replace_once(source: str, old: str, new: str, *, label: str) -> str:
    count = source.count(old)
    if count != 1:
        raise SystemExit(f"{label}: expected one match, found {count}")
    return source.replace(old, new, 1)


def patch_idempotency() -> None:
    source = IDEMPOTENCY.read_text(encoding="utf-8")
    source = replace_once(
        source,
        """        return dict(response)

    def prune(self, *, retention_days: int) -> int:
""",
        """        return dict(response)

    def release(
        self,
        request_id: str,
        operation: str,
        fingerprint: str,
    ) -> bool:
        \"\"\"Release only an exact pending reservation.

        Completed responses are durable and can never be removed through this
        path. This is used only when validation proves that a one-shot mutation
        did not start.
        \"\"\"

        normalized_id, normalized_operation, normalized_fingerprint = (
            self._validate_identity(request_id, operation, fingerprint)
        )
        with self._lock, self._connect() as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute(
                "SELECT operation, request_fingerprint, client_scope, response_json "
                "FROM idempotency_results WHERE request_id=?",
                (normalized_id,),
            ).fetchone()
            if row is None:
                db.commit()
                return False
            if (
                str(row["operation"]) != normalized_operation
                or str(row["request_fingerprint"]) != normalized_fingerprint
                or str(row["client_scope"]) != self.client_scope
            ):
                db.rollback()
                raise IdempotencyConflict(normalized_id)
            if str(row["response_json"] or ""):
                db.commit()
                return False
            deleted = db.execute(
                "DELETE FROM idempotency_results WHERE request_id=? "
                "AND operation=? AND request_fingerprint=? AND client_scope=? "
                "AND response_json=''",
                (
                    normalized_id,
                    normalized_operation,
                    normalized_fingerprint,
                    self.client_scope,
                ),
            ).rowcount
            db.commit()
            return bool(deleted)

    def prune(self, *, retention_days: int) -> int:
""",
        label="idempotency release method",
    )
    IDEMPOTENCY.write_text(source, encoding="utf-8")


def patch_service() -> None:
    source = SERVICE.read_text(encoding="utf-8")
    source = replace_once(
        source,
        "from .idempotency import IdempotencyConflict, IdempotencyInProgress, IdempotencyStore\n"
        "from .store import DispatcherStore\n",
        "from .idempotency import IdempotencyConflict, IdempotencyInProgress, IdempotencyStore\n"
        "from .delivery_store import DeliveryStore\n"
        "from .provider_api_v2 import (\n"
        "    PROVIDER_API_OPERATIONS,\n"
        "    ProviderApiV2,\n"
        "    ProviderApiValidationError,\n"
        ")\n"
        "from .store import DispatcherStore\n",
        label="service imports",
    )
    source = replace_once(
        source,
        """    "migration.import_legacy",
    "maintenance.prune",
)
IDEMPOTENT_OPERATIONS = frozenset({
""",
        """    "migration.import_legacy",
    "maintenance.prune",
    *PROVIDER_API_OPERATIONS,
)
IDEMPOTENT_OPERATIONS = frozenset({
""",
        label="service operation allowlist",
    )
    source = replace_once(
        source,
        """    "config.apply", "collector.collect", "admin.execute", "migration.import_legacy",
    "maintenance.prune",
})


""",
        """    "config.apply", "collector.collect", "admin.execute", "migration.import_legacy",
    "maintenance.prune", "provider.v2.renew", "provider.v2.register_recipients",
    "provider.v2.record_recipients", "provider.v2.complete", "provider.v2.heartbeat",
})
ONE_SHOT_SENSITIVE_OPERATIONS = frozenset({"provider.v2.claim"})
PROVIDER_REQUEST_ID_REQUIRED = frozenset(PROVIDER_API_OPERATIONS)


""",
        label="service idempotency sets",
    )
    source = replace_once(
        source,
        """        self.idempotency = IdempotencyStore(config.database_path)
        self._lock = threading.RLock()
""",
        """        self.idempotency = IdempotencyStore(config.database_path)
        self._provider_api: ProviderApiV2 | None = None
        self._lock = threading.RLock()
""",
        label="service provider API slot",
    )
    source = replace_once(
        source,
        """    def _status(self) -> dict[str, Any]:
""",
        """    def _provider_worker_api(self) -> ProviderApiV2:
        if self._provider_api is None:
            self._provider_api = ProviderApiV2(
                DeliveryStore(self.config.database_path, self.key_provider)
            )
        return self._provider_api

    def _status(self) -> dict[str, Any]:
""",
        label="service provider API factory",
    )
    source = replace_once(
        source,
        """        fingerprint = ""
        reservation_active = False
        if operation in IDEMPOTENT_OPERATIONS and request_id:
""",
        """        if operation in PROVIDER_REQUEST_ID_REQUIRED and not request_id:
            return self._error(
                "invalid_request_id",
                "provider v2 mutations require a request_id",
            )

        fingerprint = ""
        reservation_active = False
        operation_exception: Exception | None = None
        if operation in (IDEMPOTENT_OPERATIONS | ONE_SHOT_SENSITIVE_OPERATIONS) and request_id:
""",
        label="service reservation setup",
    )
    source = replace_once(
        source,
        """        except Exception as exc:  # API boundary: never expose internal traceback.
            with self._lock:
""",
        """        except Exception as exc:  # API boundary: never expose internal traceback.
            operation_exception = exc
            with self._lock:
""",
        label="service exception tracking",
    )
    source = replace_once(
        source,
        """        if reservation_active:
            try:
                self.idempotency.complete(request_id, operation, fingerprint, response)
""",
        """        if reservation_active and operation in ONE_SHOT_SENSITIVE_OPERATIONS:
            if isinstance(operation_exception, ProviderApiValidationError):
                try:
                    self.idempotency.release(
                        request_id,
                        operation,
                        fingerprint,
                    )
                except IdempotencyConflict:
                    return self._error(
                        "idempotency_conflict",
                        "request_id was already used with a different operation or body",
                    )
                except Exception:
                    return self._error(
                        "idempotency_persist_failed",
                        "one-shot request reservation could not be released",
                    )
            # A successful or operationally ambiguous claim response contains a
            # secret token and is deliberately never persisted in response_json.
            return response

        if reservation_active:
            try:
                self.idempotency.complete(request_id, operation, fingerprint, response)
""",
        label="service one-shot completion handling",
    )
    source = replace_once(
        source,
        """        if operation == "status.get_redacted":
            return self._status_v2()
""",
        """        if operation == "status.get_redacted":
            return self._status_v2()
        if operation in PROVIDER_API_OPERATIONS:
            return self._provider_worker_api().dispatch(operation, body)
""",
        label="service provider dispatch",
    )
    SERVICE.write_text(source, encoding="utf-8")


def patch_architecture_test() -> None:
    source = ARCHITECTURE_TEST.read_text(encoding="utf-8")
    source = replace_once(
        source,
        """        "migration.import_legacy",
        "maintenance.prune",
    )
""",
        """        "migration.import_legacy",
        "maintenance.prune",
        "provider.v2.claim",
        "provider.v2.renew",
        "provider.v2.register_recipients",
        "provider.v2.record_recipients",
        "provider.v2.complete",
        "provider.v2.heartbeat",
    )
""",
        label="architecture operation tuple",
    )
    ARCHITECTURE_TEST.write_text(source, encoding="utf-8")


def main() -> None:
    patch_idempotency()
    patch_service()
    patch_architecture_test()


if __name__ == "__main__":
    main()
