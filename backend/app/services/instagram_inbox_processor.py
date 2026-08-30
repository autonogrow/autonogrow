import hashlib
import json
from datetime import datetime

from sqlalchemy.orm import Session

from app.models import Business, Conversation, ConversationMessage, WebhookInboxEvent
from app.services.channel_provider_contracts import InboxProcessResult, InvalidChannelInboxPayload
from app.services.conversation_automation_service import process_inbound_automation
from app.services.conversation_service import (
    add_message,
    auto_associate_conversation_customer,
    create_or_get_conversation,
)
from app.services.inbox_queue_service import finish_inbox_job
from app.services.incident_service import report_incident
from app.services.instagram_echo_service import process_instagram_echo
from app.services.instagram_integration_service import resolve_instagram_integration_for_event
from app.services.instagram_provider import parse_instagram_webhook


class InvalidInboxPayload(InvalidChannelInboxPayload):
    pass


def process_instagram_inbox_event(db: Session, inbox_id: int) -> InboxProcessResult:
    row = db.get(WebhookInboxEvent, inbox_id)
    if row is None or row.status != "processing":
        raise InvalidInboxPayload("Inbox job is unavailable")
    try:
        raw_event = json.loads(row.payload_json)
    except (TypeError, ValueError) as exc:
        raise InvalidInboxPayload("Stored webhook event is invalid") from exc
    if not isinstance(raw_event, dict):
        raise InvalidInboxPayload("Stored webhook event is invalid")
    events = parse_instagram_webhook({"object": "instagram", "entry": [{"messaging": [raw_event]}]})
    if len(events) != 1:
        raise InvalidInboxPayload("Stored webhook event is unsupported")
    event = events[0]
    integration = resolve_instagram_integration_for_event(
        db,
        sender_id=event.sender_id,
        recipient_id=event.recipient_id,
        is_echo=event.is_echo,
    )
    if integration is None:
        routing_id = event.sender_id if event.is_echo else event.recipient_id
        fingerprint = hashlib.sha256(routing_id.encode()).hexdigest()[:16]
        row.last_error_code = "instagram_unmapped_account"
        row.safe_error_message = "Instagram account is not mapped"
        finish_inbox_job(row, status="ignored")
        report_incident(
            db,
            category="instagram_unmapped_account",
            severity="medium",
            business_id=None,
            channel="instagram",
            provider="instagram",
            provider_error_code=f"unmapped-{fingerprint}",
            operation=f"process_inbox_{row.id}",
            safe_details={"inbox_id": row.id, "event_type": row.event_type},
        )
        return InboxProcessResult("ignored")
    row.integration_id = integration.id
    row.business_id = integration.business_id
    if integration.integration_status not in {"connected", "degraded"}:
        row.last_error_code = f"integration_{integration.integration_status}"
        row.safe_error_message = "Instagram integration is unavailable"
        finish_inbox_job(row, status="ignored")
        return InboxProcessResult("ignored")
    business = (
        db.query(Business)
        .filter(Business.id == integration.business_id, Business.status == "active")
        .first()
    )
    if business is None:
        row.last_error_code = "business_unavailable"
        row.safe_error_message = "Business is unavailable"
        finish_inbox_job(row, status="ignored")
        return InboxProcessResult("ignored")
    integration.last_success_at = datetime.utcnow()
    if event.is_echo:
        action, _ = process_instagram_echo(db, business=business, event=event)
        finish_inbox_job(row)
        return InboxProcessResult(action)
    if event.message_id:
        duplicate = (
            db.query(ConversationMessage)
            .join(Conversation, Conversation.id == ConversationMessage.conversation_id)
            .filter(
                Conversation.business_id == business.id,
                ConversationMessage.provider_message_id == event.message_id,
            )
            .first()
        )
        if duplicate:
            finish_inbox_job(row)
            return InboxProcessResult("duplicate")
    conversation, _ = create_or_get_conversation(
        db,
        business_id=business.id,
        channel="instagram",
        external_user_id=event.sender_id,
        external_conversation_id=event.sender_id,
    )
    auto_associate_conversation_customer(db, business=business, conversation=conversation)
    message = add_message(
        db,
        conversation=conversation,
        direction="inbound",
        sender_type="customer",
        body=event.text,
        provider_message_id=event.message_id,
        raw_payload=event.raw_payload,
    )
    automation = process_inbound_automation(
        db, business=business, conversation=conversation, message=message
    )
    finish_inbox_job(row)
    return InboxProcessResult("processed", automation)
