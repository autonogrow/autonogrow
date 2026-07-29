"""Owner-only business management endpoints protected by the signed session."""

import json
import re
import unicodedata
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from sqlalchemy import and_, or_
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.audit import record_audit
from app.core.security import require_owner
from app.models import (
    AvailabilitySettings,
    Booking,
    Business,
    BusinessService,
    BusinessGalleryImage,
    BusinessUser,
    User,
    MessageOutbox,
    ReviewRequest,
    SystemIncident,
)
from app.schemas.owner import (
    OwnerBusinessCreate,
    OwnerBusinessUpdate,
    OwnerBusinessUserCreate,
    OwnerBusinessUserUpdate,
    OwnerIncidentUpdate,
)
from app.schemas.branding import resolve_branding
from app.services.availability_service import serialize_settings
from app.services.incident_service import SEVERITY_ORDER, serialize_incident


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
        "pending_bookings": booking_query.filter(Booking.status.in_(PENDING_BOOKING_STATUSES)).count(),
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
        "active_services": db.query(BusinessService).filter(
            BusinessService.business_id == business.id, BusinessService.active.is_(True)
        ).count(),
        "message_outbox_pending": db.query(MessageOutbox).filter(
            MessageOutbox.business_id == business.id, MessageOutbox.status == "pending"
        ).count(),
        "review_requests_pending": db.query(ReviewRequest).filter(
            ReviewRequest.business_id == business.id, ReviewRequest.status == "pending"
        ).count(),
    }


def build_health(db: Session, business: Business, metrics: dict) -> dict:
    settings = db.query(AvailabilitySettings).filter(AvailabilitySettings.business_id == business.id).first()
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
        "has_gallery": db.query(BusinessGalleryImage).filter(BusinessGalleryImage.business_id == business.id, BusinessGalleryImage.active.is_(True)).count() > 0,
        "has_colors": bool(business.primary_color and business.secondary_color and business.accent_color and business.background_color),
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
    return {**serialize_business(business), "metrics": metrics, "health": build_health(db, business, metrics)}


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
    rows = query.order_by(
        SystemIncident.last_occurred_at.desc(), SystemIncident.id.desc()
    ).limit(limit).all()
    open_count = db.query(SystemIncident).filter(
        SystemIncident.status.in_(("open", "acknowledged"))
    ).count()
    return {
        "incidents": [serialize_incident(item) for item in rows],
        "open_count": open_count,
    }


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
    services = db.query(BusinessService).filter(BusinessService.business_id == business.id).order_by(BusinessService.id).all()
    settings = db.query(AvailabilitySettings).filter(AvailabilitySettings.business_id == business.id).first()
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

    business_fields = payload.model_dump(exclude={"slug", "active", "services", "schedule_template"})
    business = Business(slug=slug, status="active" if payload.active else "inactive", **business_fields)
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
    record_audit(db, action="business_created", request=request, actor=actor, business_id=business.id, resource_type="business", resource_id=business.id)
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
    action = "business_enabled" if active is True else "business_disabled" if active is False else "settings_changed"
    record_audit(db, action=action, request=request, actor=actor, business_id=business.id, resource_type="business", resource_id=business.id)
    return {"ok": True, "business": serialize_owner_summary(db, business)}


@router.get("/businesses/{business_slug}/users")
def list_business_users(business_slug: str, db: Session = Depends(get_db)):
    business = get_business_or_404(db, business_slug)
    items = db.query(BusinessUser).filter(BusinessUser.business_id == business.id).order_by(BusinessUser.id).all()
    return {"business_slug": business.slug, "users": [serialize_business_user(item) for item in items]}


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
    membership = db.query(BusinessUser).filter(
        BusinessUser.business_id == business.id,
        BusinessUser.user_id == user.id,
    ).first()
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
    record_audit(db, action="user_assigned_to_business", request=request, actor=actor, business_id=business.id, resource_type="business_user", resource_id=membership.id, metadata={"role": membership.role})
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
    item = db.query(BusinessUser).filter(BusinessUser.id == business_user_id, BusinessUser.business_id == business.id).first()
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
    record_audit(db, action=action, request=request, actor=actor, business_id=business.id, resource_type="business_user", resource_id=item.id, metadata={"role": item.role, "active": item.active})
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
    item = db.query(BusinessUser).filter(BusinessUser.id == business_user_id, BusinessUser.business_id == business.id).first()
    if item is None:
        raise HTTPException(status_code=404, detail="Business user not found")
    item.active = False
    db.commit()
    record_audit(db, action="user_deactivated", request=request, actor=actor, business_id=business.id, resource_type="business_user", resource_id=item.id)
    return {"ok": True}
