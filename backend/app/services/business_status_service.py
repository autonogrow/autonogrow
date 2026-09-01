from __future__ import annotations

from datetime import datetime

from fastapi import HTTPException
from sqlalchemy.orm import Session

from app.models import (
    Business,
    ChannelOutboxMessage,
    ConversationMessage,
    InstagramPublishJob,
    MetaIntegrationJob,
)

OPERATIONAL_BUSINESS_STATUS = "active"
BUSINESS_NOT_OPERATIONAL_CODE = "business_not_operational"
BUSINESS_NOT_OPERATIONAL_MESSAGE = (
    "Este negocio no está activo. Las operaciones están temporalmente deshabilitadas."
)


def business_not_operational_detail(business: Business) -> dict[str, str]:
    return {
        "code": BUSINESS_NOT_OPERATIONAL_CODE,
        "message": BUSINESS_NOT_OPERATIONAL_MESSAGE,
        "business_status": business.status,
    }


def ensure_business_operational(business: Business) -> None:
    if business.status != OPERATIONAL_BUSINESS_STATUS:
        raise HTTPException(status_code=403, detail=business_not_operational_detail(business))


def freeze_business_jobs(db: Session, business: Business) -> dict[str, int]:
    """Stop safely-recoverable queued work without deleting operational history.

    Reactivation deliberately does not requeue these rows. An operator must review and retry
    work explicitly so stale messages or publications are not emitted after a long suspension.
    """

    now = datetime.utcnow()
    outbox_rows = (
        db.query(ChannelOutboxMessage)
        .filter(
            ChannelOutboxMessage.business_id == business.id,
            ChannelOutboxMessage.status.in_(("pending", "retry", "processing")),
        )
        .all()
    )
    for row in outbox_rows:
        row.status = "blocked"
        row.failed_at = now
        row.next_retry_at = None
        row.locked_by = None
        row.lock_expires_at = None
        row.last_error_code = BUSINESS_NOT_OPERATIONAL_CODE
        row.safe_error_message = BUSINESS_NOT_OPERATIONAL_MESSAGE
        row.updated_at = now
        if row.conversation_message_id:
            message = db.get(ConversationMessage, row.conversation_message_id)
            if message is not None and message.delivery_status not in {"sent", "delivered"}:
                message.delivery_status = "blocked"

    publication_rows = (
        db.query(InstagramPublishJob)
        .filter(
            InstagramPublishJob.business_id == business.id,
            InstagramPublishJob.status.in_(
                ("queued", "retry_wait", "claimed", "simulating_publish")
            ),
        )
        .all()
    )
    for row in publication_rows:
        row.status = "action_required"
        row.provider_status = "business_not_operational"
        row.provider_error_code = BUSINESS_NOT_OPERATIONAL_CODE
        row.safe_error_message = BUSINESS_NOT_OPERATIONAL_MESSAGE
        row.claimed_at = None
        row.claim_expires_at = None
        row.claimed_by = None
        row.next_attempt_at = None

    meta_rows = (
        db.query(MetaIntegrationJob)
        .filter(
            MetaIntegrationJob.business_id == business.id,
            MetaIntegrationJob.status.in_(("queued", "retry", "processing")),
        )
        .all()
    )
    for row in meta_rows:
        row.status = "failed"
        row.failed_at = now
        row.next_retry_at = None
        row.locked_by = None
        row.lock_expires_at = None
        row.last_error_code = BUSINESS_NOT_OPERATIONAL_CODE
        row.safe_error_message = BUSINESS_NOT_OPERATIONAL_MESSAGE
        row.updated_at = now

    db.flush()
    return {
        "outbox_blocked": len(outbox_rows),
        "publications_held": len(publication_rows),
        "meta_jobs_stopped": len(meta_rows),
    }
