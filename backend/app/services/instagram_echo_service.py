import json
from datetime import datetime, timedelta
from typing import Any

from sqlalchemy.orm import Session

from app.models import Business, Conversation, ConversationMessage
from app.services.conversation_automation_service import ensure_automation_configuration
from app.services.conversation_automation_state_service import apply_human_reply_pause
from app.services.conversation_intent_service import normalize_text
from app.services.conversation_service import add_message, create_or_get_conversation
from app.services.instagram_provider import InstagramInboundMessage

INSTAGRAM_ECHO_RECONCILIATION_SECONDS = 120


def _event_time(event: InstagramInboundMessage) -> datetime:
    if event.timestamp is None:
        return datetime.utcnow()
    try:
        return datetime.utcfromtimestamp(event.timestamp / 1000)
    except (OSError, OverflowError, ValueError):
        return datetime.utcnow()


def _attachments_from_raw(raw_payload_json: str | None) -> list[dict[str, Any]]:
    try:
        raw = json.loads(raw_payload_json or "null")
    except (TypeError, ValueError):
        return []
    if not isinstance(raw, dict):
        return []
    message = raw.get("message")
    attachments = message.get("attachments") if isinstance(message, dict) else None
    if not isinstance(attachments, list):
        return []
    return [item for item in attachments if isinstance(item, dict)]


def _attachment_signature(attachments: list[dict[str, Any]]) -> str | None:
    if not attachments:
        return None
    stable = []
    for attachment in attachments:
        payload = attachment.get("payload")
        stable_payload = {}
        if isinstance(payload, dict):
            for key in ("attachment_id", "url", "title", "filename"):
                if payload.get(key) is not None:
                    stable_payload[key] = str(payload[key])
        stable.append(
            {
                "type": str(attachment.get("type", "")),
                "payload": stable_payload,
            }
        )
    return json.dumps(stable, sort_keys=True, ensure_ascii=True)


def _matches_echo(candidate: ConversationMessage, event: InstagramInboundMessage) -> bool:
    event_text = normalize_text(event.text)
    if event_text and normalize_text(candidate.body) == event_text:
        return True
    event_signature = _attachment_signature(event.attachments)
    return bool(
        event_signature
        and event_signature
        == _attachment_signature(_attachments_from_raw(candidate.raw_payload_json))
    )


def _touch_conversation_from_echo(
    conversation: Conversation,
    message: ConversationMessage,
    event_time: datetime,
) -> None:
    if conversation.last_message_at is None or event_time >= conversation.last_message_at:
        conversation.last_message_at = event_time
        conversation.last_message_text = message.body
    if conversation.last_outbound_at is None or event_time >= conversation.last_outbound_at:
        conversation.last_outbound_at = event_time
    conversation.updated_at = datetime.utcnow()


def process_instagram_echo(
    db: Session,
    *,
    business: Business,
    event: InstagramInboundMessage,
) -> tuple[str, ConversationMessage]:
    if not event.is_echo:
        raise ValueError("Instagram event is not an echo")

    existing = None
    if event.message_id:
        existing = (
            db.query(ConversationMessage)
            .join(Conversation, Conversation.id == ConversationMessage.conversation_id)
            .filter(
                Conversation.business_id == business.id,
                ConversationMessage.provider_message_id == event.message_id,
            )
            .first()
        )
    if existing is not None:
        if existing.direction == "outbound":
            existing.delivery_status = "sent"
            _touch_conversation_from_echo(existing.conversation, existing, _event_time(event))
        return "duplicate", existing

    conversation, _ = create_or_get_conversation(
        db,
        business_id=business.id,
        channel="instagram",
        external_user_id=event.recipient_id,
        external_conversation_id=event.recipient_id,
    )
    event_time = _event_time(event)
    cutoff_before = event_time - timedelta(seconds=INSTAGRAM_ECHO_RECONCILIATION_SECONDS)
    cutoff_after = event_time + timedelta(seconds=INSTAGRAM_ECHO_RECONCILIATION_SECONDS)
    candidates = (
        db.query(ConversationMessage)
        .filter(
            ConversationMessage.conversation_id == conversation.id,
            ConversationMessage.direction == "outbound",
            ConversationMessage.provider_message_id.is_(None),
            ConversationMessage.delivery_status.in_(("pending", "sent")),
            ConversationMessage.created_at >= cutoff_before,
            ConversationMessage.created_at <= cutoff_after,
        )
        .order_by(ConversationMessage.created_at.desc(), ConversationMessage.id.desc())
        .all()
    )
    matches = [candidate for candidate in candidates if _matches_echo(candidate, event)]
    if len(matches) == 1:
        message = matches[0]
        message.provider_message_id = event.message_id
        message.delivery_status = "sent"
        _touch_conversation_from_echo(conversation, message, event_time)
        if message.sender_type == "business":
            settings, _ = ensure_automation_configuration(db, business)
            apply_human_reply_pause(
                conversation,
                settings,
                now=message.created_at,
            )
        db.flush()
        return "reconciled", message

    message = add_message(
        db,
        conversation=conversation,
        direction="outbound",
        sender_type="business",
        body=event.text,
        provider_message_id=event.message_id,
        delivery_status="sent",
        raw_payload=event.raw_payload,
    )
    settings, _ = ensure_automation_configuration(db, business)
    apply_human_reply_pause(conversation, settings)
    db.flush()
    return "created", message
