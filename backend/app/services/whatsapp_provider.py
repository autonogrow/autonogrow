import re
from dataclasses import dataclass
from typing import Any

import requests

from app.core.config import Settings, get_settings
from app.services.channel_provider_contracts import ProviderSendResult

WHATSAPP_OBJECT = "whatsapp_business_account"
SUPPORTED_STATUS_VALUES = {"sent", "delivered", "read", "failed"}
WHATSAPP_TEXT_MAX_LENGTH = 4096
WHATSAPP_PHONE_NUMBER_ID_PATTERN = re.compile(r"[1-9][0-9]{5,24}")
WHATSAPP_RECIPIENT_PATTERN = re.compile(r"[1-9][0-9]{7,14}")


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
    status_error_code: str | None = None
    status_error_type: str | None = None

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
            "status_error_code": self.status_error_code,
            "status_error_type": self.status_error_type,
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
                    status_error_code = None
                    status_error_type = None
                    errors = status_payload.get("errors")
                    if isinstance(errors, list) and errors and isinstance(errors[0], dict):
                        status_error_code = _clean_string(errors[0].get("code"), max_length=120)
                        status_error_type = _clean_string(
                            errors[0].get("type"),
                            max_length=120,
                        )
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
                            status_error_code=status_error_code,
                            status_error_type=status_error_type,
                        )
                    )
    return result


def whatsapp_status_is_supported(status: str | None) -> bool:
    return bool(status and status in SUPPORTED_STATUS_VALUES)


def _whatsapp_error_code(payload: dict[str, Any], http_status: int | None) -> str:
    error = payload.get("error")
    meta_code = str(error.get("code", "")) if isinstance(error, dict) else ""
    if http_status == 429 or meta_code == "130429":
        return "provider_rate_limited"
    if meta_code == "190":
        return "token_revoked"
    if meta_code in {"10", "200", "131005"}:
        return "insufficient_permissions"
    if meta_code in {"131030", "131026"}:
        return "invalid_recipient"
    if meta_code == "131047":
        return "whatsapp_template_required"
    if meta_code == "131031":
        return "account_suspended"
    if meta_code == "133010":
        return "number_not_registered"
    if meta_code in {"131000", "131016"}:
        return "provider_unavailable"
    if meta_code == "100":
        return "invalid_payload"
    return "provider_rejected"


def send_whatsapp_text_message(
    recipient_id: str,
    text: str,
    *,
    access_token: str,
    external_account_id: str,
    settings: Settings | None = None,
    timeout_seconds: float = 10.0,
) -> ProviderSendResult:
    settings = settings or get_settings()
    recipient = recipient_id.strip()
    body = text.strip()
    phone_number_id = external_account_id.strip()
    version = settings.meta_graph_api_version.strip()
    if not access_token.strip():
        return ProviderSendResult(
            delivery_status="failed",
            error_message="WhatsApp integration is not configured",
            error_code="integration_not_configured",
        )
    if re.fullmatch(r"v[0-9]+\.[0-9]+", version) is None:
        return ProviderSendResult(
            delivery_status="failed",
            error_message="WhatsApp provider configuration is invalid",
            error_code="invalid_integration_configuration",
        )
    if WHATSAPP_PHONE_NUMBER_ID_PATTERN.fullmatch(phone_number_id) is None:
        return ProviderSendResult(
            delivery_status="failed",
            error_message="WhatsApp phone number ID is invalid",
            error_code="invalid_phone_number_id",
        )
    if WHATSAPP_RECIPIENT_PATTERN.fullmatch(recipient) is None:
        return ProviderSendResult(
            delivery_status="failed",
            error_message="WhatsApp recipient is invalid",
            error_code="invalid_recipient",
        )
    if not body or len(body) > WHATSAPP_TEXT_MAX_LENGTH:
        return ProviderSendResult(
            delivery_status="failed",
            error_message="WhatsApp text message is invalid",
            error_code="invalid_payload",
        )

    url = f"https://graph.facebook.com/{version}/{phone_number_id}/messages"
    try:
        response = requests.post(
            url,
            headers={
                "Authorization": f"Bearer {access_token.strip()}",
                "Content-Type": "application/json",
            },
            json={
                "messaging_product": "whatsapp",
                "recipient_type": "individual",
                "to": recipient,
                "type": "text",
                "text": {"preview_url": False, "body": body},
            },
            timeout=timeout_seconds,
        )
    except requests.Timeout:
        return ProviderSendResult(
            delivery_status="failed",
            error_message="WhatsApp provider request timed out",
            error_code="provider_timeout",
            timed_out=True,
        )
    except requests.RequestException:
        return ProviderSendResult(
            delivery_status="failed",
            error_message="WhatsApp provider request failed",
            error_code="request_failed",
        )

    try:
        response_payload = response.json()
    except ValueError:
        response_payload = {}
    if not isinstance(response_payload, dict):
        response_payload = {}
    http_status = getattr(response, "status_code", None)
    if response.ok:
        messages = response_payload.get("messages")
        provider_message_id = (
            messages[0].get("id")
            if isinstance(messages, list) and messages and isinstance(messages[0], dict)
            else None
        )
        if not isinstance(provider_message_id, str) or not provider_message_id.strip():
            return ProviderSendResult(
                delivery_status="failed",
                error_message="WhatsApp provider response is invalid",
                http_status=http_status,
                error_code="invalid_provider_response",
            )
        return ProviderSendResult(
            delivery_status="sent",
            provider_message_id=provider_message_id.strip()[:255],
            http_status=http_status,
        )

    error = response_payload.get("error")
    error_code = error.get("code") if isinstance(error, dict) else None
    error_subcode = error.get("error_subcode") if isinstance(error, dict) else None
    error_type = error.get("type") if isinstance(error, dict) else None
    return ProviderSendResult(
        delivery_status="failed",
        error_message="WhatsApp provider rejected the message",
        http_status=http_status,
        error_code=_whatsapp_error_code(response_payload, http_status),
        error_subcode=str(error_subcode)[:120] if error_subcode is not None else None,
        error_type=(
            str(error_type)[:120]
            if error_type is not None
            else str(error_code)[:120]
            if error_code is not None
            else None
        ),
    )
