import json
from datetime import datetime
from typing import Any

from sqlalchemy import or_
from sqlalchemy.orm import Session

from app.models import (
    Business,
    Conversation,
    ConversationMessage,
    ConversationTemplate,
)


DEFAULT_TEMPLATES = (
    (
        "Enviar enlace de reserva",
        "Puedes reservar tu cita aquí: {public_booking_url}",
    ),
    (
        "Enviar servicios",
        "Puedes ver nuestros servicios y reservar aquí: {public_booking_url}",
    ),
    (
        "Enviar ubicación",
        "Estamos en {business_address}",
    ),
    (
        "Mensaje de bienvenida",
        "Hola 👋 Gracias por escribir a {business_name}. Puedes ver servicios y reservar aquí: {public_booking_url}.",
    ),
)


def serialize_message(message: ConversationMessage) -> dict[str, Any]:
    return {
        "id": message.id,
        "conversation_id": message.conversation_id,
        "direction": message.direction,
        "sender_type": message.sender_type,
        "body": message.body,
        "provider_message_id": message.provider_message_id,
        "delivery_status": message.delivery_status,
        "created_at": message.created_at.isoformat() if message.created_at else None,
    }


def unread_count(db: Session, conversation: Conversation) -> int:
    query = db.query(ConversationMessage).filter(
        ConversationMessage.conversation_id == conversation.id,
        ConversationMessage.direction == "inbound",
    )
    if conversation.last_outbound_at is not None:
        query = query.filter(
            ConversationMessage.created_at > conversation.last_outbound_at
        )
    return query.count()


def serialize_conversation(
    db: Session, conversation: Conversation, *, include_messages: bool = False
) -> dict[str, Any]:
    result = {
        "id": conversation.id,
        "business_id": conversation.business_id,
        "channel": conversation.channel,
        "external_conversation_id": conversation.external_conversation_id,
        "external_user_id": conversation.external_user_id,
        "customer_name": conversation.customer_name,
        "customer_phone": conversation.customer_phone,
        "customer_username": conversation.customer_username,
        "status": conversation.status,
        "last_message_text": conversation.last_message_text,
        "last_message_at": (
            conversation.last_message_at.isoformat()
            if conversation.last_message_at
            else None
        ),
        "last_inbound_at": (
            conversation.last_inbound_at.isoformat()
            if conversation.last_inbound_at
            else None
        ),
        "last_outbound_at": (
            conversation.last_outbound_at.isoformat()
            if conversation.last_outbound_at
            else None
        ),
        "assigned_business_user_id": conversation.assigned_business_user_id,
        "unread_count": unread_count(db, conversation),
        "created_at": conversation.created_at.isoformat(),
        "updated_at": conversation.updated_at.isoformat(),
    }
    if include_messages:
        result["messages"] = [serialize_message(item) for item in conversation.messages]
    return result


def serialize_template(template: ConversationTemplate, business: Business) -> dict[str, Any]:
    return {
        "id": template.id,
        "business_id": template.business_id,
        "name": template.name,
        "body": template.body,
        "rendered_body": render_template(template.body, business),
        "active": template.active,
        "created_at": template.created_at.isoformat(),
        "updated_at": template.updated_at.isoformat(),
    }


def list_conversations(
    db: Session,
    *,
    business_id: int,
    status: str | None = None,
    channel: str | None = None,
    q: str | None = None,
    limit: int = 50,
    offset: int = 0,
) -> tuple[list[Conversation], int]:
    query = db.query(Conversation).filter(Conversation.business_id == business_id)
    if status:
        query = query.filter(Conversation.status == status)
    if channel:
        query = query.filter(Conversation.channel == channel)
    if q and q.strip():
        pattern = f"%{q.strip()}%"
        query = query.filter(
            or_(
                Conversation.customer_name.ilike(pattern),
                Conversation.customer_phone.ilike(pattern),
                Conversation.customer_username.ilike(pattern),
                Conversation.last_message_text.ilike(pattern),
            )
        )
    total = query.count()
    rows = (
        query.order_by(
            Conversation.last_message_at.desc(),
            Conversation.updated_at.desc(),
            Conversation.id.desc(),
        )
        .offset(offset)
        .limit(limit)
        .all()
    )
    return rows, total


def get_conversation(
    db: Session, *, business_id: int, conversation_id: int
) -> Conversation | None:
    return (
        db.query(Conversation)
        .filter(
            Conversation.id == conversation_id,
            Conversation.business_id == business_id,
        )
        .first()
    )


def create_or_get_conversation(
    db: Session,
    *,
    business_id: int,
    channel: str,
    external_user_id: str | None = None,
    external_conversation_id: str | None = None,
    customer_name: str | None = None,
    customer_phone: str | None = None,
    customer_username: str | None = None,
) -> tuple[Conversation, bool]:
    conversation = None
    if external_user_id:
        conversation = (
            db.query(Conversation)
            .filter(
                Conversation.business_id == business_id,
                Conversation.channel == channel,
                Conversation.external_user_id == external_user_id,
            )
            .first()
        )
    created = conversation is None
    if conversation is None:
        conversation = Conversation(
            business_id=business_id,
            channel=channel,
            external_user_id=external_user_id,
            external_conversation_id=external_conversation_id,
            customer_name=customer_name,
            customer_phone=customer_phone,
            customer_username=customer_username,
            status="pending",
        )
        db.add(conversation)
        db.flush()
    else:
        if customer_name:
            conversation.customer_name = customer_name
        if customer_phone:
            conversation.customer_phone = customer_phone
        if customer_username:
            conversation.customer_username = customer_username
        if external_conversation_id:
            conversation.external_conversation_id = external_conversation_id
    return conversation, created


def add_message(
    db: Session,
    *,
    conversation: Conversation,
    direction: str,
    sender_type: str,
    body: str,
    provider_message_id: str | None = None,
    delivery_status: str | None = None,
    raw_payload: dict[str, Any] | None = None,
) -> ConversationMessage:
    now = datetime.utcnow()
    message = ConversationMessage(
        conversation_id=conversation.id,
        direction=direction,
        sender_type=sender_type,
        body=body.strip(),
        provider_message_id=provider_message_id,
        delivery_status=delivery_status,
        raw_payload_json=(
            json.dumps(raw_payload, ensure_ascii=False) if raw_payload is not None else None
        ),
        created_at=now,
    )
    db.add(message)
    conversation.last_message_text = message.body
    conversation.last_message_at = now
    conversation.updated_at = now
    if direction == "inbound":
        conversation.last_inbound_at = now
        conversation.status = "pending"
    elif direction == "outbound":
        conversation.last_outbound_at = now
        conversation.status = "replied"
    db.flush()
    return message


def send_manual_message(
    db: Session, *, conversation: Conversation, body: str
) -> ConversationMessage:
    return add_message(
        db,
        conversation=conversation,
        direction="outbound",
        sender_type="business",
        body=body,
        delivery_status="sent",
    )


def update_status(conversation: Conversation, status: str) -> None:
    conversation.status = status
    conversation.updated_at = datetime.utcnow()


def close_conversation(conversation: Conversation) -> None:
    update_status(conversation, "closed")


def reopen_conversation(conversation: Conversation) -> None:
    update_status(conversation, "pending")


def list_messages(conversation: Conversation) -> list[ConversationMessage]:
    return list(conversation.messages)


def ensure_default_templates(
    db: Session, business: Business
) -> list[ConversationTemplate]:
    existing = (
        db.query(ConversationTemplate)
        .filter(ConversationTemplate.business_id == business.id)
        .all()
    )
    if existing:
        return sorted(existing, key=lambda item: item.id or 0)

    created = []
    for name, body in DEFAULT_TEMPLATES:
        item = ConversationTemplate(
            business_id=business.id,
            name=name,
            body=body,
            active=True,
        )
        db.add(item)
        created.append(item)
    db.flush()
    return created


def render_template(body: str, business: Business) -> str:
    public_booking_url = f"/autonogrow-landing/?b={business.slug}"
    if not business.address and body == "Estamos en {business_address}":
        return f"Puedes ver la información del negocio aquí: {public_booking_url}"
    business_address = business.address or public_booking_url
    values = {
        "business_name": business.name,
        "business_slug": business.slug,
        "public_booking_url": public_booking_url,
        "business_phone": business.phone or "",
        "business_address": business_address,
    }
    rendered = body
    for key, value in values.items():
        rendered = rendered.replace(f"{{{key}}}", value)
    return rendered
