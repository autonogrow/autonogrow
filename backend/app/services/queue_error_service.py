import random
from dataclasses import dataclass
from datetime import datetime, timedelta


@dataclass(frozen=True)
class QueueErrorClassification:
    code: str
    retryable: bool
    blocked: bool = False
    safe_message: str = "Queue operation failed"


RETRYABLE_HTTP_STATUSES = {408, 429, 500, 502, 503, 504}
BLOCKED_CODES = {
    "190",
    "integration_not_configured",
    "integration_expired",
    "integration_disconnected",
    "integration_revoked",
    "integration_unavailable",
    "integration_decryption_failed",
    "invalid_recipient",
    "insufficient_permissions",
    "token_expired",
    "token_revoked",
    "account_suspended",
    "invalid_phone_number_id",
    "number_not_registered",
    "whatsapp_template_required",
}
BACKOFF_SECONDS = (30, 120, 600, 1800, 7200)


def classify_queue_error(
    *,
    error_code: str | None = None,
    http_status: int | None = None,
    timed_out: bool = False,
    database_locked: bool = False,
) -> QueueErrorClassification:
    code = (error_code or "queue_processing_failed").strip().lower()
    if timed_out:
        return QueueErrorClassification("provider_timeout", True, safe_message="Provider timed out")
    if database_locked:
        return QueueErrorClassification(
            "worker_database_locked", True, safe_message="Database is temporarily busy"
        )
    if http_status in RETRYABLE_HTTP_STATUSES:
        return QueueErrorClassification(
            "provider_rate_limited" if http_status == 429 else f"provider_http_{http_status}",
            True,
            safe_message="Provider is temporarily unavailable",
        )
    if code in BLOCKED_CODES or http_status in {401, 403}:
        return QueueErrorClassification(code, False, True, "Integration is unavailable")
    if code in {
        "connection_error",
        "provider_rate_limited",
        "provider_unavailable",
        "request_failed",
    }:
        return QueueErrorClassification(
            code, True, safe_message="Provider is temporarily unavailable"
        )
    return QueueErrorClassification(code, False, safe_message="Queue operation failed permanently")


def calculate_next_retry(
    attempt_count: int,
    *,
    now: datetime | None = None,
    random_value: float | None = None,
) -> datetime:
    base = BACKOFF_SECONDS[min(max(attempt_count, 1) - 1, len(BACKOFF_SECONDS) - 1)]
    sample = random.random() if random_value is None else min(max(random_value, 0.0), 1.0)
    jitter_multiplier = 0.9 + sample * 0.2
    return (now or datetime.utcnow()) + timedelta(seconds=base * jitter_multiplier)
