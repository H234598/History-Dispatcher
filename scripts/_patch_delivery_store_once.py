from __future__ import annotations

from pathlib import Path


PATH = Path("history_dispatcher/delivery_store.py")
PATCH_REVISION = 2


REPLACEMENTS = (
    (
        ") VALUES (?,NULL,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,'ready','',0,?,?, '')",
        ") VALUES (?,NULL,?,?,?,?,?,?,?,?,?,?,?,?,?,?,'ready','',0,?,?,'')",
    ),
    (
        """    @staticmethod
    def _normalize_recipient_ref(value: Any) -> str:
        return TelegramRecipientOutcome(
            recipient_ref=str(value),
            status="failed",
        ).recipient_ref
""",
        """    @staticmethod
    def _normalize_recipient_ref(value: Any) -> str:
        if not isinstance(value, str):
            raise DeliveryStoreError("recipient_ref must be a string")
        return TelegramRecipientOutcome(
            recipient_ref=value,
            status="failed",
        ).recipient_ref
""",
    ),
    (
        """                    "AND td.state IN ('pending','failed_retryable','partial') "
                    "AND (td.next_attempt_at='' OR td.next_attempt_at<=?) "
""",
        """                    "AND (td.state IN ('pending','failed_retryable') OR "
                    "(td.state='partial' AND (td.target_id<>'telegram' OR EXISTS ("
                    "SELECT 1 FROM recipient_deliveries rd "
                    "WHERE rd.target_delivery_id=td.id "
                    "AND rd.state IN ('pending','failed_retryable')"
                    ")))) "
                    "AND (td.next_attempt_at='' OR td.next_attempt_at<=?) "
""",
    ),
    (
        """        open_refs = tuple(
            str(row["recipient_ref"])
            for row in rows
            if str(row["state"]) not in _TERMINAL_RECIPIENT_STATES
        )
""",
        """        open_refs = tuple(
            str(row["recipient_ref"])
            for row in rows
            if str(row["state"]) in {"pending", "claimed", "failed_retryable"}
        )
""",
    ),
    (
        """                if (
                    state is TargetDeliveryState.FAILED_RETRYABLE
                    and attempt_no >= max(1, int(max_attempts))
                ):
""",
        """                if (
                    state
                    in {
                        TargetDeliveryState.FAILED_RETRYABLE,
                        TargetDeliveryState.PARTIAL,
                    }
                    and attempt_no >= max(1, int(max_attempts))
                ):
""",
    ),
    (
        """                next_attempt_at = ""
                if state in {
                    TargetDeliveryState.FAILED_RETRYABLE,
                    TargetDeliveryState.PARTIAL,
                }:
                    delay = max(
""",
        """                next_attempt_at = ""
                retry_delay = 0
                if state in {
                    TargetDeliveryState.FAILED_RETRYABLE,
                    TargetDeliveryState.PARTIAL,
                }:
                    retry_delay = max(
""",
    ),
    (
        """                    next_attempt_at = self._format_time(
                        now_dt + timedelta(seconds=delay)
                    )
""",
        """                    next_attempt_at = self._format_time(
                        now_dt + timedelta(seconds=retry_delay)
                    )
""",
    ),
    (
        """                        max(0, int(retry_after_seconds)),
                        target_delivery_id,
""",
        """                        retry_delay,
                        target_delivery_id,
""",
    ),
)


def main() -> None:
    source = PATH.read_text(encoding="utf-8")
    for old, new in REPLACEMENTS:
        count = source.count(old)
        if count != 1:
            raise SystemExit(
                f"expected exactly one occurrence, found {count}: {old[:80]!r}"
            )
        source = source.replace(old, new, 1)
    PATH.write_text(source, encoding="utf-8")


if __name__ == "__main__":
    main()
