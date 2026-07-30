import json
import logging
from datetime import datetime, timedelta

from sqlalchemy import and_, or_
from sqlalchemy.orm import Session

from app.core.observability import request_id_context
from app.models import ChannelOutboxMessage, Conversation, ConversationMessage
from app.services.queue_error_service import QueueErrorClassification, calculate_next_retry

logger = logging.getLogger(__name__)


def create_channel_outbox(
    db: Session,
    *,
    conversation: Conversation,
    message: ConversationMessage,
    integration_id: int,
    recipient_external_id: str,
    max_attempts: int,
) -> ChannelOutboxMessage:
    row = ChannelOutboxMessage(
        business_id=conversation.business_id,
        integration_id=integration_id,
        conversation_id=conversation.id,
        conversation_message_id=message.id,
        channel=conversation.channel,
        provider="instagram",
        recipient_external_id=recipient_external_id,
        payload_json=json.dumps({"text": message.body}, ensure_ascii=False),
        idempotency_key=f"instagram:outbound-message:{message.id}",
        request_id=request_id_context.get(),
        status="pending",
        max_attempts=max_attempts,
    )
    db.add(row)
    db.flush()
    return row


def claim_outbox_jobs(
    db: Session,
    *,
    worker_id: str,
    limit: int,
    lock_timeout_seconds: int,
    now: datetime | None = None,
) -> list[int]:
    current = now or datetime.utcnow()
    eligible = or_(
        and_(
            ChannelOutboxMessage.status == "pending", ChannelOutboxMessage.available_at <= current
        ),
        and_(ChannelOutboxMessage.status == "retry", ChannelOutboxMessage.next_retry_at <= current),
        and_(
            ChannelOutboxMessage.status == "processing",
            ChannelOutboxMessage.lock_expires_at < current,
        ),
    )
    query = (
        db.query(ChannelOutboxMessage)
        .filter(eligible)
        .order_by(ChannelOutboxMessage.available_at, ChannelOutboxMessage.id)
        .limit(limit)
    )
    if db.get_bind().dialect.name == "postgresql":
        query = query.with_for_update(skip_locked=True)
    rows = query.all()
    expires = current + timedelta(seconds=lock_timeout_seconds)
    for row in rows:
        if row.status == "processing":
            logger.warning(
                "expired_lock_recovered job_type=outbox outbox_id=%s previous_worker=%s attempt=%s",
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
        if row.conversation_message_id:
            message = db.get(ConversationMessage, row.conversation_message_id)
            if message:
                message.delivery_status = "processing"
    db.flush()
    return [row.id for row in rows]


def finish_outbox_job(
    row: ChannelOutboxMessage,
    message: ConversationMessage | None,
    *,
    provider_message_id: str | None,
    now: datetime | None = None,
) -> None:
    current = now or datetime.utcnow()
    row.status = "sent"
    row.sent_at = current
    row.provider_message_id = provider_message_id
    row.locked_by = None
    row.lock_expires_at = None
    row.next_retry_at = None
    row.safe_error_message = None
    row.updated_at = current
    if message:
        message.delivery_status = "sent"
        message.provider_message_id = provider_message_id


def fail_outbox_job(
    row: ChannelOutboxMessage,
    message: ConversationMessage | None,
    *,
    classification: QueueErrorClassification,
    http_status: int | None = None,
    error_subcode: str | None = None,
    error_type: str | None = None,
    now: datetime | None = None,
) -> None:
    current = now or datetime.utcnow()
    exhausted = row.attempt_count >= row.max_attempts
    if classification.blocked:
        row.status = "blocked"
    elif classification.retryable and not exhausted:
        row.status = "retry"
    elif exhausted:
        row.status = "dead_letter"
    else:
        row.status = "failed"
    row.next_retry_at = (
        calculate_next_retry(row.attempt_count, now=current) if row.status == "retry" else None
    )
    row.failed_at = current if row.status in {"blocked", "failed", "dead_letter"} else None
    row.last_http_status = http_status
    row.last_error_code = classification.code[:120]
    row.last_error_subcode = error_subcode[:120] if error_subcode else None
    row.last_error_type = error_type[:120] if error_type else None
    row.safe_error_message = classification.safe_message[:500]
    row.locked_by = None
    row.lock_expires_at = None
    row.updated_at = current
    if message:
        message.delivery_status = {"retry": "retry", "blocked": "blocked"}.get(row.status, "failed")
