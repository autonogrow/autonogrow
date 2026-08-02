from collections.abc import Callable, Mapping
from datetime import datetime, timezone

from sqlalchemy.orm import Session

from app.core.config import Settings
from app.models import BusinessChannelIntegration, WebhookInboxEvent
from app.services.channel_provider_contracts import (
    InboxProcessResult,
    InvalidChannelInboxPayload,
    ProviderSender,
    UnsupportedChannelProvider,
)
from app.services.instagram_provider import send_instagram_text_message

InboxProcessor = Callable[[Session, int], InboxProcessResult]


def _process_instagram_inbox_event(db: Session, inbox_event_id: int) -> InboxProcessResult:
    # Local import avoids coupling the common conversation service back to the
    # Instagram inbox processor during module initialization.
    from app.services.instagram_inbox_processor import process_instagram_inbox_event

    return process_instagram_inbox_event(db, inbox_event_id)


def _process_whatsapp_inbox_event(db: Session, inbox_event_id: int) -> InboxProcessResult:
    from app.services.whatsapp_inbox_processor import process_whatsapp_inbox_event

    return process_whatsapp_inbox_event(db, inbox_event_id)


INBOX_PROCESSORS: dict[str, InboxProcessor] = {
    "instagram": _process_instagram_inbox_event,
    "whatsapp": _process_whatsapp_inbox_event,
}

INBOX_CHANNELS_BY_PROVIDER: Mapping[str, str] = {
    "instagram": "instagram",
    "whatsapp": "whatsapp",
}

PROVIDER_SENDERS: dict[str, ProviderSender] = {
    "instagram": send_instagram_text_message,
}

DELIVERY_PROVIDERS_BY_CHANNEL: Mapping[str, str] = {
    "instagram": "instagram",
}


def process_channel_inbox_event(db: Session, inbox_event_id: int) -> InboxProcessResult:
    row = db.get(WebhookInboxEvent, inbox_event_id)
    if row is None:
        raise InvalidChannelInboxPayload("Inbox job is unavailable")
    processor = INBOX_PROCESSORS.get(row.provider)
    if processor is None or INBOX_CHANNELS_BY_PROVIDER.get(row.provider) != row.channel:
        raise UnsupportedChannelProvider(row.provider, operation="inbox")
    return processor(db, inbox_event_id)


def delivery_provider_for_channel(channel: str) -> str | None:
    return DELIVERY_PROVIDERS_BY_CHANNEL.get(channel)


def inbound_supported(channel: str) -> bool:
    return any(
        registered_channel == channel and provider in INBOX_PROCESSORS
        for provider, registered_channel in INBOX_CHANNELS_BY_PROVIDER.items()
    )


def delivery_supported(*, channel: str, provider: str | None = None) -> bool:
    resolved_provider = provider or delivery_provider_for_channel(channel)
    return bool(
        resolved_provider
        and DELIVERY_PROVIDERS_BY_CHANNEL.get(channel) == resolved_provider
        and resolved_provider in PROVIDER_SENDERS
    )


def provider_enabled(settings: Settings, provider: str) -> bool:
    if provider == "instagram":
        return bool(getattr(settings, "instagram_provider_enabled", False))
    return False


def integration_credentials_expired(
    integration: BusinessChannelIntegration,
    *,
    now: datetime | None = None,
) -> bool:
    expires_at = integration.token_expires_at
    if expires_at is None:
        return False
    normalized = (
        expires_at.replace(tzinfo=timezone.utc)
        if expires_at.tzinfo is None
        else expires_at.astimezone(timezone.utc)
    )
    return normalized <= (now or datetime.now(timezone.utc))


def provider_senders(
    overrides: Mapping[str, ProviderSender] | None = None,
) -> dict[str, ProviderSender]:
    return dict(PROVIDER_SENDERS if overrides is None else overrides)
