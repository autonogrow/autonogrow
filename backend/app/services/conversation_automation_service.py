import json
from datetime import datetime
from typing import Any

from sqlalchemy.orm import Session

from app.models import (
    Business,
    Conversation,
    ConversationAutomationRule,
    ConversationAutomationSettings,
    ConversationMessage,
    ConversationSuggestion,
    ConversationTemplate,
)
from app.services.conversation_intent_service import (
    AVAILABLE_INTENTS,
    INTENT_LABELS,
    INTENT_TEMPLATE_NAMES,
    IntentDetection,
    detect_intent,
)
from app.services.conversation_service import (
    add_message,
    ensure_default_templates,
    render_template,
)


DEFAULT_RULE_MODES = {
    "welcome_intent": "semi_automatic",
    "booking_intent": "semi_automatic",
    "price_intent": "semi_automatic",
    "service_intent": "semi_automatic",
    "location_intent": "semi_automatic",
    "hours_intent": "semi_automatic",
    "human_intent": "disabled",
    "complaint_intent": "disabled",
    "cancel_reschedule_intent": "disabled",
    "unknown": "disabled",
}


def current_period() -> str:
    return datetime.utcnow().strftime("%Y-%m")


def reset_monthly_usage(settings: ConversationAutomationSettings) -> bool:
    period = current_period()
    if settings.period_yyyymm == period:
        return False
    settings.period_yyyymm = period
    settings.auto_used_current_period = 0
    settings.updated_at = datetime.utcnow()
    return True


def ensure_automation_configuration(
    db: Session,
    business: Business,
) -> tuple[ConversationAutomationSettings, list[ConversationAutomationRule]]:
    templates = ensure_default_templates(db, business)
    templates_by_name = {template.name: template for template in templates}
    settings = (
        db.query(ConversationAutomationSettings)
        .filter(ConversationAutomationSettings.business_id == business.id)
        .first()
    )
    if settings is None:
        settings = ConversationAutomationSettings(
            business_id=business.id,
            automation_enabled=False,
            monthly_auto_limit=1000,
            auto_used_current_period=0,
            period_yyyymm=current_period(),
            on_limit_reached="semi_automatic",
            auto_threshold=80,
        )
        db.add(settings)
        db.flush()
    else:
        reset_monthly_usage(settings)

    existing_rules = {
        rule.intent: rule
        for rule in db.query(ConversationAutomationRule)
        .filter(ConversationAutomationRule.business_id == business.id)
        .all()
    }
    for intent in AVAILABLE_INTENTS:
        if intent in existing_rules:
            continue
        template_name = INTENT_TEMPLATE_NAMES.get(intent)
        template = templates_by_name.get(template_name) if template_name else None
        rule = ConversationAutomationRule(
            business_id=business.id,
            intent=intent,
            mode=DEFAULT_RULE_MODES[intent],
            template_id=template.id if template else None,
            active=True,
        )
        db.add(rule)
        existing_rules[intent] = rule
    db.flush()
    rules = sorted(
        existing_rules.values(),
        key=lambda rule: AVAILABLE_INTENTS.index(rule.intent),
    )
    return settings, rules


def serialize_settings(settings: ConversationAutomationSettings) -> dict[str, Any]:
    limit_reached = (
        settings.automation_enabled
        and settings.auto_used_current_period >= settings.monthly_auto_limit
    )
    return {
        "id": settings.id,
        "business_id": settings.business_id,
        "automation_enabled": settings.automation_enabled,
        "monthly_auto_limit": settings.monthly_auto_limit,
        "auto_used_current_period": settings.auto_used_current_period,
        "period_yyyymm": settings.period_yyyymm,
        "on_limit_reached": settings.on_limit_reached,
        "auto_threshold": settings.auto_threshold,
        "limit_reached": limit_reached,
        "created_at": settings.created_at.isoformat(),
        "updated_at": settings.updated_at.isoformat(),
    }


def serialize_rule(rule: ConversationAutomationRule) -> dict[str, Any]:
    return {
        "id": rule.id,
        "business_id": rule.business_id,
        "intent": rule.intent,
        "intent_label": INTENT_LABELS[rule.intent],
        "mode": rule.mode,
        "template_id": rule.template_id,
        "active": rule.active,
        "created_at": rule.created_at.isoformat(),
        "updated_at": rule.updated_at.isoformat(),
    }


def serialize_suggestion(suggestion: ConversationSuggestion) -> dict[str, Any]:
    return {
        "id": suggestion.id,
        "conversation_id": suggestion.conversation_id,
        "message_id": suggestion.message_id,
        "intent": suggestion.intent,
        "intent_label": INTENT_LABELS[suggestion.intent],
        "confidence": suggestion.confidence,
        "body": suggestion.body,
        "status": suggestion.status,
        "created_at": suggestion.created_at.isoformat(),
        "updated_at": suggestion.updated_at.isoformat(),
    }


def resolve_template(
    db: Session,
    *,
    business_id: int,
    rule: ConversationAutomationRule,
    detection: IntentDetection,
) -> ConversationTemplate | None:
    query = db.query(ConversationTemplate).filter(
        ConversationTemplate.business_id == business_id,
        ConversationTemplate.active.is_(True),
    )
    if rule.template_id is not None:
        template = query.filter(ConversationTemplate.id == rule.template_id).first()
        if template is not None:
            return template
    if detection.recommended_template_key:
        return query.filter(
            ConversationTemplate.name == detection.recommended_template_key
        ).first()
    return None


def create_suggestion(
    db: Session,
    *,
    conversation: Conversation,
    message: ConversationMessage,
    detection: IntentDetection,
    template: ConversationTemplate,
    business: Business,
) -> ConversationSuggestion:
    suggestion = ConversationSuggestion(
        conversation_id=conversation.id,
        message_id=message.id,
        intent=detection.intent,
        confidence=detection.confidence,
        body=render_template(template.body, business),
        status="pending",
    )
    db.add(suggestion)
    db.flush()
    return suggestion


def process_inbound_automation(
    db: Session,
    *,
    business: Business,
    conversation: Conversation,
    message: ConversationMessage,
) -> dict[str, Any]:
    detection = detect_intent(message.body)
    conversation.detected_intent = detection.intent
    conversation.intent_confidence = detection.confidence
    conversation.matched_patterns_json = json.dumps(
        detection.matched_patterns,
        ensure_ascii=False,
    )
    settings, rules = ensure_automation_configuration(db, business)
    result: dict[str, Any] = {
        "action": "manual",
        "detection": detection.to_dict(),
        "suggestion_id": None,
        "outbound_message_id": None,
        "limit_reached": False,
    }
    if not settings.automation_enabled:
        return result

    rule = next((item for item in rules if item.intent == detection.intent), None)
    if rule is None or not rule.active or rule.mode == "disabled":
        return result
    template = resolve_template(
        db,
        business_id=business.id,
        rule=rule,
        detection=detection,
    )
    if template is None:
        return result

    if rule.mode == "semi_automatic":
        suggestion = create_suggestion(
            db,
            conversation=conversation,
            message=message,
            detection=detection,
            template=template,
            business=business,
        )
        result.update(action="suggestion", suggestion_id=suggestion.id)
        return result

    limit_reached = settings.auto_used_current_period >= settings.monthly_auto_limit
    can_send_automatically = (
        rule.mode == "automatic"
        and detection.safe_for_auto
        and detection.confidence >= settings.auto_threshold
        and not limit_reached
    )
    if can_send_automatically:
        outbound = add_message(
            db,
            conversation=conversation,
            direction="outbound",
            sender_type="automation",
            body=render_template(template.body, business),
            delivery_status="sent",
        )
        settings.auto_used_current_period += 1
        settings.updated_at = datetime.utcnow()
        result.update(action="automatic", outbound_message_id=outbound.id)
        return result

    result["limit_reached"] = limit_reached
    if not limit_reached or settings.on_limit_reached == "semi_automatic":
        suggestion = create_suggestion(
            db,
            conversation=conversation,
            message=message,
            detection=detection,
            template=template,
            business=business,
        )
        result.update(action="suggestion", suggestion_id=suggestion.id)
    return result


def get_suggestion_for_business(
    db: Session,
    *,
    business_id: int,
    suggestion_id: int,
) -> ConversationSuggestion | None:
    return (
        db.query(ConversationSuggestion)
        .join(Conversation, Conversation.id == ConversationSuggestion.conversation_id)
        .filter(
            ConversationSuggestion.id == suggestion_id,
            Conversation.business_id == business_id,
        )
        .first()
    )


def update_suggestion_status(
    suggestion: ConversationSuggestion,
    status: str,
) -> None:
    suggestion.status = status
    suggestion.updated_at = datetime.utcnow()
