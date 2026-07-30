import hashlib
import json
from secrets import compare_digest

from fastapi import APIRouter, Depends, Header, HTTPException, Query, Request
from fastapi.responses import PlainTextResponse
from sqlalchemy.orm import Session

from app.core.audit import record_audit
from app.core.config import get_settings
from app.core.database import get_db
from app.models import Business, Conversation, ConversationMessage
from app.services.conversation_automation_service import process_inbound_automation
from app.services.conversation_service import add_message, create_or_get_conversation
from app.services.instagram_echo_service import process_instagram_echo
from app.services.instagram_integration_service import (
    mask_external_account_id,
    report_integration_incident,
    resolve_instagram_integration_for_event,
    utc_now,
)
from app.services.instagram_provider import (
    parse_instagram_webhook,
    verify_meta_signature,
)

router = APIRouter(prefix="/api/webhooks/instagram", tags=["instagram-webhook"])


@router.get("")
def verify_instagram_webhook(
    hub_mode: str | None = Query(default=None, alias="hub.mode"),
    hub_verify_token: str | None = Query(default=None, alias="hub.verify_token"),
    hub_challenge: str | None = Query(default=None, alias="hub.challenge"),
):
    configured_token = get_settings().meta_verify_token.strip()
    if (
        hub_mode == "subscribe"
        and configured_token
        and hub_verify_token
        and compare_digest(hub_verify_token, configured_token)
    ):
        return PlainTextResponse(hub_challenge or "")
    raise HTTPException(status_code=403, detail="Webhook verification failed")


@router.post("")
async def receive_instagram_webhook(
    request: Request,
    x_hub_signature_256: str | None = Header(default=None),
    db: Session = Depends(get_db),
):
    settings = get_settings()
    raw_body = await request.body()
    if settings.instagram_require_signature and not verify_meta_signature(
        raw_body,
        x_hub_signature_256,
        settings.meta_app_secret,
    ):
        raise HTTPException(status_code=403, detail="Invalid webhook signature")
    try:
        payload = json.loads(raw_body.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise HTTPException(status_code=400, detail="Invalid webhook payload") from error
    if not isinstance(payload, dict):
        raise HTTPException(status_code=400, detail="Invalid webhook payload")

    message_events = parse_instagram_webhook(payload)
    processed = 0
    duplicates = 0
    echoes = 0
    reconciled = 0
    ignored = 0
    automation_results = []
    for inbound in message_events:
        integration = resolve_instagram_integration_for_event(
            db,
            sender_id=inbound.sender_id,
            recipient_id=inbound.recipient_id,
            is_echo=inbound.is_echo,
        )
        external_account_id = (
            inbound.sender_id if inbound.is_echo else inbound.recipient_id
        )
        if integration is None:
            account_fingerprint = hashlib.sha256(
                external_account_id.encode("utf-8")
            ).hexdigest()[:16]
            report_integration_incident(
                db,
                integration=None,
                business_id=None,
                category="instagram_unmapped_account",
                severity="medium",
                operation="receive_webhook",
                error_code=f"unmapped-{account_fingerprint}",
                safe_details={
                    "external_account_id": mask_external_account_id(
                        external_account_id
                    ),
                    "event_type": "echo" if inbound.is_echo else "inbound",
                    "provider_message_id": inbound.message_id,
                },
            )
            record_audit(
                db,
                action="instagram_unmapped_account_received",
                resource_type="instagram_webhook_event",
                resource_id=inbound.message_id,
                metadata={
                    "external_account_id": mask_external_account_id(
                        external_account_id
                    ),
                    "event_type": "echo" if inbound.is_echo else "inbound",
                    "provider_message_id": inbound.message_id,
                    "timestamp": utc_now().isoformat(),
                },
                commit=False,
            )
            ignored += 1
            continue
        if integration.integration_status not in {"connected", "degraded"}:
            category = {
                "expired": "instagram_token_expired",
                "revoked": "instagram_token_revoked",
            }.get(integration.integration_status, "instagram_authentication")
            report_integration_incident(
                db,
                integration=integration,
                category=category,
                severity="high",
                operation="receive_webhook",
                error_code=f"integration_{integration.integration_status}",
                safe_details={
                    "external_account_id": mask_external_account_id(
                        external_account_id
                    ),
                    "event_type": "echo" if inbound.is_echo else "inbound",
                    "provider_message_id": inbound.message_id,
                    "integration_status": integration.integration_status,
                },
            )
            ignored += 1
            continue
        business = (
            db.query(Business)
            .filter(Business.id == integration.business_id, Business.status == "active")
            .first()
        )
        if business is None:
            ignored += 1
            continue
        integration.last_success_at = utc_now()
        if inbound.is_echo:
            action, _ = process_instagram_echo(
                db,
                business=business,
                event=inbound,
            )
            if action == "duplicate":
                duplicates += 1
            else:
                processed += 1
                echoes += 1
                if action == "reconciled":
                    reconciled += 1
            continue
        if inbound.message_id:
            duplicate = (
                db.query(ConversationMessage)
                .join(Conversation, Conversation.id == ConversationMessage.conversation_id)
                .filter(
                    Conversation.business_id == business.id,
                    ConversationMessage.provider_message_id == inbound.message_id,
                )
                .first()
            )
            if duplicate is not None:
                duplicates += 1
                continue
        conversation, _ = create_or_get_conversation(
            db,
            business_id=business.id,
            channel="instagram",
            external_user_id=inbound.sender_id,
            external_conversation_id=inbound.sender_id,
        )
        message = add_message(
            db,
            conversation=conversation,
            direction="inbound",
            sender_type="customer",
            body=inbound.text,
            provider_message_id=inbound.message_id,
            raw_payload=inbound.raw_payload,
        )
        automation_results.append(
            process_inbound_automation(
                db,
                business=business,
                conversation=conversation,
                message=message,
            )
        )
        processed += 1
    db.commit()
    return {
        "ok": True,
        "processed": processed,
        "duplicates": duplicates,
        "echoes": echoes,
        "reconciled": reconciled,
        "ignored": ignored,
        "automation": automation_results,
    }
