from secrets import compare_digest

from fastapi import APIRouter, Depends, Header, HTTPException, Query, Request
from sqlalchemy.orm import Session

from app.core.audit import record_audit
from app.core.config import get_settings
from app.core.database import get_db
from app.core.security import require_business_access, require_business_admin
from app.models import (
    Business,
    ConversationSuggestion,
    ConversationTemplate,
    User,
)
from app.schemas.conversation import (
    CHANNELS,
    CONVERSATION_STATUSES,
    ConversationCreate,
    ConversationAutomationRuleUpdate,
    ConversationAutomationSettingsUpdate,
    ConversationMessageCreate,
    ConversationStatusUpdate,
    ConversationTemplateCreate,
    ConversationTemplateUpdate,
    ConversationSuggestionUpdate,
    TestInboundMessageCreate,
)
from app.services.conversation_automation_service import (
    ensure_automation_configuration,
    get_suggestion_for_business,
    process_inbound_automation,
    serialize_rule,
    serialize_settings,
    serialize_suggestion,
    update_suggestion_status,
)
from app.services.conversation_intent_service import (
    AVAILABLE_INTENTS,
    INTENT_LABELS,
)
from app.services.conversation_service import (
    add_message,
    create_or_get_conversation,
    ensure_default_templates,
    get_conversation,
    list_conversations,
    send_manual_message,
    serialize_conversation,
    serialize_message,
    serialize_template,
    update_status,
)


admin_router = APIRouter(
    prefix="/api/admin/businesses/{business_slug}",
    tags=["conversations"],
    dependencies=[Depends(require_business_access)],
)
webhook_router = APIRouter(prefix="/api/webhooks/test", tags=["test-webhooks"])


def get_business_or_404(db: Session, business_slug: str) -> Business:
    business = db.query(Business).filter(Business.slug == business_slug).first()
    if business is None:
        raise HTTPException(status_code=404, detail="Business not found")
    return business


def get_conversation_or_404(
    db: Session, *, business_id: int, conversation_id: int
):
    conversation = get_conversation(
        db, business_id=business_id, conversation_id=conversation_id
    )
    if conversation is None:
        raise HTTPException(status_code=404, detail="Conversation not found")
    return conversation


@admin_router.get("/conversations")
def admin_list_conversations(
    business_slug: str,
    status: str | None = Query(default=None),
    channel: str | None = Query(default=None),
    q: str | None = Query(default=None, max_length=200),
    limit: int = Query(default=50, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    db: Session = Depends(get_db),
):
    if status is not None and status not in CONVERSATION_STATUSES:
        raise HTTPException(status_code=422, detail="Invalid conversation status")
    if channel is not None and channel not in CHANNELS:
        raise HTTPException(status_code=422, detail="Invalid channel")
    business = get_business_or_404(db, business_slug)
    rows, total = list_conversations(
        db,
        business_id=business.id,
        status=status,
        channel=channel,
        q=q,
        limit=limit,
        offset=offset,
    )
    return {
        "business_slug": business.slug,
        "total": total,
        "limit": limit,
        "offset": offset,
        "conversations": [serialize_conversation(db, item) for item in rows],
    }


@admin_router.get("/conversations/{conversation_id}")
def admin_get_conversation(
    business_slug: str,
    conversation_id: int,
    db: Session = Depends(get_db),
):
    business = get_business_or_404(db, business_slug)
    conversation = get_conversation_or_404(
        db, business_id=business.id, conversation_id=conversation_id
    )
    return {
        "business_slug": business.slug,
        "conversation": serialize_conversation(
            db, conversation, include_messages=True
        ),
    }


@admin_router.post("/conversations", status_code=201)
def admin_create_conversation(
    business_slug: str,
    payload: ConversationCreate,
    request: Request,
    actor: User = Depends(require_business_admin),
    db: Session = Depends(get_db),
):
    business = get_business_or_404(db, business_slug)
    conversation, created = create_or_get_conversation(
        db,
        business_id=business.id,
        channel=payload.channel,
        external_user_id=payload.external_user_id,
        customer_name=payload.customer_name,
        customer_phone=payload.customer_phone,
        customer_username=payload.customer_username,
    )
    if payload.initial_message:
        add_message(
            db,
            conversation=conversation,
            direction="inbound",
            sender_type="customer",
            body=payload.initial_message,
        )
    db.commit()
    db.refresh(conversation)
    record_audit(
        db,
        action="conversation_created" if created else "conversation_updated",
        request=request,
        actor=actor,
        business_id=business.id,
        resource_type="conversation",
        resource_id=conversation.id,
        metadata={"channel": conversation.channel},
    )
    return {
        "ok": True,
        "created": created,
        "conversation": serialize_conversation(
            db, conversation, include_messages=True
        ),
    }


@admin_router.post("/conversations/{conversation_id}/messages", status_code=201)
def admin_send_conversation_message(
    business_slug: str,
    conversation_id: int,
    payload: ConversationMessageCreate,
    request: Request,
    actor: User = Depends(require_business_access),
    db: Session = Depends(get_db),
):
    business = get_business_or_404(db, business_slug)
    conversation = get_conversation_or_404(
        db, business_id=business.id, conversation_id=conversation_id
    )
    suggestion = None
    if payload.suggestion_id is not None:
        suggestion = get_suggestion_for_business(
            db,
            business_id=business.id,
            suggestion_id=payload.suggestion_id,
        )
        if suggestion is None or suggestion.conversation_id != conversation.id:
            raise HTTPException(status_code=404, detail="Conversation suggestion not found")
        if suggestion.status != "pending":
            raise HTTPException(status_code=409, detail="Conversation suggestion is not pending")
    message = send_manual_message(db, conversation=conversation, body=payload.body)
    if suggestion is not None:
        update_suggestion_status(suggestion, "used")
    db.commit()
    db.refresh(message)
    record_audit(
        db,
        action="conversation_message_sent",
        request=request,
        actor=actor,
        business_id=business.id,
        resource_type="conversation",
        resource_id=conversation.id,
        metadata={"channel": conversation.channel},
    )
    return {
        "ok": True,
        "message": serialize_message(message),
        "conversation": serialize_conversation(db, conversation),
    }


@admin_router.patch("/conversations/{conversation_id}/status")
def admin_update_conversation_status(
    business_slug: str,
    conversation_id: int,
    payload: ConversationStatusUpdate,
    request: Request,
    actor: User = Depends(require_business_access),
    db: Session = Depends(get_db),
):
    business = get_business_or_404(db, business_slug)
    conversation = get_conversation_or_404(
        db, business_id=business.id, conversation_id=conversation_id
    )
    update_status(conversation, payload.status)
    db.commit()
    db.refresh(conversation)
    record_audit(
        db,
        action="conversation_status_changed",
        request=request,
        actor=actor,
        business_id=business.id,
        resource_type="conversation",
        resource_id=conversation.id,
        metadata={"status": conversation.status},
    )
    return {"ok": True, "conversation": serialize_conversation(db, conversation)}


@admin_router.get("/conversation-templates")
def admin_list_conversation_templates(
    business_slug: str,
    db: Session = Depends(get_db),
):
    business = get_business_or_404(db, business_slug)
    templates = ensure_default_templates(db, business)
    db.commit()
    return {
        "business_slug": business.slug,
        "templates": [serialize_template(item, business) for item in templates],
    }


@admin_router.post("/conversation-templates", status_code=201)
def admin_create_conversation_template(
    business_slug: str,
    payload: ConversationTemplateCreate,
    request: Request,
    actor: User = Depends(require_business_admin),
    db: Session = Depends(get_db),
):
    business = get_business_or_404(db, business_slug)
    duplicate = (
        db.query(ConversationTemplate)
        .filter(
            ConversationTemplate.business_id == business.id,
            ConversationTemplate.name == payload.name,
        )
        .first()
    )
    if duplicate:
        raise HTTPException(status_code=409, detail="Template name already exists")
    template = ConversationTemplate(business_id=business.id, **payload.model_dump())
    db.add(template)
    db.commit()
    db.refresh(template)
    record_audit(
        db,
        action="conversation_template_created",
        request=request,
        actor=actor,
        business_id=business.id,
        resource_type="conversation_template",
        resource_id=template.id,
    )
    return {"ok": True, "template": serialize_template(template, business)}


@admin_router.patch("/conversation-templates/{template_id}")
def admin_update_conversation_template(
    business_slug: str,
    template_id: int,
    payload: ConversationTemplateUpdate,
    request: Request,
    actor: User = Depends(require_business_admin),
    db: Session = Depends(get_db),
):
    business = get_business_or_404(db, business_slug)
    template = (
        db.query(ConversationTemplate)
        .filter(
            ConversationTemplate.id == template_id,
            ConversationTemplate.business_id == business.id,
        )
        .first()
    )
    if template is None:
        raise HTTPException(status_code=404, detail="Conversation template not found")
    updates = payload.model_dump(exclude_unset=True)
    if "name" in updates:
        duplicate = (
            db.query(ConversationTemplate)
            .filter(
                ConversationTemplate.business_id == business.id,
                ConversationTemplate.name == updates["name"],
                ConversationTemplate.id != template.id,
            )
            .first()
        )
        if duplicate:
            raise HTTPException(status_code=409, detail="Template name already exists")
    for field, value in updates.items():
        setattr(template, field, value)
    db.commit()
    db.refresh(template)
    record_audit(
        db,
        action="conversation_template_updated",
        request=request,
        actor=actor,
        business_id=business.id,
        resource_type="conversation_template",
        resource_id=template.id,
    )
    return {"ok": True, "template": serialize_template(template, business)}


@admin_router.delete("/conversation-templates/{template_id}")
def admin_delete_conversation_template(
    business_slug: str,
    template_id: int,
    request: Request,
    actor: User = Depends(require_business_admin),
    db: Session = Depends(get_db),
):
    business = get_business_or_404(db, business_slug)
    template = (
        db.query(ConversationTemplate)
        .filter(
            ConversationTemplate.id == template_id,
            ConversationTemplate.business_id == business.id,
        )
        .first()
    )
    if template is None:
        raise HTTPException(status_code=404, detail="Conversation template not found")
    db.delete(template)
    db.commit()
    record_audit(
        db,
        action="conversation_template_deleted",
        request=request,
        actor=actor,
        business_id=business.id,
        resource_type="conversation_template",
        resource_id=template_id,
    )
    return {"ok": True}


@admin_router.get("/conversation-automation")
def admin_get_conversation_automation(
    business_slug: str,
    actor: User = Depends(require_business_admin),
    db: Session = Depends(get_db),
):
    business = get_business_or_404(db, business_slug)
    settings, rules = ensure_automation_configuration(db, business)
    db.commit()
    templates = (
        db.query(ConversationTemplate)
        .filter(ConversationTemplate.business_id == business.id)
        .order_by(ConversationTemplate.name, ConversationTemplate.id)
        .all()
    )
    serialized_settings = serialize_settings(settings)
    return {
        "business_slug": business.slug,
        "settings": serialized_settings,
        "rules": [serialize_rule(rule) for rule in rules],
        "usage": {
            "used": settings.auto_used_current_period,
            "limit": settings.monthly_auto_limit,
            "remaining": max(
                0,
                settings.monthly_auto_limit - settings.auto_used_current_period,
            ),
            "period_yyyymm": settings.period_yyyymm,
            "limit_reached": serialized_settings["limit_reached"],
        },
        "available_intents": [
            {"key": intent, "label": INTENT_LABELS[intent]}
            for intent in AVAILABLE_INTENTS
        ],
        "templates": [serialize_template(template, business) for template in templates],
    }


@admin_router.patch("/conversation-automation/settings")
def admin_update_conversation_automation_settings(
    business_slug: str,
    payload: ConversationAutomationSettingsUpdate,
    request: Request,
    actor: User = Depends(require_business_admin),
    db: Session = Depends(get_db),
):
    business = get_business_or_404(db, business_slug)
    settings, _ = ensure_automation_configuration(db, business)
    updates = {
        field: value
        for field, value in payload.model_dump(exclude_unset=True).items()
        if value is not None
    }
    for field, value in updates.items():
        setattr(settings, field, value)
    db.commit()
    db.refresh(settings)
    record_audit(
        db,
        action="conversation_automation_settings_updated",
        request=request,
        actor=actor,
        business_id=business.id,
        resource_type="conversation_automation_settings",
        resource_id=settings.id,
    )
    return {"ok": True, "settings": serialize_settings(settings)}


@admin_router.patch("/conversation-automation/rules/{intent}")
def admin_update_conversation_automation_rule(
    business_slug: str,
    intent: str,
    payload: ConversationAutomationRuleUpdate,
    request: Request,
    actor: User = Depends(require_business_admin),
    db: Session = Depends(get_db),
):
    if intent not in AVAILABLE_INTENTS:
        raise HTTPException(status_code=404, detail="Automation intent not found")
    business = get_business_or_404(db, business_slug)
    _, rules = ensure_automation_configuration(db, business)
    rule = next(item for item in rules if item.intent == intent)
    updates = payload.model_dump(exclude_unset=True)
    for field in ("mode", "active"):
        if updates.get(field) is None:
            updates.pop(field, None)
    if updates.get("template_id") is not None:
        template_exists = (
            db.query(ConversationTemplate)
            .filter(
                ConversationTemplate.id == updates["template_id"],
                ConversationTemplate.business_id == business.id,
            )
            .first()
        )
        if template_exists is None:
            raise HTTPException(status_code=404, detail="Conversation template not found")
    for field, value in updates.items():
        setattr(rule, field, value)
    db.commit()
    db.refresh(rule)
    record_audit(
        db,
        action="conversation_automation_rule_updated",
        request=request,
        actor=actor,
        business_id=business.id,
        resource_type="conversation_automation_rule",
        resource_id=rule.id,
        metadata={"intent": intent},
    )
    return {"ok": True, "rule": serialize_rule(rule)}


@admin_router.get("/conversations/{conversation_id}/suggestions")
def admin_list_conversation_suggestions(
    business_slug: str,
    conversation_id: int,
    db: Session = Depends(get_db),
):
    business = get_business_or_404(db, business_slug)
    conversation = get_conversation_or_404(
        db,
        business_id=business.id,
        conversation_id=conversation_id,
    )
    settings, _ = ensure_automation_configuration(db, business)
    db.commit()
    suggestions = (
        db.query(ConversationSuggestion)
        .filter(ConversationSuggestion.conversation_id == conversation.id)
        .order_by(ConversationSuggestion.created_at.desc(), ConversationSuggestion.id.desc())
        .all()
    )
    limit_reached = (
        settings.automation_enabled
        and settings.auto_used_current_period >= settings.monthly_auto_limit
    )
    return {
        "business_slug": business.slug,
        "conversation_id": conversation.id,
        "suggestions": [serialize_suggestion(item) for item in suggestions],
        "limit_reached": limit_reached,
        "notice": (
            "Límite mensual alcanzado. Las respuestas automáticas pasan a modo sugerencia."
            if limit_reached and settings.on_limit_reached == "semi_automatic"
            else None
        ),
    }


@admin_router.patch("/conversation-suggestions/{suggestion_id}")
def admin_update_conversation_suggestion(
    business_slug: str,
    suggestion_id: int,
    payload: ConversationSuggestionUpdate,
    request: Request,
    actor: User = Depends(require_business_access),
    db: Session = Depends(get_db),
):
    business = get_business_or_404(db, business_slug)
    suggestion = get_suggestion_for_business(
        db,
        business_id=business.id,
        suggestion_id=suggestion_id,
    )
    if suggestion is None:
        raise HTTPException(status_code=404, detail="Conversation suggestion not found")
    if suggestion.status != "pending":
        raise HTTPException(status_code=409, detail="Conversation suggestion is not pending")
    update_suggestion_status(suggestion, payload.status)
    db.commit()
    db.refresh(suggestion)
    record_audit(
        db,
        action=f"conversation_suggestion_{payload.status}",
        request=request,
        actor=actor,
        business_id=business.id,
        resource_type="conversation_suggestion",
        resource_id=suggestion.id,
    )
    return {"ok": True, "suggestion": serialize_suggestion(suggestion)}


@admin_router.post("/conversation-suggestions/{suggestion_id}/send", status_code=201)
def admin_send_conversation_suggestion(
    business_slug: str,
    suggestion_id: int,
    request: Request,
    actor: User = Depends(require_business_access),
    db: Session = Depends(get_db),
):
    business = get_business_or_404(db, business_slug)
    suggestion = get_suggestion_for_business(
        db,
        business_id=business.id,
        suggestion_id=suggestion_id,
    )
    if suggestion is None:
        raise HTTPException(status_code=404, detail="Conversation suggestion not found")
    if suggestion.status != "pending":
        raise HTTPException(status_code=409, detail="Conversation suggestion is not pending")
    conversation = get_conversation_or_404(
        db,
        business_id=business.id,
        conversation_id=suggestion.conversation_id,
    )
    try:
        message = send_manual_message(
            db,
            conversation=conversation,
            body=suggestion.body,
        )
        update_suggestion_status(suggestion, "used")
        db.commit()
    except HTTPException:
        db.rollback()
        raise
    except Exception as error:
        db.rollback()
        raise HTTPException(
            status_code=500,
            detail="No se pudo enviar la sugerencia",
        ) from error
    db.refresh(message)
    db.refresh(suggestion)
    db.refresh(conversation)
    record_audit(
        db,
        action="conversation_suggestion_sent",
        request=request,
        actor=actor,
        business_id=business.id,
        resource_type="conversation_suggestion",
        resource_id=suggestion.id,
        metadata={"conversation_id": conversation.id},
    )
    return {
        "ok": True,
        "message": serialize_message(message),
        "suggestion": serialize_suggestion(suggestion),
        "conversation": serialize_conversation(db, conversation),
    }


def verify_test_webhook_secret(provided_secret: str | None) -> None:
    settings = get_settings()
    configured_secret = settings.webhook_test_secret.strip()
    if settings.app_env == "local" and not configured_secret:
        return
    if not configured_secret:
        raise HTTPException(
            status_code=503,
            detail="WEBHOOK_TEST_SECRET is required outside local development",
        )
    if not provided_secret or not compare_digest(provided_secret, configured_secret):
        raise HTTPException(status_code=403, detail="Invalid webhook secret")


@webhook_router.post("/inbound-message", status_code=201)
def test_inbound_message(
    payload: TestInboundMessageCreate,
    x_autonogrow_webhook_secret: str | None = Header(default=None),
    db: Session = Depends(get_db),
):
    verify_test_webhook_secret(x_autonogrow_webhook_secret)
    business = (
        db.query(Business)
        .filter(Business.slug == payload.business_slug, Business.status == "active")
        .first()
    )
    if business is None:
        raise HTTPException(status_code=404, detail="Business not found")
    conversation, created = create_or_get_conversation(
        db,
        business_id=business.id,
        channel=payload.channel,
        external_user_id=payload.external_user_id,
        customer_name=payload.customer_name,
        customer_phone=payload.customer_phone,
        customer_username=payload.customer_username,
    )
    message = add_message(
        db,
        conversation=conversation,
        direction="inbound",
        sender_type="customer",
        body=payload.body,
        raw_payload=payload.model_dump(),
    )
    automation = process_inbound_automation(
        db,
        business=business,
        conversation=conversation,
        message=message,
    )
    db.commit()
    db.refresh(conversation)
    return {
        "ok": True,
        "created": created,
        "conversation_id": conversation.id,
        "message_id": message.id,
        "status": conversation.status,
        "automation": automation,
    }
