import hashlib
import json
import logging
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any

from sqlalchemy import and_, or_
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.models import WebhookInboxEvent
from app.services.instagram_provider import parse_instagram_webhook
from app.services.queue_error_service import calculate_next_retry

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class ExtractedWebhookEvent:
    event_type: str
    provider_event_id: str | None
    idempotency_key: str
    payload_hash: str
    payload_json: str
    payload_size_bytes: int


def extract_instagram_webhook_events(payload: dict[str, Any]) -> list[ExtractedWebhookEvent]:
    result: list[ExtractedWebhookEvent] = []
    for event in parse_instagram_webhook(payload):
        serialized = json.dumps(
            event.raw_payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")
        )
        encoded = serialized.encode("utf-8")
        payload_hash = hashlib.sha256(encoded).hexdigest()
        event_type = "echo" if event.is_echo else "message"
        provider_event_id = event.message_id
        if event.message_id:
            idempotency_key = f"instagram:message:{event.message_id}"
        else:
            event_id = event.raw_payload.get("id")
            if event_id:
                provider_event_id = str(event_id)
                idempotency_key = f"instagram:event:{event_id}"
            else:
                stable = f"instagram|{event_type}|{event.sender_id}|{event.recipient_id}|{event.timestamp}|{payload_hash}"
                idempotency_key = "instagram:derived:" + hashlib.sha256(stable.encode()).hexdigest()
        result.append(
            ExtractedWebhookEvent(
                event_type=event_type,
                provider_event_id=provider_event_id,
                idempotency_key=idempotency_key[:255],
                payload_hash=payload_hash,
                payload_json=serialized,
                payload_size_bytes=len(encoded),
            )
        )
    return result


def enqueue_instagram_events(
    db: Session, events: list[ExtractedWebhookEvent], *, max_attempts: int
) -> tuple[int, int]:
    accepted = duplicates = 0
    for extracted in events:
        try:
            with db.begin_nested():
                db.add(
                    WebhookInboxEvent(
                        provider="instagram",
                        channel="instagram",
                        event_type=extracted.event_type,
                        provider_event_id=extracted.provider_event_id,
                        idempotency_key=extracted.idempotency_key,
                        payload_hash=extracted.payload_hash,
                        payload_json=extracted.payload_json,
                        payload_size_bytes=extracted.payload_size_bytes,
                        status="pending",
                        max_attempts=max_attempts,
                    )
                )
                db.flush()
            accepted += 1
        except IntegrityError:
            duplicates += 1
    return accepted, duplicates


def claim_inbox_jobs(
    db: Session,
    *,
    worker_id: str,
    limit: int,
    lock_timeout_seconds: int,
    now: datetime | None = None,
) -> list[int]:
    current = now or datetime.utcnow()
    eligible = or_(
        and_(WebhookInboxEvent.status == "pending", WebhookInboxEvent.available_at <= current),
        and_(WebhookInboxEvent.status == "retry", WebhookInboxEvent.next_retry_at <= current),
        and_(WebhookInboxEvent.status == "processing", WebhookInboxEvent.lock_expires_at < current),
    )
    rows = (
        db.query(WebhookInboxEvent)
        .filter(eligible)
        .order_by(WebhookInboxEvent.available_at, WebhookInboxEvent.id)
        .limit(limit)
        .all()
    )
    expires = current + timedelta(seconds=lock_timeout_seconds)
    for row in rows:
        if row.status == "processing":
            logger.warning(
                "expired_lock_recovered job_type=inbox inbox_id=%s previous_worker=%s attempt=%s",
                row.id,
                row.locked_by,
                row.attempt_count + 1,
            )
        row.status = "processing"
        row.locked_by = worker_id
        row.lock_expires_at = expires
        row.processing_started_at = current
        row.attempt_count += 1
        row.updated_at = current
    db.flush()
    return [row.id for row in rows]


def finish_inbox_job(
    row: WebhookInboxEvent, *, status: str = "processed", now: datetime | None = None
) -> None:
    current = now or datetime.utcnow()
    row.status = status
    row.processed_at = current
    row.locked_by = None
    row.lock_expires_at = None
    row.next_retry_at = None
    row.updated_at = current


def fail_inbox_job(
    row: WebhookInboxEvent,
    *,
    error_code: str,
    safe_message: str,
    retryable: bool,
    now: datetime | None = None,
) -> None:
    current = now or datetime.utcnow()
    exhausted = row.attempt_count >= row.max_attempts
    row.status = (
        "retry" if retryable and not exhausted else ("dead_letter" if exhausted else "failed")
    )
    row.next_retry_at = (
        calculate_next_retry(row.attempt_count, now=current) if row.status == "retry" else None
    )
    row.failed_at = current if row.status in {"failed", "dead_letter"} else None
    row.last_error_code = error_code[:120]
    row.safe_error_message = safe_message[:500]
    row.locked_by = None
    row.lock_expires_at = None
    row.updated_at = current
