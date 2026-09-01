import json
import logging
import re
from datetime import datetime, timedelta
from typing import Any

from sqlalchemy import and_, or_
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.observability import request_id_context
from app.models import (
    Business,
    BusinessChannelIntegration,
    ChannelOutboxMessage,
    Conversation,
    ConversationMessage,
)
from app.services.channel_provider_service import delivery_supported
from app.services.queue_error_service import QueueErrorClassification, calculate_next_retry

logger = logging.getLogger(__name__)


def create_channel_outbox(
    db: Session,
    *,
    conversation: Conversation,
    message: ConversationMessage,
    provider: str,
    channel: str,
    integration_id: int,
    recipient_external_id: str,
    max_attempts: int,
    payload: dict[str, Any] | None = None,
    idempotency_key: str | None = None,
) -> ChannelOutboxMessage:
    provider = _validated_identifier(provider, field="provider", max_length=40)
    channel = _validated_identifier(channel, field="channel", max_length=40)
    recipient_external_id = recipient_external_id.strip()
    if not recipient_external_id or len(recipient_external_id) > 255:
        raise ValueError("Invalid recipient_external_id")
    if not 1 <= max_attempts <= 20:
        raise ValueError("Invalid max_attempts")
    if message.id is None or message.conversation_id != conversation.id:
        raise ValueError("Conversation message does not belong to the conversation")
    if conversation.channel != channel:
        raise ValueError("Outbox channel does not match the conversation")
    if not delivery_supported(channel=channel, provider=provider):
        raise ValueError("Unsupported channel provider")
    integration = db.get(BusinessChannelIntegration, integration_id)
    if (
        integration is None
        or integration.business_id != conversation.business_id
        or integration.channel != channel
        or integration.provider != provider
    ):
        raise ValueError("Integration does not match the outbox context")
    existing = (
        db.query(ChannelOutboxMessage)
        .filter(ChannelOutboxMessage.conversation_message_id == message.id)
        .first()
    )
    if existing is not None:
        _validate_existing_outbox(
            existing,
            conversation=conversation,
            integration_id=integration_id,
            channel=channel,
            provider=provider,
        )
        return existing
    serialized_payload = json.dumps(
        payload if payload is not None else {"text": message.body},
        ensure_ascii=False,
        separators=(",", ":"),
    )
    expected_idempotency_key = f"{provider}:outbound-message:{message.id}"
    resolved_idempotency_key = (
        idempotency_key.strip() if idempotency_key is not None else expected_idempotency_key
    )
    if resolved_idempotency_key != expected_idempotency_key:
        raise ValueError("Invalid idempotency_key")
    if not resolved_idempotency_key or len(resolved_idempotency_key) > 255:
        raise ValueError("Invalid idempotency_key")
    row = ChannelOutboxMessage(
        business_id=conversation.business_id,
        integration_id=integration_id,
        conversation_id=conversation.id,
        conversation_message_id=message.id,
        channel=channel,
        provider=provider,
        recipient_external_id=recipient_external_id,
        payload_json=serialized_payload,
        idempotency_key=resolved_idempotency_key,
        request_id=request_id_context.get(),
        status="pending",
        max_attempts=max_attempts,
    )
    try:
        with db.begin_nested():
            db.add(row)
            db.flush()
    except IntegrityError:
        existing = (
            db.query(ChannelOutboxMessage)
            .filter(ChannelOutboxMessage.conversation_message_id == message.id)
            .first()
        )
        if existing is None:
            raise
        _validate_existing_outbox(
            existing,
            conversation=conversation,
            integration_id=integration_id,
            channel=channel,
            provider=provider,
        )
        return existing
    return row


def _validated_identifier(value: str, *, field: str, max_length: int) -> str:
    normalized = value.strip().lower()
    if (
        value != normalized
        or len(normalized) > max_length
        or re.fullmatch(r"[a-z][a-z0-9_-]*", normalized) is None
    ):
        raise ValueError(f"Invalid {field}")
    return normalized


def _validate_existing_outbox(
    existing: ChannelOutboxMessage,
    *,
    conversation: Conversation,
    integration_id: int,
    channel: str,
    provider: str,
) -> None:
    if (
        existing.business_id != conversation.business_id
        or existing.conversation_id != conversation.id
        or existing.integration_id != integration_id
        or existing.channel != channel
        or existing.provider != provider
    ):
        raise ValueError("Existing outbox message does not match the requested context")


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
        .join(Business, Business.id == ChannelOutboxMessage.business_id)
        .filter(eligible, Business.status == "active")
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
                if message.opportunity_action is not None:
                    message.opportunity_action.status = "sending"
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
        if message.opportunity_action is not None:
            action = message.opportunity_action
            action.status = "sent" if action.status != "completed" else action.status
            action.sent_at = action.sent_at or current
            action.failed_at = None
            action.failure_reason = None


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
        if message.opportunity_action is not None:
            action = message.opportunity_action
            if row.status == "retry":
                action.status = "approved"
            else:
                action.status = "failed"
                action.failed_at = current
                action.failure_reason = classification.safe_message[:500]
