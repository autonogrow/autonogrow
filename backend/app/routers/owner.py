"""Owner-only business management endpoints protected by the signed session."""

import json
import re
import unicodedata
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, Header, HTTPException, Query, Request
from sqlalchemy import and_, func, or_
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.audit import record_audit
from app.core.config import get_settings
from app.core.database import get_db, safe_database_pool_status
from app.core.security import require_owner
from app.models import (
    AuditLog,
    AutomationCreditTransaction,
    AvailabilitySettings,
    Booking,
    Business,
    BusinessChannelIntegration,
    BusinessGalleryImage,
    BusinessService,
    BusinessUser,
    ChannelOutboxMessage,
    ConversationAutomationSettings,
    ConversationMessage,
    MessageOutbox,
    ReviewRequest,
    SystemIncident,
    User,
    WebhookInboxEvent,
    WorkerHeartbeat,
)
from app.schemas.branding import resolve_branding
from app.schemas.owner import (
    AutomationCreditAdjustmentRequest,
    AutomationCreditPurchaseRequest,
    AutomationCreditSummaryResponse,
    AutomationCreditTransactionResponse,
    InstagramIntegrationCreateRequest,
    InstagramIntegrationDisconnectRequest,
    InstagramIntegrationReconnectRequest,
    InstagramIntegrationResponse,
    InstagramIntegrationVerificationResponse,
    OwnerAutomationPeriodAdjustment,
    OwnerAutomationPeriodRenewal,
    OwnerAutomationUsageAdjustment,
    OwnerBusinessAutomationSettingsUpdate,
    OwnerBusinessCreate,
    OwnerBusinessUpdate,
    OwnerBusinessUserCreate,
    OwnerBusinessUserUpdate,
    OwnerIncidentUpdate,
    QueueJobActionRequest,
)
from app.services.automation_credit_service import (
    adjust_credit_balances,
    get_credit_transaction_by_idempotency,
    grant_period_allowance,
    purchase_additional_credits,
    serialize_credit_summary,
    serialize_credit_transaction,
)
from app.services.availability_service import serialize_settings
from app.services.conversation_automation_service import (
    AUTOMATION_PERIOD_DAYS,
    allowed_limit_behaviors,
    as_utc,
    ensure_automation_configuration,
    iso_utc,
    sync_automation_period_status,
    utc_now,
)
from app.services.conversation_automation_service import (
    serialize_settings as serialize_automation_settings,
)
from app.services.incident_service import (
    ACTIVE_STATUSES,
    SEVERITY_ORDER,
    resolve_related_incidents,
    serialize_incident,
)
from app.services.instagram_integration_service import (
    INSTAGRAM_CHANNEL,
    INSTAGRAM_PROVIDER,
    evaluate_integration_expiration,
    get_instagram_integration,
    lock_instagram_integration,
    mask_external_account_id,
    replace_integration_credentials,
    report_integration_incident,
    serialize_instagram_integration,
    verify_instagram_integration,
)
from app.services.instagram_provider import verify_instagram_access_token
from app.services.integration_crypto_service import IntegrationCryptoError
from app.services.worker_heartbeat_service import heartbeat_is_stale

router = APIRouter(prefix="/api/owner", tags=["owner"], dependencies=[Depends(require_owner)])

PENDING_BOOKING_STATUSES = ("requested", "pending")
UPCOMING_BOOKING_STATUSES = ("requested", "pending", "confirmed")

DEFAULT_BUSINESS_HOURS = {
    "0": [],
    "1": [{"start": "10:00", "end": "14:00"}, {"start": "16:00", "end": "20:00"}],
    "2": [{"start": "10:00", "end": "14:00"}, {"start": "16:00", "end": "20:00"}],
    "3": [{"start": "10:00", "end": "14:00"}, {"start": "16:00", "end": "20:00"}],
    "4": [{"start": "10:00", "end": "14:00"}, {"start": "16:00", "end": "20:00"}],
    "5": [{"start": "10:00", "end": "14:00"}, {"start": "16:00", "end": "20:00"}],
    "6": [{"start": "10:00", "end": "14:00"}],
}
MANICURA_HOURS = {
    "0": [],
    **{str(day): [{"start": "10:00", "end": "20:00"}] for day in range(1, 6)},
    "6": [{"start": "10:00", "end": "14:00"}],
}
TALLER_HOURS = {
    "0": [],
    **{
        str(day): [{"start": "09:00", "end": "14:00"}, {"start": "16:00", "end": "19:00"}]
        for day in range(1, 6)
    },
    "6": [],
}
SCHEDULE_TEMPLATES = {
    "default_business_hours": DEFAULT_BUSINESS_HOURS,
    "barberia": DEFAULT_BUSINESS_HOURS,
    "manicura": MANICURA_HOURS,
    "taller": TALLER_HOURS,
    "peluqueria": DEFAULT_BUSINESS_HOURS,
    "estetica": MANICURA_HOURS,
    "fisioterapia": DEFAULT_BUSINESS_HOURS,
    "entrenamiento_personal": DEFAULT_BUSINESS_HOURS,
    "psicologia": DEFAULT_BUSINESS_HOURS,
    "clinica_dental": DEFAULT_BUSINESS_HOURS,
    "masajes": DEFAULT_BUSINESS_HOURS,
    "custom": {str(day): [] for day in range(7)},
}


def normalize_slug(value: str) -> str:
    ascii_value = unicodedata.normalize("NFKD", value).encode("ascii", "ignore").decode("ascii")
    slug = re.sub(r"[^a-z0-9]+", "-", ascii_value.lower()).strip("-")
    if not slug:
        raise HTTPException(status_code=422, detail="El slug debe contener letras o números")
    return slug[:120].rstrip("-")


def get_business_or_404(db: Session, business_slug: str) -> Business:
    business = db.query(Business).filter(Business.slug == business_slug).first()
    if business is None:
        raise HTTPException(status_code=404, detail="Business not found")
    return business


def get_business_by_id_or_404(db: Session, business_id: int) -> Business:
    business = db.query(Business).filter(Business.id == business_id).first()
    if business is None:
        raise HTTPException(status_code=404, detail="Business not found")
    return business


def owner_automation_payload(
    db: Session,
    business: Business,
    settings: ConversationAutomationSettings,
) -> dict:
    latest_incident = (
        db.query(SystemIncident)
        .filter(SystemIncident.business_id == business.id)
        .order_by(SystemIncident.last_occurred_at.desc(), SystemIncident.id.desc())
        .first()
    )
    serialized = serialize_automation_settings(settings)
    recent_credit_transactions = (
        db.query(AutomationCreditTransaction)
        .filter(AutomationCreditTransaction.business_id == business.id)
        .order_by(
            AutomationCreditTransaction.created_at.desc(), AutomationCreditTransaction.id.desc()
        )
        .limit(8)
        .all()
    )
    return {
        "business": {"id": business.id, "slug": business.slug, "name": business.name},
        "settings": serialized,
        "usage": {
            "used": settings.auto_used_current_period,
            "limit": settings.included_credits_per_period,
            "percentage": serialized["usage_percentage"],
            "status": serialized["usage_status"],
            "period_start": serialized["period_start"],
            "period_end": serialized["period_end"],
            "period_status": serialized["period_status"],
            "payment_confirmed_at": serialized["payment_confirmed_at"],
            "days_remaining": serialized["days_remaining"],
        },
        "last_incident": serialize_incident(latest_incident) if latest_incident else None,
        "credits": credit_summary_payload(settings),
        "credit_transactions": [
            serialize_credit_transaction(item) for item in recent_credit_transactions
        ],
        "limit_max": 1_000_000,
    }


def credit_summary_payload(
    settings: ConversationAutomationSettings,
    *,
    idempotent_replay: bool = False,
) -> dict:
    return {
        **serialize_credit_summary(settings),
        "period_status": settings.period_status,
        "period_ends_at": iso_utc(settings.period_ends_at),
        "idempotent_replay": idempotent_replay,
    }


def owner_instagram_integration_payload(
    db: Session,
    integration: BusinessChannelIntegration,
) -> dict:
    payload = serialize_instagram_integration(integration)
    payload["has_open_incident"] = (
        db.query(SystemIncident)
        .filter(
            SystemIncident.integration_id == integration.id,
            SystemIncident.status.in_(ACTIVE_STATUSES),
        )
        .count()
        > 0
    )
    return payload


def owner_audit_metadata(
    request: Request,
    *,
    old_value,
    new_value,
    reason: str | None,
    field: str | None = None,
) -> dict:
    metadata = {
        "old_value": old_value,
        "new_value": new_value,
        "reason": reason,
    }
    if field:
        metadata["field"] = field
    request_id = request.headers.get("x-request-id")
    if request_id:
        metadata["request_id"] = request_id[:120]
    return metadata


def serialize_business(business: Business) -> dict:
    return {
        "id": business.id,
        "slug": business.slug,
        "name": business.name,
        "category": business.category,
        "headline": business.headline,
        "description": business.description,
        "phone": business.phone,
        "city": business.city,
        "address": business.address,
        "schedule": business.schedule,
        "maps_url": business.maps_url,
        "instagram_url": business.instagram_url,
        "reviews_url": business.reviews_url,
        "primary_color": business.primary_color,
        "secondary_color": business.secondary_color,
        "accent_color": business.accent_color,
        "background_color": business.background_color,
        "theme_key": business.theme_key,
        "template_key": business.template_key,
        "logo_url": business.logo_url,
        "logo_alt": business.logo_alt,
        "active": business.status == "active",
        "created_at": business.created_at.isoformat() if business.created_at else None,
    }


def serialize_service(service: BusinessService) -> dict:
    return {
        "id": service.id,
        "name": service.name,
        "description": service.description,
        "price_text": service.price_text,
        "duration_text": service.duration_text,
        "duration_minutes": service.duration_minutes,
        "active": service.active,
    }


def serialize_business_user(item: BusinessUser) -> dict:
    return {
        "id": item.id,
        "business_id": item.business_id,
        "user_id": item.user_id,
        "email": item.user.email,
        "name": item.user.name,
        "picture_url": item.user.picture_url,
        "role": item.role,
        "active": item.active,
        "public_name": item.public_name,
        "bookable": item.bookable,
        "show_schedule": item.show_schedule,
        "bio": item.bio,
        "avatar_url": item.avatar_url,
        "removed_at": item.removed_at.isoformat() if item.removed_at else None,
        "pending": item.user.google_sub is None,
        "created_at": item.created_at.isoformat(),
    }


def build_metrics(db: Session, business: Business) -> dict:
    now = datetime.now(ZoneInfo("Europe/Madrid")).replace(tzinfo=None)
    tomorrow = datetime.combine(now.date() + timedelta(days=1), datetime.min.time())
    today_start = datetime.combine(now.date(), datetime.min.time())
    booking_query = db.query(Booking).filter(Booking.business_id == business.id)
    return {
        "total_bookings": booking_query.count(),
        "pending_bookings": booking_query.filter(
            Booking.status.in_(PENDING_BOOKING_STATUSES)
        ).count(),
        "today_bookings": booking_query.filter(
            or_(
                and_(Booking.start_datetime >= today_start, Booking.start_datetime < tomorrow),
                Booking.preferred_date == now.date().isoformat(),
            )
        ).count(),
        "upcoming_bookings": booking_query.filter(
            Booking.status.in_(UPCOMING_BOOKING_STATUSES),
            or_(
                Booking.start_datetime >= now,
                and_(
                    Booking.start_datetime.is_(None),
                    Booking.preferred_date >= now.date().isoformat(),
                ),
            ),
        ).count(),
        "active_services": db.query(BusinessService)
        .filter(BusinessService.business_id == business.id, BusinessService.active.is_(True))
        .count(),
        "message_outbox_pending": db.query(MessageOutbox)
        .filter(MessageOutbox.business_id == business.id, MessageOutbox.status == "pending")
        .count(),
        "review_requests_pending": db.query(ReviewRequest)
        .filter(ReviewRequest.business_id == business.id, ReviewRequest.status == "pending")
        .count(),
    }


def build_health(db: Session, business: Business, metrics: dict) -> dict:
    settings = (
        db.query(AvailabilitySettings)
        .filter(AvailabilitySettings.business_id == business.id)
        .first()
    )
    has_schedule = False
    if settings:
        try:
            weekly_schedule = json.loads(settings.weekly_schedule_json)
            has_schedule = any(bool(windows) for windows in weekly_schedule.values())
        except (json.JSONDecodeError, AttributeError):
            has_schedule = False
    health = {
        "has_basic_info": bool(business.name and business.category and business.city),
        "has_phone": bool(business.phone and business.phone.strip()),
        "has_active_services": metrics["active_services"] > 0,
        "has_schedule": has_schedule,
        "has_reviews_url": bool(business.reviews_url and business.reviews_url.strip()),
        "has_logo": bool(business.logo_url),
        "has_gallery": db.query(BusinessGalleryImage)
        .filter(
            BusinessGalleryImage.business_id == business.id, BusinessGalleryImage.active.is_(True)
        )
        .count()
        > 0,
        "has_colors": bool(
            business.primary_color
            and business.secondary_color
            and business.accent_color
            and business.background_color
        ),
    }
    health["is_public_ready"] = bool(
        business.status == "active"
        and health["has_basic_info"]
        and health["has_phone"]
        and health["has_active_services"]
        and health["has_schedule"]
    )
    return health


def serialize_owner_summary(db: Session, business: Business) -> dict:
    metrics = build_metrics(db, business)
    return {
        **serialize_business(business),
        "metrics": metrics,
        "health": build_health(db, business, metrics),
    }


@router.get("/businesses")
def list_owner_businesses(db: Session = Depends(get_db)):
    businesses = db.query(Business).order_by(Business.created_at.desc(), Business.id.desc()).all()
    return [serialize_owner_summary(db, business) for business in businesses]


@router.get("/incidents")
def list_owner_incidents(
    status: str | None = None,
    severity: str | None = None,
    business_id: int | None = None,
    channel: str | None = None,
    open_only: bool = False,
    limit: int = Query(default=200, ge=1, le=500),
    db: Session = Depends(get_db),
):
    query = db.query(SystemIncident)
    if open_only:
        query = query.filter(SystemIncident.status.in_(("open", "acknowledged")))
    elif status:
        normalized_status = status.strip().lower()
        if normalized_status not in {"open", "acknowledged", "resolved", "ignored"}:
            raise HTTPException(status_code=422, detail="Invalid incident status")
        query = query.filter(SystemIncident.status == normalized_status)
    if severity:
        normalized_severity = severity.strip().lower()
        if normalized_severity not in SEVERITY_ORDER:
            raise HTTPException(status_code=422, detail="Invalid incident severity")
        query = query.filter(SystemIncident.severity == normalized_severity)
    if business_id is not None:
        query = query.filter(SystemIncident.business_id == business_id)
    if channel:
        query = query.filter(SystemIncident.channel == channel.strip().lower())
    rows = (
        query.order_by(SystemIncident.last_occurred_at.desc(), SystemIncident.id.desc())
        .limit(limit)
        .all()
    )
    open_count = (
        db.query(SystemIncident).filter(SystemIncident.status.in_(("open", "acknowledged"))).count()
    )
    return {
        "incidents": [serialize_incident(item) for item in rows],
        "open_count": open_count,
    }


@router.get("/businesses/{business_id}/automation-settings")
def get_owner_business_automation_settings(
    business_id: int,
    actor: User = Depends(require_owner),
    db: Session = Depends(get_db),
):
    require_owner(actor)
    business = get_business_by_id_or_404(db, business_id)
    settings, _ = ensure_automation_configuration(db, business)
    db.commit()
    db.refresh(settings)
    return owner_automation_payload(db, business, settings)


@router.patch("/businesses/{business_id}/automation-settings")
def update_owner_business_automation_settings(
    business_id: int,
    payload: OwnerBusinessAutomationSettingsUpdate,
    request: Request,
    actor: User = Depends(require_owner),
    db: Session = Depends(get_db),
):
    require_owner(actor)
    business = get_business_by_id_or_404(db, business_id)
    settings, _ = ensure_automation_configuration(db, business)
    updates = payload.model_dump(exclude_unset=True, exclude={"reason"})
    reason = payload.reason
    effective_allowed = updates.get("allowed_limit_behaviors", allowed_limit_behaviors(settings))
    effective_behavior = updates.get("on_limit_reached", settings.on_limit_reached)
    if effective_behavior not in effective_allowed:
        raise HTTPException(
            status_code=422,
            detail="El comportamiento al alcanzar el límite debe estar entre las opciones permitidas",
        )

    field_mapping = {
        "plan": "plan_key",
        "auto_limit_per_period": "monthly_auto_limit",
        "on_limit_reached": "on_limit_reached",
        "automation_feature_enabled": "automation_feature_enabled",
        "instagram_channel_enabled": "instagram_channel_enabled",
        "whatsapp_channel_enabled": "whatsapp_channel_enabled",
    }
    audit_actions = {
        "plan": "business_plan_changed",
        "auto_limit_per_period": "automation_limit_changed",
        "on_limit_reached": "automation_limit_behavior_changed",
    }
    for api_field, model_field in field_mapping.items():
        if api_field not in updates:
            continue
        old_value = getattr(settings, model_field)
        new_value = updates[api_field]
        if old_value == new_value:
            continue
        setattr(settings, model_field, new_value)
        if api_field == "auto_limit_per_period":
            settings.included_credits_per_period = int(new_value)
            settings.included_credits_used = min(
                settings.included_credits_used,
                settings.included_credits_per_period,
            )
        if api_field == "automation_feature_enabled":
            settings.automation_enabled = bool(new_value)
            if not new_value:
                settings.period_status = "suspended"
            else:
                period_ends_at = as_utc(settings.period_ends_at)
                settings.period_status = (
                    "active"
                    if period_ends_at is not None and utc_now() < period_ends_at
                    else "pending_renewal"
                )
        action = audit_actions.get(api_field)
        if action is None:
            action = "automation_feature_enabled" if new_value else "automation_feature_disabled"
        record_audit(
            db,
            action=action,
            request=request,
            actor=actor,
            business_id=business.id,
            resource_type="conversation_automation_settings",
            resource_id=settings.id,
            metadata=owner_audit_metadata(
                request,
                old_value=old_value,
                new_value=new_value,
                reason=reason,
                field=api_field,
            ),
            commit=False,
        )

    if "allowed_limit_behaviors" in updates:
        old_allowed = allowed_limit_behaviors(settings)
        new_allowed = updates["allowed_limit_behaviors"]
        if old_allowed != new_allowed:
            settings.allowed_limit_behaviors_json = json.dumps(new_allowed)
            record_audit(
                db,
                action="automation_limit_behavior_changed",
                request=request,
                actor=actor,
                business_id=business.id,
                resource_type="conversation_automation_settings",
                resource_id=settings.id,
                metadata=owner_audit_metadata(
                    request,
                    old_value=old_allowed,
                    new_value=new_allowed,
                    reason=reason,
                    field="allowed_limit_behaviors",
                ),
                commit=False,
            )
    settings.updated_at = utc_now()
    db.commit()
    db.refresh(settings)
    return {"ok": True, **owner_automation_payload(db, business, settings)}


@router.post("/businesses/{business_id}/automation-usage-adjustment")
def adjust_owner_business_automation_usage(
    business_id: int,
    payload: OwnerAutomationUsageAdjustment,
    request: Request,
    actor: User = Depends(require_owner),
    db: Session = Depends(get_db),
):
    require_owner(actor)
    business = get_business_by_id_or_404(db, business_id)
    settings, _ = ensure_automation_configuration(db, business)
    old_usage = settings.auto_used_current_period
    if payload.new_usage > settings.included_credits_per_period:
        raise HTTPException(
            status_code=422,
            detail="El ajuste heredado no puede superar los créditos incluidos del periodo",
        )
    settings.auto_used_current_period = payload.new_usage
    settings.included_credits_used = payload.new_usage
    settings.updated_at = utc_now()
    record_audit(
        db,
        action="automation_usage_adjusted",
        request=request,
        actor=actor,
        business_id=business.id,
        resource_type="conversation_automation_settings",
        resource_id=settings.id,
        metadata=owner_audit_metadata(
            request,
            old_value=old_usage,
            new_value=payload.new_usage,
            reason=payload.reason,
            field="auto_used_current_period",
        ),
        commit=False,
    )
    db.commit()
    db.refresh(settings)
    return {"ok": True, **owner_automation_payload(db, business, settings)}


def _renewal_audit_metadata(
    *,
    request: Request,
    actor: User,
    business: Business,
    settings: ConversationAutomationSettings,
    old_started_at,
    old_ends_at,
    old_usage: int,
    reason: str,
    amount: float | None,
    payment_method: str | None,
    external_reference: str | None,
    idempotency_key: str | None,
    confirmed_at,
) -> dict:
    metadata = {
        "owner_user_id": actor.id,
        "business_id": business.id,
        "old_period_started_at": iso_utc(old_started_at),
        "old_period_ends_at": iso_utc(old_ends_at),
        "new_period_started_at": iso_utc(settings.period_started_at),
        "new_period_ends_at": iso_utc(settings.period_ends_at),
        "old_usage": old_usage,
        "new_usage": 0,
        "plan_key": settings.plan_key,
        "monthly_auto_limit": settings.monthly_auto_limit,
        "reason": reason,
        "amount": amount,
        "payment_method": payment_method,
        "external_reference": external_reference,
        "timestamp": iso_utc(confirmed_at),
    }
    request_id = request.headers.get("x-request-id")
    if request_id:
        metadata["request_id"] = request_id[:120]
    if idempotency_key:
        metadata["idempotency_key"] = idempotency_key
    return metadata


def _renewal_was_already_processed(
    db: Session,
    *,
    business_id: int,
    idempotency_key: str | None,
) -> bool:
    if not idempotency_key:
        return False
    recent_logs = (
        db.query(AuditLog)
        .filter(
            AuditLog.business_id == business_id,
            AuditLog.action == "automation_period_renewed",
        )
        .order_by(AuditLog.id.desc())
        .limit(50)
        .all()
    )
    for item in recent_logs:
        try:
            metadata = json.loads(item.metadata_json or "{}")
        except (TypeError, ValueError):
            continue
        if metadata.get("idempotency_key") == idempotency_key:
            return True
    return False


@router.post("/businesses/{business_id}/automation-period-renewal")
def renew_owner_business_automation_period(
    business_id: int,
    payload: OwnerAutomationPeriodRenewal,
    request: Request,
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
    actor: User = Depends(require_owner),
    db: Session = Depends(get_db),
):
    require_owner(actor)
    business = get_business_by_id_or_404(db, business_id)
    settings, _ = ensure_automation_configuration(db, business)
    db.refresh(settings, with_for_update=True)
    sync_automation_period_status(settings, db=db)
    normalized_key = (
        idempotency_key.strip()[:120]
        if isinstance(idempotency_key, str) and idempotency_key.strip()
        else None
    )
    if _renewal_was_already_processed(db, business_id=business.id, idempotency_key=normalized_key):
        db.commit()
        db.refresh(settings)
        return {
            "ok": True,
            "idempotent_replay": True,
            **owner_automation_payload(db, business, settings),
        }
    existing_credit_transaction = (
        get_credit_transaction_by_idempotency(
            db,
            business_id=business.id,
            idempotency_key=normalized_key,
        )
        if normalized_key
        else None
    )
    if existing_credit_transaction is not None:
        if existing_credit_transaction.transaction_type != "period_allowance_granted":
            raise HTTPException(status_code=409, detail="Idempotency key already used")
        db.commit()
        return {
            "ok": True,
            "idempotent_replay": True,
            **owner_automation_payload(db, business, settings),
        }

    confirmed_at = utc_now()
    last_confirmation = as_utc(settings.payment_confirmed_at)
    if last_confirmation is not None and confirmed_at - last_confirmation < timedelta(seconds=10):
        db.commit()
        db.refresh(settings)
        return {
            "ok": True,
            "idempotent_replay": True,
            **owner_automation_payload(db, business, settings),
        }
    current_end = as_utc(settings.period_ends_at)
    if (
        settings.period_status == "active"
        and current_end is not None
        and confirmed_at < current_end
        and not payload.confirm_active_period
    ):
        raise HTTPException(
            status_code=409,
            detail=(
                "El periodo sigue activo. Confirma expresamente que la renovación "
                "sustituirá el periodo actual y comenzará ahora."
            ),
        )

    old_started_at = settings.period_started_at
    old_ends_at = settings.period_ends_at
    old_usage = settings.auto_used_current_period
    manually_suspended = (
        not settings.automation_feature_enabled or settings.period_status == "suspended"
    )
    settings.payment_confirmed_at = confirmed_at
    settings.period_started_at = confirmed_at
    settings.period_ends_at = confirmed_at + timedelta(days=AUTOMATION_PERIOD_DAYS)
    settings.period_status = "suspended" if manually_suspended else "active"
    settings.updated_at = confirmed_at
    allowance_transaction = grant_period_allowance(
        db,
        settings=settings,
        owner_user_id=actor.id,
        reason=payload.reason,
        idempotency_key=normalized_key,
    )
    audit_metadata = _renewal_audit_metadata(
        request=request,
        actor=actor,
        business=business,
        settings=settings,
        old_started_at=old_started_at,
        old_ends_at=old_ends_at,
        old_usage=old_usage,
        reason=payload.reason,
        amount=payload.amount,
        payment_method=payload.payment_method,
        external_reference=payload.external_reference,
        idempotency_key=normalized_key,
        confirmed_at=confirmed_at,
    )
    try:
        for action in ("automation_payment_confirmed", "automation_period_renewed"):
            record_audit(
                db,
                action=action,
                request=request,
                actor=actor,
                business_id=business.id,
                resource_type="conversation_automation_settings",
                resource_id=settings.id,
                metadata=audit_metadata,
                commit=False,
            )
        record_audit(
            db,
            action="automation_period_allowance_granted",
            request=request,
            actor=actor,
            business_id=business.id,
            resource_type="automation_credit_transaction",
            resource_id=allowance_transaction.id,
            metadata={
                **audit_metadata,
                **serialize_credit_summary(settings),
            },
            commit=False,
        )
        db.commit()
    except Exception:
        db.rollback()
        raise
    db.refresh(settings)
    return {
        "ok": True,
        "idempotent_replay": False,
        **owner_automation_payload(db, business, settings),
    }


@router.post("/businesses/{business_id}/automation-period-adjustment")
def adjust_owner_business_automation_period(
    business_id: int,
    payload: OwnerAutomationPeriodAdjustment,
    request: Request,
    actor: User = Depends(require_owner),
    db: Session = Depends(get_db),
):
    require_owner(actor)
    business = get_business_by_id_or_404(db, business_id)
    settings, _ = ensure_automation_configuration(db, business)
    db.refresh(settings, with_for_update=True)
    old_value = {
        "period_started_at": iso_utc(settings.period_started_at),
        "period_ends_at": iso_utc(settings.period_ends_at),
        "period_status": settings.period_status,
        "usage": settings.auto_used_current_period,
    }
    settings.period_started_at = as_utc(payload.period_started_at)
    settings.period_ends_at = as_utc(payload.period_ends_at)
    settings.period_status = (
        "suspended" if not settings.automation_feature_enabled else payload.period_status
    )
    settings.updated_at = utc_now()
    sync_automation_period_status(settings, db=db)
    new_value = {
        "period_started_at": iso_utc(settings.period_started_at),
        "period_ends_at": iso_utc(settings.period_ends_at),
        "period_status": settings.period_status,
        "usage": settings.auto_used_current_period,
    }
    try:
        record_audit(
            db,
            action="automation_period_adjusted",
            request=request,
            actor=actor,
            business_id=business.id,
            resource_type="conversation_automation_settings",
            resource_id=settings.id,
            metadata=owner_audit_metadata(
                request,
                old_value=old_value,
                new_value=new_value,
                reason=payload.reason,
            ),
            commit=False,
        )
        db.commit()
    except Exception:
        db.rollback()
        raise
    db.refresh(settings)
    return {"ok": True, **owner_automation_payload(db, business, settings)}


@router.get(
    "/businesses/{business_id}/integrations",
    response_model=list[InstagramIntegrationResponse],
)
def list_owner_business_integrations(
    business_id: int,
    actor: User = Depends(require_owner),
    db: Session = Depends(get_db),
):
    require_owner(actor)
    get_business_by_id_or_404(db, business_id)
    rows = (
        db.query(BusinessChannelIntegration)
        .filter(BusinessChannelIntegration.business_id == business_id)
        .order_by(BusinessChannelIntegration.provider, BusinessChannelIntegration.id)
        .all()
    )
    for item in rows:
        evaluate_integration_expiration(db, item)
    db.commit()
    return [owner_instagram_integration_payload(db, item) for item in rows]


@router.get(
    "/businesses/{business_id}/integrations/instagram",
    response_model=InstagramIntegrationResponse,
)
def get_owner_business_instagram_integration(
    business_id: int,
    actor: User = Depends(require_owner),
    db: Session = Depends(get_db),
):
    require_owner(actor)
    get_business_by_id_or_404(db, business_id)
    integration = get_instagram_integration(db, business_id=business_id)
    if integration is None:
        raise HTTPException(status_code=404, detail="Instagram integration not found")
    evaluate_integration_expiration(db, integration)
    db.commit()
    db.refresh(integration)
    return owner_instagram_integration_payload(db, integration)


@router.post(
    "/businesses/{business_id}/integrations/instagram",
    response_model=InstagramIntegrationResponse,
    status_code=201,
)
def create_owner_business_instagram_integration(
    business_id: int,
    payload: InstagramIntegrationCreateRequest,
    request: Request,
    actor: User = Depends(require_owner),
    db: Session = Depends(get_db),
):
    require_owner(actor)
    business = get_business_by_id_or_404(db, business_id)
    if get_instagram_integration(db, business_id=business_id) is not None:
        raise HTTPException(status_code=409, detail="Business already has an Instagram integration")
    conflict = (
        db.query(BusinessChannelIntegration)
        .filter(
            BusinessChannelIntegration.provider == INSTAGRAM_PROVIDER,
            BusinessChannelIntegration.external_account_id == payload.external_account_id,
        )
        .first()
    )
    if conflict is not None:
        raise HTTPException(
            status_code=409, detail="Instagram account already belongs to another business"
        )
    access_token = payload.access_token.get_secret_value()
    verification = verify_instagram_access_token(payload.external_account_id, access_token)
    if not verification.ok:
        report_integration_incident(
            db,
            integration=None,
            business_id=business.id,
            category="instagram_verification_failed",
            severity="high" if verification.error_code == "190" else "medium",
            operation="create_integration",
            error_code=verification.error_code,
            safe_details={
                "error_type": verification.error_type,
                "error_subcode": verification.error_subcode,
                "http_status": verification.http_status,
            },
        )
        db.commit()
        raise HTTPException(status_code=422, detail="Instagram account verification failed")
    now = utc_now()
    integration = BusinessChannelIntegration(
        business_id=business.id,
        channel=INSTAGRAM_CHANNEL,
        provider=INSTAGRAM_PROVIDER,
        external_account_id=payload.external_account_id,
        external_account_name=verification.account_name or payload.external_account_name,
        token_type="bearer",
        token_expires_at=payload.token_expires_at,
        granted_scopes_json=json.dumps(list(verification.scopes)),
        integration_status="connected",
        provider_status=verification.provider_status or "available",
        connected_at=now,
        last_verified_at=now,
        last_success_at=now,
    )
    try:
        replace_integration_credentials(
            integration,
            access_token=access_token,
            token_expires_at=payload.token_expires_at,
        )
        db.add(integration)
        db.flush()
        record_audit(
            db,
            action="instagram_integration_created",
            request=request,
            actor=actor,
            business_id=business.id,
            resource_type="business_channel_integration",
            resource_id=integration.id,
            metadata={
                "owner_user_id": actor.id,
                "business_id": business.id,
                "integration_id": integration.id,
                "external_account_id": mask_external_account_id(payload.external_account_id),
                "old_status": None,
                "new_status": "connected",
                "reason": payload.reason,
                "request_id": request.headers.get("x-request-id"),
                "timestamp": now.isoformat(),
            },
            commit=False,
        )
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(
            status_code=409, detail="Instagram account already belongs to another business"
        ) from exc
    except IntegrationCryptoError as exc:
        db.rollback()
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    db.refresh(integration)
    return owner_instagram_integration_payload(db, integration)


@router.post(
    "/businesses/{business_id}/integrations/instagram/verify",
    response_model=InstagramIntegrationVerificationResponse,
)
def verify_owner_business_instagram_integration(
    business_id: int,
    request: Request,
    actor: User = Depends(require_owner),
    db: Session = Depends(get_db),
):
    require_owner(actor)
    get_business_by_id_or_404(db, business_id)
    integration = get_instagram_integration(db, business_id=business_id)
    if integration is None:
        raise HTTPException(status_code=404, detail="Instagram integration not found")
    now = utc_now()
    last_verified = as_utc(integration.last_verified_at)
    if last_verified and now - last_verified < timedelta(seconds=15):
        return {
            "verified": integration.integration_status == "connected",
            "rate_limited": True,
            "integration": owner_instagram_integration_payload(db, integration),
        }
    old_status = integration.integration_status
    verification = verify_instagram_integration(db, integration)
    record_audit(
        db,
        action="instagram_integration_verified",
        request=request,
        actor=actor,
        business_id=business_id,
        resource_type="business_channel_integration",
        resource_id=integration.id,
        metadata={
            "owner_user_id": actor.id,
            "business_id": business_id,
            "integration_id": integration.id,
            "external_account_id": mask_external_account_id(integration.external_account_id),
            "old_status": old_status,
            "new_status": integration.integration_status,
            "safe_code": verification.error_code,
            "request_id": request.headers.get("x-request-id"),
            "timestamp": now.isoformat(),
        },
        commit=False,
    )
    db.commit()
    db.refresh(integration)
    return {
        "verified": verification.ok,
        "rate_limited": False,
        "integration": owner_instagram_integration_payload(db, integration),
    }


@router.post(
    "/businesses/{business_id}/integrations/instagram/reconnect",
    response_model=InstagramIntegrationResponse,
)
def reconnect_owner_business_instagram_integration(
    business_id: int,
    payload: InstagramIntegrationReconnectRequest,
    request: Request,
    actor: User = Depends(require_owner),
    db: Session = Depends(get_db),
):
    require_owner(actor)
    get_business_by_id_or_404(db, business_id)
    integration = get_instagram_integration(db, business_id=business_id)
    if integration is None:
        raise HTTPException(status_code=404, detail="Instagram integration not found")
    if payload.external_account_id != integration.external_account_id:
        conflict = (
            db.query(BusinessChannelIntegration)
            .filter(
                BusinessChannelIntegration.provider == INSTAGRAM_PROVIDER,
                BusinessChannelIntegration.external_account_id == payload.external_account_id,
            )
            .first()
        )
        if conflict is not None:
            raise HTTPException(
                status_code=409, detail="Instagram account already belongs to another business"
            )
        raise HTTPException(
            status_code=409, detail="Reconnect cannot move an integration to another account"
        )
    access_token = payload.access_token.get_secret_value()
    # Meta verification is deliberately outside the database transaction.
    db.commit()
    verification = verify_instagram_access_token(payload.external_account_id, access_token)
    integration = lock_instagram_integration(db, integration)
    if not verification.ok:
        report_integration_incident(
            db,
            integration=integration,
            category=(
                "instagram_token_revoked"
                if verification.error_code == "190"
                else "instagram_verification_failed"
            ),
            severity="high" if verification.error_code == "190" else "medium",
            operation="reconnect_integration",
            error_code=verification.error_code,
            safe_details={
                "error_type": verification.error_type,
                "error_subcode": verification.error_subcode,
                "http_status": verification.http_status,
            },
        )
        db.commit()
        raise HTTPException(status_code=422, detail="Instagram account verification failed")
    old_status = integration.integration_status
    try:
        replace_integration_credentials(
            integration,
            access_token=access_token,
            token_expires_at=payload.token_expires_at,
        )
    except IntegrationCryptoError as exc:
        db.rollback()
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    now = utc_now()
    integration.integration_status = "connected"
    integration.provider_status = verification.provider_status or "available"
    integration.external_account_name = (
        verification.account_name or integration.external_account_name
    )
    integration.granted_scopes_json = json.dumps(list(verification.scopes))
    integration.connected_at = integration.connected_at or now
    integration.last_verified_at = now
    integration.last_success_at = now
    integration.last_error_at = None
    integration.last_error_code = None
    integration.last_error_subcode = None
    integration.last_error_type = None
    integration.safe_error_message = None
    for operation in (
        "verify_integration",
        "send_message",
        "decrypt_credentials",
        "token_expiration",
    ):
        resolve_related_incidents(
            db,
            business_id=business_id,
            integration_id=integration.id,
            channel=INSTAGRAM_CHANNEL,
            provider=INSTAGRAM_PROVIDER,
            operation=operation,
        )
    record_audit(
        db,
        action="instagram_integration_reconnected",
        request=request,
        actor=actor,
        business_id=business_id,
        resource_type="business_channel_integration",
        resource_id=integration.id,
        metadata={
            "owner_user_id": actor.id,
            "business_id": business_id,
            "integration_id": integration.id,
            "external_account_id": mask_external_account_id(integration.external_account_id),
            "old_status": old_status,
            "new_status": "connected",
            "reason": payload.reason,
            "request_id": request.headers.get("x-request-id"),
            "timestamp": now.isoformat(),
        },
        commit=False,
    )
    db.commit()
    db.refresh(integration)
    return owner_instagram_integration_payload(db, integration)


@router.post(
    "/businesses/{business_id}/integrations/instagram/disconnect",
    response_model=InstagramIntegrationResponse,
)
def disconnect_owner_business_instagram_integration(
    business_id: int,
    payload: InstagramIntegrationDisconnectRequest,
    request: Request,
    actor: User = Depends(require_owner),
    db: Session = Depends(get_db),
):
    require_owner(actor)
    get_business_by_id_or_404(db, business_id)
    integration = get_instagram_integration(db, business_id=business_id)
    if integration is None:
        raise HTTPException(status_code=404, detail="Instagram integration not found")
    integration = lock_instagram_integration(db, integration)
    old_status = integration.integration_status
    now = utc_now()
    integration.integration_status = "disconnected"
    integration.provider_status = "manually_disconnected"
    integration.disconnected_at = now
    record_audit(
        db,
        action="instagram_integration_disconnected",
        request=request,
        actor=actor,
        business_id=business_id,
        resource_type="business_channel_integration",
        resource_id=integration.id,
        metadata={
            "owner_user_id": actor.id,
            "business_id": business_id,
            "integration_id": integration.id,
            "external_account_id": mask_external_account_id(integration.external_account_id),
            "old_status": old_status,
            "new_status": "disconnected",
            "reason": payload.reason,
            "request_id": request.headers.get("x-request-id"),
            "timestamp": now.isoformat(),
        },
        commit=False,
    )
    db.commit()
    db.refresh(integration)
    return owner_instagram_integration_payload(db, integration)


@router.delete(
    "/businesses/{business_id}/integrations/instagram/credentials",
    response_model=InstagramIntegrationResponse,
)
def delete_owner_business_instagram_credentials(
    business_id: int,
    payload: InstagramIntegrationDisconnectRequest,
    request: Request,
    actor: User = Depends(require_owner),
    db: Session = Depends(get_db),
):
    require_owner(actor)
    get_business_by_id_or_404(db, business_id)
    integration = get_instagram_integration(db, business_id=business_id)
    if integration is None:
        raise HTTPException(status_code=404, detail="Instagram integration not found")
    integration = lock_instagram_integration(db, integration)
    old_status = integration.integration_status
    now = utc_now()
    integration.encrypted_access_token = None
    integration.encryption_key_version = None
    integration.token_type = None
    integration.token_expires_at = None
    integration.token_last_refreshed_at = None
    integration.integration_status = "disconnected"
    integration.provider_status = "credentials_deleted"
    integration.disconnected_at = now
    record_audit(
        db,
        action="instagram_credentials_deleted",
        request=request,
        actor=actor,
        business_id=business_id,
        resource_type="business_channel_integration",
        resource_id=integration.id,
        metadata={
            "owner_user_id": actor.id,
            "business_id": business_id,
            "integration_id": integration.id,
            "external_account_id": mask_external_account_id(integration.external_account_id),
            "old_status": old_status,
            "new_status": "disconnected",
            "reason": payload.reason,
            "request_id": request.headers.get("x-request-id"),
            "timestamp": now.isoformat(),
        },
        commit=False,
    )
    db.commit()
    db.refresh(integration)
    return owner_instagram_integration_payload(db, integration)


@router.get(
    "/businesses/{business_id}/automation-credits",
    response_model=AutomationCreditSummaryResponse,
)
def get_owner_business_automation_credits(
    business_id: int,
    actor: User = Depends(require_owner),
    db: Session = Depends(get_db),
):
    require_owner(actor)
    business = get_business_by_id_or_404(db, business_id)
    settings, _ = ensure_automation_configuration(db, business)
    db.commit()
    db.refresh(settings)
    return credit_summary_payload(settings)


@router.post(
    "/businesses/{business_id}/automation-credits/purchase",
    response_model=AutomationCreditSummaryResponse,
)
def purchase_owner_business_automation_credits(
    business_id: int,
    payload: AutomationCreditPurchaseRequest,
    request: Request,
    actor: User = Depends(require_owner),
    db: Session = Depends(get_db),
):
    require_owner(actor)
    business = get_business_by_id_or_404(db, business_id)
    settings, _ = ensure_automation_configuration(db, business)
    db.refresh(settings, with_for_update=True)
    existing = get_credit_transaction_by_idempotency(
        db,
        business_id=business.id,
        idempotency_key=payload.idempotency_key,
    )
    if existing is not None:
        if existing.transaction_type != "additional_credits_purchased":
            raise HTTPException(status_code=409, detail="Idempotency key already used")
        db.commit()
        return credit_summary_payload(settings, idempotent_replay=True)
    old_summary = serialize_credit_summary(settings)
    try:
        transaction = purchase_additional_credits(
            db,
            settings=settings,
            credits=payload.credits,
            payment_amount=payload.payment_amount,
            payment_method=payload.payment_method,
            reason=payload.reason,
            external_reference=payload.external_reference,
            owner_user_id=actor.id,
            idempotency_key=payload.idempotency_key,
        )
        record_audit(
            db,
            action="automation_additional_credits_purchased",
            request=request,
            actor=actor,
            business_id=business.id,
            resource_type="automation_credit_transaction",
            resource_id=transaction.id,
            metadata={
                "owner_user_id": actor.id,
                "business_id": business.id,
                "type": transaction.transaction_type,
                "delta": payload.credits,
                "old_balance": old_summary,
                "new_balance": serialize_credit_summary(settings),
                "payment_amount": payload.payment_amount,
                "payment_method": payload.payment_method,
                "external_reference": payload.external_reference,
                "reason": payload.reason,
                "idempotency_key": payload.idempotency_key,
                "request_id": request.headers.get("x-request-id"),
                "timestamp": iso_utc(utc_now()),
            },
            commit=False,
        )
        db.commit()
    except IntegrityError:
        db.rollback()
        existing = get_credit_transaction_by_idempotency(
            db,
            business_id=business.id,
            idempotency_key=payload.idempotency_key,
        )
        if existing is None or existing.transaction_type != "additional_credits_purchased":
            raise
        settings, _ = ensure_automation_configuration(db, business)
        return credit_summary_payload(settings, idempotent_replay=True)
    except ValueError as exc:
        db.rollback()
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    db.refresh(settings)
    return credit_summary_payload(settings)


@router.post(
    "/businesses/{business_id}/automation-credits/adjustment",
    response_model=AutomationCreditSummaryResponse,
)
def adjust_owner_business_automation_credits(
    business_id: int,
    payload: AutomationCreditAdjustmentRequest,
    request: Request,
    actor: User = Depends(require_owner),
    db: Session = Depends(get_db),
):
    require_owner(actor)
    business = get_business_by_id_or_404(db, business_id)
    settings, _ = ensure_automation_configuration(db, business)
    db.refresh(settings, with_for_update=True)
    existing = get_credit_transaction_by_idempotency(
        db,
        business_id=business.id,
        idempotency_key=payload.idempotency_key,
    )
    if existing is not None:
        if existing.transaction_type != "manual_adjustment":
            raise HTTPException(status_code=409, detail="Idempotency key already used")
        db.commit()
        return credit_summary_payload(settings, idempotent_replay=True)
    old_summary = serialize_credit_summary(settings)
    try:
        transaction = adjust_credit_balances(
            db,
            settings=settings,
            included_delta=payload.included_delta,
            additional_delta=payload.additional_delta,
            reason=payload.reason,
            owner_user_id=actor.id,
            idempotency_key=payload.idempotency_key,
        )
        record_audit(
            db,
            action="automation_credit_adjusted",
            request=request,
            actor=actor,
            business_id=business.id,
            resource_type="automation_credit_transaction",
            resource_id=transaction.id,
            metadata={
                "owner_user_id": actor.id,
                "business_id": business.id,
                "type": transaction.transaction_type,
                "included_delta": payload.included_delta,
                "additional_delta": payload.additional_delta,
                "old_balance": old_summary,
                "new_balance": serialize_credit_summary(settings),
                "reason": payload.reason,
                "idempotency_key": payload.idempotency_key,
                "request_id": request.headers.get("x-request-id"),
                "timestamp": iso_utc(utc_now()),
            },
            commit=False,
        )
        db.commit()
    except IntegrityError:
        db.rollback()
        existing = get_credit_transaction_by_idempotency(
            db,
            business_id=business.id,
            idempotency_key=payload.idempotency_key,
        )
        if existing is None or existing.transaction_type != "manual_adjustment":
            raise
        settings, _ = ensure_automation_configuration(db, business)
        return credit_summary_payload(settings, idempotent_replay=True)
    except ValueError as exc:
        db.rollback()
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    db.refresh(settings)
    return credit_summary_payload(settings)


@router.get(
    "/businesses/{business_id}/automation-credits/transactions",
    response_model=list[AutomationCreditTransactionResponse],
)
def list_owner_business_automation_credit_transactions(
    business_id: int,
    limit: int = Query(default=50, ge=1, le=500),
    actor: User = Depends(require_owner),
    db: Session = Depends(get_db),
):
    require_owner(actor)
    get_business_by_id_or_404(db, business_id)
    rows = (
        db.query(AutomationCreditTransaction)
        .filter(AutomationCreditTransaction.business_id == business_id)
        .order_by(
            AutomationCreditTransaction.created_at.desc(), AutomationCreditTransaction.id.desc()
        )
        .limit(limit)
        .all()
    )
    return [serialize_credit_transaction(item) for item in rows]


@router.patch("/incidents/{incident_id}")
def update_owner_incident(
    incident_id: int,
    payload: OwnerIncidentUpdate,
    request: Request,
    actor: User = Depends(require_owner),
    db: Session = Depends(get_db),
):
    incident = db.query(SystemIncident).filter(SystemIncident.id == incident_id).first()
    if incident is None:
        raise HTTPException(status_code=404, detail="Incident not found")
    now = datetime.utcnow()
    next_status = {
        "acknowledge": "acknowledged",
        "resolve": "resolved",
        "ignore": "ignored",
        "reopen": "open",
    }[payload.action]
    incident.status = next_status
    incident.updated_at = now
    incident.resolved_at = now if next_status == "resolved" else None
    db.commit()
    db.refresh(incident)
    record_audit(
        db,
        action=f"incident_{payload.action}",
        request=request,
        actor=actor,
        business_id=incident.business_id,
        resource_type="system_incident",
        resource_id=incident.id,
        metadata={"status": incident.status, "severity": incident.severity},
    )
    return {"ok": True, "incident": serialize_incident(incident)}


@router.get("/businesses/{business_slug}")
def get_owner_business(business_slug: str, db: Session = Depends(get_db)):
    business = get_business_or_404(db, business_slug)
    summary = serialize_owner_summary(db, business)
    services = (
        db.query(BusinessService)
        .filter(BusinessService.business_id == business.id)
        .order_by(BusinessService.id)
        .all()
    )
    settings = (
        db.query(AvailabilitySettings)
        .filter(AvailabilitySettings.business_id == business.id)
        .first()
    )
    return {
        **summary,
        "settings": serialize_business(business),
        "services": [serialize_service(service) for service in services],
        "availability_settings": serialize_settings(business, settings) if settings else None,
    }


@router.post("/businesses", status_code=201)
def create_owner_business(
    payload: OwnerBusinessCreate,
    request: Request,
    actor: User = Depends(require_owner),
    db: Session = Depends(get_db),
):
    slug = normalize_slug(payload.slug or payload.name)
    if db.query(Business).filter(Business.slug == slug).first():
        raise HTTPException(status_code=409, detail="Ya existe un negocio con ese slug")

    business_fields = payload.model_dump(
        exclude={"slug", "active", "services", "schedule_template"}
    )
    business = Business(
        slug=slug, status="active" if payload.active else "inactive", **business_fields
    )
    db.add(business)
    try:
        db.flush()
        weekly_schedule = SCHEDULE_TEMPLATES[payload.schedule_template]
        db.add(
            AvailabilitySettings(
                business_id=business.id,
                timezone="Europe/Madrid",
                slot_interval_minutes=15,
                buffer_between_bookings_minutes=0,
                min_notice_minutes=120,
                max_days_ahead=30,
                weekly_schedule_json=json.dumps(weekly_schedule, ensure_ascii=False),
            )
        )
        for item in payload.services:
            service_data = item.model_dump()
            db.add(
                BusinessService(
                    business_id=business.id,
                    duration_text=f"{item.duration_minutes} min",
                    **service_data,
                )
            )
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(status_code=409, detail="Slug o nombre de servicio duplicado") from exc

    db.refresh(business)
    record_audit(
        db,
        action="business_created",
        request=request,
        actor=actor,
        business_id=business.id,
        resource_type="business",
        resource_id=business.id,
    )
    return {"ok": True, "business": serialize_owner_summary(db, business)}


@router.patch("/businesses/{business_slug}")
def update_owner_business(
    business_slug: str,
    payload: OwnerBusinessUpdate,
    request: Request,
    actor: User = Depends(require_owner),
    db: Session = Depends(get_db),
):
    business = get_business_or_404(db, business_slug)
    updates = payload.model_dump(exclude_unset=True)
    active = updates.pop("active", None)
    if updates.get("theme_key"):
        updates = resolve_branding(updates)
    for field, value in updates.items():
        setattr(business, field, value.strip() or None if isinstance(value, str) else value)
    if active is not None:
        business.status = "active" if active else "inactive"
    db.commit()
    db.refresh(business)
    action = (
        "business_enabled"
        if active is True
        else "business_disabled"
        if active is False
        else "settings_changed"
    )
    record_audit(
        db,
        action=action,
        request=request,
        actor=actor,
        business_id=business.id,
        resource_type="business",
        resource_id=business.id,
    )
    return {"ok": True, "business": serialize_owner_summary(db, business)}


@router.get("/businesses/{business_slug}/users")
def list_business_users(business_slug: str, db: Session = Depends(get_db)):
    business = get_business_or_404(db, business_slug)
    items = (
        db.query(BusinessUser)
        .filter(BusinessUser.business_id == business.id)
        .order_by(BusinessUser.id)
        .all()
    )
    return {
        "business_slug": business.slug,
        "users": [serialize_business_user(item) for item in items],
    }


@router.post("/businesses/{business_slug}/users", status_code=201)
def add_business_user(
    business_slug: str,
    payload: OwnerBusinessUserCreate,
    request: Request,
    actor: User = Depends(require_owner),
    db: Session = Depends(get_db),
):
    business = get_business_or_404(db, business_slug)
    user = db.query(User).filter(User.email == payload.email).first()
    if user is None:
        user = User(email=payload.email, email_verified=False, is_active=True)
        db.add(user)
        db.flush()
    membership = (
        db.query(BusinessUser)
        .filter(
            BusinessUser.business_id == business.id,
            BusinessUser.user_id == user.id,
        )
        .first()
    )
    if membership and membership.active:
        raise HTTPException(status_code=409, detail="El usuario ya está asignado a este negocio")
    if membership is None:
        membership = BusinessUser(
            business_id=business.id,
            user_id=user.id,
            role=payload.role,
            active=True,
            public_name=payload.public_name,
            bookable=payload.bookable,
            show_schedule=payload.show_schedule,
            bio=payload.bio,
        )
        db.add(membership)
    else:
        membership.role = payload.role
        membership.active = True
        membership.removed_at = None
        membership.public_name = payload.public_name
        membership.bookable = payload.bookable
        membership.show_schedule = payload.show_schedule
        membership.bio = payload.bio
    db.commit()
    db.refresh(membership)
    record_audit(
        db,
        action="user_assigned_to_business",
        request=request,
        actor=actor,
        business_id=business.id,
        resource_type="business_user",
        resource_id=membership.id,
        metadata={"role": membership.role},
    )
    return {"ok": True, "business_user": serialize_business_user(membership)}


@router.patch("/businesses/{business_slug}/users/{business_user_id}")
def update_business_user(
    business_slug: str,
    business_user_id: int,
    payload: OwnerBusinessUserUpdate,
    request: Request,
    actor: User = Depends(require_owner),
    db: Session = Depends(get_db),
):
    business = get_business_or_404(db, business_slug)
    item = (
        db.query(BusinessUser)
        .filter(BusinessUser.id == business_user_id, BusinessUser.business_id == business.id)
        .first()
    )
    if item is None:
        raise HTTPException(status_code=404, detail="Business user not found")
    updates = payload.model_dump(exclude_unset=True)
    for field, value in updates.items():
        setattr(item, field, value)
    if updates.get("active") is True:
        item.removed_at = None
    db.commit()
    db.refresh(item)
    action = "user_deactivated" if updates.get("active") is False else "user_role_changed"
    record_audit(
        db,
        action=action,
        request=request,
        actor=actor,
        business_id=business.id,
        resource_type="business_user",
        resource_id=item.id,
        metadata={"role": item.role, "active": item.active},
    )
    return {"ok": True, "business_user": serialize_business_user(item)}


@router.delete("/businesses/{business_slug}/users/{business_user_id}")
def deactivate_business_user(
    business_slug: str,
    business_user_id: int,
    request: Request,
    actor: User = Depends(require_owner),
    db: Session = Depends(get_db),
):
    business = get_business_or_404(db, business_slug)
    item = (
        db.query(BusinessUser)
        .filter(BusinessUser.id == business_user_id, BusinessUser.business_id == business.id)
        .first()
    )
    if item is None:
        raise HTTPException(status_code=404, detail="Business user not found")
    item.active = False
    db.commit()
    record_audit(
        db,
        action="user_deactivated",
        request=request,
        actor=actor,
        business_id=business.id,
        resource_type="business_user",
        resource_id=item.id,
    )
    return {"ok": True}


QUEUE_INCIDENT_CATEGORIES = {
    "webhook_processing_failed",
    "webhook_dead_letter",
    "instagram_unmapped_account",
    "outbox_send_failed",
    "outbox_dead_letter",
    "worker_stalled_job",
    "worker_database_locked",
    "integration_unavailable",
    "provider_rate_limited",
    "database_unavailable",
    "deadlock_detected",
    "lock_timeout",
    "pool_timeout",
    "serialization_failure",
    "database_statement_timeout",
}

DATABASE_INCIDENT_CATEGORIES = {
    "connection_timeout",
    "deadlock_detected",
    "lock_timeout",
    "pool_timeout",
    "serialization_failure",
    "database_statement_timeout",
    "database_unavailable",
    "worker_database_locked",
}


def _status_counts(
    db: Session, model: type[WebhookInboxEvent] | type[ChannelOutboxMessage]
) -> dict[str, int]:
    return {
        status: count
        for status, count in db.query(model.status, func.count(model.id))
        .group_by(model.status)
        .all()
    }


def _safe_queue_job(job_type: str, row: WebhookInboxEvent | ChannelOutboxMessage) -> dict:
    return {
        "job_type": job_type,
        "id": row.id,
        "business_id": row.business_id,
        "integration_id": row.integration_id,
        "status": row.status,
        "attempt_count": row.attempt_count,
        "max_attempts": row.max_attempts,
        "last_error_code": row.last_error_code,
        "created_at": row.created_at.isoformat(),
        "next_retry_at": row.next_retry_at.isoformat() if row.next_retry_at else None,
    }


def _safe_worker(row: WorkerHeartbeat, *, stale_after_seconds: int) -> dict:
    return {
        "worker": f"worker-{row.id}",
        "worker_type": row.worker_type,
        "status": row.status,
        "stale": heartbeat_is_stale(row, stale_after_seconds=stale_after_seconds),
        "current_job_type": row.current_job_type,
        "current_job_id": row.current_job_id,
        "last_heartbeat": row.last_seen_at.isoformat(),
        "started_at": row.started_at.isoformat(),
        "version": row.version,
    }


@router.get("/system/queue-status")
def get_queue_status(db: Session = Depends(get_db)):
    settings = get_settings()
    heartbeats = (
        db.query(WorkerHeartbeat).order_by(WorkerHeartbeat.last_seen_at.desc()).limit(100).all()
    )
    heartbeat = heartbeats[0] if heartbeats else None
    safe_workers = [
        _safe_worker(row, stale_after_seconds=settings.worker_stale_after_seconds)
        for row in heartbeats
    ]
    active_worker_count = sum(not item["stale"] for item in safe_workers)
    stale_worker_count = sum(item["stale"] for item in safe_workers)
    inbox_counts = _status_counts(db, WebhookInboxEvent)
    outbox_counts = _status_counts(db, ChannelOutboxMessage)
    oldest_values = [
        db.query(func.min(WebhookInboxEvent.available_at))
        .filter(WebhookInboxEvent.status.in_({"pending", "retry"}))
        .scalar(),
        db.query(func.min(ChannelOutboxMessage.available_at))
        .filter(ChannelOutboxMessage.status.in_({"pending", "retry"}))
        .scalar(),
    ]
    oldest = min((value for value in oldest_values if value is not None), default=None)
    last_success_values = [
        db.query(func.max(WebhookInboxEvent.processed_at))
        .filter(WebhookInboxEvent.status == "processed")
        .scalar(),
        db.query(func.max(ChannelOutboxMessage.sent_at))
        .filter(ChannelOutboxMessage.status == "sent")
        .scalar(),
    ]
    last_success = max((value for value in last_success_values if value is not None), default=None)
    incidents = (
        db.query(SystemIncident)
        .filter(SystemIncident.category.in_(QUEUE_INCIDENT_CATEGORIES))
        .order_by(SystemIncident.last_occurred_at.desc())
        .limit(10)
        .all()
    )
    database_incident_counts = {
        category: count
        for category, count in db.query(SystemIncident.category, func.count(SystemIncident.id))
        .filter(SystemIncident.category.in_(DATABASE_INCIDENT_CATEGORIES))
        .group_by(SystemIncident.category)
        .all()
    }
    jobs: list[dict] = []
    for row in (
        db.query(WebhookInboxEvent)
        .filter(WebhookInboxEvent.status.in_({"retry", "failed", "dead_letter"}))
        .order_by(WebhookInboxEvent.updated_at.desc())
        .limit(20)
    ):
        jobs.append(_safe_queue_job("inbox", row))
    for row in (
        db.query(ChannelOutboxMessage)
        .filter(ChannelOutboxMessage.status.in_({"retry", "blocked", "failed", "dead_letter"}))
        .order_by(ChannelOutboxMessage.updated_at.desc())
        .limit(20)
    ):
        jobs.append(_safe_queue_job("outbox", row))
    return {
        "worker_active": not heartbeat_is_stale(
            heartbeat, stale_after_seconds=settings.worker_stale_after_seconds
        ),
        "last_heartbeat": heartbeat.last_seen_at.isoformat() if heartbeat else None,
        "worker_status": heartbeat.status if heartbeat else "unavailable",
        "active_worker_count": active_worker_count,
        "stale_worker_count": stale_worker_count,
        "workers": safe_workers,
        "database": {
            **safe_database_pool_status(db.get_bind()),
            "recent_incident_counts": database_incident_counts,
        },
        "pending_inbox": inbox_counts.get("pending", 0),
        "retry_inbox": inbox_counts.get("retry", 0),
        "dead_letter_inbox": inbox_counts.get("dead_letter", 0),
        "pending_outbox": outbox_counts.get("pending", 0),
        "retry_outbox": outbox_counts.get("retry", 0),
        "blocked_outbox": outbox_counts.get("blocked", 0),
        "dead_letter_outbox": outbox_counts.get("dead_letter", 0),
        "oldest_pending_at": oldest.isoformat() if oldest else None,
        "last_successful_processing_at": last_success.isoformat() if last_success else None,
        "incidents": [serialize_incident(row) for row in incidents],
        "jobs": sorted(jobs, key=lambda item: item["created_at"], reverse=True)[:30],
    }


def _owner_queue_action(
    db: Session,
    *,
    model: type[WebhookInboxEvent] | type[ChannelOutboxMessage],
    job_type: str,
    job_id: int,
    action: str,
    reason: str,
    request: Request,
    actor: User,
) -> dict:
    row = db.get(model, job_id)
    if row is None:
        raise HTTPException(status_code=404, detail="Queue job not found")
    allowed = (
        {"failed", "dead_letter", "blocked"}
        if action == "retry"
        else {"pending", "retry", "failed", "dead_letter", "blocked"}
    )
    if row.status not in allowed:
        raise HTTPException(status_code=409, detail="Invalid queue job transition")
    previous_status = row.status
    now = datetime.utcnow()
    row.status = "pending" if action == "retry" else "cancelled"
    row.available_at = now
    row.next_retry_at = None
    row.locked_by = None
    row.lock_expires_at = None
    row.failed_at = now if action == "cancel" else None
    row.updated_at = now
    if isinstance(row, ChannelOutboxMessage) and row.conversation_message_id:
        message = db.get(ConversationMessage, row.conversation_message_id)
        if message is not None:
            message.delivery_status = "queued" if action == "retry" else "cancelled"
    record_audit(
        db,
        action=f"queue_{job_type}_{action}",
        request=request,
        actor=actor,
        business_id=row.business_id,
        resource_type=f"{job_type}_queue_job",
        resource_id=row.id,
        metadata={"reason": reason, "previous_status": previous_status, "new_status": row.status},
        commit=False,
    )
    db.commit()
    return {"ok": True, "job": _safe_queue_job(job_type, row)}


@router.post("/queue/inbox/{job_id}/retry")
def retry_inbox_job(
    job_id: int,
    payload: QueueJobActionRequest,
    request: Request,
    actor: User = Depends(require_owner),
    db: Session = Depends(get_db),
):
    return _owner_queue_action(
        db,
        model=WebhookInboxEvent,
        job_type="inbox",
        job_id=job_id,
        action="retry",
        reason=payload.reason,
        request=request,
        actor=actor,
    )


@router.post("/queue/inbox/{job_id}/cancel")
def cancel_inbox_job(
    job_id: int,
    payload: QueueJobActionRequest,
    request: Request,
    actor: User = Depends(require_owner),
    db: Session = Depends(get_db),
):
    return _owner_queue_action(
        db,
        model=WebhookInboxEvent,
        job_type="inbox",
        job_id=job_id,
        action="cancel",
        reason=payload.reason,
        request=request,
        actor=actor,
    )


@router.post("/queue/outbox/{job_id}/retry")
def retry_outbox_job(
    job_id: int,
    payload: QueueJobActionRequest,
    request: Request,
    actor: User = Depends(require_owner),
    db: Session = Depends(get_db),
):
    return _owner_queue_action(
        db,
        model=ChannelOutboxMessage,
        job_type="outbox",
        job_id=job_id,
        action="retry",
        reason=payload.reason,
        request=request,
        actor=actor,
    )


@router.post("/queue/outbox/{job_id}/cancel")
def cancel_outbox_job(
    job_id: int,
    payload: QueueJobActionRequest,
    request: Request,
    actor: User = Depends(require_owner),
    db: Session = Depends(get_db),
):
    return _owner_queue_action(
        db,
        model=ChannelOutboxMessage,
        job_type="outbox",
        job_id=job_id,
        action="cancel",
        reason=payload.reason,
        request=request,
        actor=actor,
    )
