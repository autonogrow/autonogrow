import json
import logging
from datetime import datetime, timedelta, timezone
from math import ceil
from typing import Any

from sqlalchemy import or_
from sqlalchemy.orm import Session

from app.core.audit import record_audit
from app.models import (
    Business,
    Conversation,
    ConversationAutomationRule,
    ConversationAutomationSettings,
    ConversationMessage,
    ConversationSuggestion,
    ConversationTemplate,
)
from app.services.automation_credit_service import (
    consume_automation_credit,
    serialize_credit_summary,
    total_credits_available,
)
from app.services.channel_control_service import channel_automation_is_authorized
from app.services.channel_provider_service import delivery_supported, inbound_supported
from app.services.conversation_automation_state_service import automation_block_reason
from app.services.conversation_intent_service import (
    AVAILABLE_INTENTS,
    INTENT_LABELS,
    INTENT_TEMPLATE_NAMES,
    IntentDetection,
    detect_intent,
    normalize_text,
)
from app.services.conversation_service import (
    conversation_delivery_capabilities,
    ensure_default_templates,
    render_template,
    send_outbound_message,
)

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
AUTOMATION_PERIOD_DAYS = 30


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
    """Deprecated compatibility value; never use it to reset usage."""
    return utc_now().strftime("%Y-%m")


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def as_utc(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def iso_utc(value: datetime | None) -> str | None:
    normalized = as_utc(value)
    return normalized.isoformat().replace("+00:00", "Z") if normalized else None


def sync_automation_period_status(
    settings: ConversationAutomationSettings,
    now: datetime | None = None,
    *,
    db: Session | None = None,
) -> bool:
    """Expire an active moving period once, without renewing or resetting usage."""
    effective_now = as_utc(now) or utc_now()
    period_ends_at = as_utc(settings.period_ends_at)
    if settings.period_status != "active":
        return False
    if period_ends_at is not None and effective_now < period_ends_at:
        return False

    old_status = settings.period_status
    settings.period_status = "pending_renewal"
    settings.updated_at = effective_now
    if db is not None:
        record_audit(
            db,
            action="automation_period_expired",
            business_id=settings.business_id,
            resource_type="conversation_automation_settings",
            resource_id=settings.id,
            metadata={
                "old_status": old_status,
                "new_status": "pending_renewal",
                "period_started_at": iso_utc(settings.period_started_at),
                "period_ends_at": iso_utc(settings.period_ends_at),
                "usage": settings.auto_used_current_period,
                "timestamp": iso_utc(effective_now),
            },
            commit=False,
        )
    return True


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
            included_credits_per_period=DEFAULT_AUTOMATION_MESSAGES_PER_PERIOD,
            included_credits_used=0,
            additional_credits_balance=0,
            period_yyyymm=current_period(),
            period_started_at=None,
            period_ends_at=None,
            payment_confirmed_at=None,
            period_status="pending_renewal",
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
    sync_automation_period_status(settings, db=db)

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
    sync_automation_period_status(settings)
    credits = serialize_credit_summary(settings)
    limit_reached = credits["total_available"] <= 0
    percentage = (
        100
        if settings.included_credits_per_period == 0
        else min(
            100,
            round(settings.included_credits_used * 100 / settings.included_credits_per_period),
        )
    )
    period_ends_at = as_utc(settings.period_ends_at)
    remaining_seconds = (
        max(0, (period_ends_at - utc_now()).total_seconds()) if period_ends_at is not None else 0
    )
    days_remaining = ceil(remaining_seconds / 86400)
    if settings.period_status == "suspended":
        usage_status = "suspended"
    elif settings.period_status != "active":
        usage_status = "pending_renewal"
    elif limit_reached:
        usage_status = "limit_reached"
    elif not settings.automation_feature_enabled or not settings.automation_enabled:
        usage_status = "automation_paused"
    elif percentage >= LIMIT_WARNING_PERCENT:
        usage_status = "near_limit"
    else:
        usage_status = "available"
    return {
        "id": settings.id,
        "business_id": settings.business_id,
        "automation_enabled": settings.automation_enabled,
        "monthly_auto_limit": settings.monthly_auto_limit,
        "auto_limit_per_period": settings.included_credits_per_period,
        "auto_used_current_period": settings.auto_used_current_period,
        **credits,
        "period_yyyymm": settings.period_yyyymm,
        "period_started_at": iso_utc(settings.period_started_at),
        "period_ends_at": iso_utc(settings.period_ends_at),
        "payment_confirmed_at": iso_utc(settings.payment_confirmed_at),
        "period_status": settings.period_status,
        "period_start": iso_utc(settings.period_started_at),
        "period_end": iso_utc(settings.period_ends_at),
        "days_remaining": days_remaining,
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
        return query.filter(ConversationTemplate.name == detection.recommended_template_key).first()
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
    cutoff = message.created_at - timedelta(seconds=IDENTICAL_MESSAGE_DEBOUNCE_SECONDS)
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
        item.id for item in recent_inbounds if normalize_text(item.body) == normalized_body
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
            automation.get("inbound_message_id") if isinstance(automation, dict) else None
        )
        if source_message_id in identical_inbound_ids:
            return True
        if source_message_id is None:
            legacy_inbound = _legacy_automation_inbound(db, outbound)
            if legacy_inbound is not None and legacy_inbound.id in identical_inbound_ids:
                return True
    return False


def _has_automation_for_inbound(
    db: Session,
    *,
    message: ConversationMessage,
) -> bool:
    outbound_messages = (
        db.query(ConversationMessage)
        .filter(
            ConversationMessage.conversation_id == message.conversation_id,
            ConversationMessage.direction == "outbound",
            ConversationMessage.sender_type == "automation",
            ConversationMessage.raw_payload_json.is_not(None),
        )
        .order_by(ConversationMessage.id.desc())
        .all()
    )
    for outbound in outbound_messages:
        try:
            payload = json.loads(outbound.raw_payload_json or "null")
        except (TypeError, ValueError):
            continue
        automation = payload.get("automation") if isinstance(payload, dict) else None
        if isinstance(automation, dict) and automation.get("inbound_message_id") == message.id:
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
        "Automation skipped: reason=%s business_id=%s conversation_id=%s message_id=%s intent=%s",
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
    if db.get_bind().dialect.name == "postgresql":
        db.query(Conversation).filter(Conversation.id == conversation.id).with_for_update().one()
    detection = detect_intent(message.body)
    conversation.detected_intent = detection.intent
    conversation.intent_confidence = detection.confidence
    conversation.matched_patterns_json = json.dumps(
        detection.matched_patterns,
        ensure_ascii=False,
    )
    settings, rules = ensure_automation_configuration(db, business)
    # Lock the wallet row for the availability check and the post-delivery debit.
    # Backends without row-level locks (SQLite) still retain message-level
    # idempotency through the unique ledger constraint.
    db.refresh(settings, with_for_update=True)
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
    if settings.period_status != "active":
        return _skip_automatic_response(
            result,
            business=business,
            conversation=conversation,
            message=message,
            intent=detection.intent,
            reason="period_pending_renewal",
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
    if not channel_automation_is_authorized(
        db,
        business_id=business.id,
        channel=conversation.channel,
    ):
        return _skip_automatic_response(
            result,
            business=business,
            conversation=conversation,
            message=message,
            intent=detection.intent,
            reason="channel_automation_not_enabled",
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

    limit_reached = total_credits_available(settings) <= 0
    can_send_automatically = (
        rule.mode == "automatic"
        and detection.safe_for_auto
        and (detection.confidence >= settings.auto_threshold or detection.intent == "unknown")
        and not limit_reached
    )
    if can_send_automatically and conversation.channel == "whatsapp":
        delivery_capabilities = conversation_delivery_capabilities(
            db,
            conversation=conversation,
            now=message.created_at,
        )
    else:
        delivery_capabilities = None
    if can_send_automatically and (
        (
            conversation.channel == "whatsapp"
            and delivery_capabilities is not None
            and not delivery_capabilities.integrated_delivery_available
        )
        or (
            conversation.channel != "whatsapp"
            and inbound_supported(conversation.channel)
            and not delivery_supported(channel=conversation.channel)
        )
    ):
        suggestion = create_suggestion(
            db,
            conversation=conversation,
            message=message,
            detection=detection,
            template=template,
            business=business,
        )
        result.update(
            action="suggestion",
            reason=(
                delivery_capabilities.unavailable_reason
                if delivery_capabilities is not None
                else "delivery_not_supported"
            )
            or "delivery_not_available",
            suggestion_id=suggestion.id,
        )
        return result
    if can_send_automatically:
        if _has_automation_for_inbound(db, message=message):
            return _skip_automatic_response(
                result,
                business=business,
                conversation=conversation,
                message=message,
                intent=detection.intent,
                reason="inbound_already_processed",
            )
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
        consume_automation_credit(
            db,
            settings=settings,
            related_message_id=outbound.id,
        )
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
    if limit_reached:
        result.update(status="skipped", reason="credits_exhausted")
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
