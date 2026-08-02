import hashlib
import hmac
import re
from dataclasses import dataclass
from typing import Any

import requests

from app.core.config import Settings, get_settings
from app.services.channel_provider_contracts import ProviderSendResult


@dataclass(frozen=True)
class InstagramInboundMessage:
    sender_id: str
    recipient_id: str
    message_id: str | None
    text: str
    timestamp: int | None
    raw_payload: dict[str, Any]
    has_attachments: bool
    is_echo: bool
    attachments: list[dict[str, Any]]


@dataclass(frozen=True)
class InstagramVerificationResult:
    ok: bool
    account_id: str | None = None
    account_name: str | None = None
    provider_status: str | None = None
    scopes: tuple[str, ...] = ()
    error_message: str | None = None
    http_status: int | None = None
    error_code: str | None = None
    error_subcode: str | None = None
    error_type: str | None = None
    timed_out: bool = False


def is_instagram_provider_configured(settings: Settings) -> bool:
    return bool(
        getattr(settings, "instagram_provider_enabled", False)
        and getattr(settings, "instagram_access_token", "").strip()
        and getattr(settings, "instagram_business_account_id", "").strip()
    )


def verify_meta_signature(
    raw_body: bytes,
    signature_header: str | None,
    app_secret: str,
) -> bool:
    if not signature_header or not app_secret:
        return False
    if not signature_header.startswith("sha256="):
        return False
    expected = (
        "sha256="
        + hmac.new(
            app_secret.encode("utf-8"),
            raw_body,
            hashlib.sha256,
        ).hexdigest()
    )
    return hmac.compare_digest(expected, signature_header)


def parse_instagram_webhook(
    payload: dict[str, Any],
    *,
    business_account_id: str | None = None,
) -> list[InstagramInboundMessage]:
    parsed: list[InstagramInboundMessage] = []
    if payload.get("object") not in {None, "instagram"}:
        return parsed
    entries = payload.get("entry")
    if not isinstance(entries, list):
        return parsed
    for entry in entries:
        if not isinstance(entry, dict):
            continue
        messaging_events = entry.get("messaging")
        if not isinstance(messaging_events, list):
            continue
        for event in messaging_events:
            if not isinstance(event, dict):
                continue
            message = event.get("message")
            if not isinstance(message, dict):
                continue
            sender = event.get("sender")
            recipient = event.get("recipient")
            sender_id = str(sender.get("id", "")).strip() if isinstance(sender, dict) else ""
            recipient_id = (
                str(recipient.get("id", "")).strip() if isinstance(recipient, dict) else ""
            )
            if not sender_id or not recipient_id:
                continue
            is_echo = message.get("is_echo") is True or bool(
                business_account_id and sender_id == business_account_id
            )
            text = message.get("text")
            attachments = message.get("attachments")
            has_attachments = isinstance(attachments, list) and bool(attachments)
            if isinstance(text, str) and text.strip():
                body = text.strip()
            elif has_attachments:
                body = "[Adjunto enviado]" if is_echo else "[Adjunto recibido]"
            else:
                continue
            timestamp = event.get("timestamp")
            parsed.append(
                InstagramInboundMessage(
                    sender_id=sender_id,
                    recipient_id=recipient_id,
                    message_id=(
                        str(message["mid"]).strip() if message.get("mid") is not None else None
                    ),
                    text=body,
                    timestamp=timestamp if isinstance(timestamp, int) else None,
                    raw_payload=event,
                    has_attachments=has_attachments,
                    is_echo=is_echo,
                    attachments=(
                        [item for item in attachments if isinstance(item, dict)]
                        if isinstance(attachments, list)
                        else []
                    ),
                )
            )
    return parsed


def _has_safe_graph_api_configuration(
    settings: Settings,
    external_account_id: str,
) -> bool:
    version = settings.meta_graph_api_version.strip()
    if not re.fullmatch(r"v\d+\.\d+", version):
        return False
    if not re.fullmatch(r"[A-Za-z0-9_-]+", external_account_id.strip()):
        return False
    return True


def send_instagram_text_message(
    recipient_id: str,
    text: str,
    *,
    access_token: str,
    external_account_id: str,
    settings: Settings | None = None,
    timeout_seconds: float = 10.0,
) -> ProviderSendResult:
    settings = settings or get_settings()
    if not settings.instagram_provider_enabled or not access_token.strip():
        return ProviderSendResult(
            delivery_status="failed",
            error_message="Instagram provider is not configured",
            error_code="integration_not_configured",
        )
    if (
        not _has_safe_graph_api_configuration(settings, external_account_id)
        or not recipient_id.strip()
        or not text.strip()
    ):
        return ProviderSendResult(
            delivery_status="failed",
            error_message="Instagram provider configuration is invalid",
        )
    version = settings.meta_graph_api_version.strip()
    url = f"https://graph.instagram.com/{version}/me/messages"
    try:
        response = requests.post(
            url,
            headers={
                "Authorization": f"Bearer {access_token.strip()}",
                "Content-Type": "application/json",
            },
            json={
                "recipient": {"id": recipient_id.strip()},
                "message": {"text": text.strip()},
            },
            timeout=timeout_seconds,
        )
    except requests.Timeout:
        return ProviderSendResult(
            delivery_status="failed",
            error_message="Instagram provider request timed out",
            timed_out=True,
        )
    except requests.RequestException:
        return ProviderSendResult(
            delivery_status="failed",
            error_message="Instagram provider request failed",
        )
    try:
        response_payload = response.json()
    except ValueError:
        response_payload = {}
    if response.ok:
        provider_message_id = (
            response_payload.get("message_id")
            or response_payload.get("mid")
            or response_payload.get("id")
        )
        return ProviderSendResult(
            delivery_status="sent",
            provider_message_id=(
                str(provider_message_id) if provider_message_id is not None else None
            ),
            http_status=getattr(response, "status_code", None),
        )
    error = response_payload.get("error")
    error_code = error.get("code") if isinstance(error, dict) else None
    error_subcode = error.get("error_subcode") if isinstance(error, dict) else None
    error_type = error.get("type") if isinstance(error, dict) else None
    return ProviderSendResult(
        delivery_status="failed",
        error_message=(
            f"Instagram provider rejected the message (code {error_code})"
            if error_code is not None
            else "Instagram provider rejected the message"
        ),
        http_status=getattr(response, "status_code", None),
        error_code=str(error_code) if error_code is not None else None,
        error_subcode=str(error_subcode) if error_subcode is not None else None,
        error_type=str(error_type)[:120] if error_type is not None else None,
    )


def verify_instagram_access_token(
    external_account_id: str,
    access_token: str,
    *,
    settings: Settings | None = None,
    timeout_seconds: float = 10.0,
) -> InstagramVerificationResult:
    settings = settings or get_settings()
    if not access_token.strip() or not _has_safe_graph_api_configuration(
        settings, external_account_id
    ):
        return InstagramVerificationResult(
            ok=False,
            error_message="Instagram integration configuration is invalid",
            error_code="invalid_integration_configuration",
        )
    version = settings.meta_graph_api_version.strip()
    url = f"https://graph.instagram.com/{version}/{external_account_id.strip()}"
    try:
        response = requests.get(
            url,
            headers={"Authorization": f"Bearer {access_token.strip()}"},
            params={"fields": "id,user_id,username,name"},
            timeout=timeout_seconds,
        )
    except requests.Timeout:
        return InstagramVerificationResult(
            ok=False,
            error_message="Instagram verification timed out",
            error_code="verification_timeout",
            timed_out=True,
        )
    except requests.RequestException:
        return InstagramVerificationResult(
            ok=False,
            error_message="Instagram verification request failed",
            error_code="verification_request_failed",
        )
    try:
        payload = response.json()
    except ValueError:
        payload = {}
    if response.ok:
        provider_scoped_id = str(payload.get("id", "")).strip()
        routing_account_id = str(payload.get("user_id", "")).strip() or provider_scoped_id
        if routing_account_id != external_account_id.strip():
            return InstagramVerificationResult(
                ok=False,
                account_id=routing_account_id or None,
                error_message="Instagram account ID did not match",
                http_status=getattr(response, "status_code", None),
                error_code="account_id_mismatch",
            )
        account_name = payload.get("username") or payload.get("name")
        scopes = payload.get("scopes")
        return InstagramVerificationResult(
            ok=True,
            account_id=routing_account_id,
            account_name=str(account_name)[:255] if account_name else None,
            provider_status="available",
            scopes=tuple(str(item)[:120] for item in scopes) if isinstance(scopes, list) else (),
            http_status=getattr(response, "status_code", None),
        )
    error = payload.get("error") if isinstance(payload, dict) else None
    error_code = error.get("code") if isinstance(error, dict) else None
    error_subcode = error.get("error_subcode") if isinstance(error, dict) else None
    error_type = error.get("type") if isinstance(error, dict) else None
    return InstagramVerificationResult(
        ok=False,
        error_message="Instagram verification was rejected",
        http_status=getattr(response, "status_code", None),
        error_code=str(error_code) if error_code is not None else None,
        error_subcode=str(error_subcode) if error_subcode is not None else None,
        error_type=str(error_type)[:120] if error_type is not None else None,
    )
