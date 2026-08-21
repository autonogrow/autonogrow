import json
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any

from sqlalchemy import or_
from sqlalchemy.orm import Session

from app.core.config import Settings, get_settings
from app.models import (
    Business,
    BusinessChannelIntegration,
    Conversation,
    ConversationAutomationSettings,
    ConversationMessage,
    ConversationTemplate,
)
from app.services.channel_control_service import integrated_delivery_is_authorized
from app.services.channel_provider_service import (
    delivery_provider_for_channel,
    delivery_supported,
    integration_credentials_expired,
    provider_enabled,
)
from app.services.conversation_automation_state_service import (
    serialize_conversation_automation_state,
)
from app.services.incident_service import INSTAGRAM_AUTH_CLIENT_MESSAGE
from app.services.integration_crypto_service import IntegrationCryptoError, decrypt_secret
from app.services.message_outbox_service import build_whatsapp_url
from app.services.meta_integration_job_service import integration_health_blocks_delivery
from app.services.outbox_queue_service import create_channel_outbox
from app.services.whatsapp_provider import (
    WHATSAPP_PHONE_NUMBER_ID_PATTERN,
    WHATSAPP_TEXT_MAX_LENGTH,
)


@dataclass(frozen=True)
class OutboundMessageResult:
    message: ConversationMessage
    provider_configured: bool
    provider_attempted: bool
    error_message: str | None = None
    client_error_message: str | None = None
    incident_id: str | None = None
    unavailable_reason: str | None = None

    @property
    def ok(self) -> bool:
        return self.message.delivery_status not in {"failed", "blocked", "cancelled"}


@dataclass(frozen=True)
class ConversationDeliveryCapabilities:
    provider: str | None
    integration: BusinessChannelIntegration | None
    delivery_supported: bool
    provider_configured: bool
    channel_enabled: bool
    customer_service_window_open: bool
    integrated_delivery_available: bool
    assisted_delivery_available: bool
    unavailable_reason: str | None

    @property
    def delivery_mode(self) -> str:
        if self.integrated_delivery_available:
            return "integrated"
        if self.assisted_delivery_available:
            return "assisted"
        return "unavailable"


class ConversationDeliveryUnavailable(ValueError):
    def __init__(self, reason: str, safe_message: str, *, status_code: int = 409) -> None:
        self.reason = reason
        self.safe_message = safe_message
        self.status_code = status_code
        super().__init__(safe_message)


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
        "delivered": "Entregado",
        "read": "Leído",
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
    capabilities = conversation_delivery_capabilities(db, conversation=conversation)
    provider = capabilities.provider
    integration = capabilities.integration
    provider_is_configured = capabilities.provider_configured
    if integration is None:
        integration_status = None
    elif conversation.channel == "whatsapp":
        integration_status = integration.integration_status
    elif integration_credentials_expired(integration):
        integration_status = "expired"
    else:
        integration_status = integration.integration_status
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
        "provider_configured": provider_is_configured,
        "integration_status": integration_status,
        "delivery_supported": delivery_supported(
            channel=conversation.channel,
            provider=provider,
        ),
        "integrated_delivery_available": capabilities.integrated_delivery_available,
        "assisted_delivery_available": capabilities.assisted_delivery_available,
        "delivery_mode": capabilities.delivery_mode,
        "customer_service_window_open": capabilities.customer_service_window_open,
        "delivery_unavailable_reason": capabilities.unavailable_reason,
        # Compatibility for the current Admin panel. New consumers must use
        # provider_configured together with delivery_supported.
        "instagram_provider_configured": (
            provider_is_configured if conversation.channel == "instagram" else None
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


def resolve_delivery_integration(
    db: Session,
    *,
    conversation: Conversation,
) -> tuple[str | None, BusinessChannelIntegration | None]:
    provider = delivery_provider_for_channel(conversation.channel)
    if provider is None:
        return None, None
    integration = (
        db.query(BusinessChannelIntegration)
        .filter(
            BusinessChannelIntegration.business_id == conversation.business_id,
            BusinessChannelIntegration.channel == conversation.channel,
            BusinessChannelIntegration.provider == provider,
        )
        .first()
    )
    return provider, integration


def integration_is_ready(integration: BusinessChannelIntegration | None) -> bool:
    return bool(
        integration
        and integration.integration_status in {"connected", "degraded"}
        and integration.encrypted_access_token
        and integration.encryption_key_version
        and not integration_credentials_expired(integration)
        and not integration_health_blocks_delivery(integration)
    )


def is_provider_configured(
    *,
    settings: Settings,
    provider: str | None,
    integration: BusinessChannelIntegration | None,
) -> bool:
    if not provider or not provider_enabled(settings, provider):
        return False
    if provider == "whatsapp":
        return integration is not None
    return integration_is_ready(integration)


def _whatsapp_integration_is_usable(
    *,
    settings: Settings,
    integration: BusinessChannelIntegration | None,
) -> bool:
    if not integration_is_ready(integration):
        return False
    assert integration is not None
    if WHATSAPP_PHONE_NUMBER_ID_PATTERN.fullmatch(integration.external_account_id.strip()) is None:
        return False
    try:
        token = decrypt_secret(
            integration.encrypted_access_token or "",
            integration.encryption_key_version or "",
            settings=settings,
        )
    except IntegrationCryptoError:
        return False
    return bool(token.strip())


def _as_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def _whatsapp_inbound_provider_time(message: ConversationMessage) -> datetime | None:
    if not message.provider_message_id or not message.raw_payload_json:
        return None
    try:
        payload = json.loads(message.raw_payload_json)
        timestamp = payload.get("timestamp") if isinstance(payload, dict) else None
        numeric = int(timestamp) if isinstance(timestamp, str) and timestamp.isdigit() else None
        return datetime.fromtimestamp(numeric, tz=timezone.utc) if numeric is not None else None
    except (OverflowError, TypeError, ValueError):
        return None


def is_whatsapp_customer_service_window_open(
    db: Session,
    *,
    conversation: Conversation,
    settings: Settings | None = None,
    now: datetime | None = None,
) -> bool:
    if conversation.channel != "whatsapp":
        return True
    inbound_messages = (
        db.query(ConversationMessage)
        .filter(
            ConversationMessage.conversation_id == conversation.id,
            ConversationMessage.direction == "inbound",
            ConversationMessage.provider_message_id.is_not(None),
        )
        .order_by(ConversationMessage.created_at.desc(), ConversationMessage.id.desc())
        .all()
    )
    if not inbound_messages:
        return False
    if _whatsapp_inbound_provider_time(inbound_messages[0]) is None:
        return False
    provider_times = [
        provider_time
        for inbound in inbound_messages
        if (provider_time := _whatsapp_inbound_provider_time(inbound)) is not None
    ]
    provider_time = max(provider_times)
    current = _as_utc(now or datetime.now(timezone.utc))
    if provider_time > current:
        return False
    configured = settings or get_settings()
    return current - provider_time <= timedelta(
        hours=configured.whatsapp_customer_service_window_hours
    )


def _assisted_delivery_available(conversation: Conversation) -> bool:
    if conversation.channel != "whatsapp":
        return False
    try:
        build_whatsapp_url(conversation.customer_phone or conversation.external_user_id, "test")
    except ValueError:
        return False
    return True


def conversation_delivery_capabilities(
    db: Session,
    *,
    conversation: Conversation,
    settings: Settings | None = None,
    now: datetime | None = None,
) -> ConversationDeliveryCapabilities:
    configured_settings = settings or get_settings()
    provider, integration = resolve_delivery_integration(db, conversation=conversation)
    system_supported = delivery_supported(channel=conversation.channel, provider=provider)
    provider_is_configured = is_provider_configured(
        settings=configured_settings,
        provider=provider,
        integration=integration,
    )
    integration_is_usable = (
        _whatsapp_integration_is_usable(
            settings=configured_settings,
            integration=integration,
        )
        if provider == "whatsapp"
        else provider_is_configured
    )
    commercial_settings = (
        db.query(ConversationAutomationSettings)
        .filter(ConversationAutomationSettings.business_id == conversation.business_id)
        .first()
    )
    channel_enabled = (
        {
            "instagram": commercial_settings.instagram_channel_enabled,
            "whatsapp": commercial_settings.whatsapp_channel_enabled,
        }.get(conversation.channel, True)
        if commercial_settings is not None
        else True
    )
    channel_enabled = channel_enabled and integrated_delivery_is_authorized(
        db,
        business_id=conversation.business_id,
        channel=conversation.channel,
    )
    window_open = is_whatsapp_customer_service_window_open(
        db,
        conversation=conversation,
        settings=configured_settings,
        now=now,
    )
    integrated_available = bool(
        system_supported and integration_is_usable and channel_enabled and window_open
    )
    reason = None
    if not system_supported:
        reason = "delivery_not_supported"
    elif not provider_is_configured:
        reason = "provider_not_configured"
    elif not integration_is_usable:
        reason = "delivery_not_available"
    elif not channel_enabled:
        reason = "integrated_delivery_not_in_plan"
    elif not window_open:
        reason = "whatsapp_template_required"
    return ConversationDeliveryCapabilities(
        provider=provider,
        integration=integration,
        delivery_supported=system_supported,
        provider_configured=provider_is_configured,
        channel_enabled=channel_enabled,
        customer_service_window_open=window_open,
        integrated_delivery_available=integrated_available,
        assisted_delivery_available=_assisted_delivery_available(conversation),
        unavailable_reason=reason,
    )


def build_conversation_assisted_whatsapp_url(
    conversation: Conversation,
    body: str,
) -> str:
    if conversation.channel != "whatsapp":
        raise ConversationDeliveryUnavailable(
            "assisted_delivery_not_available",
            "El envío asistido sólo está disponible para WhatsApp.",
        )
    return build_whatsapp_url(conversation.customer_phone or conversation.external_user_id, body)


def send_outbound_message(
    db: Session,
    *,
    conversation: Conversation,
    body: str,
    sender_type: str,
    intent: str | None = None,
) -> OutboundMessageResult:
    settings = get_settings()
    capabilities = conversation_delivery_capabilities(
        db,
        conversation=conversation,
        settings=settings,
    )
    provider = capabilities.provider
    integration = capabilities.integration
    provider_configured = capabilities.provider_configured
    if conversation.channel == "whatsapp":
        if len(body.strip()) > WHATSAPP_TEXT_MAX_LENGTH:
            raise ConversationDeliveryUnavailable(
                "invalid_payload",
                "El mensaje de WhatsApp supera el máximo de 4096 caracteres.",
                status_code=422,
            )
        if not capabilities.integrated_delivery_available:
            safe_messages = {
                "provider_not_configured": "La integración de WhatsApp no está disponible.",
                "integrated_delivery_not_in_plan": (
                    "El envío integrado de WhatsApp no está habilitado para este negocio."
                ),
                "whatsapp_template_required": (
                    "Se requiere una plantilla aprobada de WhatsApp para iniciar de nuevo "
                    "la conversación."
                ),
            }
            reason = capabilities.unavailable_reason or "delivery_not_available"
            raise ConversationDeliveryUnavailable(
                reason,
                safe_messages.get(reason, "El envío integrado de WhatsApp no está disponible."),
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
    channel_enabled = (
        {
            "instagram": commercial_settings.instagram_channel_enabled,
            "whatsapp": commercial_settings.whatsapp_channel_enabled,
        }.get(conversation.channel, True)
        if commercial_settings is not None
        else True
    )
    channel_enabled = channel_enabled and integrated_delivery_is_authorized(
        db,
        business_id=conversation.business_id,
        channel=conversation.channel,
    )
    if not channel_enabled:
        policy_blocked = True
        delivery_status = "blocked"
        client_error_message = (
            f"El canal {conversation.channel.title()} no está habilitado para este negocio. "
            "Contacta con el equipo de AutonoGrow."
        )
    if provider is not None and not policy_blocked:
        integration_ready = bool(
            integration_is_ready(integration) and conversation.external_user_id
        )
        delivery_status = (
            "simulated" if legacy_simulation else ("queued" if integration_ready else "blocked")
        )
        if not integration_ready and not legacy_simulation:
            client_error_message = (
                INSTAGRAM_AUTH_CLIENT_MESSAGE
                if provider == "instagram"
                else "La integración del canal no está disponible."
            )
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
    if provider is not None and integration and delivery_status == "queued":
        create_channel_outbox(
            db,
            conversation=conversation,
            message=message,
            provider=provider,
            channel=conversation.channel,
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
        unavailable_reason=capabilities.unavailable_reason,
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
