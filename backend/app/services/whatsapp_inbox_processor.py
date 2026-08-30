import json
from datetime import datetime

from sqlalchemy.orm import Session

from app.models import (
    Business,
    BusinessChannelIntegration,
    ChannelOutboxMessage,
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
from app.services.conversation_service import (
    add_message,
    auto_associate_conversation_customer,
    create_or_get_conversation,
)
from app.services.inbox_queue_service import finish_inbox_job
from app.services.whatsapp_provider import whatsapp_status_is_supported

WHATSAPP_PROVIDER = "whatsapp"
WHATSAPP_CHANNEL = "whatsapp"
USABLE_INTEGRATION_STATUSES = {"connected", "degraded"}
WHATSAPP_DELIVERY_STATUS_RANK = {"sent": 1, "delivered": 2, "read": 3}


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


def _merge_whatsapp_delivery_metadata(
    message: ConversationMessage,
    *,
    status: str,
    timestamp: str | None,
    error_code: str | None,
    error_type: str | None,
) -> None:
    try:
        metadata = json.loads(message.raw_payload_json or "{}")
    except (TypeError, ValueError):
        metadata = {}
    if not isinstance(metadata, dict):
        metadata = {}
    metadata["whatsapp_delivery"] = {
        "status": status,
        "timestamp": timestamp,
        "error_code": error_code,
        "error_type": error_type,
    }
    message.raw_payload_json = json.dumps(metadata, ensure_ascii=False, sort_keys=True)


def _reconcile_whatsapp_status(
    db: Session,
    *,
    inbox: WebhookInboxEvent,
    payload: dict,
) -> InboxProcessResult:
    status = payload.get("status")
    if not whatsapp_status_is_supported(status if isinstance(status, str) else None):
        inbox.last_error_code = "whatsapp_unsupported_status"
        inbox.safe_error_message = "WhatsApp status is not supported"
        finish_inbox_job(inbox, status="ignored")
        return InboxProcessResult("ignored")
    assert isinstance(status, str)
    message_id = _required_text(payload, "message_id")
    phone_number_id = _required_text(payload, "phone_number_id")
    matches = (
        db.query(ChannelOutboxMessage)
        .filter(
            ChannelOutboxMessage.provider == WHATSAPP_PROVIDER,
            ChannelOutboxMessage.channel == WHATSAPP_CHANNEL,
            ChannelOutboxMessage.provider_message_id == message_id,
        )
        .limit(2)
        .all()
    )
    if not matches:
        finish_inbox_job(inbox)
        return InboxProcessResult("status_recorded")
    if len(matches) != 1:
        raise ChannelInboxProcessingError(
            error_code="whatsapp_status_ambiguous",
            safe_message="WhatsApp status mapping is ambiguous",
            retryable=False,
        )
    outbox = matches[0]
    integration = db.get(BusinessChannelIntegration, outbox.integration_id)
    if (
        integration is None
        or integration.business_id != outbox.business_id
        or integration.provider != WHATSAPP_PROVIDER
        or integration.channel != WHATSAPP_CHANNEL
        or integration.external_account_id != phone_number_id
    ):
        raise ChannelInboxProcessingError(
            error_code="whatsapp_status_context_mismatch",
            safe_message="WhatsApp status context is invalid",
            retryable=False,
        )
    message = (
        db.get(ConversationMessage, outbox.conversation_message_id)
        if outbox.conversation_message_id is not None
        else None
    )
    conversation = db.get(Conversation, outbox.conversation_id)
    if (
        message is None
        or conversation is None
        or message.conversation_id != conversation.id
        or conversation.business_id != outbox.business_id
        or conversation.channel != WHATSAPP_CHANNEL
    ):
        raise ChannelInboxProcessingError(
            error_code="whatsapp_status_message_missing",
            safe_message="WhatsApp status message is unavailable",
            retryable=False,
        )
    inbox.business_id = outbox.business_id
    inbox.integration_id = integration.id
    current_status = message.delivery_status or ""
    error_code = payload.get("status_error_code")
    safe_error_code = error_code[:120] if isinstance(error_code, str) else None
    error_type = payload.get("status_error_type")
    safe_error_type = error_type[:120] if isinstance(error_type, str) else None
    should_update = False
    if status == "failed":
        should_update = current_status not in {"delivered", "failed", "read"}
        if should_update:
            outbox.status = "failed"
            outbox.failed_at = datetime.utcnow()
            outbox.last_error_code = safe_error_code or "whatsapp_delivery_failed"
            outbox.last_error_type = safe_error_type
            outbox.safe_error_message = "WhatsApp delivery failed"
    elif current_status != "failed":
        should_update = WHATSAPP_DELIVERY_STATUS_RANK[status] > WHATSAPP_DELIVERY_STATUS_RANK.get(
            current_status, 0
        )
    if should_update:
        message.delivery_status = status
        _merge_whatsapp_delivery_metadata(
            message,
            status=status,
            timestamp=(
                payload.get("timestamp") if isinstance(payload.get("timestamp"), str) else None
            ),
            error_code=safe_error_code,
            error_type=safe_error_type,
        )
    finish_inbox_job(inbox)
    return InboxProcessResult("status_reconciled" if should_update else "status_unchanged")


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
        return _reconcile_whatsapp_status(db, inbox=row, payload=payload)

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
    auto_associate_conversation_customer(db, business=business, conversation=conversation)
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
