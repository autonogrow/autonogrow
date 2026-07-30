import json
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from sqlalchemy import or_
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.models import (
    Business,
    Conversation,
    ConversationAutomationSettings,
    ConversationMessage,
    ConversationTemplate,
)
from app.services.conversation_automation_state_service import (
    serialize_conversation_automation_state,
)
from app.services.incident_service import INSTAGRAM_AUTH_CLIENT_MESSAGE
from app.services.instagram_integration_service import (
    get_instagram_integration,
    integration_expiration_state,
)
from app.services.outbox_queue_service import create_channel_outbox


@dataclass(frozen=True)
class OutboundMessageResult:
    message: ConversationMessage
    provider_configured: bool
    provider_attempted: bool
    error_message: str | None = None
    client_error_message: str | None = None
    incident_id: str | None = None

    @property
    def ok(self) -> bool:
        return self.message.delivery_status not in {"failed", "blocked", "cancelled"}


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
    (
        "Respuesta segura a queja",
        "Sentimos lo ocurrido. Hemos avisado al equipo para que revise tu caso y te responda personalmente lo antes posible.",
    ),
    (
        "Derivación a atención humana",
        "Claro. Hemos avisado al equipo para que una persona continúe contigo. Te responderán en cuanto sea posible.",
    ),
    (
        "Acuse de cambio o cancelación",
        "Hemos recibido tu solicitud de cambio o cancelación. Para evitar modificar una cita incorrecta, una persona revisará tu caso y te responderá.",
    ),
    (
        "Respuesta segura sin intención",
        "Gracias por escribirnos. No hemos identificado con seguridad lo que necesitas, así que hemos avisado al equipo para que pueda ayudarte.",
    ),
)


def serialize_message(message: ConversationMessage) -> dict[str, Any]:
    labels = {
        "queued": "En cola",
        "processing": "Enviando",
        "sent": "Enviado",
        "delivered": "Enviado",
        "retry": "Error temporal",
        "blocked": "No enviado por conexión",
        "failed": "Error definitivo",
        "cancelled": "Error definitivo",
    }
    return {
        "id": message.id,
        "conversation_id": message.conversation_id,
        "direction": message.direction,
        "sender_type": message.sender_type,
        "body": message.body,
        "provider_message_id": message.provider_message_id,
        "delivery_status": message.delivery_status,
        "delivery_status_label": labels.get(message.delivery_status or "", message.delivery_status),
        "created_at": message.created_at.isoformat() if message.created_at else None,
    }


def unread_count(db: Session, conversation: Conversation) -> int:
    query = db.query(ConversationMessage).filter(
        ConversationMessage.conversation_id == conversation.id,
        ConversationMessage.direction == "inbound",
    )
    if conversation.last_outbound_at is not None:
        query = query.filter(ConversationMessage.created_at > conversation.last_outbound_at)
    return query.count()


def serialize_conversation(
    db: Session, conversation: Conversation, *, include_messages: bool = False
) -> dict[str, Any]:
    try:
        matched_patterns = json.loads(conversation.matched_patterns_json or "[]")
    except (TypeError, ValueError):
        matched_patterns = []
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
            conversation.last_message_at.isoformat() if conversation.last_message_at else None
        ),
        "last_inbound_at": (
            conversation.last_inbound_at.isoformat() if conversation.last_inbound_at else None
        ),
        "last_outbound_at": (
            conversation.last_outbound_at.isoformat() if conversation.last_outbound_at else None
        ),
        "assigned_business_user_id": conversation.assigned_business_user_id,
        "detected_intent": conversation.detected_intent,
        "intent_confidence": conversation.intent_confidence,
        "matched_patterns": matched_patterns,
        "automation": serialize_conversation_automation_state(conversation),
        "instagram_provider_configured": (
            bool(
                getattr(get_settings(), "instagram_provider_enabled", False)
                and (
                    integration := get_instagram_integration(
                        db, business_id=conversation.business_id
                    )
                )
                and integration.integration_status in {"connected", "degraded"}
                and integration.encrypted_access_token
                and not integration_expiration_state(integration)[0]
            )
            if conversation.channel == "instagram"
            else None
        ),
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


def get_conversation(db: Session, *, business_id: int, conversation_id: int) -> Conversation | None:
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


def send_outbound_message(
    db: Session,
    *,
    conversation: Conversation,
    body: str,
    sender_type: str,
    intent: str | None = None,
) -> OutboundMessageResult:
    settings = get_settings()
    integration = (
        get_instagram_integration(db, business_id=conversation.business_id)
        if conversation.channel == "instagram"
        else None
    )
    provider_configured = bool(
        getattr(settings, "instagram_provider_enabled", False)
        and integration
        and integration.encrypted_access_token
        and integration.integration_status in {"connected", "degraded"}
        and not integration_expiration_state(integration)[0]
    )
    legacy_simulation = not hasattr(settings, "worker_max_attempts")
    provider_attempted = False
    error_message = None
    client_error_message = None
    incident_id = None
    policy_blocked = False
    delivery_status = "sent"
    commercial_settings = (
        db.query(ConversationAutomationSettings)
        .filter(ConversationAutomationSettings.business_id == conversation.business_id)
        .first()
    )
    if commercial_settings is not None:
        channel_enabled = {
            "instagram": commercial_settings.instagram_channel_enabled,
            "whatsapp": commercial_settings.whatsapp_channel_enabled,
        }.get(conversation.channel, True)
        if not channel_enabled:
            policy_blocked = True
            delivery_status = "blocked"
            client_error_message = (
                f"El canal {conversation.channel.title()} no está habilitado para este negocio. "
                "Contacta con el equipo de AutonoGrow."
            )
    if conversation.channel == "instagram" and not policy_blocked:
        integration_ready = bool(
            integration
            and integration.encrypted_access_token
            and integration.encryption_key_version
            and integration.integration_status in {"connected", "degraded"}
            and not integration_expiration_state(integration)[0]
            and conversation.external_user_id
        )
        delivery_status = (
            "simulated" if legacy_simulation else ("queued" if integration_ready else "blocked")
        )
        if not integration_ready and not legacy_simulation:
            client_error_message = INSTAGRAM_AUTH_CLIENT_MESSAGE
    previous_last_outbound_at = conversation.last_outbound_at
    message = add_message(
        db,
        conversation=conversation,
        direction="outbound",
        sender_type=sender_type,
        body=body,
        provider_message_id=None,
        delivery_status=delivery_status,
    )
    if delivery_status in {"failed", "blocked"}:
        conversation.status = "pending"
        conversation.last_outbound_at = previous_last_outbound_at
        return OutboundMessageResult(
            message=message,
            provider_configured=provider_configured,
            provider_attempted=False,
            client_error_message=client_error_message,
        )
    if conversation.channel == "instagram" and integration and delivery_status == "queued":
        create_channel_outbox(
            db,
            conversation=conversation,
            message=message,
            integration_id=integration.id,
            recipient_external_id=conversation.external_user_id or "",
            max_attempts=settings.worker_max_attempts,
        )
    return OutboundMessageResult(
        message=message,
        provider_configured=provider_configured,
        provider_attempted=provider_attempted,
        error_message=error_message,
        client_error_message=client_error_message,
        incident_id=incident_id,
    )


def send_manual_message(
    db: Session, *, conversation: Conversation, body: str
) -> ConversationMessage:
    return send_outbound_message(
        db,
        conversation=conversation,
        body=body,
        sender_type="business",
    ).message


def update_status(conversation: Conversation, status: str) -> None:
    conversation.status = status
    conversation.updated_at = datetime.utcnow()


def close_conversation(conversation: Conversation) -> None:
    update_status(conversation, "closed")


def reopen_conversation(conversation: Conversation) -> None:
    update_status(conversation, "pending")


def list_messages(conversation: Conversation) -> list[ConversationMessage]:
    return list(conversation.messages)


def ensure_default_templates(db: Session, business: Business) -> list[ConversationTemplate]:
    existing = (
        db.query(ConversationTemplate).filter(ConversationTemplate.business_id == business.id).all()
    )
    existing_by_name = {item.name: item for item in existing}
    for name, body in DEFAULT_TEMPLATES:
        if name in existing_by_name:
            continue
        item = ConversationTemplate(
            business_id=business.id,
            name=name,
            body=body,
            active=True,
        )
        db.add(item)
        existing.append(item)
        existing_by_name[name] = item
    db.flush()
    return sorted(existing, key=lambda item: item.id or 0)


def render_template(body: str, business: Business) -> str:
    booking_path = f"/autonogrow-landing/?b={business.slug}"
    frontend_origins = get_settings().frontend_origin_list
    public_booking_url = (
        f"{frontend_origins[0].rstrip('/')}{booking_path}" if frontend_origins else booking_path
    )
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
