from dataclasses import dataclass
from typing import Any

WHATSAPP_OBJECT = "whatsapp_business_account"
SUPPORTED_STATUS_VALUES = {"sent", "delivered", "read", "failed"}


@dataclass(frozen=True)
class WhatsAppWebhookEvent:
    event_type: str
    provider_event_id: str | None
    message_id: str | None
    phone_number_id: str | None
    waba_id: str | None
    sender_id: str | None
    contact_name: str | None
    text: str | None
    timestamp: str | None
    message_type: str | None
    status: str | None

    def normalized_payload(self) -> dict[str, str | None]:
        return {
            "message_id": self.message_id,
            "phone_number_id": self.phone_number_id,
            "waba_id": self.waba_id,
            "sender_id": self.sender_id,
            "contact_name": self.contact_name,
            "text": self.text,
            "timestamp": self.timestamp,
            "message_type": self.message_type,
            "status": self.status,
        }


def _clean_string(value: Any, *, max_length: int = 255) -> str | None:
    if value is None:
        return None
    normalized = str(value).strip()
    return normalized[:max_length] if normalized else None


def _clean_text(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    normalized = value.strip()
    return normalized or None


def _contact_names(value: dict[str, Any]) -> dict[str, str]:
    result: dict[str, str] = {}
    contacts = value.get("contacts")
    if not isinstance(contacts, list):
        return result
    for contact in contacts:
        if not isinstance(contact, dict):
            continue
        wa_id = _clean_string(contact.get("wa_id"))
        profile = contact.get("profile")
        name = (
            _clean_string(profile.get("name"), max_length=200)
            if isinstance(profile, dict)
            else None
        )
        if wa_id and name:
            result[wa_id] = name
    return result


def parse_whatsapp_webhook(payload: dict[str, Any]) -> list[WhatsAppWebhookEvent]:
    if payload.get("object") != WHATSAPP_OBJECT:
        return []
    entries = payload.get("entry")
    if not isinstance(entries, list):
        return []

    result: list[WhatsAppWebhookEvent] = []
    for entry in entries:
        if not isinstance(entry, dict):
            continue
        waba_id = _clean_string(entry.get("id"))
        changes = entry.get("changes")
        if not isinstance(changes, list):
            continue
        for change in changes:
            if not isinstance(change, dict) or change.get("field") != "messages":
                continue
            value = change.get("value")
            if not isinstance(value, dict):
                continue
            metadata = value.get("metadata")
            phone_number_id = (
                _clean_string(metadata.get("phone_number_id"))
                if isinstance(metadata, dict)
                else None
            )
            names = _contact_names(value)
            messages = value.get("messages")
            if isinstance(messages, list):
                for message in messages:
                    if not isinstance(message, dict):
                        continue
                    message_id = _clean_string(message.get("id"))
                    sender_id = _clean_string(message.get("from"))
                    message_type = _clean_string(message.get("type"), max_length=40)
                    text_payload = message.get("text")
                    text = (
                        _clean_text(text_payload.get("body"))
                        if message_type == "text" and isinstance(text_payload, dict)
                        else None
                    )
                    result.append(
                        WhatsAppWebhookEvent(
                            event_type=(
                                "message" if message_type == "text" else "unsupported_message"
                            ),
                            provider_event_id=message_id,
                            message_id=message_id,
                            phone_number_id=phone_number_id,
                            waba_id=waba_id,
                            sender_id=sender_id,
                            contact_name=names.get(sender_id or ""),
                            text=text,
                            timestamp=_clean_string(message.get("timestamp"), max_length=40),
                            message_type=message_type,
                            status=None,
                        )
                    )
            statuses = value.get("statuses")
            if isinstance(statuses, list):
                for status_payload in statuses:
                    if not isinstance(status_payload, dict):
                        continue
                    status = _clean_string(status_payload.get("status"), max_length=40)
                    message_id = _clean_string(status_payload.get("id"))
                    result.append(
                        WhatsAppWebhookEvent(
                            event_type="status",
                            provider_event_id=message_id,
                            message_id=message_id,
                            phone_number_id=phone_number_id,
                            waba_id=waba_id,
                            sender_id=_clean_string(status_payload.get("recipient_id")),
                            contact_name=None,
                            text=None,
                            timestamp=_clean_string(status_payload.get("timestamp"), max_length=40),
                            message_type=None,
                            status=status,
                        )
                    )
    return result


def whatsapp_status_is_supported(status: str | None) -> bool:
    return bool(status and status in SUPPORTED_STATUS_VALUES)
