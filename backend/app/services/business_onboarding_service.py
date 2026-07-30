from __future__ import annotations

import hashlib
import json
import re
import unicodedata
from copy import deepcopy
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from typing import Any

from fastapi import HTTPException
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.models import (
    AutomationCreditTransaction,
    AvailabilitySettings,
    Business,
    BusinessOnboardingSession,
    BusinessOnboardingTemplate,
    BusinessService,
    BusinessStaffProfile,
    ConversationAutomationSettings,
    ConversationTemplate,
)
from app.services.automation_credit_service import (
    get_credit_transaction_by_idempotency,
    lock_credit_wallet,
    record_credit_transaction,
)
from app.services.conversation_automation_service import ensure_automation_configuration
from app.services.onboarding_template_catalog import template_has_forbidden_data

ONBOARDING_STEPS = (
    "template",
    "business_identity",
    "contact_and_location",
    "services",
    "staff",
    "schedules",
    "booking_rules",
    "branding",
    "landing_content",
    "automations",
    "integrations",
    "credits_and_plan",
    "readiness_review",
    "preview",
    "activation",
)

STEP_DEPENDENCIES = {
    "business_identity": ("template",),
    "contact_and_location": ("business_identity",),
    "services": ("business_identity",),
    "staff": ("services",),
    "schedules": ("business_identity",),
    "booking_rules": ("services", "schedules"),
    "branding": ("business_identity",),
    "landing_content": ("business_identity",),
    "automations": ("business_identity",),
    "integrations": ("business_identity",),
    "credits_and_plan": ("business_identity",),
    "readiness_review": ("services", "schedules", "booking_rules"),
    "preview": ("readiness_review",),
    "activation": ("readiness_review", "preview"),
}

BUSINESS_TRANSITIONS = {
    "draft": {"onboarding", "archived"},
    "onboarding": {"configuration_pending", "ready", "archived"},
    "configuration_pending": {"ready", "archived"},
    "ready": {"active", "archived"},
    "active": {"suspended"},
    "suspended": {"active", "archived"},
    "archived": set(),
}

RESERVED_SLUGS = {
    "admin",
    "api",
    "app",
    "auth",
    "autonogrow",
    "business",
    "businesses",
    "customer",
    "health",
    "login",
    "owner",
    "privacy",
    "staging",
    "static",
    "support",
    "uploads",
    "www",
}

ALLOWED_PLACEHOLDERS = {
    "business_name",
    "customer_name",
    "booking_date",
    "booking_time",
    "service_name",
}
PLACEHOLDER_RE = re.compile(r"{{\s*([a-z_]+)\s*}}")


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def load_json(value: str | None, fallback: Any) -> Any:
    try:
        loaded = json.loads(value or "null")
    except (TypeError, ValueError):
        return deepcopy(fallback)
    return deepcopy(fallback) if loaded is None else loaded


def normalize_onboarding_slug(value: str) -> str:
    ascii_value = unicodedata.normalize("NFKD", value).encode("ascii", "ignore").decode("ascii")
    slug = re.sub(r"[^a-z0-9]+", "-", ascii_value.lower()).strip("-")
    if not 3 <= len(slug) <= 120 or slug in RESERVED_SLUGS:
        raise ValueError("reserved_or_invalid_slug")
    return slug


def validate_placeholders(text: str) -> None:
    placeholders = set(PLACEHOLDER_RE.findall(text))
    if placeholders - ALLOWED_PLACEHOLDERS:
        raise ValueError("unsupported_automation_placeholder")
    stripped = PLACEHOLDER_RE.sub("", text)
    if "{{" in stripped or "}}" in stripped:
        raise ValueError("invalid_automation_placeholder")


def transition_business(business: Business, target: str, *, now: datetime | None = None) -> None:
    if target == business.status:
        return
    if target not in BUSINESS_TRANSITIONS.get(business.status, set()):
        raise ValueError("invalid_business_transition")
    business.status = target
    business.status_updated_at = now or utc_now()
    business.seo_noindex = target != "active"
    if target == "archived":
        business.archived_at = now or utc_now()


def lock_business(db: Session, business_id: int) -> Business:
    query = db.query(Business).filter(Business.id == business_id)
    if db.get_bind().dialect.name == "postgresql":
        query = query.populate_existing().with_for_update()
    business = query.first()
    if business is None:
        raise HTTPException(status_code=404, detail="Business not found")
    return business


def get_active_onboarding_session(
    db: Session, business_id: int, *, lock: bool = False
) -> BusinessOnboardingSession:
    query = db.query(BusinessOnboardingSession).filter(
        BusinessOnboardingSession.business_id == business_id,
        BusinessOnboardingSession.status.in_(("in_progress", "blocked")),
    )
    if lock and db.get_bind().dialect.name == "postgresql":
        query = query.populate_existing().with_for_update()
    session = query.first()
    if session is None:
        raise HTTPException(status_code=404, detail="Active onboarding session not found")
    return session


def step_statuses(session: BusinessOnboardingSession) -> list[dict[str, Any]]:
    completed = set(load_json(session.completed_steps_json, []))
    skipped = set(load_json(session.skipped_steps_json, []))
    return [
        {
            "key": step,
            "status": (
                "completed"
                if step in completed
                else "skipped"
                if step in skipped
                else "in_progress"
                if step == session.current_step
                else "blocked"
                if any(
                    dependency not in completed for dependency in STEP_DEPENDENCIES.get(step, ())
                )
                else "pending"
            ),
            "dependencies": list(STEP_DEPENDENCIES.get(step, ())),
        }
        for step in ONBOARDING_STEPS
    ]


def serialize_onboarding_session(session: BusinessOnboardingSession) -> dict[str, Any]:
    template = session.template
    return {
        "id": session.id,
        "business_id": session.business_id,
        "status": session.status,
        "current_step": session.current_step,
        "steps_version": session.steps_version,
        "steps": step_statuses(session),
        "completed_steps": load_json(session.completed_steps_json, []),
        "skipped_steps": load_json(session.skipped_steps_json, []),
        "step_activity": load_json(session.step_activity_json, {}),
        "validation_summary": load_json(session.validation_summary_json, None),
        "template": (
            {"id": template.id, "key": template.key, "version": template.version}
            if template
            else None
        ),
        "started_at": session.started_at,
        "last_activity_at": session.last_activity_at,
        "completed_at": session.completed_at,
    }


def mark_step_saved(
    session: BusinessOnboardingSession,
    *,
    step: str,
    actor_user_id: int,
    completed: bool,
    summary: dict[str, Any] | None = None,
) -> None:
    if step not in ONBOARDING_STEPS:
        raise ValueError("invalid_onboarding_step")
    now = utc_now()
    completed_steps = list(load_json(session.completed_steps_json, []))
    skipped_steps = list(load_json(session.skipped_steps_json, []))
    if completed and step not in completed_steps:
        completed_steps.append(step)
    if completed and step in skipped_steps:
        skipped_steps.remove(step)
    activity = dict(load_json(session.step_activity_json, {}))
    activity[step] = {
        "updated_by_user_id": actor_user_id,
        "updated_at": now.isoformat(),
        "summary": summary or {},
    }
    session.completed_steps_json = json.dumps(completed_steps)
    session.skipped_steps_json = json.dumps(skipped_steps)
    session.step_activity_json = json.dumps(activity, sort_keys=True)
    session.last_updated_by_user_id = actor_user_id
    session.last_activity_at = now
    session.updated_at = now
    current_index = ONBOARDING_STEPS.index(step)
    if completed and current_index + 1 < len(ONBOARDING_STEPS):
        session.current_step = ONBOARDING_STEPS[current_index + 1]


def skip_step(
    session: BusinessOnboardingSession, *, step: str, actor_user_id: int, reason: str
) -> None:
    if step not in ONBOARDING_STEPS or step in {
        "business_identity",
        "services",
        "schedules",
        "booking_rules",
        "readiness_review",
        "activation",
    }:
        raise ValueError("onboarding_step_cannot_be_skipped")
    skipped = list(load_json(session.skipped_steps_json, []))
    if step not in skipped:
        skipped.append(step)
    session.skipped_steps_json = json.dumps(skipped)
    mark_step_saved(
        session,
        step=step,
        actor_user_id=actor_user_id,
        completed=False,
        summary={"skipped": True, "reason_length": len(reason)},
    )


def find_template(
    db: Session, *, key: str, version: int | None = None
) -> BusinessOnboardingTemplate:
    query = db.query(BusinessOnboardingTemplate).filter(
        BusinessOnboardingTemplate.key == key,
        BusinessOnboardingTemplate.is_active.is_(True),
    )
    if version is not None:
        query = query.filter(BusinessOnboardingTemplate.version == version)
    template = query.order_by(BusinessOnboardingTemplate.version.desc()).first()
    if template is None:
        raise HTTPException(status_code=404, detail="Onboarding template not found")
    return template


def template_payload(template: BusinessOnboardingTemplate) -> dict[str, Any]:
    configuration = load_json(template.configuration_json, {})
    if not isinstance(configuration, dict) or template_has_forbidden_data(configuration):
        raise ValueError("unsafe_onboarding_template")
    return configuration


def _set_if_allowed(target: object, field: str, value: Any, *, retain_existing: bool) -> None:
    current = getattr(target, field, None)
    if not retain_existing or current in (None, ""):
        setattr(target, field, value)


def _availability_from_configuration(
    db: Session,
    business: Business,
    configuration: dict[str, Any],
    *,
    retain_existing: bool,
) -> AvailabilitySettings:
    settings = (
        db.query(AvailabilitySettings)
        .filter(AvailabilitySettings.business_id == business.id)
        .first()
    )
    schedule = configuration.get("schedules") or {}
    booking = configuration.get("booking_rules") or {}
    if settings is None:
        settings = AvailabilitySettings(
            business_id=business.id,
            timezone=schedule.get("timezone", business.timezone),
            weekly_schedule_json=json.dumps(schedule.get("weekly_schedule", {})),
        )
        db.add(settings)
    if not retain_existing:
        settings.timezone = schedule.get("timezone", settings.timezone)
        settings.weekly_schedule_json = json.dumps(
            schedule.get("weekly_schedule", load_json(settings.weekly_schedule_json, {}))
        )
    for field in (
        "min_notice_minutes",
        "max_days_ahead",
        "slot_interval_minutes",
        "buffer_between_bookings_minutes",
        "auto_confirm_bookings",
        "cancellation_allowed",
        "cancellation_notice_minutes",
        "reschedule_allowed",
        "max_simultaneous_bookings",
    ):
        if field in booking and (not retain_existing or settings.id is None):
            setattr(settings, field, booking[field])
    return settings


def apply_template(
    db: Session,
    *,
    business: Business,
    session: BusinessOnboardingSession,
    template: BusinessOnboardingTemplate,
    actor_user_id: int,
    retain_existing: bool,
) -> dict[str, int]:
    configuration = template_payload(template)
    created = {"services": 0}
    identity = configuration.get("identity") or {}
    for field in ("category",):
        if field in identity:
            _set_if_allowed(business, field, identity[field], retain_existing=retain_existing)

    for index, item in enumerate(configuration.get("services") or []):
        source_key = f"template:{template.key}:v{template.version}:{index}"
        existing = (
            db.query(BusinessService)
            .filter(
                BusinessService.business_id == business.id,
                BusinessService.source_key == source_key,
            )
            .first()
        )
        if existing is not None:
            continue
        name_conflict = (
            db.query(BusinessService)
            .filter(
                BusinessService.business_id == business.id,
                BusinessService.name == item["name"],
            )
            .first()
        )
        if name_conflict is not None:
            continue
        db.add(
            BusinessService(
                business_id=business.id,
                name=item["name"],
                description=item.get("description"),
                duration_minutes=item["duration_minutes"],
                duration_text=f"{item['duration_minutes']} min",
                price_amount=Decimal(str(item["price_amount"]))
                if item.get("price_amount") is not None
                else None,
                currency=item.get("currency", business.currency),
                category=item.get("category"),
                visible=item.get("visible", True),
                bookable=item.get("bookable", True),
                requires_approval=item.get("requires_approval", False),
                buffer_before_minutes=item.get("buffer_before_minutes", 0),
                buffer_after_minutes=item.get("buffer_after_minutes", 0),
                position=item.get("position", index),
                active=True,
                source_key=source_key,
            )
        )
        created["services"] += 1

    _availability_from_configuration(db, business, configuration, retain_existing=retain_existing)
    for section in ("branding", "landing_content"):
        for field, value in (configuration.get(section) or {}).items():
            if hasattr(business, field):
                _set_if_allowed(business, field, value, retain_existing=retain_existing)

    automation = configuration.get("automations") or {}
    settings, _rules = ensure_automation_configuration(db, business)
    if not retain_existing:
        for field in (
            "automation_enabled",
            "auto_threshold",
            "human_reply_pause_minutes",
        ):
            if field in automation:
                setattr(settings, field, automation[field])
    for name, body in (automation.get("messages") or {}).items():
        validate_placeholders(body)
        source_name = f"onboarding:{name}"
        existing_message = (
            db.query(ConversationTemplate)
            .filter(
                ConversationTemplate.business_id == business.id,
                ConversationTemplate.name == source_name,
            )
            .first()
        )
        if existing_message is None:
            db.add(
                ConversationTemplate(
                    business_id=business.id,
                    name=source_name,
                    body=body,
                    active=True,
                )
            )

    session.template_id = template.id
    mark_step_saved(
        session,
        step="template",
        actor_user_id=actor_user_id,
        completed=True,
        summary={
            "template_key": template.key,
            "template_version": template.version,
            "created_services": created["services"],
        },
    )
    if business.status == "draft":
        transition_business(business, "onboarding")
    db.flush()
    return created


def initialize_plan(
    db: Session,
    *,
    business: Business,
    plan_key: str,
    included_credits: int,
    additional_credits: int,
    period_days: int,
    actor_user_id: int,
) -> tuple[ConversationAutomationSettings, AutomationCreditTransaction]:
    idempotency_key = f"onboarding-plan:{business.id}"
    existing_transaction = get_credit_transaction_by_idempotency(
        db, business_id=business.id, idempotency_key=idempotency_key
    )
    settings, _rules = ensure_automation_configuration(db, business)
    if existing_transaction is not None:
        return settings, existing_transaction
    settings = lock_credit_wallet(db, settings)
    now = utc_now()
    settings.plan_key = plan_key
    settings.included_credits_per_period = included_credits
    settings.included_credits_used = 0
    settings.additional_credits_balance = additional_credits
    settings.monthly_auto_limit = included_credits
    settings.auto_used_current_period = 0
    settings.period_started_at = now
    settings.period_ends_at = now + timedelta(days=period_days)
    settings.period_yyyymm = now.strftime("%Y-%m")
    settings.period_status = "active"
    transaction = record_credit_transaction(
        db,
        settings=settings,
        transaction_type="manual_adjustment",
        amount=included_credits + additional_credits,
        included_delta=included_credits,
        additional_delta=additional_credits,
        reason="Inicialización idempotente del plan durante onboarding",
        owner_user_id=actor_user_id,
        idempotency_key=idempotency_key,
        safe_metadata={"plan_key": plan_key, "period_days": period_days},
    )
    return settings, transaction


def clone_configuration(
    db: Session,
    *,
    source: Business,
    target: Business,
    sections: list[str],
) -> dict[str, Any]:
    if source.id == target.id:
        raise ValueError("cannot_clone_same_business")
    result: dict[str, Any] = {"created_services": 0, "sections": sections, "warnings": []}
    if "services" in sections:
        source_services = (
            db.query(BusinessService)
            .filter(BusinessService.business_id == source.id, BusinessService.archived_at.is_(None))
            .order_by(BusinessService.id)
            .all()
        )
        for service in source_services:
            source_key = f"clone:{source.id}:service:{service.id}"
            existing = (
                db.query(BusinessService)
                .filter(
                    BusinessService.business_id == target.id,
                    BusinessService.source_key == source_key,
                )
                .first()
            )
            if existing is not None:
                continue
            name_conflict = (
                db.query(BusinessService)
                .filter(
                    BusinessService.business_id == target.id,
                    BusinessService.name == service.name,
                )
                .first()
            )
            if name_conflict is not None:
                continue
            db.add(
                BusinessService(
                    business_id=target.id,
                    name=service.name,
                    description=service.description,
                    price_text=service.price_text,
                    duration_text=service.duration_text,
                    duration_minutes=service.duration_minutes,
                    price_amount=service.price_amount,
                    currency=service.currency,
                    category=service.category,
                    visible=service.visible,
                    bookable=service.bookable,
                    requires_approval=service.requires_approval,
                    buffer_before_minutes=service.buffer_before_minutes,
                    buffer_after_minutes=service.buffer_after_minutes,
                    position=service.position,
                    active=service.active,
                    source_key=source_key,
                )
            )
            result["created_services"] += 1

    source_availability = (
        db.query(AvailabilitySettings).filter(AvailabilitySettings.business_id == source.id).first()
    )
    if source_availability and ({"schedules", "booking_rules"} & set(sections)):
        target_availability = (
            db.query(AvailabilitySettings)
            .filter(AvailabilitySettings.business_id == target.id)
            .first()
        )
        if target_availability is None:
            target_availability = AvailabilitySettings(
                business_id=target.id,
                weekly_schedule_json="{}",
            )
            db.add(target_availability)
        if "schedules" in sections:
            target_availability.timezone = source_availability.timezone
            target_availability.weekly_schedule_json = source_availability.weekly_schedule_json
        if "booking_rules" in sections:
            for field in (
                "slot_interval_minutes",
                "buffer_between_bookings_minutes",
                "min_notice_minutes",
                "max_days_ahead",
                "auto_confirm_bookings",
                "cancellation_allowed",
                "cancellation_notice_minutes",
                "reschedule_allowed",
                "max_simultaneous_bookings",
            ):
                setattr(target_availability, field, getattr(source_availability, field))

    if "branding" in sections:
        for field in (
            "primary_color",
            "secondary_color",
            "accent_color",
            "background_color",
            "theme_key",
            "template_key",
            "logo_alt",
        ):
            setattr(target, field, getattr(source, field))
    if "landing_content" in sections:
        for field in (
            "headline",
            "description",
            "landing_cta",
            "schedule",
            "reviews_url",
            "seo_title",
            "seo_description",
        ):
            setattr(target, field, getattr(source, field))
    if "automations" in sections:
        source_settings = (
            db.query(ConversationAutomationSettings)
            .filter(ConversationAutomationSettings.business_id == source.id)
            .first()
        )
        target_settings, _rules = ensure_automation_configuration(db, target)
        if source_settings:
            for field in (
                "automation_enabled",
                "auto_threshold",
                "human_reply_pause_minutes",
                "on_limit_reached",
            ):
                setattr(target_settings, field, getattr(source_settings, field))
        source_templates = (
            db.query(ConversationTemplate)
            .filter(ConversationTemplate.business_id == source.id)
            .all()
        )
        for item in source_templates:
            clone_name = f"clone:{source.id}:{item.id}:{item.name}"[:160]
            if (
                not db.query(ConversationTemplate)
                .filter(
                    ConversationTemplate.business_id == target.id,
                    ConversationTemplate.name == clone_name,
                )
                .first()
            ):
                db.add(
                    ConversationTemplate(
                        business_id=target.id,
                        name=clone_name,
                        body=item.body,
                        active=item.active,
                    )
                )
    if "staff_roles" in sections:
        roles = sorted(
            {
                item.role_label
                for item in db.query(BusinessStaffProfile)
                .filter(BusinessStaffProfile.business_id == source.id)
                .all()
            }
        )
        result["staff_role_suggestions"] = roles
        result["warnings"].append("Los roles se sugieren sin copiar datos personales del personal")
    db.flush()
    return result


def readiness_version(business: Business, checks: list[dict[str, Any]]) -> str:
    payload = {
        "business_id": business.id,
        "status": business.status,
        "updated_at": str(business.updated_at),
        "checks": [
            {
                "key": item["key"],
                "status": item["status"],
                "blocking": item["blocking"],
            }
            for item in checks
        ],
    }
    return hashlib.sha256(json.dumps(payload, sort_keys=True).encode()).hexdigest()


def finish_activation_session(session: BusinessOnboardingSession, *, actor_user_id: int) -> None:
    now = utc_now()
    for step in ("readiness_review", "preview", "activation"):
        mark_step_saved(
            session,
            step=step,
            actor_user_id=actor_user_id,
            completed=True,
            summary={"completed": True},
        )
    session.status = "completed"
    session.completed_at = now
    session.last_activity_at = now


def flush_with_conflict(db: Session, *, detail: str) -> None:
    try:
        db.flush()
    except IntegrityError as exc:
        raise HTTPException(status_code=409, detail=detail) from exc
