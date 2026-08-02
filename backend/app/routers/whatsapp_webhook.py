import json
from secrets import compare_digest

from fastapi import APIRouter, Depends, Header, HTTPException, Query, Request
from fastapi.responses import PlainTextResponse
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.database import get_db
from app.services.inbox_queue_service import (
    enqueue_whatsapp_events,
    extract_whatsapp_webhook_events,
)
from app.services.instagram_provider import verify_meta_signature
from app.services.whatsapp_provider import WHATSAPP_OBJECT

router = APIRouter(prefix="/api/webhooks/whatsapp", tags=["whatsapp-webhook"])


@router.get("")
def verify_whatsapp_webhook(
    hub_mode: str | None = Query(default=None, alias="hub.mode"),
    hub_verify_token: str | None = Query(default=None, alias="hub.verify_token"),
    hub_challenge: str | None = Query(default=None, alias="hub.challenge"),
):
    settings = get_settings()
    if not settings.whatsapp_webhook_enabled:
        raise HTTPException(status_code=503, detail="WhatsApp webhook is not enabled")
    configured_token = settings.whatsapp_verify_token.strip()
    if (
        hub_mode == "subscribe"
        and configured_token
        and hub_verify_token
        and hub_challenge is not None
        and compare_digest(hub_verify_token, configured_token)
    ):
        return PlainTextResponse(hub_challenge)
    raise HTTPException(status_code=403, detail="Webhook verification failed")


@router.post("")
async def receive_whatsapp_webhook(
    request: Request,
    x_hub_signature_256: str | None = Header(default=None),
    db: Session = Depends(get_db),
):
    settings = get_settings()
    if not settings.whatsapp_webhook_enabled:
        raise HTTPException(status_code=503, detail="WhatsApp webhook is not enabled")
    body = bytearray()
    async for chunk in request.stream():
        if len(body) + len(chunk) > settings.webhook_max_payload_bytes:
            raise HTTPException(status_code=413, detail="Webhook payload too large")
        body.extend(chunk)
    raw_body = bytes(body)
    if settings.whatsapp_require_signature and not verify_meta_signature(
        raw_body,
        x_hub_signature_256,
        settings.meta_app_secret,
    ):
        raise HTTPException(status_code=403, detail="Invalid webhook signature")
    try:
        payload = json.loads(raw_body.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise HTTPException(status_code=400, detail="Invalid webhook payload") from error
    if (
        not isinstance(payload, dict)
        or payload.get("object") != WHATSAPP_OBJECT
        or not isinstance(payload.get("entry"), list)
    ):
        raise HTTPException(status_code=400, detail="Invalid webhook payload")
    events = extract_whatsapp_webhook_events(payload)
    accepted, duplicates = enqueue_whatsapp_events(
        db,
        events,
        max_attempts=settings.worker_max_attempts,
        request_id=getattr(request.state, "request_id", None),
    )
    db.commit()
    return {"ok": True, "accepted": accepted, "duplicates": duplicates}
