import json
import logging
from datetime import datetime, timedelta
from typing import Any

from sqlalchemy import or_
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
    normalize_text,
)
from app.services.conversation_service import (
    ensure_default_templates,
    render_template,
    send_outbound_message,
)
from app.services.conversation_automation_state_service import automation_block_reason


logger = logging.getLogger(__name__)

# Conservative first-version safeguards. They intentionally live beside the
# automation flow until per-business controls are added to the settings model.
WELCOME_COOLDOWN_HOURS = 24
DEFAULT_INTENT_COOLDOWN_MINUTES = 5
IDENTICAL_MESSAGE_DEBOUNCE_SECONDS = 10
MAX_AUTOMATION_MESSAGES_PER_PERIOD = 1_000_000
DEFAULT_AUTOMATION_MESSAGES_PER_PERIOD = 1_000
LIMIT_WARNING_PERCENT = 80
LIMIT_BEHAVIORS = ("semi_automatic", "disabled")


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


def period_bounds(period_yyyymm: str) -> tuple[datetime | None, datetime | None]:
    try:
        year, month = (int(value) for value in period_yyyymm.split("-", 1))
        start = datetime(year, month, 1)
    except (TypeError, ValueError):
        return None, None
    end = datetime(year + 1, 1, 1) if month == 12 else datetime(year, month + 1, 1)
    return start, end


def allowed_limit_behaviors(settings: ConversationAutomationSettings) -> list[str]:
    try:
        values = json.loads(settings.allowed_limit_behaviors_json or "[]")
    except (TypeError, ValueError):
        values = []
    allowed = [value for value in values if value in LIMIT_BEHAVIORS]
    return allowed or ["disabled"]


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
            monthly_auto_limit=DEFAULT_AUTOMATION_MESSAGES_PER_PERIOD,
            auto_used_current_period=0,
            period_yyyymm=current_period(),
            on_limit_reached="semi_automatic",
            auto_threshold=80,
            human_reply_pause_minutes=60,
            automation_feature_enabled=True,
            instagram_channel_enabled=True,
            whatsapp_channel_enabled=True,
            allowed_limit_behaviors_json=json.dumps(LIMIT_BEHAVIORS),
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
    limit_reached = settings.auto_used_current_period >= settings.monthly_auto_limit
    percentage = (
        100
        if settings.monthly_auto_limit == 0
        else min(100, round(settings.auto_used_current_period * 100 / settings.monthly_auto_limit))
    )
    period_start, period_end = period_bounds(settings.period_yyyymm)
    if not settings.automation_feature_enabled or not settings.automation_enabled:
        usage_status = "automation_paused"
    elif limit_reached:
        usage_status = "limit_reached"
    elif percentage >= LIMIT_WARNING_PERCENT:
        usage_status = "near_limit"
    else:
        usage_status = "available"
    return {
        "id": settings.id,
        "business_id": settings.business_id,
        "automation_enabled": settings.automation_enabled,
        "monthly_auto_limit": settings.monthly_auto_limit,
        "auto_limit_per_period": settings.monthly_auto_limit,
        "auto_used_current_period": settings.auto_used_current_period,
        "period_yyyymm": settings.period_yyyymm,
        "period_start": period_start.isoformat() if period_start else None,
        "period_end": period_end.isoformat() if period_end else None,
        "on_limit_reached": settings.on_limit_reached,
        "auto_threshold": settings.auto_threshold,
        "human_reply_pause_minutes": settings.human_reply_pause_minutes,
        "plan": settings.plan_key,
        "automation_feature_enabled": settings.automation_feature_enabled,
        "instagram_channel_enabled": settings.instagram_channel_enabled,
        "whatsapp_channel_enabled": settings.whatsapp_channel_enabled,
        "allowed_limit_behaviors": allowed_limit_behaviors(settings),
        "usage_percentage": percentage,
        "usage_status": usage_status,
        "limit_warning_percent": LIMIT_WARNING_PERCENT,
        "can_request_limit_change": True,
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


def _automation_intent_from_metadata(message: ConversationMessage) -> str | None:
    if not message.raw_payload_json:
        return None
    try:
        payload = json.loads(message.raw_payload_json)
    except (TypeError, ValueError):
        return None
    if not isinstance(payload, dict):
        return None
    automation = payload.get("automation")
    if not isinstance(automation, dict):
        return None
    intent = automation.get("intent")
    return intent if intent in AVAILABLE_INTENTS else None


def _legacy_automation_inbound(
    db: Session,
    outbound: ConversationMessage,
) -> ConversationMessage | None:
    return (
        db.query(ConversationMessage)
        .filter(
            ConversationMessage.conversation_id == outbound.conversation_id,
            ConversationMessage.direction == "inbound",
            or_(
                ConversationMessage.created_at < outbound.created_at,
                (
                    (ConversationMessage.created_at == outbound.created_at)
                    & (ConversationMessage.id < outbound.id)
                ),
            ),
        )
        .order_by(
            ConversationMessage.created_at.desc(),
            ConversationMessage.id.desc(),
        )
        .first()
    )


def _infer_legacy_automation_intent(
    db: Session,
    outbound: ConversationMessage,
) -> str | None:
    """Infer intent for automation messages created before metadata was stored."""
    inbound = _legacy_automation_inbound(db, outbound)
    return detect_intent(inbound.body).intent if inbound is not None else None


def _has_recent_successful_automation_for_intent(
    db: Session,
    *,
    conversation_id: int,
    intent: str,
    reference_time: datetime,
    cooldown: timedelta,
) -> bool:
    cutoff = reference_time - cooldown
    outbound_messages = (
        db.query(ConversationMessage)
        .filter(
            ConversationMessage.conversation_id == conversation_id,
            ConversationMessage.direction == "outbound",
            ConversationMessage.sender_type == "automation",
            ConversationMessage.created_at > cutoff,
            ConversationMessage.created_at <= reference_time,
            or_(
                ConversationMessage.delivery_status.is_(None),
                ConversationMessage.delivery_status != "failed",
            ),
        )
        .order_by(
            ConversationMessage.created_at.desc(),
            ConversationMessage.id.desc(),
        )
        .all()
    )
    for outbound in outbound_messages:
        outbound_intent = _automation_intent_from_metadata(outbound)
        if outbound_intent is None:
            outbound_intent = _infer_legacy_automation_intent(db, outbound)
        if outbound_intent == intent:
            return True
    return False


def _has_recent_identical_inbound(
    db: Session,
    *,
    message: ConversationMessage,
) -> bool:
    normalized_body = normalize_text(message.body)
    if not normalized_body:
        return False
    cutoff = message.created_at - timedelta(
        seconds=IDENTICAL_MESSAGE_DEBOUNCE_SECONDS
    )
    recent_inbounds = (
        db.query(ConversationMessage)
        .filter(
            ConversationMessage.conversation_id == message.conversation_id,
            ConversationMessage.direction == "inbound",
            ConversationMessage.id != message.id,
            ConversationMessage.created_at > cutoff,
            ConversationMessage.created_at <= message.created_at,
        )
        .order_by(
            ConversationMessage.created_at.desc(),
            ConversationMessage.id.desc(),
        )
        .all()
    )
    identical_inbound_ids = {
        item.id
        for item in recent_inbounds
        if normalize_text(item.body) == normalized_body
    }
    if not identical_inbound_ids:
        return False

    successful_outbounds = (
        db.query(ConversationMessage)
        .filter(
            ConversationMessage.conversation_id == message.conversation_id,
            ConversationMessage.direction == "outbound",
            ConversationMessage.sender_type == "automation",
            ConversationMessage.created_at > cutoff,
            ConversationMessage.created_at <= message.created_at,
            or_(
                ConversationMessage.delivery_status.is_(None),
                ConversationMessage.delivery_status != "failed",
            ),
        )
        .order_by(
            ConversationMessage.created_at.desc(),
            ConversationMessage.id.desc(),
        )
        .all()
    )
    for outbound in successful_outbounds:
        try:
            payload = json.loads(outbound.raw_payload_json or "null")
        except (TypeError, ValueError):
            payload = None
        automation = payload.get("automation") if isinstance(payload, dict) else None
        source_message_id = (
            automation.get("inbound_message_id")
            if isinstance(automation, dict)
            else None
        )
        if source_message_id in identical_inbound_ids:
            return True
        if source_message_id is None:
            legacy_inbound = _legacy_automation_inbound(db, outbound)
            if legacy_inbound is not None and legacy_inbound.id in identical_inbound_ids:
                return True
    return False


def _skip_automatic_response(
    result: dict[str, Any],
    *,
    business: Business,
    conversation: Conversation,
    message: ConversationMessage,
    intent: str,
    reason: str,
) -> dict[str, Any]:
    logger.info(
        "Automation skipped: reason=%s business_id=%s conversation_id=%s "
        "message_id=%s intent=%s",
        reason,
        business.id,
        conversation.id,
        message.id,
        intent,
    )
    result.update(status="skipped", reason=reason)
    return result


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
        "status": "processed",
        "reason": None,
        "detection": detection.to_dict(),
        "suggestion_id": None,
        "outbound_message_id": None,
        "delivery_status": None,
        "limit_reached": False,
    }
    if not settings.automation_feature_enabled:
        return _skip_automatic_response(
            result,
            business=business,
            conversation=conversation,
            message=message,
            intent=detection.intent,
            reason="automation_feature_disabled",
        )
    channel_enabled = {
        "instagram": settings.instagram_channel_enabled,
        "whatsapp": settings.whatsapp_channel_enabled,
    }.get(conversation.channel, True)
    if not channel_enabled:
        return _skip_automatic_response(
            result,
            business=business,
            conversation=conversation,
            message=message,
            intent=detection.intent,
            reason="channel_not_in_plan",
        )
    if not settings.automation_enabled:
        block_reason = automation_block_reason(conversation, now=message.created_at)
        if block_reason:
            return _skip_automatic_response(
                result,
                business=business,
                conversation=conversation,
                message=message,
                intent=detection.intent,
                reason=block_reason,
            )
        return result

    rule = next((item for item in rules if item.intent == detection.intent), None)
    template = None
    if rule is not None and rule.active and rule.mode != "disabled":
        template = resolve_template(
            db,
            business_id=business.id,
            rule=rule,
            detection=detection,
        )

    block_reason = automation_block_reason(conversation, now=message.created_at)
    if block_reason:
        if template is not None:
            suggestion = create_suggestion(
                db,
                conversation=conversation,
                message=message,
                detection=detection,
                template=template,
                business=business,
            )
            result.update(action="suggestion", suggestion_id=suggestion.id)
        return _skip_automatic_response(
            result,
            business=business,
            conversation=conversation,
            message=message,
            intent=detection.intent,
            reason=block_reason,
        )

    if rule is None or not rule.active or rule.mode == "disabled" or template is None:
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
        and (
            detection.confidence >= settings.auto_threshold
            or detection.intent == "unknown"
        )
        and not limit_reached
    )
    if can_send_automatically:
        if detection.intent == "welcome_intent" and (
            _has_recent_successful_automation_for_intent(
                db,
                conversation_id=conversation.id,
                intent=detection.intent,
                reference_time=message.created_at,
                cooldown=timedelta(hours=WELCOME_COOLDOWN_HOURS),
            )
        ):
            return _skip_automatic_response(
                result,
                business=business,
                conversation=conversation,
                message=message,
                intent=detection.intent,
                reason="welcome_already_sent",
            )
        if _has_recent_identical_inbound(db, message=message):
            return _skip_automatic_response(
                result,
                business=business,
                conversation=conversation,
                message=message,
                intent=detection.intent,
                reason="identical_message_debounce",
            )
        if detection.intent != "welcome_intent" and (
            _has_recent_successful_automation_for_intent(
                db,
                conversation_id=conversation.id,
                intent=detection.intent,
                reference_time=message.created_at,
                cooldown=timedelta(minutes=DEFAULT_INTENT_COOLDOWN_MINUTES),
            )
        ):
            return _skip_automatic_response(
                result,
                business=business,
                conversation=conversation,
                message=message,
                intent=detection.intent,
                reason="intent_cooldown",
            )
        delivery = send_outbound_message(
            db,
            conversation=conversation,
            sender_type="automation",
            body=render_template(template.body, business),
            intent=detection.intent,
        )
        outbound = delivery.message
        outbound.raw_payload_json = json.dumps(
            {
                "automation": {
                    "intent": detection.intent,
                    "inbound_message_id": message.id,
                }
            },
            ensure_ascii=False,
        )
        result.update(
            outbound_message_id=outbound.id,
            delivery_status=outbound.delivery_status,
        )
        if not delivery.ok:
            result.update(
                action="automatic_failed",
                error_message=delivery.client_error_message,
                incident_id=delivery.incident_id,
            )
            return result
        settings.auto_used_current_period += 1
        settings.updated_at = datetime.utcnow()
        if detection.intent in {
            "complaint_intent",
            "human_intent",
            "cancel_reschedule_intent",
            "unknown",
        }:
            conversation.status = "pending"
        result.update(action="automatic")
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
