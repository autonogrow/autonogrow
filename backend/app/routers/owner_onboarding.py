from __future__ import annotations

import hashlib
import json
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.audit import record_audit
from app.core.database import get_db
from app.core.security import require_owner
from app.models import (
    AvailabilitySettings,
    Business,
    BusinessChannelIntegration,
    BusinessOnboardingSession,
    BusinessOnboardingTemplate,
    BusinessService,
    BusinessStaffProfile,
    BusinessStaffProfileService,
    ConversationTemplate,
    User,
)
from app.schemas.onboarding import (
    ActivationRequest,
    AutomationsStepRequest,
    BookingRulesStepRequest,
    BrandingStepRequest,
    BusinessStateReasonRequest,
    CloneConfigurationRequest,
    ContactStepRequest,
    CreditsPlanStepRequest,
    IdentityStepRequest,
    LandingStepRequest,
    OnboardingStartRequest,
    SchedulesStepRequest,
    ServicesStepRequest,
    StaffStepRequest,
    StepSkipRequest,
    TemplateApplyRequest,
)
from app.services.business_onboarding_service import (
    apply_template,
    clone_configuration,
    find_template,
    finish_activation_session,
    get_active_onboarding_session,
    initialize_plan,
    lock_business,
    mark_step_saved,
    normalize_onboarding_slug,
    serialize_onboarding_session,
    skip_step,
    transition_business,
    utc_now,
    validate_placeholders,
)
from app.services.business_readiness_service import evaluate_business_readiness
from app.services.business_status_service import freeze_business_jobs
from app.services.capability_service import configure_business_modules, module_capabilities
from app.services.conversation_automation_service import ensure_automation_configuration
from app.services.incident_service import report_incident

router = APIRouter(
    prefix="/api/owner",
    tags=["owner-onboarding"],
    dependencies=[Depends(require_owner)],
)


def business_or_404(db: Session, business_id: int) -> Business:
    business = db.get(Business, business_id)
    if business is None:
        raise HTTPException(status_code=404, detail="Business not found")
    return business


def _request_id(request: Request) -> str | None:
    value = request.headers.get("x-request-id")
    return value[:120] if value else None


def _audit(
    db: Session,
    *,
    action: str,
    request: Request,
    actor: User,
    business: Business,
    metadata: dict[str, Any] | None = None,
) -> None:
    safe_metadata = {**(metadata or {}), "request_id": _request_id(request)}
    record_audit(
        db,
        action=action,
        request=request,
        actor=actor,
        business_id=business.id,
        resource_type="business_onboarding",
        resource_id=business.id,
        metadata=safe_metadata,
        commit=False,
    )


def _safe_incident(
    db: Session,
    *,
    business_id: int | None,
    category: str,
    operation: str,
    safe_details: dict[str, Any] | None = None,
) -> None:
    try:
        report_incident(
            db,
            category=category,
            severity="high",
            business_id=business_id,
            channel=None,
            provider="onboarding",
            provider_error_code=None,
            operation=operation,
            safe_details=safe_details,
        )
        db.commit()
    except Exception:
        db.rollback()


def _serialize_business_for_onboarding(business: Business) -> dict[str, Any]:
    return {
        "id": business.id,
        "name": business.name,
        "slug": business.slug,
        "status": business.status,
        "category": business.category,
        "description": business.description,
        "legal_name": business.legal_name,
        "tax_identifier": business.tax_identifier,
        "phone": business.phone,
        "whatsapp_phone": business.whatsapp_phone,
        "public_email": business.public_email,
        "city": business.city,
        "address": business.address,
        "postal_code": business.postal_code,
        "region": business.region,
        "country_code": business.country_code,
        "language_code": business.language_code,
        "timezone": business.timezone,
        "currency": business.currency,
        "maps_url": business.maps_url,
        "instagram_url": business.instagram_url,
        "tiktok_url": business.tiktok_url,
        "external_website_url": business.external_website_url,
        "headline": business.headline,
        "landing_cta": business.landing_cta,
        "seo_title": business.seo_title,
        "seo_description": business.seo_description,
        "seo_noindex": business.seo_noindex,
        "theme_key": business.theme_key,
        "template_key": business.template_key,
        "primary_color": business.primary_color,
        "secondary_color": business.secondary_color,
        "accent_color": business.accent_color,
        "background_color": business.background_color,
        "logo_url": business.logo_url,
        "activated_at": business.activated_at,
        "updated_at": business.updated_at,
    }


def _step_context(db: Session, business_id: int) -> tuple[Business, BusinessOnboardingSession]:
    business = lock_business(db, business_id)
    session = get_active_onboarding_session(db, business_id, lock=True)
    if business.status == "archived":
        raise HTTPException(status_code=409, detail="Archived business cannot be edited")
    return business, session


def _save_step_audit(
    db: Session,
    *,
    business: Business,
    session: BusinessOnboardingSession,
    step: str,
    actor: User,
    request: Request,
    completed: bool,
    summary: dict[str, Any],
) -> dict[str, Any]:
    mark_step_saved(
        session,
        step=step,
        actor_user_id=actor.id,
        completed=completed,
        summary=summary,
    )
    if business.status == "draft":
        transition_business(business, "onboarding")
    _audit(
        db,
        action="business_onboarding_step_saved",
        request=request,
        actor=actor,
        business=business,
        metadata={"step": step, "completed": completed},
    )
    db.commit()
    db.refresh(session)
    return {
        "ok": True,
        "business": _serialize_business_for_onboarding(business),
        "onboarding": serialize_onboarding_session(session),
    }


@router.get("/onboarding/templates")
def list_onboarding_templates(db: Session = Depends(get_db)):
    templates = (
        db.query(BusinessOnboardingTemplate)
        .filter(BusinessOnboardingTemplate.is_active.is_(True))
        .order_by(BusinessOnboardingTemplate.category, BusinessOnboardingTemplate.name)
        .all()
    )
    return {
        "templates": [
            {
                "id": item.id,
                "key": item.key,
                "name": item.name,
                "category": item.category,
                "description": item.description,
                "version": item.version,
                "is_system": item.is_system,
            }
            for item in templates
        ]
    }


@router.post("/businesses/onboarding", status_code=201)
def start_business_onboarding(
    payload: OnboardingStartRequest,
    request: Request,
    actor: User = Depends(require_owner),
    db: Session = Depends(get_db),
):
    try:
        slug = normalize_onboarding_slug(payload.slug or payload.name)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail="Slug inválido o reservado") from exc
    if db.query(Business).filter(Business.slug == slug).first():
        raise HTTPException(status_code=409, detail="Business slug already exists")
    business = Business(
        name=payload.name.strip(),
        slug=slug,
        status="draft",
        seo_noindex=True,
        status_updated_at=utc_now(),
    )
    db.add(business)
    try:
        db.flush()
        configure_business_modules(
            db,
            business_id=business.id,
            enabled_modules=payload.modules,
            actor_user_id=actor.id,
        )
        session = BusinessOnboardingSession(
            business_id=business.id,
            status="in_progress",
            current_step="template",
            started_by_user_id=actor.id,
            last_updated_by_user_id=actor.id,
        )
        db.add(session)
        db.flush()
        transition_business(business, "onboarding")
        if payload.template_key:
            template = find_template(db, key=payload.template_key, version=payload.template_version)
            apply_template(
                db,
                business=business,
                session=session,
                template=template,
                actor_user_id=actor.id,
                retain_existing=True,
            )
        _audit(
            db,
            action="business_onboarding_started",
            request=request,
            actor=actor,
            business=business,
            metadata={"steps_version": session.steps_version, "modules": payload.modules},
        )
        db.commit()
    except HTTPException:
        db.rollback()
        raise
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(status_code=409, detail="Active onboarding already exists") from exc
    except Exception:
        db.rollback()
        _safe_incident(
            db,
            business_id=business.id,
            category="onboarding_template_failed",
            operation="start_business_onboarding",
        )
        raise
    db.refresh(business)
    db.refresh(session)
    return {
        "ok": True,
        "business": _serialize_business_for_onboarding(business),
        "modules": module_capabilities(db, business.id),
        "onboarding": serialize_onboarding_session(session),
    }


@router.get("/businesses/{business_id}/onboarding")
def get_business_onboarding(business_id: int, db: Session = Depends(get_db)):
    business = business_or_404(db, business_id)
    session = (
        db.query(BusinessOnboardingSession)
        .filter(BusinessOnboardingSession.business_id == business_id)
        .order_by(BusinessOnboardingSession.id.desc())
        .first()
    )
    if session is None:
        raise HTTPException(status_code=404, detail="Onboarding session not found")
    services = (
        db.query(BusinessService)
        .filter(BusinessService.business_id == business.id)
        .order_by(BusinessService.position, BusinessService.id)
        .all()
    )
    staff = (
        db.query(BusinessStaffProfile)
        .filter(BusinessStaffProfile.business_id == business.id)
        .order_by(BusinessStaffProfile.id)
        .all()
    )
    staff_service_ids: dict[int, list[int]] = {}
    for link in (
        db.query(BusinessStaffProfileService)
        .join(
            BusinessStaffProfile,
            BusinessStaffProfile.id == BusinessStaffProfileService.staff_profile_id,
        )
        .filter(BusinessStaffProfile.business_id == business.id)
        .all()
    ):
        staff_service_ids.setdefault(link.staff_profile_id, []).append(link.service_id)
    availability = (
        db.query(AvailabilitySettings)
        .filter(AvailabilitySettings.business_id == business.id)
        .first()
    )
    integrations = (
        db.query(BusinessChannelIntegration)
        .filter(BusinessChannelIntegration.business_id == business.id)
        .all()
    )
    return {
        "business": _serialize_business_for_onboarding(business),
        "modules": module_capabilities(db, business.id),
        "onboarding": serialize_onboarding_session(session),
        "services": [
            {
                "id": item.id,
                "name": item.name,
                "description": item.description,
                "duration_minutes": item.duration_minutes,
                "price_amount": str(item.price_amount) if item.price_amount is not None else None,
                "currency": item.currency,
                "bookable": item.bookable,
                "visible": item.visible,
                "active": item.active,
                "position": item.position,
            }
            for item in services
        ],
        "staff": [
            {
                "id": item.id,
                "public_name": item.public_name,
                "email": item.email,
                "role_label": item.role_label,
                "capacity": item.capacity,
                "active": item.active,
                "service_ids": sorted(staff_service_ids.get(item.id, [])),
                "has_application_access": item.linked_business_user_id is not None,
            }
            for item in staff
        ],
        "availability": (
            {
                "timezone": availability.timezone,
                "weekly_schedule": json.loads(availability.weekly_schedule_json),
                "slot_interval_minutes": availability.slot_interval_minutes,
                "min_notice_minutes": availability.min_notice_minutes,
                "max_days_ahead": availability.max_days_ahead,
            }
            if availability
            else None
        ),
        "integrations": [
            {
                "channel": item.channel,
                "provider": item.provider,
                "status": item.integration_status,
            }
            for item in integrations
        ],
    }


@router.post("/businesses/{business_id}/onboarding/template")
def set_onboarding_template(
    business_id: int,
    payload: TemplateApplyRequest,
    request: Request,
    actor: User = Depends(require_owner),
    db: Session = Depends(get_db),
):
    business, session = _step_context(db, business_id)
    template = find_template(db, key=payload.template_key, version=payload.template_version)
    if session.template_id and session.template_id != template.id and not payload.confirm_change:
        raise HTTPException(
            status_code=409,
            detail="Changing template requires confirmation; existing data will be retained",
        )
    previous_template_id = session.template_id
    try:
        result = apply_template(
            db,
            business=business,
            session=session,
            template=template,
            actor_user_id=actor.id,
            retain_existing=payload.retain_existing,
        )
        _audit(
            db,
            action="business_template_applied",
            request=request,
            actor=actor,
            business=business,
            metadata={
                "template_key": template.key,
                "template_version": template.version,
                "previous_template_id": previous_template_id,
                "retain_existing": payload.retain_existing,
            },
        )
        db.commit()
    except Exception:
        db.rollback()
        _safe_incident(
            db,
            business_id=business.id,
            category="onboarding_template_failed",
            operation="apply_onboarding_template",
            safe_details={"template_key": template.key, "template_version": template.version},
        )
        raise
    db.refresh(session)
    return {"ok": True, "result": result, "onboarding": serialize_onboarding_session(session)}


@router.put("/businesses/{business_id}/onboarding/identity")
def save_identity_step(
    business_id: int,
    payload: IdentityStepRequest,
    request: Request,
    actor: User = Depends(require_owner),
    db: Session = Depends(get_db),
):
    business, session = _step_context(db, business_id)
    updates = payload.model_dump(exclude_unset=True, exclude={"confirm_active_slug_change"})
    if "slug" in updates:
        try:
            slug = normalize_onboarding_slug(updates["slug"])
        except ValueError as exc:
            raise HTTPException(status_code=422, detail="Slug inválido o reservado") from exc
        if (
            business.status == "active"
            and slug != business.slug
            and not payload.confirm_active_slug_change
        ):
            raise HTTPException(status_code=409, detail="Active slug change requires confirmation")
        conflict = (
            db.query(Business).filter(Business.slug == slug, Business.id != business.id).first()
        )
        if conflict:
            raise HTTPException(status_code=409, detail="Business slug already exists")
        old_slug = business.slug
        business.slug = slug
        if old_slug != slug:
            _audit(
                db,
                action="business_slug_changed",
                request=request,
                actor=actor,
                business=business,
                metadata={"previous_slug_hash": hashlib.sha256(old_slug.encode()).hexdigest()[:12]},
            )
    for field, value in updates.items():
        if field != "slug":
            setattr(business, field, value.strip() if isinstance(value, str) else value)
    completed = bool(business.name and business.slug)
    return _save_step_audit(
        db,
        business=business,
        session=session,
        step="business_identity",
        actor=actor,
        request=request,
        completed=completed,
        summary={"identity_complete": completed},
    )


@router.put("/businesses/{business_id}/onboarding/contact")
def save_contact_step(
    business_id: int,
    payload: ContactStepRequest,
    request: Request,
    actor: User = Depends(require_owner),
    db: Session = Depends(get_db),
):
    business, session = _step_context(db, business_id)
    for field, value in payload.model_dump(exclude_unset=True).items():
        setattr(business, field, value)
    completed = bool(business.phone or business.public_email or business.address)
    return _save_step_audit(
        db,
        business=business,
        session=session,
        step="contact_and_location",
        actor=actor,
        request=request,
        completed=completed,
        summary={"public_contact_configured": completed},
    )


@router.put("/businesses/{business_id}/onboarding/services")
def save_services_step(
    business_id: int,
    payload: ServicesStepRequest,
    request: Request,
    actor: User = Depends(require_owner),
    db: Session = Depends(get_db),
):
    business, session = _step_context(db, business_id)
    for item in payload.services:
        row = db.get(BusinessService, item.id) if item.id else None
        if row is not None and row.business_id != business.id:
            raise HTTPException(status_code=404, detail="Service not found")
        if row is None:
            row = BusinessService(business_id=business.id, name=item.name)
            db.add(row)
        data = item.model_dump(exclude={"id"})
        for field, value in data.items():
            setattr(row, field, value)
        row.duration_text = f"{item.duration_minutes} min"
        row.price_text = str(item.price_amount) if item.price_amount is not None else None
    try:
        db.flush()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(status_code=409, detail="Duplicated service name") from exc
    count = (
        db.query(BusinessService)
        .filter(
            BusinessService.business_id == business.id,
            BusinessService.active.is_(True),
            BusinessService.bookable.is_(True),
            BusinessService.archived_at.is_(None),
        )
        .count()
    )
    return _save_step_audit(
        db,
        business=business,
        session=session,
        step="services",
        actor=actor,
        request=request,
        completed=count > 0,
        summary={"bookable_service_count": count},
    )


@router.put("/businesses/{business_id}/onboarding/staff")
def save_staff_step(
    business_id: int,
    payload: StaffStepRequest,
    request: Request,
    actor: User = Depends(require_owner),
    db: Session = Depends(get_db),
):
    business, session = _step_context(db, business_id)
    for item in payload.staff:
        row = db.get(BusinessStaffProfile, item.id) if item.id else None
        if row is not None and row.business_id != business.id:
            raise HTTPException(status_code=404, detail="Staff profile not found")
        if row is None:
            row = BusinessStaffProfile(
                business_id=business.id,
                public_name=item.public_name,
            )
            db.add(row)
        for field, value in item.model_dump(exclude={"id", "service_ids"}).items():
            setattr(row, field, value)
        db.flush()
        requested_service_ids = set(item.service_ids)
        if requested_service_ids:
            valid_count = (
                db.query(BusinessService)
                .filter(
                    BusinessService.business_id == business.id,
                    BusinessService.id.in_(requested_service_ids),
                )
                .count()
            )
            if valid_count != len(requested_service_ids):
                raise HTTPException(status_code=404, detail="Assigned service not found")
        existing_links = {
            link.service_id: link
            for link in db.query(BusinessStaffProfileService)
            .filter(BusinessStaffProfileService.staff_profile_id == row.id)
            .all()
        }
        for service_id, link in existing_links.items():
            if service_id not in requested_service_ids:
                db.delete(link)
        for service_id in requested_service_ids - set(existing_links):
            db.add(
                BusinessStaffProfileService(
                    staff_profile_id=row.id,
                    service_id=service_id,
                )
            )
    try:
        db.flush()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(status_code=409, detail="Duplicated staff email") from exc
    count = (
        db.query(BusinessStaffProfile)
        .filter(
            BusinessStaffProfile.business_id == business.id,
            BusinessStaffProfile.active.is_(True),
        )
        .count()
    )
    return _save_step_audit(
        db,
        business=business,
        session=session,
        step="staff",
        actor=actor,
        request=request,
        completed=count > 0,
        summary={"staff_profile_count": count, "access_accounts_created": 0},
    )


@router.put("/businesses/{business_id}/onboarding/schedules")
def save_schedules_step(
    business_id: int,
    payload: SchedulesStepRequest,
    request: Request,
    actor: User = Depends(require_owner),
    db: Session = Depends(get_db),
):
    business, session = _step_context(db, business_id)
    settings = (
        db.query(AvailabilitySettings)
        .filter(AvailabilitySettings.business_id == business.id)
        .first()
    )
    if settings is None:
        settings = AvailabilitySettings(
            business_id=business.id,
            weekly_schedule_json="{}",
        )
        db.add(settings)
    if payload.timezone:
        settings.timezone = payload.timezone
        business.timezone = payload.timezone
    schedule = {
        day: [window.model_dump() for window in windows]
        for day, windows in payload.weekly_schedule.items()
    }
    settings.weekly_schedule_json = json.dumps(schedule, sort_keys=True)
    completed = any(schedule.values())
    return _save_step_audit(
        db,
        business=business,
        session=session,
        step="schedules",
        actor=actor,
        request=request,
        completed=completed,
        summary={"open_days": sum(bool(windows) for windows in schedule.values())},
    )


@router.put("/businesses/{business_id}/onboarding/booking")
def save_booking_step(
    business_id: int,
    payload: BookingRulesStepRequest,
    request: Request,
    actor: User = Depends(require_owner),
    db: Session = Depends(get_db),
):
    business, session = _step_context(db, business_id)
    settings = (
        db.query(AvailabilitySettings)
        .filter(AvailabilitySettings.business_id == business.id)
        .first()
    )
    if settings is None:
        settings = AvailabilitySettings(
            business_id=business.id,
            weekly_schedule_json="{}",
        )
        db.add(settings)
    for field, value in payload.model_dump().items():
        setattr(settings, field, value)
    return _save_step_audit(
        db,
        business=business,
        session=session,
        step="booking_rules",
        actor=actor,
        request=request,
        completed=True,
        summary={"slot_interval_minutes": settings.slot_interval_minutes},
    )


@router.put("/businesses/{business_id}/onboarding/branding")
def save_branding_step(
    business_id: int,
    payload: BrandingStepRequest,
    request: Request,
    actor: User = Depends(require_owner),
    db: Session = Depends(get_db),
):
    business, session = _step_context(db, business_id)
    for field, value in payload.model_dump(exclude_unset=True).items():
        setattr(business, field, value)
    completed = bool(business.primary_color or business.logo_url)
    return _save_step_audit(
        db,
        business=business,
        session=session,
        step="branding",
        actor=actor,
        request=request,
        completed=completed,
        summary={"logo_configured": bool(business.logo_url)},
    )


@router.put("/businesses/{business_id}/onboarding/landing")
def save_landing_step(
    business_id: int,
    payload: LandingStepRequest,
    request: Request,
    actor: User = Depends(require_owner),
    db: Session = Depends(get_db),
):
    business, session = _step_context(db, business_id)
    for field, value in payload.model_dump(exclude_unset=True).items():
        setattr(business, field, value)
    business.seo_noindex = business.status != "active"
    completed = bool(business.headline and business.description)
    return _save_step_audit(
        db,
        business=business,
        session=session,
        step="landing_content",
        actor=actor,
        request=request,
        completed=completed,
        summary={"content_complete": completed, "noindex": business.seo_noindex},
    )


@router.put("/businesses/{business_id}/onboarding/automations")
def save_automations_step(
    business_id: int,
    payload: AutomationsStepRequest,
    request: Request,
    actor: User = Depends(require_owner),
    db: Session = Depends(get_db),
):
    business, session = _step_context(db, business_id)
    settings, _rules = ensure_automation_configuration(db, business)
    for field in ("automation_enabled", "auto_threshold", "human_reply_pause_minutes"):
        value = getattr(payload, field)
        if value is not None:
            setattr(settings, field, value)
    for name, body in payload.messages.items():
        try:
            validate_placeholders(body)
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        template_name = f"onboarding:{name}"
        item = (
            db.query(ConversationTemplate)
            .filter(
                ConversationTemplate.business_id == business.id,
                ConversationTemplate.name == template_name,
            )
            .first()
        )
        if item is None:
            item = ConversationTemplate(
                business_id=business.id,
                name=template_name,
                body=body,
                active=True,
            )
            db.add(item)
        else:
            item.body = body
    return _save_step_audit(
        db,
        business=business,
        session=session,
        step="automations",
        actor=actor,
        request=request,
        completed=True,
        summary={"enabled": settings.automation_enabled, "message_count": len(payload.messages)},
    )


@router.put("/businesses/{business_id}/onboarding/credits")
def save_credits_step(
    business_id: int,
    payload: CreditsPlanStepRequest,
    request: Request,
    actor: User = Depends(require_owner),
    db: Session = Depends(get_db),
):
    business, session = _step_context(db, business_id)
    try:
        settings, transaction = initialize_plan(
            db,
            business=business,
            plan_key=payload.plan_key,
            included_credits=payload.included_credits,
            additional_credits=payload.additional_credits,
            period_days=payload.period_days,
            actor_user_id=actor.id,
        )
        _audit(
            db,
            action="business_plan_initialized",
            request=request,
            actor=actor,
            business=business,
            metadata={"plan_key": payload.plan_key, "transaction_id": transaction.id},
        )
        result = _save_step_audit(
            db,
            business=business,
            session=session,
            step="credits_and_plan",
            actor=actor,
            request=request,
            completed=True,
            summary={"plan_key": settings.plan_key},
        )
    except Exception:
        db.rollback()
        _safe_incident(
            db,
            business_id=business.id,
            category="onboarding_plan_initialization_failed",
            operation="initialize_onboarding_plan",
        )
        raise
    return result


@router.post("/businesses/{business_id}/onboarding/steps/{step}/skip")
def skip_onboarding_step(
    business_id: int,
    step: str,
    payload: StepSkipRequest,
    request: Request,
    actor: User = Depends(require_owner),
    db: Session = Depends(get_db),
):
    business, session = _step_context(db, business_id)
    try:
        skip_step(session, step=step, actor_user_id=actor.id, reason=payload.reason)
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    _audit(
        db,
        action="business_onboarding_step_saved",
        request=request,
        actor=actor,
        business=business,
        metadata={"step": step, "skipped": True},
    )
    db.commit()
    return {"ok": True, "onboarding": serialize_onboarding_session(session)}


@router.post("/businesses/{business_id}/clone-configuration")
def clone_business_configuration(
    business_id: int,
    payload: CloneConfigurationRequest,
    request: Request,
    actor: User = Depends(require_owner),
    db: Session = Depends(get_db),
):
    target, session = _step_context(db, business_id)
    source = business_or_404(db, payload.source_business_id)
    try:
        result = clone_configuration(
            db,
            source=source,
            target=target,
            sections=list(payload.sections),
        )
        _audit(
            db,
            action="business_configuration_cloned",
            request=request,
            actor=actor,
            business=target,
            metadata={
                "source_business_id": source.id,
                "sections": list(payload.sections),
                "reason": payload.reason,
            },
        )
        mark_step_saved(
            session,
            step="services" if "services" in payload.sections else session.current_step,
            actor_user_id=actor.id,
            completed="services" in payload.sections,
            summary={"cloned_sections": list(payload.sections)},
        )
        db.commit()
    except Exception:
        db.rollback()
        _safe_incident(
            db,
            business_id=target.id,
            category="onboarding_clone_failed",
            operation="clone_business_configuration",
            safe_details={"source_business_id": source.id, "section_count": len(payload.sections)},
        )
        raise
    return {"ok": True, "result": result}


@router.get("/businesses/{business_id}/readiness")
def get_business_readiness(
    business_id: int,
    request: Request,
    actor: User = Depends(require_owner),
    db: Session = Depends(get_db),
):
    business = business_or_404(db, business_id)
    try:
        readiness = evaluate_business_readiness(db, business)
        session = (
            db.query(BusinessOnboardingSession)
            .filter(
                BusinessOnboardingSession.business_id == business.id,
                BusinessOnboardingSession.status.in_(("in_progress", "blocked")),
            )
            .first()
        )
        if session:
            session.validation_summary_json = json.dumps(readiness, default=str, sort_keys=True)
            session.status = "in_progress" if readiness["ready"] else "blocked"
            mark_step_saved(
                session,
                step="readiness_review",
                actor_user_id=actor.id,
                completed=readiness["ready"],
                summary={
                    "score": readiness["score"],
                    "blocking_count": readiness["blocking_count"],
                },
            )
        _audit(
            db,
            action="business_readiness_checked",
            request=request,
            actor=actor,
            business=business,
            metadata={
                "score": readiness["score"],
                "blocking_count": readiness["blocking_count"],
                "readiness_version": readiness["version"],
            },
        )
        db.commit()
    except Exception:
        db.rollback()
        _safe_incident(
            db,
            business_id=business.id,
            category="onboarding_readiness_error",
            operation="evaluate_business_readiness",
        )
        raise
    return readiness


@router.get("/businesses/{business_id}/preview")
def preview_business(business_id: int, db: Session = Depends(get_db)):
    business = business_or_404(db, business_id)
    if business.status == "archived":
        raise HTTPException(status_code=409, detail="Archived business cannot be previewed")
    services = (
        db.query(BusinessService)
        .filter(
            BusinessService.business_id == business.id,
            BusinessService.visible.is_(True),
            BusinessService.active.is_(True),
        )
        .order_by(BusinessService.position, BusinessService.id)
        .all()
    )
    return {
        "preview": True,
        "banner": "Vista previa",
        "robots": "noindex,nofollow",
        "booking_mode": "disabled",
        "automations_enabled": False,
        "credits_consumed": False,
        "business": {
            "name": business.name,
            "slug": business.slug,
            "headline": business.headline,
            "description": business.description,
            "landing_cta": business.landing_cta,
            "logo_url": business.logo_url,
            "primary_color": business.primary_color,
        },
        "services": [
            {
                "name": item.name,
                "description": item.description,
                "duration_minutes": item.duration_minutes,
                "price_amount": str(item.price_amount) if item.price_amount is not None else None,
                "currency": item.currency,
            }
            for item in services
        ],
    }


@router.post("/businesses/{business_id}/activate")
def activate_business(
    business_id: int,
    payload: ActivationRequest,
    request: Request,
    actor: User = Depends(require_owner),
    db: Session = Depends(get_db),
):
    business = lock_business(db, business_id)
    if business.status == "active":
        return {
            "ok": True,
            "already_active": True,
            "business": _serialize_business_for_onboarding(business),
        }
    if business.status in {"archived", "suspended", "draft"}:
        raise HTTPException(status_code=409, detail="Invalid activation transition")
    try:
        readiness = evaluate_business_readiness(db, business)
        if readiness["version"] != payload.expected_readiness_version:
            raise HTTPException(status_code=409, detail="Readiness changed; review again")
        if not readiness["ready"]:
            raise HTTPException(
                status_code=409,
                detail={
                    "code": "business_not_ready",
                    "blocking_count": readiness["blocking_count"],
                },
            )
        previous_status = business.status
        if business.status in {"onboarding", "configuration_pending"}:
            transition_business(business, "ready")
        transition_business(business, "active")
        now = utc_now()
        business.activated_at = business.activated_at or now
        business.activated_by_user_id = business.activated_by_user_id or actor.id
        business.seo_noindex = False
        session = get_active_onboarding_session(db, business.id, lock=True)
        finish_activation_session(session, actor_user_id=actor.id)
        _audit(
            db,
            action="business_onboarding_completed",
            request=request,
            actor=actor,
            business=business,
            metadata={"readiness_version": readiness["version"]},
        )
        _audit(
            db,
            action="business_activated",
            request=request,
            actor=actor,
            business=business,
            metadata={
                "previous_status": previous_status,
                "new_status": business.status,
                "reason": payload.reason,
            },
        )
        db.commit()
    except HTTPException:
        db.rollback()
        raise
    except Exception:
        db.rollback()
        _safe_incident(
            db,
            business_id=business.id,
            category="onboarding_activation_failed",
            operation="activate_business",
        )
        raise
    return {
        "ok": True,
        "already_active": False,
        "business": _serialize_business_for_onboarding(business),
    }


def _change_active_state(
    db: Session,
    *,
    business_id: int,
    target: str,
    action: str,
    payload: BusinessStateReasonRequest,
    request: Request,
    actor: User,
) -> dict[str, Any]:
    business = lock_business(db, business_id)
    previous_status = business.status
    try:
        transition_business(business, target)
    except ValueError as exc:
        raise HTTPException(status_code=409, detail="Invalid business state transition") from exc
    frozen_jobs = (
        freeze_business_jobs(db, business)
        if target in {"suspended", "archived"}
        else None
    )
    if target == "active":
        readiness = evaluate_business_readiness(db, business)
        if not readiness["ready"]:
            db.rollback()
            raise HTTPException(status_code=409, detail="Business is no longer ready")
        business.seo_noindex = False
    _audit(
        db,
        action=action,
        request=request,
        actor=actor,
        business=business,
        metadata={
            "previous_status": previous_status,
            "new_status": target,
            "reason": payload.reason,
            "frozen_jobs": frozen_jobs,
        },
    )
    db.commit()
    return {"ok": True, "business": _serialize_business_for_onboarding(business)}


@router.post("/businesses/{business_id}/suspend")
def suspend_business(
    business_id: int,
    payload: BusinessStateReasonRequest,
    request: Request,
    actor: User = Depends(require_owner),
    db: Session = Depends(get_db),
):
    return _change_active_state(
        db,
        business_id=business_id,
        target="suspended",
        action="business_suspended",
        payload=payload,
        request=request,
        actor=actor,
    )


@router.post("/businesses/{business_id}/reactivate")
def reactivate_business(
    business_id: int,
    payload: BusinessStateReasonRequest,
    request: Request,
    actor: User = Depends(require_owner),
    db: Session = Depends(get_db),
):
    return _change_active_state(
        db,
        business_id=business_id,
        target="active",
        action="business_reactivated",
        payload=payload,
        request=request,
        actor=actor,
    )


@router.post("/businesses/{business_id}/archive")
def archive_business(
    business_id: int,
    payload: BusinessStateReasonRequest,
    request: Request,
    actor: User = Depends(require_owner),
    db: Session = Depends(get_db),
):
    return _change_active_state(
        db,
        business_id=business_id,
        target="archived",
        action="business_archived",
        payload=payload,
        request=request,
        actor=actor,
    )
