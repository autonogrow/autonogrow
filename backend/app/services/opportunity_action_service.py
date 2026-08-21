from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.models import (
    Business,
    ChannelOutboxMessage,
    Conversation,
    CustomerOpportunity,
    OpportunityAction,
)
from app.services.conversation_service import (
    ConversationDeliveryCapabilities,
    conversation_delivery_capabilities,
)
from app.services.customer_identity_service import normalize_phone
from app.services.message_outbox_service import build_whatsapp_url
from app.services.opportunity_template_service import (
    OpportunityMessageTemplateService,
    booking_url,
)

DRAFT_TTL = timedelta(days=7)


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _normalized_phone(value: str | None) -> str:
    return normalize_phone(value, region="ES") or ""


@dataclass(frozen=True)
class ActionChannelResolution:
    conversation: Conversation | None
    capabilities: ConversationDeliveryCapabilities | None
    assisted_phone: str | None = None

    @property
    def channel(self) -> str | None:
        return self.conversation.channel if self.conversation is not None else None

    @property
    def can_send(self) -> bool:
        return bool(
            self.capabilities is not None
            and self.capabilities.integrated_delivery_available
        )

    @property
    def assisted_delivery_available(self) -> bool:
        if self.capabilities is not None:
            return self.capabilities.assisted_delivery_available
        try:
            build_whatsapp_url(self.assisted_phone, "test")
        except ValueError:
            return False
        return True

    @property
    def delivery_mode(self) -> str:
        if self.can_send:
            return "integrated"
        if self.assisted_delivery_available:
            return "assisted"
        return "unavailable"

    @property
    def unavailable_reason(self) -> str | None:
        if self.conversation is None:
            return "no_customer_channel"
        if self.capabilities is None:
            return "delivery_not_available"
        return self.capabilities.unavailable_reason


def resolve_action_channel(
    db: Session,
    *,
    opportunity: CustomerOpportunity,
    requested_conversation_id: int | None = None,
) -> ActionChannelResolution:
    candidates: list[Conversation] = []
    if requested_conversation_id is not None:
        requested = (
            db.query(Conversation)
            .filter(
                Conversation.id == requested_conversation_id,
                Conversation.business_id == opportunity.business_id,
            )
            .first()
        )
        if requested is None:
            raise ValueError("conversation_not_found")
        customer_phone = _normalized_phone(opportunity.customer.phone)
        conversation_phone = _normalized_phone(requested.customer_phone)
        if (
            requested.id != opportunity.source_conversation_id
            and (not customer_phone or customer_phone != conversation_phone)
        ):
            raise ValueError("conversation_customer_mismatch")
        candidates.append(requested)
    elif opportunity.source_conversation is not None:
        candidates.append(opportunity.source_conversation)

    phone = _normalized_phone(opportunity.customer.phone)
    if phone and requested_conversation_id is None:
        known = (
            db.query(Conversation)
            .filter(Conversation.business_id == opportunity.business_id)
            .order_by(Conversation.last_message_at.desc(), Conversation.id.desc())
            .all()
        )
        candidates.extend(
            row
            for row in known
            if row.id not in {candidate.id for candidate in candidates}
            and _normalized_phone(row.customer_phone) == phone
        )

    assisted_fallback: ActionChannelResolution | None = None
    unavailable_fallback: ActionChannelResolution | None = None
    for conversation in candidates:
        if conversation.channel not in {"whatsapp", "instagram"}:
            continue
        capabilities = conversation_delivery_capabilities(db, conversation=conversation)
        resolution = ActionChannelResolution(conversation, capabilities)
        if resolution.can_send:
            return resolution
        if resolution.assisted_delivery_available:
            assisted_fallback = assisted_fallback or resolution
        else:
            unavailable_fallback = unavailable_fallback or resolution
    phone_fallback = ActionChannelResolution(None, None, opportunity.customer.phone)
    if assisted_fallback is not None:
        return assisted_fallback
    if phone_fallback.assisted_delivery_available:
        return phone_fallback
    return unavailable_fallback or phone_fallback


def build_action_assisted_whatsapp_url(action: OpportunityAction) -> str:
    if action.action_type != "contact_customer":
        raise ValueError("assisted_delivery_not_available")
    phone = (
        action.conversation.customer_phone or action.conversation.external_user_id
        if action.conversation is not None
        else action.customer.phone
    )
    body = (action.final_text or action.suggested_text or "").strip()
    if not body:
        raise ValueError("empty_message")
    return build_whatsapp_url(phone, body)


def sync_action_from_message(
    action: OpportunityAction, *, now: datetime | None = None
) -> OpportunityAction:
    message = action.message
    if message is None:
        return action
    current = now or utc_now()
    status = message.delivery_status
    if status == "processing" and action.status == "approved":
        action.status = "sending"
    elif status in {"sent", "delivered", "read"}:
        action.status = "sent" if action.status != "completed" else action.status
        action.sent_at = action.sent_at or current
        action.failed_at = None
        action.failure_reason = None
    elif status in {"failed", "blocked", "cancelled"} and action.status != "completed":
        action.status = "failed" if status != "cancelled" else "cancelled"
        action.failed_at = current if status != "cancelled" else action.failed_at
        action.cancelled_at = current if status == "cancelled" else action.cancelled_at
    elif status in {"queued", "retry"} and action.status == "sending":
        action.status = "approved"
    return action


def expire_drafts(
    db: Session, *, business_id: int, now: datetime | None = None
) -> int:
    current = now or utc_now()
    rows = (
        db.query(OpportunityAction)
        .filter(
            OpportunityAction.business_id == business_id,
            OpportunityAction.status == "draft",
            OpportunityAction.expires_at.is_not(None),
            OpportunityAction.expires_at <= current,
        )
        .all()
    )
    for row in rows:
        row.status = "cancelled"
        row.cancelled_at = current
        row.failure_reason = "draft_expired"
    return len(rows)


def invalidate_actions_for_resolved_opportunity(
    db: Session,
    *,
    opportunity: CustomerOpportunity,
    now: datetime | None = None,
) -> int:
    current = now or utc_now()
    changed = 0
    for action in opportunity.actions:
        sync_action_from_message(action, now=current)
        if action.status == "draft":
            action.status = "cancelled"
            action.cancelled_at = current
            action.failure_reason = "opportunity_no_longer_relevant"
            changed += 1
        elif action.status == "approved" and action.message_id is not None:
            outbox = (
                db.query(ChannelOutboxMessage)
                .filter(
                    ChannelOutboxMessage.conversation_message_id == action.message_id,
                    ChannelOutboxMessage.business_id == opportunity.business_id,
                    ChannelOutboxMessage.status.in_(("pending", "retry")),
                )
                .first()
            )
            if outbox is not None:
                outbox.status = "cancelled"
                outbox.failed_at = current
                outbox.next_retry_at = None
                outbox.safe_error_message = "Opportunity is no longer relevant"
                if action.message is not None:
                    action.message.delivery_status = "cancelled"
                action.status = "cancelled"
                action.cancelled_at = current
                action.failure_reason = "opportunity_no_longer_relevant"
                changed += 1
    return changed


class OpportunityActionService:
    def __init__(self, db: Session, *, now: datetime | None = None) -> None:
        self.db = db
        self.now = now or utc_now()

    def prepare(
        self,
        *,
        business: Business,
        opportunity: CustomerOpportunity,
        actor_user_id: int,
        action_type: str = "contact_customer",
        requested_conversation_id: int | None = None,
    ) -> tuple[OpportunityAction, bool]:
        if opportunity.business_id != business.id:
            raise ValueError("opportunity_business_mismatch")
        if opportunity.status != "pending":
            raise ValueError("opportunity_not_actionable")
        existing = (
            self.db.query(OpportunityAction)
            .filter(
                OpportunityAction.business_id == business.id,
                OpportunityAction.opportunity_id == opportunity.id,
                OpportunityAction.action_type == action_type,
            )
            .first()
        )
        if existing is not None:
            sync_action_from_message(existing, now=self.now)
            return existing, False

        resolution = resolve_action_channel(
            self.db,
            opportunity=opportunity,
            requested_conversation_id=requested_conversation_id,
        )
        if action_type == "open_conversation" and resolution.conversation is None:
            raise ValueError("conversation_not_found")
        status = "draft" if action_type == "contact_customer" else "completed"
        row = OpportunityAction(
            business_id=business.id,
            opportunity_id=opportunity.id,
            customer_id=opportunity.customer_id,
            action_type=action_type,
            status=status,
            channel=resolution.channel,
            conversation_id=(resolution.conversation.id if resolution.conversation else None),
            created_by_user_id=actor_user_id,
            completed_at=self.now if status == "completed" else None,
            expires_at=self.now + DRAFT_TTL if status == "draft" else None,
        )
        try:
            with self.db.begin_nested():
                self.db.add(row)
                self.db.flush()
        except IntegrityError:
            row = (
                self.db.query(OpportunityAction)
                .filter(
                    OpportunityAction.business_id == business.id,
                    OpportunityAction.opportunity_id == opportunity.id,
                    OpportunityAction.action_type == action_type,
                )
                .one()
            )
            return row, False
        if action_type == "contact_customer":
            text = OpportunityMessageTemplateService().render(
                business=business,
                opportunity=opportunity,
                action=row,
            )
            row.suggested_text = text
            row.final_text = text
        return row, True


def serialize_action(db: Session, row: OpportunityAction) -> dict[str, Any]:
    sync_action_from_message(row)
    resolution = (
        ActionChannelResolution(
            row.conversation,
            conversation_delivery_capabilities(db, conversation=row.conversation),
        )
        if row.conversation is not None
        else ActionChannelResolution(None, None, row.customer.phone)
    )
    action_booking_url = None
    if row.action_type == "contact_customer":
        action_booking_url = booking_url(row.business, row)
    return {
        "id": row.id,
        "business_id": row.business_id,
        "opportunity_id": row.opportunity_id,
        "customer_id": row.customer_id,
        "action_type": row.action_type,
        "status": row.status,
        "channel": row.channel,
        "conversation_id": row.conversation_id,
        "message_id": row.message_id,
        "booking_id": row.booking_id,
        "suggested_text": row.suggested_text,
        "final_text": row.final_text,
        "can_send": resolution.can_send,
        "assisted_delivery_available": resolution.assisted_delivery_available,
        "delivery_mode": resolution.delivery_mode,
        "unavailable_reason": resolution.unavailable_reason,
        "booking_url": action_booking_url,
        "created_by_user_id": row.created_by_user_id,
        "last_edited_by_user_id": row.last_edited_by_user_id,
        "approved_by_user_id": row.approved_by_user_id,
        "sent_by_user_id": row.sent_by_user_id,
        "approved_at": row.approved_at.isoformat() if row.approved_at else None,
        "sent_at": row.sent_at.isoformat() if row.sent_at else None,
        "failed_at": row.failed_at.isoformat() if row.failed_at else None,
        "cancelled_at": row.cancelled_at.isoformat() if row.cancelled_at else None,
        "completed_at": row.completed_at.isoformat() if row.completed_at else None,
        "expires_at": row.expires_at.isoformat() if row.expires_at else None,
        "failure_reason": row.failure_reason,
        "created_at": row.created_at.isoformat(),
        "updated_at": row.updated_at.isoformat(),
    }
