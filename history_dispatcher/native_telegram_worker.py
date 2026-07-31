from __future__ import annotations

import math
import re
import time
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from typing import Any, Protocol

from .crypto import SecretServiceKeyProvider
from .delivery_store import NATIVE_TELEGRAM_CAPABILITY_V1
from .identifiers import persistent_opaque_id
from .telegram_bot_api import (
    TelegramApiPossibleDuplicate,
    TelegramApiRateLimited,
    TelegramApiRejected,
    TelegramApiSuccess,
    TelegramBotApiClient,
)
from .telegram_formatter import (
    FormattedTelegramDelivery,
    TelegramFormattingError,
    format_telegram_delivery,
)
from .telegram_provider import TelegramRecipientOutcome
from .telegram_secrets import NativeTelegramSecretStore, TelegramSecretError


NATIVE_TARGET_ID = "telegram"
NATIVE_PROVIDER_ID = "history_dispatcher"
DEFAULT_CLAIM_LIMIT = 20
DEFAULT_LEASE_SECONDS = 120
DEFAULT_MAX_CLAIM_LIFETIME_SECONDS = 1800
DEFAULT_MAX_ATTEMPTS = 8
DEFAULT_BASE_BACKOFF_SECONDS = 5
DEFAULT_MAX_BACKOFF_SECONDS = 3600
DEFAULT_JITTER_RATIO = 0.20
DEFAULT_IDLE_SECONDS = 5.0
MAX_RETRY_AFTER_SECONDS = 7 * 24 * 3600

_REASON_RE = re.compile(r"^[a-z][a-z0-9_]{0,95}$")
_SENDABLE_RECIPIENT_STATES = frozenset(
    {"pending", "claimed", "failed_retryable"}
)
_TERMINAL_RECIPIENT_STATES = frozenset(
    {
        "accepted",
        "delivered",
        "acknowledged",
        "failed_terminal",
        "quarantined",
        "skipped",
        "possible_duplicate",
        "legacy_hold",
    }
)


class ProviderApiProtocol(Protocol):
    def dispatch(self, operation: str, body: Mapping[str, Any]) -> dict[str, Any]: ...


class TelegramSecretStoreProtocol(Protocol):
    def lookup_bot_token(self, profile_ref: str) -> str: ...
    def lookup_chat_id(self, profile_ref: str) -> str: ...


class TelegramClientProtocol(Protocol):
    def send_message(self, token: str, chat_id: str, text: str) -> object: ...
    def send_document(
        self,
        token: str,
        chat_id: str,
        filename: str,
        document: bytes,
        caption: str,
    ) -> object: ...


@dataclass(frozen=True)
class NativeTelegramWorkerReport:
    claimed: int = 0
    delivered: int = 0
    failed: int = 0
    possible_duplicate: int = 0
    rate_limited: int = 0
    skipped: int = 0


class TelegramRateLimiter:
    def __init__(
        self,
        *,
        clock: Callable[[], float] | None = None,
        sleeper: Callable[[float], None] | None = None,
        per_recipient_seconds: float = 1.05,
        global_seconds: float = 0.04,
    ) -> None:
        if (
            not math.isfinite(per_recipient_seconds)
            or not math.isfinite(global_seconds)
            or per_recipient_seconds < 0.0
            or global_seconds < 0.0
        ):
            raise ValueError("Telegram rate-limit interval is invalid")
        self._clock = clock or time.monotonic
        self._sleeper = sleeper or time.sleep
        self._per_recipient_seconds = float(per_recipient_seconds)
        self._global_seconds = float(global_seconds)
        self._last_global: float | None = None
        self._last_recipient: dict[str, float] = {}

    def wait(self, recipient_ref: str) -> None:
        now = float(self._clock())
        deadline = now
        if self._last_global is not None:
            deadline = max(deadline, self._last_global + self._global_seconds)
        previous = self._last_recipient.get(recipient_ref)
        if previous is not None:
            deadline = max(deadline, previous + self._per_recipient_seconds)
        delay = round(max(0.0, deadline - now), 6)
        if delay > 0.0:
            self._sleeper(delay)
        sent_at = float(self._clock())
        self._last_global = sent_at
        self._last_recipient[recipient_ref] = sent_at


@dataclass
class _MutableReport:
    claimed: int = 0
    delivered: int = 0
    failed: int = 0
    possible_duplicate: int = 0
    rate_limited: int = 0
    skipped: int = 0

    def freeze(self) -> NativeTelegramWorkerReport:
        return NativeTelegramWorkerReport(
            claimed=self.claimed,
            delivered=self.delivered,
            failed=self.failed,
            possible_duplicate=self.possible_duplicate,
            rate_limited=self.rate_limited,
            skipped=self.skipped,
        )


class NativeTelegramWorker:
    def __init__(
        self,
        *,
        provider_api: ProviderApiProtocol,
        secret_store: TelegramSecretStoreProtocol | None = None,
        client: TelegramClientProtocol | None = None,
        key_provider: SecretServiceKeyProvider,
        worker_id: str,
        formatter: Callable[..., FormattedTelegramDelivery] | None = None,
        rate_limiter: TelegramRateLimiter | None = None,
        sleeper: Callable[[float], None] | None = None,
        idle_seconds: float = DEFAULT_IDLE_SECONDS,
        claim_limit: int = DEFAULT_CLAIM_LIMIT,
        lease_seconds: int = DEFAULT_LEASE_SECONDS,
        max_attempts: int = DEFAULT_MAX_ATTEMPTS,
        base_backoff_seconds: int = DEFAULT_BASE_BACKOFF_SECONDS,
        max_backoff_seconds: int = DEFAULT_MAX_BACKOFF_SECONDS,
        jitter_ratio: float = DEFAULT_JITTER_RATIO,
    ) -> None:
        if not isinstance(worker_id, str) or not worker_id.strip():
            raise ValueError("native Telegram worker_id is invalid")
        if not math.isfinite(idle_seconds) or idle_seconds < 0.1 or idle_seconds > 3600:
            raise ValueError("native Telegram idle interval is invalid")
        self.provider_api = provider_api
        self.secret_store = secret_store or NativeTelegramSecretStore()
        self.client = client or TelegramBotApiClient()
        self.key_provider = key_provider
        self.worker_id = worker_id.strip()
        self.formatter = formatter or format_telegram_delivery
        self.rate_limiter = rate_limiter or TelegramRateLimiter()
        self._sleeper = sleeper or time.sleep
        self.idle_seconds = float(idle_seconds)
        self.claim_limit = max(1, min(int(claim_limit), 100))
        self.lease_seconds = max(10, min(int(lease_seconds), 1800))
        self.max_attempts = max(1, min(int(max_attempts), 100))
        self.base_backoff_seconds = max(1, min(int(base_backoff_seconds), 86400))
        self.max_backoff_seconds = max(
            self.base_backoff_seconds,
            min(int(max_backoff_seconds), MAX_RETRY_AFTER_SECONDS),
        )
        self.jitter_ratio = max(0.0, min(float(jitter_ratio), 0.5))

    def run_once(self) -> NativeTelegramWorkerReport:
        report = _MutableReport()
        blocked = False
        self._heartbeat("starting", report)
        response = self.provider_api.dispatch(
            "provider.v2.claim",
            {
                "target_id": NATIVE_TARGET_ID,
                "provider_id": NATIVE_PROVIDER_ID,
                "worker_id": self.worker_id,
                "capability_version": NATIVE_TELEGRAM_CAPABILITY_V1,
                "limit": self.claim_limit,
                "lease_seconds": self.lease_seconds,
                "max_attempts": self.max_attempts,
                "base_backoff_seconds": self.base_backoff_seconds,
                "max_backoff_seconds": self.max_backoff_seconds,
                "jitter_ratio": self.jitter_ratio,
            },
        )
        raw_claims = response.get("claims", []) if isinstance(response, Mapping) else []
        if not isinstance(raw_claims, Sequence) or isinstance(
            raw_claims,
            (str, bytes, bytearray),
        ):
            raw_claims = []
            blocked = True
        for raw_claim in raw_claims:
            report.claimed += 1
            if not isinstance(raw_claim, Mapping):
                report.failed += 1
                blocked = True
                continue
            claim = dict(raw_claim)
            invalid_reason = self._claim_invalid_reason(claim)
            if invalid_reason:
                report.failed += 1
                blocked = True
                self._complete(
                    claim,
                    outcome="quarantined",
                    error_class=invalid_reason,
                    retry_after_seconds=0,
                )
                continue
            claim_blocked = self._process_claim(claim, report)
            blocked = blocked or claim_blocked
        final_state = (
            "blocked"
            if blocked
            else "degraded"
            if report.failed or report.possible_duplicate or report.rate_limited
            else "idle"
        )
        self._heartbeat(final_state, report)
        return report.freeze()

    def run_forever(self, stop_event: Any) -> None:
        while not bool(stop_event.is_set()):
            self.run_once()
            if bool(stop_event.is_set()):
                break
            self._sleeper(self.idle_seconds)

    def _process_claim(
        self,
        claim: dict[str, Any],
        report: _MutableReport,
    ) -> bool:
        binding = dict(claim["binding"])
        successful = {
            str(value)
            for value in claim.get("successful_recipient_refs", [])
            if isinstance(value, str)
        }
        planned = tuple(
            dict.fromkeys(
                str(value)
                for value in binding.get("recipient_refs", [])
                if isinstance(value, str) and value not in successful
            )
        )
        if not planned:
            report.skipped += max(1, len(successful))
            self._complete(claim, outcome=None, error_class="", retry_after_seconds=0)
            return False

        try:
            formatted = self.formatter(
                dict(claim["payload"]),
                event_id=str(claim["event_id"]),
            )
        except TelegramFormattingError as exc:
            self._record_terminal_format_failure(claim, planned, str(exc), report)
            return False
        except Exception:
            self._record_terminal_format_failure(
                claim,
                planned,
                "payload_format_failed",
                report,
            )
            return False

        registration = self.provider_api.dispatch(
            "provider.v2.register_recipients",
            {
                "target_delivery_id": str(claim["target_delivery_id"]),
                "worker_id": self.worker_id,
                "claim_token": str(claim["claim_token"]),
                "recipient_refs": list(planned),
            },
        )
        snapshots = registration.get("recipients", [])
        if not isinstance(snapshots, Sequence) or isinstance(
            snapshots,
            (str, bytes, bytearray),
        ):
            report.failed += len(planned)
            self._complete(
                claim,
                outcome="quarantined",
                error_class="recipient_state_invalid",
                retry_after_seconds=0,
            )
            return True
        state_by_ref: dict[str, str] = {}
        for snapshot in snapshots:
            if not isinstance(snapshot, Mapping):
                continue
            recipient_ref = snapshot.get("recipient_ref")
            state = snapshot.get("state")
            if isinstance(recipient_ref, str) and isinstance(state, str):
                state_by_ref[recipient_ref] = state

        max_retry_after = 0
        failure_reasons: list[str] = []
        for recipient_ref in planned:
            state = state_by_ref.get(recipient_ref, "")
            if state in _TERMINAL_RECIPIENT_STATES:
                report.skipped += 1
                continue
            if state not in _SENDABLE_RECIPIENT_STATES:
                report.failed += 1
                failure_reasons.append("recipient_state_invalid")
                continue
            self.provider_api.dispatch(
                "provider.v2.renew",
                {
                    "target_delivery_id": str(claim["target_delivery_id"]),
                    "worker_id": self.worker_id,
                    "claim_token": str(claim["claim_token"]),
                    "lease_seconds": self.lease_seconds,
                    "max_claim_lifetime_seconds": DEFAULT_MAX_CLAIM_LIFETIME_SECONDS,
                },
            )
            try:
                token = self.secret_store.lookup_bot_token(
                    str(binding["credential_ref"])
                )
                chat_id = self.secret_store.lookup_chat_id(recipient_ref)
            except TelegramSecretError:
                outcome = self._outcome(
                    recipient_ref,
                    status="failed",
                    reason_code="credential_unavailable",
                )
                report.failed += 1
                failure_reasons.append("credential_unavailable")
                self._record(claim, outcome)
                continue
            except Exception:
                outcome = self._outcome(
                    recipient_ref,
                    status="failed",
                    reason_code="credential_unavailable",
                )
                report.failed += 1
                failure_reasons.append("credential_unavailable")
                self._record(claim, outcome)
                continue

            self.rate_limiter.wait(recipient_ref)
            result = self._send(formatted, token, chat_id)
            outcome, retry_after = self._map_result(recipient_ref, result)
            if outcome.status == "delivered":
                report.delivered += 1
            elif outcome.status == "possible_duplicate":
                report.possible_duplicate += 1
                failure_reasons.append(outcome.reason_code)
            else:
                report.failed += 1
                failure_reasons.append(outcome.reason_code)
                if outcome.reason_code == "rate_limited":
                    report.rate_limited += 1
            max_retry_after = max(max_retry_after, retry_after)
            self._record(claim, outcome)

        error_class = self._completion_reason(
            failure_reasons,
            max_retry_after=max_retry_after,
        )
        self._complete(
            claim,
            outcome=None,
            error_class=error_class,
            retry_after_seconds=max_retry_after,
        )
        return False

    def _send(
        self,
        formatted: FormattedTelegramDelivery,
        token: str,
        chat_id: str,
    ) -> object:
        if formatted.mode == "text":
            return self.client.send_message(token, chat_id, formatted.text)
        if formatted.mode == "document":
            return self.client.send_document(
                token,
                chat_id,
                formatted.filename,
                formatted.document,
                formatted.caption,
            )
        return TelegramApiPossibleDuplicate("telegram_format_mode_unknown")

    def _map_result(
        self,
        recipient_ref: str,
        result: object,
    ) -> tuple[TelegramRecipientOutcome, int]:
        if isinstance(result, TelegramApiSuccess):
            message_ref = persistent_opaque_id(
                self.key_provider,
                "telegram-message-ref",
                f"{recipient_ref}|{result.message_id}",
                prefix="message",
            )
            return (
                self._outcome(
                    recipient_ref,
                    status="delivered",
                    message_ref_key=message_ref,
                ),
                0,
            )
        if isinstance(result, TelegramApiRateLimited):
            retry_after = max(
                1,
                min(int(result.retry_after_seconds), MAX_RETRY_AFTER_SECONDS),
            )
            return (
                self._outcome(
                    recipient_ref,
                    status="failed",
                    reason_code="rate_limited",
                ),
                retry_after,
            )
        if isinstance(result, TelegramApiPossibleDuplicate):
            return (
                self._outcome(
                    recipient_ref,
                    status="possible_duplicate",
                    possible_duplicate=True,
                    reason_code=self._reason(result.reason_code),
                ),
                0,
            )
        if isinstance(result, TelegramApiRejected):
            return (
                self._outcome(
                    recipient_ref,
                    status="failed" if result.retryable else "failed_terminal",
                    reason_code=self._reason(result.reason_code),
                ),
                0,
            )
        return (
            self._outcome(
                recipient_ref,
                status="possible_duplicate",
                possible_duplicate=True,
                reason_code="telegram_result_unknown",
            ),
            0,
        )

    @staticmethod
    def _outcome(
        recipient_ref: str,
        *,
        status: str,
        possible_duplicate: bool = False,
        message_ref_key: str = "",
        reason_code: str = "",
    ) -> TelegramRecipientOutcome:
        return TelegramRecipientOutcome(
            recipient_ref=recipient_ref,
            status=status,
            possible_duplicate=possible_duplicate,
            message_ref_key=message_ref_key,
            reason_code=reason_code,
        )

    def _record(
        self,
        claim: Mapping[str, Any],
        outcome: TelegramRecipientOutcome,
    ) -> None:
        self.provider_api.dispatch(
            "provider.v2.record_recipients",
            {
                "target_delivery_id": str(claim["target_delivery_id"]),
                "worker_id": self.worker_id,
                "claim_token": str(claim["claim_token"]),
                "outcomes": [
                    {
                        "recipient_ref": outcome.recipient_ref,
                        "status": outcome.status,
                        "possible_duplicate": outcome.possible_duplicate,
                        "message_ref_key": outcome.message_ref_key,
                        "reason_code": outcome.reason_code,
                    }
                ],
            },
        )

    def _record_terminal_format_failure(
        self,
        claim: Mapping[str, Any],
        recipients: Sequence[str],
        reason: str,
        report: _MutableReport,
    ) -> None:
        safe_reason = self._reason(reason, fallback="payload_format_failed")
        self.provider_api.dispatch(
            "provider.v2.register_recipients",
            {
                "target_delivery_id": str(claim["target_delivery_id"]),
                "worker_id": self.worker_id,
                "claim_token": str(claim["claim_token"]),
                "recipient_refs": list(recipients),
            },
        )
        for recipient_ref in recipients:
            self._record(
                claim,
                self._outcome(
                    recipient_ref,
                    status="failed_terminal",
                    reason_code=safe_reason,
                ),
            )
            report.failed += 1
        self._complete(
            claim,
            outcome=None,
            error_class=safe_reason,
            retry_after_seconds=0,
        )

    def _complete(
        self,
        claim: Mapping[str, Any],
        *,
        outcome: str | None,
        error_class: str,
        retry_after_seconds: int,
    ) -> None:
        self.provider_api.dispatch(
            "provider.v2.complete",
            {
                "target_delivery_id": str(claim.get("target_delivery_id") or ""),
                "worker_id": self.worker_id,
                "claim_token": str(claim.get("claim_token") or ""),
                "outcome": outcome,
                "error_class": self._reason(error_class, fallback=""),
                "retry_after_seconds": max(
                    0,
                    min(int(retry_after_seconds), MAX_RETRY_AFTER_SECONDS),
                ),
                "max_attempts": self.max_attempts,
                "base_backoff_seconds": self.base_backoff_seconds,
                "max_backoff_seconds": self.max_backoff_seconds,
                "jitter_ratio": self.jitter_ratio,
            },
        )

    def _heartbeat(self, state: str, report: _MutableReport) -> None:
        self.provider_api.dispatch(
            "provider.v2.heartbeat",
            {
                "worker_id": self.worker_id,
                "target_id": NATIVE_TARGET_ID,
                "provider_id": NATIVE_PROVIDER_ID,
                "capability_version": NATIVE_TELEGRAM_CAPABILITY_V1,
                "state": state,
                "details": {
                    "claimed": report.claimed,
                    "delivered": report.delivered,
                    "failed": report.failed,
                    "possible_duplicate": report.possible_duplicate,
                    "rate_limited": report.rate_limited,
                    "skipped": report.skipped,
                },
            },
        )

    def _claim_invalid_reason(self, claim: Mapping[str, Any]) -> str:
        if str(claim.get("target_id") or "") != NATIVE_TARGET_ID:
            return "target_mismatch"
        if str(claim.get("provider_id") or "") != NATIVE_PROVIDER_ID:
            return "provider_mismatch"
        if (
            str(claim.get("capability_version") or "")
            != NATIVE_TELEGRAM_CAPABILITY_V1
        ):
            return "capability_mismatch"
        if str(claim.get("worker_id") or "") != self.worker_id:
            return "worker_mismatch"
        if bool(claim.get("reconciliation_only")):
            return "reconciliation_only"
        binding = claim.get("binding")
        if not isinstance(binding, Mapping):
            return "binding_invalid"
        if str(binding.get("provider") or "") != NATIVE_PROVIDER_ID:
            return "binding_provider_mismatch"
        credential_ref = binding.get("credential_ref")
        recipients = binding.get("recipient_refs")
        if not isinstance(credential_ref, str) or not credential_ref:
            return "credential_binding_invalid"
        if not isinstance(recipients, Sequence) or isinstance(
            recipients,
            (str, bytes, bytearray),
        ):
            return "recipient_binding_invalid"
        if not isinstance(claim.get("payload"), Mapping):
            return "payload_invalid"
        return ""

    @staticmethod
    def _completion_reason(
        reasons: Sequence[str],
        *,
        max_retry_after: int,
    ) -> str:
        if max_retry_after > 0:
            return "rate_limited"
        if "telegram_accept_unknown" in reasons:
            return "possible_duplicate"
        return reasons[0] if reasons else ""

    @staticmethod
    def _reason(value: object, *, fallback: str = "telegram_error") -> str:
        normalized = str(value or "").strip().casefold()
        if normalized and _REASON_RE.fullmatch(normalized):
            return normalized
        return fallback
