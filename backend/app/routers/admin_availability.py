import json
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.core.audit import record_audit
from app.core.database import get_db
from app.core.security import require_business_admin
from app.models import AvailabilityException, AvailabilitySettings, Business, User
from app.services.availability_service import (
    DEFAULT_BUFFER_BETWEEN_BOOKINGS_MINUTES,
    DEFAULT_MAX_DAYS_AHEAD,
    DEFAULT_MIN_NOTICE_MINUTES,
    DEFAULT_SLOT_INTERVAL_MINUTES,
    DEFAULT_TIMEZONE,
    get_or_create_availability_settings,
    normalize_weekly_schedule,
    parse_windows_from_json,
    serialize_exception,
    serialize_settings,
)
from app.services.booking_service import lock_business_schedule

router = APIRouter(
    prefix="/api/admin/{business_slug}",
    tags=["admin-availability"],
    dependencies=[Depends(require_business_admin)],
)


class AvailabilitySettingsUpdate(BaseModel):
    timezone: str = Field(default=DEFAULT_TIMEZONE, max_length=80)
    slot_interval_minutes: int = Field(default=DEFAULT_SLOT_INTERVAL_MINUTES, ge=5, le=120)
    buffer_between_bookings_minutes: int = Field(
        default=DEFAULT_BUFFER_BETWEEN_BOOKINGS_MINUTES,
        ge=0,
        le=240,
    )
    min_notice_minutes: int = Field(default=DEFAULT_MIN_NOTICE_MINUTES, ge=0, le=10080)
    max_days_ahead: int = Field(default=DEFAULT_MAX_DAYS_AHEAD, ge=1, le=365)
    weekly_schedule: dict[str, list[dict[str, str]]] | None = None


class AvailabilityExceptionCreate(BaseModel):
    date: str = Field(pattern=r"^\d{4}-\d{2}-\d{2}$")
    type: str = Field(pattern=r"^(closed|custom_hours)$")
    windows: list[dict[str, str]] | None = None
    reason: str | None = Field(default=None, max_length=500)


def get_business_or_404(db: Session, business_slug: str) -> Business:
    business = db.query(Business).filter(Business.slug == business_slug).first()

    if business is None:
        raise HTTPException(status_code=404, detail="Business not found")

    return business


def serialize_settings_payload(
    business: Business,
    settings: AvailabilitySettings,
) -> dict[str, Any]:
    return serialize_settings(business, settings)


@router.get("/availability-settings")
def get_availability_settings(
    business_slug: str,
    db: Session = Depends(get_db),
):
    business = get_business_or_404(db, business_slug)
    settings = get_or_create_availability_settings(db, business)
    db.commit()
    db.refresh(settings)

    return serialize_settings_payload(business, settings)


@router.patch("/availability-settings")
def update_availability_settings(
    business_slug: str,
    payload: AvailabilitySettingsUpdate,
    request: Request,
    actor: User = Depends(require_business_admin),
    db: Session = Depends(get_db),
):
    business = lock_business_schedule(db, get_business_or_404(db, business_slug))
    settings = get_or_create_availability_settings(db, business)

    settings.timezone = payload.timezone or DEFAULT_TIMEZONE
    settings.slot_interval_minutes = payload.slot_interval_minutes
    settings.buffer_between_bookings_minutes = payload.buffer_between_bookings_minutes
    settings.min_notice_minutes = payload.min_notice_minutes
    settings.max_days_ahead = payload.max_days_ahead
    settings.weekly_schedule_json = json.dumps(
        normalize_weekly_schedule(payload.weekly_schedule),
        ensure_ascii=False,
    )

    db.commit()
    db.refresh(settings)
    record_audit(
        db,
        action="settings_changed",
        request=request,
        actor=actor,
        business_id=business.id,
        resource_type="availability_settings",
        resource_id=settings.id,
    )

    return {
        "ok": True,
        "message": "Horarios guardados correctamente",
        "settings": serialize_settings_payload(business, settings),
    }


@router.get("/availability-exceptions")
def list_availability_exceptions(
    business_slug: str,
    db: Session = Depends(get_db),
):
    business = get_business_or_404(db, business_slug)
    exceptions = (
        db.query(AvailabilityException)
        .filter(AvailabilityException.business_id == business.id)
        .order_by(AvailabilityException.date.asc(), AvailabilityException.id.asc())
        .all()
    )

    return {
        "business_slug": business.slug,
        "exceptions": [serialize_exception(exception, business) for exception in exceptions],
    }


@router.post("/availability-exceptions", status_code=201)
def create_availability_exception(
    business_slug: str,
    payload: AvailabilityExceptionCreate,
    request: Request,
    actor: User = Depends(require_business_admin),
    db: Session = Depends(get_db),
):
    business = lock_business_schedule(db, get_business_or_404(db, business_slug))

    if payload.type == "custom_hours" and not payload.windows:
        raise HTTPException(status_code=400, detail="Custom hours require windows")

    windows_json = None

    if payload.type == "custom_hours":
        windows_json = json.dumps(
            parse_windows_from_json(json.dumps(payload.windows)), ensure_ascii=False
        )

    existing = (
        db.query(AvailabilityException)
        .filter(
            AvailabilityException.business_id == business.id,
            AvailabilityException.date == payload.date,
        )
        .first()
    )

    if existing:
        existing.type = payload.type
        existing.windows_json = windows_json
        existing.reason = payload.reason
        exception = existing
    else:
        exception = AvailabilityException(
            business_id=business.id,
            date=payload.date,
            type=payload.type,
            windows_json=windows_json,
            reason=payload.reason,
        )
        db.add(exception)

    db.commit()
    db.refresh(exception)
    record_audit(
        db,
        action="settings_changed",
        request=request,
        actor=actor,
        business_id=business.id,
        resource_type="availability_exception",
        resource_id=exception.id,
    )

    return {
        "ok": True,
        "message": "Excepción guardada correctamente",
        "exception": serialize_exception(exception, business),
    }


@router.delete("/availability-exceptions/{exception_id}")
def delete_availability_exception(
    business_slug: str,
    exception_id: int,
    request: Request,
    actor: User = Depends(require_business_admin),
    db: Session = Depends(get_db),
):
    business = lock_business_schedule(db, get_business_or_404(db, business_slug))
    exception = (
        db.query(AvailabilityException)
        .filter(
            AvailabilityException.id == exception_id,
            AvailabilityException.business_id == business.id,
        )
        .first()
    )

    if exception is None:
        raise HTTPException(status_code=404, detail="Exception not found")

    db.delete(exception)
    db.commit()
    record_audit(
        db,
        action="settings_changed",
        request=request,
        actor=actor,
        business_id=business.id,
        resource_type="availability_exception",
        resource_id=exception_id,
    )

    return {
        "ok": True,
        "message": "Excepción eliminada correctamente",
    }
