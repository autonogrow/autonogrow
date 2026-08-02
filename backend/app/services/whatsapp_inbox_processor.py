import json
from datetime import datetime

from sqlalchemy.orm import Session

from app.models import (
    Business,
    BusinessChannelIntegration,
    Conversation,
    ConversationMessage,
    WebhookInboxEvent,
)
from app.services.channel_provider_contracts import (
    ChannelInboxProcessingError,
    InboxProcessResult,
    InvalidChannelInboxPayload,
)
from app.services.conversation_automation_service import process_inbound_automation
from app.services.conversation_service import add_message, create_or_get_conversation
from app.services.inbox_queue_service import finish_inbox_job
from app.services.whatsapp_provider import whatsapp_status_is_supported

WHATSAPP_PROVIDER = "whatsapp"
WHATSAPP_CHANNEL = "whatsapp"
USABLE_INTEGRATION_STATUSES = {"connected", "degraded"}


def _required_text(payload: dict, field: str, *, max_length: int = 255) -> str:
    value = payload.get(field)
    if not isinstance(value, str) or not value.strip() or len(value.strip()) > max_length:
        raise InvalidChannelInboxPayload(f"Stored WhatsApp {field} is invalid")
    return value.strip()


def _resolve_whatsapp_integration(
    db: Session,
    *,
    phone_number_id: str,
) -> BusinessChannelIntegration:
    integrations = (
        db.query(BusinessChannelIntegration)
        .filter(
            BusinessChannelIntegration.provider == WHATSAPP_PROVIDER,
            BusinessChannelIntegration.channel == WHATSAPP_CHANNEL,
            BusinessChannelIntegration.external_account_id == phone_number_id,
        )
        .limit(2)
        .all()
    )
    if not integrations:
        raise ChannelInboxProcessingError(
            error_code="whatsapp_integration_not_found",
            safe_message="WhatsApp account is not mapped",
            retryable=False,
        )
    if len(integrations) != 1:
        raise ChannelInboxProcessingError(
            error_code="whatsapp_integration_ambiguous",
            safe_message="WhatsApp account mapping is ambiguous",
            retryable=False,
        )
    integration = integrations[0]
    if integration.integration_status not in USABLE_INTEGRATION_STATUSES:
        raise ChannelInboxProcessingError(
            error_code=f"integration_{integration.integration_status}",
            safe_message="WhatsApp integration is unavailable",
            retryable=False,
        )
    return integration


def process_whatsapp_inbox_event(db: Session, inbox_id: int) -> InboxProcessResult:
    row = db.get(WebhookInboxEvent, inbox_id)
    if row is None or row.status != "processing":
        raise InvalidChannelInboxPayload("Inbox job is unavailable")
    if row.provider != WHATSAPP_PROVIDER or row.channel != WHATSAPP_CHANNEL:
        raise InvalidChannelInboxPayload("Stored channel provider is invalid")
    try:
        payload = json.loads(row.payload_json)
    except (TypeError, ValueError) as exc:
        raise InvalidChannelInboxPayload("Stored WhatsApp event is invalid") from exc
    if not isinstance(payload, dict):
        raise InvalidChannelInboxPayload("Stored WhatsApp event is invalid")

    if row.event_type == "status":
        status = payload.get("status")
        if whatsapp_status_is_supported(status if isinstance(status, str) else None):
            finish_inbox_job(row)
            return InboxProcessResult("status_recorded")
        row.last_error_code = "whatsapp_unsupported_status"
        row.safe_error_message = "WhatsApp status is not supported"
        finish_inbox_job(row, status="ignored")
        return InboxProcessResult("ignored")

    if row.event_type == "unsupported_message":
        row.last_error_code = "whatsapp_unsupported_message"
        row.safe_error_message = "WhatsApp message type is not supported"
        finish_inbox_job(row, status="ignored")
        return InboxProcessResult("ignored")
    if row.event_type != "message":
        raise InvalidChannelInboxPayload("Stored WhatsApp event type is invalid")

    message_id = _required_text(payload, "message_id")
    phone_number_id = _required_text(payload, "phone_number_id")
    sender_id = _required_text(payload, "sender_id")
    text = _required_text(payload, "text", max_length=10_000)
    integration = _resolve_whatsapp_integration(db, phone_number_id=phone_number_id)
    row.integration_id = integration.id
    row.business_id = integration.business_id
    business = (
        db.query(Business)
        .filter(Business.id == integration.business_id, Business.status == "active")
        .first()
    )
    if business is None:
        raise ChannelInboxProcessingError(
            error_code="business_unavailable",
            safe_message="Business is unavailable",
            retryable=False,
        )
    duplicate = (
        db.query(ConversationMessage)
        .join(Conversation, Conversation.id == ConversationMessage.conversation_id)
        .filter(
            Conversation.business_id == business.id,
            Conversation.channel == WHATSAPP_CHANNEL,
            ConversationMessage.provider_message_id == message_id,
        )
        .first()
    )
    if duplicate is not None:
        finish_inbox_job(row)
        return InboxProcessResult("duplicate")

    contact_name = payload.get("contact_name")
    safe_contact_name = (
        contact_name.strip()[:200]
        if isinstance(contact_name, str) and contact_name.strip()
        else None
    )
    conversation, _ = create_or_get_conversation(
        db,
        business_id=business.id,
        channel=WHATSAPP_CHANNEL,
        external_user_id=sender_id,
        external_conversation_id=sender_id,
        customer_name=safe_contact_name,
        customer_phone=sender_id,
    )
    message = add_message(
        db,
        conversation=conversation,
        direction="inbound",
        sender_type="customer",
        body=text,
        provider_message_id=message_id,
        raw_payload=payload,
    )
    integration.last_success_at = datetime.utcnow()
    automation = process_inbound_automation(
        db,
        business=business,
        conversation=conversation,
        message=message,
    )
    finish_inbox_job(row)
    return InboxProcessResult("processed", automation)
