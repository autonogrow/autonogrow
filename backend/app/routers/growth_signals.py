from __future__ import annotations

from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from sqlalchemy.orm import Session

from app.core.audit import record_audit
from app.core.database import get_db
from app.core.security import require_business_access, require_business_admin
from app.models import (
    Business,
    BusinessCalendarEvent,
    BusinessGrowthSignal,
    BusinessService,
    User,
)
from app.models.business_growth_signal import (
    GROWTH_SIGNAL_SEVERITIES,
    GROWTH_SIGNAL_STATUSES,
    GROWTH_SIGNAL_TYPES,
)
from app.schemas.business_growth_signal import (
    BusinessCalendarEventCreate,
    BusinessCalendarEventUpdate,
)
from app.services.business_growth_signal_service import (
    serialize_calendar_event,
    serialize_growth_signal,
    utc_now,
)
from app.services.capability_service import require_growth_access

router = APIRouter(
    prefix="/api/admin/businesses/{business_slug}",
    tags=["growth-signals"],
    dependencies=[Depends(require_growth_access)],
)


def business_or_404(db: Session, business_slug: str) -> Business:
    row = db.query(Business).filter(Business.slug == business_slug).first()
    if row is None:
        raise HTTPException(status_code=404, detail="Business not found")
    return row


def signal_or_404(
    db: Session, *, business_id: int, signal_id: int, lock: bool = False
) -> BusinessGrowthSignal:
    query = db.query(BusinessGrowthSignal).filter(
        BusinessGrowthSignal.id == signal_id,
        BusinessGrowthSignal.business_id == business_id,
    )
    if lock and db.get_bind().dialect.name == "postgresql":
        query = query.with_for_update()
    row = query.first()
    if row is None:
        raise HTTPException(status_code=404, detail="Growth signal not found")
    return row


def event_or_404(
    db: Session, *, business_id: int, event_id: int
) -> BusinessCalendarEvent:
    row = (
        db.query(BusinessCalendarEvent)
        .filter(
            BusinessCalendarEvent.id == event_id,
            BusinessCalendarEvent.business_id == business_id,
        )
        .first()
    )
    if row is None:
        raise HTTPException(status_code=404, detail="Calendar event not found")
    return row


def service_or_422(db: Session, *, business_id: int, service_id: int | None):
    if service_id is None:
        return None
    row = (
        db.query(BusinessService)
        .filter(
            BusinessService.id == service_id,
            BusinessService.business_id == business_id,
        )
        .first()
    )
    if row is None:
        raise HTTPException(status_code=422, detail="Service does not belong to this business")
    return row


def aware(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


@router.get("/growth-signals")
def list_growth_signals(
    business_slug: str,
    status: str | None = Query(default=None),
    type: str | None = Query(default=None),  # noqa: A002
    severity: str | None = Query(default=None),
    service_id: int | None = Query(default=None),
    period_from: datetime | None = Query(default=None, alias="from"),
    period_to: datetime | None = Query(default=None, alias="to"),
    limit: int = Query(default=100, ge=1, le=250),
    db: Session = Depends(get_db),
):
    business = business_or_404(db, business_slug)
    if status is not None and status not in GROWTH_SIGNAL_STATUSES:
        raise HTTPException(status_code=422, detail="Unsupported signal status")
    if type is not None and type not in GROWTH_SIGNAL_TYPES:
        raise HTTPException(status_code=422, detail="Unsupported signal type")
    if severity is not None and severity not in GROWTH_SIGNAL_SEVERITIES:
        raise HTTPException(status_code=422, detail="Unsupported signal severity")
    if service_id is not None:
        service_or_422(db, business_id=business.id, service_id=service_id)
    query = db.query(BusinessGrowthSignal).filter(
        BusinessGrowthSignal.business_id == business.id
    )
    if status:
        query = query.filter(BusinessGrowthSignal.status == status)
    if type:
        query = query.filter(BusinessGrowthSignal.type == type)
    if severity:
        query = query.filter(BusinessGrowthSignal.severity == severity)
    if service_id is not None:
        query = query.filter(BusinessGrowthSignal.service_id == service_id)
    if period_from is not None:
        query = query.filter(BusinessGrowthSignal.period_end >= aware(period_from))
    if period_to is not None:
        query = query.filter(BusinessGrowthSignal.period_start <= aware(period_to))
    rows = (
        query.order_by(
            BusinessGrowthSignal.detected_at.desc(), BusinessGrowthSignal.id.desc()
        )
        .limit(limit)
        .all()
    )
    return {
        "business_slug": business.slug,
        "signals": [serialize_growth_signal(row) for row in rows],
    }


@router.get("/growth-signals-summary")
def growth_signals_summary(
    business_slug: str,
    db: Session = Depends(get_db),
):
    business = business_or_404(db, business_slug)
    rows = (
        db.query(BusinessGrowthSignal)
        .filter(BusinessGrowthSignal.business_id == business.id)
        .all()
    )
    active = [row for row in rows if row.status == "active"]
    return {
        "business_slug": business.slug,
        "active_count": len(active),
        "by_type": {
            signal_type: sum(1 for row in active if row.type == signal_type)
            for signal_type in GROWTH_SIGNAL_TYPES
        },
        "by_severity": {
            severity: sum(1 for row in active if row.severity == severity)
            for severity in GROWTH_SIGNAL_SEVERITIES
        },
        "last_evaluated_at": max(
            (row.last_evaluated_at for row in rows), default=None
        ),
        "data_state": "evaluated" if rows else "insufficient_history_or_not_evaluated",
    }


@router.get("/growth-calendar-events")
def list_calendar_events(
    business_slug: str,
    enabled: bool | None = Query(default=None),
    db: Session = Depends(get_db),
):
    business = business_or_404(db, business_slug)
    query = db.query(BusinessCalendarEvent).filter(
        BusinessCalendarEvent.business_id == business.id
    )
    if enabled is not None:
        query = query.filter(BusinessCalendarEvent.enabled.is_(enabled))
    rows = query.order_by(
        BusinessCalendarEvent.starts_at.asc(), BusinessCalendarEvent.id.asc()
    ).all()
    return {
        "business_slug": business.slug,
        "events": [serialize_calendar_event(row) for row in rows],
    }


@router.post(
    "/growth-calendar-events",
    status_code=201,
    dependencies=[Depends(require_business_admin)],
)
def create_calendar_event(
    business_slug: str,
    payload: BusinessCalendarEventCreate,
    request: Request,
    actor: User = Depends(require_business_admin),
    db: Session = Depends(get_db),
):
    business = business_or_404(db, business_slug)
    service_or_422(db, business_id=business.id, service_id=payload.service_id)
    row = BusinessCalendarEvent(
        business_id=business.id,
        title=payload.title,
        starts_at=aware(payload.starts_at),
        ends_at=aware(payload.ends_at),
        category=payload.category,
        service_id=payload.service_id,
        enabled=payload.enabled,
        yearly_recurrence=payload.yearly_recurrence,
        created_by_user_id=actor.id,
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    record_audit(
        db,
        action="growth_calendar_event_created",
        request=request,
        actor=actor,
        business_id=business.id,
        resource_type="business_calendar_event",
        resource_id=row.id,
        metadata={"service_id": row.service_id, "yearly_recurrence": row.yearly_recurrence},
    )
    return {"ok": True, "event": serialize_calendar_event(row)}


@router.patch(
    "/growth-calendar-events/{event_id}",
    dependencies=[Depends(require_business_admin)],
)
def update_calendar_event(
    business_slug: str,
    event_id: int,
    payload: BusinessCalendarEventUpdate,
    request: Request,
    actor: User = Depends(require_business_admin),
    db: Session = Depends(get_db),
):
    business = business_or_404(db, business_slug)
    row = event_or_404(db, business_id=business.id, event_id=event_id)
    updates = payload.model_dump(exclude_unset=True)
    if "service_id" in updates:
        service_or_422(db, business_id=business.id, service_id=updates["service_id"])
    starts_at = aware(updates.get("starts_at", row.starts_at))
    ends_at = aware(updates.get("ends_at", row.ends_at))
    if ends_at <= starts_at:
        raise HTTPException(status_code=422, detail="ends_at must be after starts_at")
    updates["starts_at"] = starts_at
    updates["ends_at"] = ends_at
    for key, value in updates.items():
        setattr(row, key, value)
    db.commit()
    db.refresh(row)
    record_audit(
        db,
        action="growth_calendar_event_updated",
        request=request,
        actor=actor,
        business_id=business.id,
        resource_type="business_calendar_event",
        resource_id=row.id,
        metadata={"fields": sorted(updates)},
    )
    return {"ok": True, "event": serialize_calendar_event(row)}


@router.delete(
    "/growth-calendar-events/{event_id}",
    dependencies=[Depends(require_business_admin)],
)
def delete_calendar_event(
    business_slug: str,
    event_id: int,
    request: Request,
    actor: User = Depends(require_business_admin),
    db: Session = Depends(get_db),
):
    business = business_or_404(db, business_slug)
    row = event_or_404(db, business_id=business.id, event_id=event_id)
    now = utc_now()
    for signal in row.signals:
        if signal.status == "active":
            signal.status = "resolved"
            signal.resolved_at = now
            signal.last_evaluated_at = now
    db.delete(row)
    db.commit()
    record_audit(
        db,
        action="growth_calendar_event_deleted",
        request=request,
        actor=actor,
        business_id=business.id,
        resource_type="business_calendar_event",
        resource_id=event_id,
    )
    return {"ok": True}


@router.get("/growth-signals/{signal_id}")
def get_growth_signal(
    business_slug: str,
    signal_id: int,
    db: Session = Depends(get_db),
):
    business = business_or_404(db, business_slug)
    return {
        "signal": serialize_growth_signal(
            signal_or_404(db, business_id=business.id, signal_id=signal_id)
        )
    }


@router.post("/growth-signals/{signal_id}/dismiss")
def dismiss_growth_signal(
    business_slug: str,
    signal_id: int,
    request: Request,
    actor: User = Depends(require_business_access),
    db: Session = Depends(get_db),
):
    business = business_or_404(db, business_slug)
    row = signal_or_404(db, business_id=business.id, signal_id=signal_id, lock=True)
    if row.status == "dismissed":
        return {"ok": True, "idempotent": True, "signal": serialize_growth_signal(row)}
    if row.status != "active":
        raise HTTPException(status_code=409, detail="Only an active signal can be dismissed")
    row.status = "dismissed"
    row.dismissed_at = utc_now()
    row.last_evaluated_at = row.dismissed_at
    db.commit()
    db.refresh(row)
    record_audit(
        db,
        action="business_growth_signal_dismissed",
        request=request,
        actor=actor,
        business_id=business.id,
        resource_type="business_growth_signal",
        resource_id=row.id,
        metadata={"type": row.type, "service_id": row.service_id},
    )
    return {"ok": True, "idempotent": False, "signal": serialize_growth_signal(row)}
