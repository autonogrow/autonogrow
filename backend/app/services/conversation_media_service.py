import json
import logging
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import requests
from sqlalchemy.orm import Session

from app.core.config import Settings, get_settings
from app.models import BusinessChannelIntegration, ConversationMessage
from app.services.integration_crypto_service import IntegrationCryptoError, decrypt_secret

logger = logging.getLogger(__name__)

MAX_MEDIA_BYTES = 25 * 1024 * 1024
SAFE_INLINE_MIME_TYPES = {
    "image/gif",
    "image/jpeg",
    "image/png",
    "image/webp",
    "video/mp4",
    "video/webm",
    "audio/aac",
    "audio/m4a",
    "audio/mp4",
    "audio/mpeg",
    "audio/ogg",
    "audio/webm",
    "audio/wav",
}
LEGACY_MEDIA_FALLBACKS = {
    "[Adjunto recibido]",
    "[Adjunto enviado]",
    "Imagen recibida",
    "Vídeo recibido",
    "Audio recibido",
    "Documento recibido",
    "Archivo recibido",
    "Adjunto no compatible",
}
MEDIA_LABELS = {
    "image": "Imagen",
    "video": "Vídeo",
    "audio": "Audio",
    "document": "Documento",
    "unknown": "Adjunto",
}
PROVIDER_MEDIA_HOST_SUFFIXES = (
    ".cdninstagram.com",
    ".facebook.com",
    ".fbcdn.net",
    ".fbsbx.com",
)


class ConversationMediaError(RuntimeError):
    def __init__(self, code: str, *, status_code: int = 502) -> None:
        self.code = code
        self.status_code = status_code
        super().__init__(code)


@dataclass(frozen=True)
class ConversationMediaContent:
    content: bytes
    content_type: str
    filename: str
    disposition: str


def _raw_payload(message: ConversationMessage) -> dict[str, Any]:
    try:
        value = json.loads(message.raw_payload_json or "null")
    except (TypeError, ValueError):
        return {}
    return value if isinstance(value, dict) else {}


def _clean_text(value: Any, *, limit: int = 500) -> str | None:
    if not isinstance(value, str):
        return None
    cleaned = " ".join(value.replace("\x00", "").split()).strip()
    return cleaned[:limit] if cleaned else None


def _clean_filename(value: Any, *, kind: str) -> str:
    cleaned = _clean_text(value, limit=180)
    if cleaned:
        cleaned = Path(cleaned.replace("\\", "/")).name
        cleaned = re.sub(r"[^\w.()\- ]", "_", cleaned, flags=re.UNICODE).strip(" .")
    if cleaned:
        return cleaned
    return {
        "image": "imagen",
        "video": "video",
        "audio": "audio",
        "document": "documento",
    }.get(kind, "adjunto")


def _kind(value: Any) -> str:
    normalized = str(value or "").strip().lower()
    if normalized in {"image", "video", "audio"}:
        return normalized
    if normalized in {"document", "file"}:
        return "document"
    if normalized == "sticker":
        return "image"
    return "unknown"


def _positive_int(value: Any) -> int | None:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return None
    return parsed if parsed >= 0 else None


def _safe_provider_url(value: Any) -> str | None:
    if not isinstance(value, str) or len(value) > 4096:
        return None
    try:
        parsed = urlparse(value)
    except ValueError:
        return None
    hostname = (parsed.hostname or "").lower()
    try:
        port = parsed.port
    except ValueError:
        return None
    if (
        parsed.scheme != "https"
        or not hostname
        or parsed.username
        or parsed.password
        or port not in {None, 443}
        or not any(hostname == suffix[1:] or hostname.endswith(suffix) for suffix in PROVIDER_MEDIA_HOST_SUFFIXES)
    ):
        return None
    return value


def _instagram_raw_attachments(raw: dict[str, Any]) -> list[dict[str, Any]]:
    message = raw.get("message")
    attachments = message.get("attachments") if isinstance(message, dict) else None
    return [item for item in attachments if isinstance(item, dict)] if isinstance(attachments, list) else []


def _normalized_raw_attachments(raw: dict[str, Any]) -> list[dict[str, Any]]:
    attachments = raw.get("attachments")
    return [item for item in attachments if isinstance(item, dict)] if isinstance(attachments, list) else []


def _private_attachments(message: ConversationMessage) -> list[dict[str, Any]]:
    raw = _raw_payload(message)
    source = message.conversation.channel
    values = _instagram_raw_attachments(raw) if source == "instagram" else _normalized_raw_attachments(raw)
    result: list[dict[str, Any]] = []
    for index, item in enumerate(values, start=1):
        payload = item.get("payload") if isinstance(item.get("payload"), dict) else {}
        kind = _kind(item.get("kind") or item.get("type"))
        provider_url = _safe_provider_url(
            item.get("provider_url") or item.get("url") or payload.get("url")
        )
        thumbnail_provider_url = _safe_provider_url(
            item.get("thumbnail_provider_url")
            or item.get("thumbnail_url")
            or payload.get("thumbnail_url")
        )
        provider_media_id = _clean_text(
            item.get("provider_media_id") or item.get("media_id") or payload.get("attachment_id"),
            limit=255,
        )
        explicit_status = _clean_text(item.get("status"), limit=30)
        if explicit_status in {"expired", "unavailable"}:
            status = "unavailable"
        elif explicit_status == "unsupported" or kind == "unknown":
            status = "unsupported"
        elif provider_url or provider_media_id:
            status = "available"
        else:
            status = "unavailable"
        mime_type = _clean_text(
            item.get("mime_type") or item.get("content_type") or payload.get("mime_type"),
            limit=120,
        )
        filename = _clean_filename(
            item.get("filename") or item.get("title") or payload.get("filename") or payload.get("title"),
            kind=kind,
        )
        result.append(
            {
                "id": str(index),
                "kind": kind,
                "mime_type": mime_type,
                "filename": filename,
                "size_bytes": _positive_int(item.get("size_bytes") or item.get("size")),
                "caption": _clean_text(item.get("caption") or payload.get("caption"), limit=2000),
                "status": status,
                "source": source,
                "_provider_url": provider_url,
                "_thumbnail_provider_url": thumbnail_provider_url,
                "_provider_media_id": provider_media_id,
            }
        )
    return result


def serialize_message_attachments(
    message: ConversationMessage,
    *,
    business_slug: str,
) -> list[dict[str, Any]]:
    result = []
    for attachment in _private_attachments(message):
        access_url = (
            f"/api/admin/businesses/{business_slug}/conversations/{message.conversation_id}"
            f"/messages/{message.id}/attachments/{attachment['id']}/content"
        )
        public = {key: value for key, value in attachment.items() if not key.startswith("_")}
        public["access_url"] = access_url if attachment["status"] == "available" else None
        public["thumbnail_url"] = (
            f"{access_url}?variant=thumbnail"
            if attachment["status"] == "available"
            and attachment["kind"] == "image"
            and attachment.get("_thumbnail_provider_url")
            else access_url
            if attachment["status"] == "available" and attachment["kind"] == "image"
            else None
        )
        result.append(public)
    return result


def message_has_media_fallback(message: ConversationMessage) -> bool:
    return bool(_private_attachments(message) and message.body.strip() in LEGACY_MEDIA_FALLBACKS)


def message_media_preview(message: ConversationMessage) -> str | None:
    attachments = _private_attachments(message)
    if not attachments:
        return None
    if message.body.strip() and message.body.strip() not in LEGACY_MEDIA_FALLBACKS:
        return message.body
    first = attachments[0]
    label = MEDIA_LABELS.get(first["kind"], "Adjunto")
    return label if len(attachments) == 1 else f"{label} y {len(attachments) - 1} adjunto(s) más"


def get_message_attachment(
    message: ConversationMessage,
    attachment_id: str,
) -> dict[str, Any] | None:
    return next(
        (item for item in _private_attachments(message) if item["id"] == attachment_id),
        None,
    )


def _bounded_response_content(response: requests.Response) -> bytes:
    content_length = _positive_int(response.headers.get("Content-Length"))
    if content_length is not None and content_length > MAX_MEDIA_BYTES:
        raise ConversationMediaError("attachment_too_large", status_code=413)
    content = bytearray()
    for chunk in response.iter_content(chunk_size=64 * 1024):
        if not chunk:
            continue
        content.extend(chunk)
        if len(content) > MAX_MEDIA_BYTES:
            raise ConversationMediaError("attachment_too_large", status_code=413)
    return bytes(content)


def _provider_get(
    url: str,
    *,
    token: str | None = None,
    timeout: tuple[float, float] = (5.0, 20.0),
) -> requests.Response:
    try:
        response = requests.get(
            url,
            headers={"Authorization": f"Bearer {token}"} if token else {},
            timeout=timeout,
            stream=True,
            allow_redirects=False,
        )
    except requests.Timeout as exc:
        raise ConversationMediaError("provider_timeout", status_code=504) from exc
    except requests.RequestException as exc:
        raise ConversationMediaError("provider_fetch_failed") from exc
    if response.status_code in {401, 403, 404, 410}:
        raise ConversationMediaError("attachment_unavailable", status_code=410)
    if not response.ok or 300 <= response.status_code < 400:
        raise ConversationMediaError("provider_fetch_failed")
    return response


def _integration_token(
    db: Session,
    *,
    message: ConversationMessage,
    provider: str,
    settings: Settings,
) -> str:
    integration = (
        db.query(BusinessChannelIntegration)
        .filter(
            BusinessChannelIntegration.business_id == message.conversation.business_id,
            BusinessChannelIntegration.channel == message.conversation.channel,
            BusinessChannelIntegration.provider == provider,
        )
        .first()
    )
    if (
        integration is None
        or integration.integration_status not in {"connected", "degraded"}
        or not integration.encrypted_access_token
        or not integration.encryption_key_version
    ):
        raise ConversationMediaError("attachment_unavailable", status_code=410)
    try:
        return decrypt_secret(
            integration.encrypted_access_token,
            integration.encryption_key_version,
            settings=settings,
        )
    except IntegrationCryptoError as exc:
        raise ConversationMediaError("attachment_unavailable", status_code=410) from exc


def fetch_message_attachment(
    db: Session,
    *,
    message: ConversationMessage,
    attachment: dict[str, Any],
    variant: str = "content",
    settings: Settings | None = None,
) -> ConversationMediaContent:
    settings = settings or get_settings()
    if attachment.get("status") != "available":
        raise ConversationMediaError("attachment_unavailable", status_code=410)
    source = attachment.get("source")
    if source == "instagram":
        url = (
            attachment.get("_thumbnail_provider_url")
            if variant == "thumbnail"
            else attachment.get("_provider_url")
        ) or attachment.get("_provider_url")
        if not url or not _safe_provider_url(url):
            raise ConversationMediaError("attachment_unavailable", status_code=410)
        response = _provider_get(url)
    elif source == "whatsapp":
        media_id = attachment.get("_provider_media_id")
        if not isinstance(media_id, str) or not re.fullmatch(r"[A-Za-z0-9_-]{1,255}", media_id):
            raise ConversationMediaError("attachment_unavailable", status_code=410)
        token = _integration_token(
            db,
            message=message,
            provider="whatsapp",
            settings=settings,
        )
        version = settings.meta_graph_api_version.strip()
        if not re.fullmatch(r"v\d+\.\d+", version):
            raise ConversationMediaError("attachment_unavailable", status_code=410)
        metadata_response = _provider_get(
            f"https://graph.facebook.com/{version}/{media_id}", token=token
        )
        try:
            metadata = metadata_response.json()
        except ValueError as exc:
            raise ConversationMediaError("provider_response_invalid") from exc
        provider_url = _safe_provider_url(metadata.get("url") if isinstance(metadata, dict) else None)
        if not provider_url:
            raise ConversationMediaError("provider_response_invalid")
        response = _provider_get(provider_url, token=token)
    else:
        raise ConversationMediaError("attachment_unavailable", status_code=410)

    content = _bounded_response_content(response)
    header_type = _clean_text(response.headers.get("Content-Type"), limit=120)
    content_type = (header_type or attachment.get("mime_type") or "application/octet-stream").split(
        ";", 1
    )[0].lower()
    inline = attachment.get("kind") in {"image", "video", "audio"} and content_type in SAFE_INLINE_MIME_TYPES
    if not inline and content_type in {"image/svg+xml", "text/html", "application/xhtml+xml"}:
        content_type = "application/octet-stream"
    return ConversationMediaContent(
        content=content,
        content_type=content_type,
        filename=_clean_filename(attachment.get("filename"), kind=attachment.get("kind", "unknown")),
        disposition="inline" if inline else "attachment",
    )
