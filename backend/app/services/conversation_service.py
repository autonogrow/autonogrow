import json
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any

from sqlalchemy import func, or_
from sqlalchemy.orm import Session, joinedload

from app.core.config import Settings, get_settings
from app.models import (
    AuditLog,
    Business,
    BusinessChannelControl,
    BusinessChannelIntegration,
    Conversation,
    ConversationAutomationSettings,
    ConversationMessage,
    ConversationTemplate,
    Customer,
    CustomerAccountLink,
    User,
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
from app.services.customer_identity_service import normalize_phone
from app.services.idempotent_insert_service import insert_rows_ignore_conflicts
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
WHATSAPP_WINDOW_MESSAGE_SCAN_LIMIT = 100


def conversation_has_manual_customer_decision(
    db: Session, *, conversation: Conversation
) -> bool:
    return (
        db.query(AuditLog.id)
        .filter(
            AuditLog.business_id == conversation.business_id,
            AuditLog.action == "conversation_customer_association_changed",
            AuditLog.resource_type == "conversation",
            AuditLog.resource_id == str(conversation.id),
        )
        .first()
        is not None
    )


def auto_associate_conversation_customer(
    db: Session,
    *,
    business: Business,
    conversation: Conversation,
) -> Customer | None:
    """Use one strong candidate and never override a manual identity decision."""

    if conversation.customer_id is not None or conversation_has_manual_customer_decision(
        db, conversation=conversation
    ):
        return conversation.customer

    customer: Customer | None = None
    if conversation.channel == "whatsapp":
        normalized_phone = normalize_phone(
            conversation.customer_phone,
            region=business.country_code,
        )
        if normalized_phone:
            candidates = (
                db.query(Customer)
                .filter(
                    Customer.business_id == business.id,
                    Customer.phone_normalized == normalized_phone,
                )
                .limit(2)
                .all()
            )
            if len(candidates) == 1:
                customer = candidates[0]
    elif conversation.channel == "instagram" and conversation.external_user_id:
        customer = (
            db.query(Customer)
            .join(CustomerAccountLink, CustomerAccountLink.customer_id == Customer.id)
            .join(User, User.id == CustomerAccountLink.user_id)
            .filter(
                Customer.business_id == business.id,
                CustomerAccountLink.business_id == business.id,
                User.is_active.is_(True),
                User.instagram_verified.is_(True),
                User.instagram_provider_user_id == conversation.external_user_id,
            )
            .first()
        )

    if customer is not None:
        conversation.customer = customer
        db.flush()
    return customer


def serialize_conversation_customer(customer: Customer | None) -> dict[str, Any] | None:
    if customer is None:
        return None
    return {
        "customer_id": customer.id,
        "name": customer.name,
        "phone": customer.phone,
        "phone_normalized": customer.phone_normalized,
        "email": customer.email,
        "status": customer.status,
    }


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
    db: Session,
    conversation: Conversation,
    *,
    include_messages: bool = False,
    capabilities: ConversationDeliveryCapabilities | None = None,
    unread_count_value: int | None = None,
) -> dict[str, Any]:
    try:
        matched_patterns = json.loads(conversation.matched_patterns_json or "[]")
    except (TypeError, ValueError):
        matched_patterns = []
    capabilities = capabilities or conversation_delivery_capabilities(db, conversation=conversation)
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
    customer = conversation.customer
    phone_normalized = normalize_phone(
        conversation.customer_phone,
        region=conversation.business.country_code,
    )
    result = {
        "id": conversation.id,
        "business_id": conversation.business_id,
        "customer_id": conversation.customer_id,
        "customer": serialize_conversation_customer(customer),
        "customer_memory_eligible": bool(customer and customer.account_link),
        "association_status": "associated" if customer else "unassociated",
        "channel_identity": {
            "display_name": conversation.customer_name,
            "username": conversation.customer_username,
            "phone": conversation.customer_phone,
            "phone_normalized": phone_normalized,
        },
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
        "unread_count": (
            unread_count_value
            if unread_count_value is not None
            else unread_count(db, conversation)
        ),
        "created_at": conversation.created_at.isoformat(),
        "updated_at": conversation.updated_at.isoformat(),
    }
    if include_messages:
        result["messages"] = [serialize_message(item) for item in conversation.messages]
    return result


def serialize_conversation_list(
    db: Session,
    conversations: list[Conversation],
) -> list[dict[str, Any]]:
    if not conversations:
        return []
    conversation_ids = [conversation.id for conversation in conversations]
    business_ids = {conversation.business_id for conversation in conversations}
    channels = {conversation.channel for conversation in conversations}
    providers = {
        provider
        for channel in channels
        if (provider := delivery_provider_for_channel(channel)) is not None
    }
    integrations = {
        (row.business_id, row.channel, row.provider): row
        for row in db.query(BusinessChannelIntegration)
        .filter(
            BusinessChannelIntegration.business_id.in_(business_ids),
            BusinessChannelIntegration.channel.in_(channels),
            BusinessChannelIntegration.provider.in_(providers),
        )
        .all()
    }
    commercial_settings = {
        row.business_id: row
        for row in db.query(ConversationAutomationSettings)
        .filter(ConversationAutomationSettings.business_id.in_(business_ids))
        .all()
    }
    controls = {
        (row.business_id, row.channel): row
        for row in db.query(BusinessChannelControl)
        .filter(
            BusinessChannelControl.business_id.in_(business_ids),
            BusinessChannelControl.channel.in_(channels),
        )
        .all()
    }
    unread_counts = {
        conversation_id: count
        for conversation_id, count in db.query(
            ConversationMessage.conversation_id,
            func.count(ConversationMessage.id),
        )
        .join(Conversation, Conversation.id == ConversationMessage.conversation_id)
        .filter(
            ConversationMessage.conversation_id.in_(conversation_ids),
            ConversationMessage.direction == "inbound",
            or_(
                Conversation.last_outbound_at.is_(None),
                ConversationMessage.created_at > Conversation.last_outbound_at,
            ),
        )
        .group_by(ConversationMessage.conversation_id)
        .all()
    }
    whatsapp_ids = [
        conversation.id for conversation in conversations if conversation.channel == "whatsapp"
    ]
    inbound_window_times: dict[int, datetime | None] = {}
    if whatsapp_ids:
        ranked = (
            db.query(
                ConversationMessage.conversation_id.label("conversation_id"),
                ConversationMessage.provider_message_id.label("provider_message_id"),
                ConversationMessage.raw_payload_json.label("raw_payload_json"),
                func.row_number()
                .over(
                    partition_by=ConversationMessage.conversation_id,
                    order_by=(
                        ConversationMessage.created_at.desc(),
                        ConversationMessage.id.desc(),
                    ),
                )
                .label("position"),
            )
            .filter(
                ConversationMessage.conversation_id.in_(whatsapp_ids),
                ConversationMessage.direction == "inbound",
                ConversationMessage.provider_message_id.is_not(None),
            )
            .subquery()
        )
        ranked_rows = (
            db.query(ranked)
            .filter(ranked.c.position <= WHATSAPP_WINDOW_MESSAGE_SCAN_LIMIT)
            .order_by(ranked.c.conversation_id, ranked.c.position)
            .all()
        )
        by_conversation: dict[int, list[datetime | None]] = {}
        for row in ranked_rows:
            by_conversation.setdefault(row.conversation_id, []).append(
                _inbound_provider_time(row.provider_message_id, row.raw_payload_json)
            )
        for conversation_id, provider_times in by_conversation.items():
            if not provider_times or provider_times[0] is None:
                inbound_window_times[conversation_id] = None
                continue
            inbound_window_times[conversation_id] = max(
                value for value in provider_times if value is not None
            )

    configured_settings = get_settings()
    now = datetime.now(timezone.utc)
    results = []
    for conversation in conversations:
        provider = delivery_provider_for_channel(conversation.channel)
        integration = (
            integrations.get((conversation.business_id, conversation.channel, provider))
            if provider is not None
            else None
        )
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
        plan = commercial_settings.get(conversation.business_id)
        channel_enabled = (
            {
                "instagram": plan.instagram_channel_enabled,
                "whatsapp": plan.whatsapp_channel_enabled,
            }.get(conversation.channel, True)
            if plan is not None
            else True
        )
        control = controls.get((conversation.business_id, conversation.channel))
        if control is not None:
            channel_enabled = channel_enabled and (
                control.status == "approved" and control.integrated_delivery_enabled
            )
        if conversation.channel == "whatsapp":
            window_open = _provider_time_is_in_window(
                inbound_window_times.get(conversation.id),
                settings=configured_settings,
                now=now,
            )
        else:
            window_open = True
        system_supported = delivery_supported(channel=conversation.channel, provider=provider)
        integrated_available = bool(
            system_supported and integration_is_usable and channel_enabled and window_open
        )
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
        else:
            reason = None
        capabilities = ConversationDeliveryCapabilities(
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
        results.append(
            serialize_conversation(
                db,
                conversation,
                capabilities=capabilities,
                unread_count_value=unread_counts.get(conversation.id, 0),
            )
        )
    return results


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
    query = (
        db.query(Conversation)
        .options(
            joinedload(Conversation.business),
            joinedload(Conversation.customer).joinedload(Customer.account_link),
        )
        .filter(Conversation.business_id == business_id)
    )
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
        .options(
            joinedload(Conversation.business),
            joinedload(Conversation.customer).joinedload(Customer.account_link),
        )
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


def _inbound_provider_time(
    provider_message_id: str | None,
    raw_payload_json: str | None,
) -> datetime | None:
    if not provider_message_id or not raw_payload_json:
        return None
    try:
        payload = json.loads(raw_payload_json)
        timestamp = payload.get("timestamp") if isinstance(payload, dict) else None
        numeric = int(timestamp) if isinstance(timestamp, str) and timestamp.isdigit() else None
        return datetime.fromtimestamp(numeric, tz=timezone.utc) if numeric is not None else None
    except (OverflowError, TypeError, ValueError):
        return None


def _whatsapp_inbound_provider_time(message: ConversationMessage) -> datetime | None:
    return _inbound_provider_time(message.provider_message_id, message.raw_payload_json)


def _provider_time_is_in_window(
    provider_time: datetime | None,
    *,
    settings: Settings,
    now: datetime,
) -> bool:
    if provider_time is None:
        return False
    current = _as_utc(now)
    if provider_time > current:
        return False
    return current - provider_time <= timedelta(hours=settings.whatsapp_customer_service_window_hours)


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
        .limit(WHATSAPP_WINDOW_MESSAGE_SCAN_LIMIT)
        .all()
    )
    configured = settings or get_settings()
    provider_times = [_whatsapp_inbound_provider_time(message) for message in inbound_messages]
    provider_time = (
        max(value for value in provider_times if value is not None)
        if provider_times and provider_times[0] is not None
        else None
    )
    return _provider_time_is_in_window(
        provider_time,
        settings=configured,
        now=now or datetime.now(timezone.utc),
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
    insert_rows_ignore_conflicts(
        db,
        ConversationTemplate,
        [
            {"business_id": business.id, "name": name, "body": body, "active": True}
            for name, body in DEFAULT_TEMPLATES
        ],
        index_elements=["business_id", "name"],
    )
    return (
        db.query(ConversationTemplate)
        .filter(ConversationTemplate.business_id == business.id)
        .order_by(ConversationTemplate.id)
        .all()
    )


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
