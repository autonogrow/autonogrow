from datetime import date, datetime
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel
from sqlalchemy import case
from sqlalchemy.orm import Session

from app.core.audit import record_audit
from app.core.database import get_db
from app.core.security import (
    ensure_can_manage_booking,
    get_business_membership,
    require_business_access,
    require_business_admin,
)
from app.models import (
    Booking,
    Business,
    BusinessService,
    Customer,
    MessageOutbox,
    ReviewRequest,
    SyncJob,
    User,
)
from app.routers.bookings import parse_reschedule_start
from app.schemas.branding import resolve_branding
from app.schemas.business import BusinessSettingsUpdate
from app.schemas.message_outbox import MessageOutboxStatusUpdate
from app.schemas.review_request import ReviewRequestStatusUpdate
from app.schemas.service import AdminServiceCreate, AdminServiceUpdate
from app.services.booking_attribution_service import sync_attributed_booking_status
from app.services.booking_service import (
    list_bookings_for_business,
    reschedule_existing_booking,
    serialize_booking,
)
from app.services.growth_opportunity_service import (
    GrowthOpportunityService,
    snapshot_booking_follow_up,
)
from app.services.message_outbox_service import (
    create_booking_confirmed_message,
    create_booking_rejected_message,
    create_review_request_message,
    mark_opened,
    mark_sent,
    mark_skipped,
    normalize_whatsapp_phone,
    serialize_message_outbox,
)
from app.services.review_request_service import (
    get_or_create_review_request,
    serialize_review_request,
)

router = APIRouter(
    prefix="/api/admin/businesses/{business_slug}",
    tags=["admin"],
    dependencies=[Depends(require_business_access)],
)


class BookingStatusUpdate(BaseModel):
    status: str


class BookingRescheduleUpdate(BaseModel):
    preferred_date: str | None = None
    preferred_day_label: str | None = None
    preferred_time: str | None = None
    start_datetime: str | None = None


class BookingInternalNotesUpdate(BaseModel):
    internal_notes: str | None = None


def serialize_business_settings(business: Business) -> dict:
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
    }


@router.patch("/bookings/{booking_id}/internal-notes")
def update_booking_internal_notes(
    business_slug: str,
    booking_id: int,
    payload: BookingInternalNotesUpdate,
    request: Request,
    actor: User = Depends(require_business_access),
    db: Session = Depends(get_db),
):
    business = get_admin_business_or_404(db, business_slug)
    booking = (
        db.query(Booking)
        .filter(Booking.id == booking_id, Booking.business_id == business.id)
        .first()
    )
    if booking is None:
        raise HTTPException(status_code=404, detail="Booking not found")
    ensure_can_manage_booking(db, business_slug=business_slug, booking=booking, user=actor)
    notes = payload.internal_notes.strip() if payload.internal_notes else None
    if notes and len(notes) > 4000:
        raise HTTPException(status_code=422, detail="Internal notes are too long")
    booking.internal_notes = notes
    db.commit()
    db.refresh(booking)
    record_audit(
        db,
        action="booking_internal_notes_changed",
        request=request,
        actor=actor,
        business_id=business.id,
        resource_type="booking",
        resource_id=booking.id,
    )
    return {"ok": True, "booking": serialize_booking(booking)}


def serialize_admin_service(service: BusinessService) -> dict:
    return {
        "id": service.id,
        "business_id": service.business_id,
        "name": service.name,
        "description": service.description,
        "price_text": service.price_text,
        "duration_text": service.duration_text,
        "duration_minutes": service.duration_minutes,
        "active": service.active,
        "follow_up_enabled": service.follow_up_enabled,
        "follow_up_interval_days": service.follow_up_interval_days,
        "follow_up_window_days": service.follow_up_window_days,
    }


def get_admin_business_or_404(db: Session, business_slug: str) -> Business:
    business = db.query(Business).filter(Business.slug == business_slug).first()
    if business is None:
        raise HTTPException(status_code=404, detail="Business not found")
    return business


@router.get("/settings", dependencies=[Depends(require_business_admin)])
def get_business_settings(business_slug: str, db: Session = Depends(get_db)):
    return serialize_business_settings(get_admin_business_or_404(db, business_slug))


@router.patch("/settings")
def update_business_settings(
    business_slug: str,
    payload: BusinessSettingsUpdate,
    request: Request,
    actor: User = Depends(require_business_admin),
    db: Session = Depends(get_db),
):
    business = get_admin_business_or_404(db, business_slug)
    if payload.phone:
        try:
            normalize_whatsapp_phone(payload.phone)
        except ValueError as exc:
            raise HTTPException(
                status_code=400,
                detail="El tel\u00e9fono no tiene un formato internacional v\u00e1lido para WhatsApp.",
            ) from exc

    updates = payload.model_dump(exclude={"active"}, exclude_unset=True)
    if updates.get("theme_key"):
        updates = resolve_branding(updates)
    for field, value in updates.items():
        setattr(business, field, value)
    db.commit()
    db.refresh(business)
    record_audit(
        db,
        action="settings_changed",
        request=request,
        actor=actor,
        business_id=business.id,
        resource_type="business",
        resource_id=business.id,
    )
    return {"ok": True, "settings": serialize_business_settings(business)}


@router.get("/services", dependencies=[Depends(require_business_admin)])
def admin_list_services(business_slug: str, db: Session = Depends(get_db)):
    business = get_admin_business_or_404(db, business_slug)
    services = (
        db.query(BusinessService)
        .filter(BusinessService.business_id == business.id)
        .order_by(BusinessService.id.asc())
        .all()
    )
    return {
        "business_slug": business.slug,
        "services": [serialize_admin_service(item) for item in services],
    }


@router.post("/services", status_code=201, dependencies=[Depends(require_business_admin)])
def admin_create_service(
    business_slug: str,
    payload: AdminServiceCreate,
    db: Session = Depends(get_db),
):
    business = get_admin_business_or_404(db, business_slug)
    duplicate = (
        db.query(BusinessService)
        .filter(
            BusinessService.business_id == business.id,
            BusinessService.name == payload.name,
        )
        .first()
    )
    if duplicate:
        raise HTTPException(status_code=409, detail="Ya existe un servicio con ese nombre")

    service = BusinessService(
        business_id=business.id,
        name=payload.name,
        description=payload.description,
        price_text=payload.price_text,
        duration_minutes=payload.duration_minutes,
        duration_text=f"{payload.duration_minutes} min",
        active=payload.active,
        follow_up_enabled=payload.follow_up_enabled,
        follow_up_interval_days=payload.follow_up_interval_days,
        follow_up_window_days=payload.follow_up_window_days,
    )
    db.add(service)
    db.commit()
    db.refresh(service)
    return {"ok": True, "service": serialize_admin_service(service)}


@router.patch("/services/{service_id}", dependencies=[Depends(require_business_admin)])
def admin_update_service(
    business_slug: str,
    service_id: int,
    payload: AdminServiceUpdate,
    db: Session = Depends(get_db),
):
    business = get_admin_business_or_404(db, business_slug)
    service = (
        db.query(BusinessService)
        .filter(
            BusinessService.id == service_id,
            BusinessService.business_id == business.id,
        )
        .first()
    )
    if service is None:
        raise HTTPException(status_code=404, detail="Service not found")

    if payload.name is not None:
        duplicate = (
            db.query(BusinessService)
            .filter(
                BusinessService.business_id == business.id,
                BusinessService.name == payload.name,
                BusinessService.id != service.id,
            )
            .first()
        )
        if duplicate:
            raise HTTPException(status_code=409, detail="Ya existe un servicio con ese nombre")

    updates = payload.model_dump(exclude_unset=True)
    required_fields = {"name", "duration_minutes", "active"}
    if any(field in updates and updates[field] is None for field in required_fields):
        raise HTTPException(status_code=400, detail="Name, duration and active cannot be null")

    effective_follow_up_enabled = updates.get("follow_up_enabled", service.follow_up_enabled)
    effective_follow_up_interval = updates.get(
        "follow_up_interval_days", service.follow_up_interval_days
    )
    effective_follow_up_window = updates.get("follow_up_window_days", service.follow_up_window_days)
    if effective_follow_up_enabled and effective_follow_up_interval is None:
        raise HTTPException(
            status_code=422,
            detail="Follow-up interval is required when follow-up is enabled",
        )
    if effective_follow_up_window is None:
        raise HTTPException(status_code=422, detail="Follow-up window cannot be null")

    for field, value in updates.items():
        setattr(service, field, value)
    if payload.duration_minutes is not None:
        service.duration_text = f"{payload.duration_minutes} min"

    db.commit()
    db.refresh(service)
    return {"ok": True, "service": serialize_admin_service(service)}


@router.get("/bookings")
def admin_list_bookings(
    business_slug: str,
    from_date: date | None = Query(default=None, alias="from"),
    to_date: date | None = Query(default=None, alias="to"),
    actor: User = Depends(require_business_access),
    db: Session = Depends(get_db),
):
    from_date = from_date if isinstance(from_date, date) else None
    to_date = to_date if isinstance(to_date, date) else None
    if from_date and to_date and (to_date <= from_date or (to_date - from_date).days > 62):
        raise HTTPException(status_code=422, detail="Booking range must span between 1 and 62 days")
    membership = (
        None
        if actor.is_owner
        else get_business_membership(db, business_slug=business_slug, user_id=actor.id)
    )
    staff_id = membership.id if membership and membership.role == "business_staff" else None
    try:
        bookings = list_bookings_for_business(
            db,
            business_slug=business_slug,
            staff_business_user_id=staff_id,
            from_date=from_date,
            to_date=to_date,
        )
    except ValueError as exc:
        if str(exc) == "business_not_found":
            raise HTTPException(status_code=404, detail="Business not found") from exc
        raise
    business = db.query(Business).filter(Business.slug == business_slug).first()

    return {
        "business_slug": business_slug,
        "business_timezone": business.timezone if business else None,
        "bookings": bookings,
    }


@router.get("/panel")
def admin_panel(
    business_slug: str,
    actor: User = Depends(require_business_access),
    db: Session = Depends(get_db),
):
    business = db.query(Business).filter(Business.slug == business_slug).first()

    if business is None:
        raise HTTPException(status_code=404, detail="Business not found")

    membership = (
        None
        if actor.is_owner
        else get_business_membership(db, business_slug=business_slug, user_id=actor.id)
    )
    is_staff = bool(membership and membership.role == "business_staff")
    booking_query = db.query(Booking).filter(Booking.business_id == business.id)
    if is_staff:
        booking_query = booking_query.filter(Booking.staff_business_user_id == membership.id)
    total_bookings = booking_query.count()

    pending_bookings = booking_query.filter(
        Booking.status.in_(["requested", "pending"]),
    ).count()

    upcoming_bookings = booking_query.filter(
        Booking.status.in_(["requested", "pending", "confirmed"]),
        Booking.start_datetime >= datetime.utcnow(),
    ).count()

    active_services = (
        db.query(BusinessService)
        .filter(
            BusinessService.business_id == business.id,
            BusinessService.active == True,  # noqa: E712
        )
        .count()
    )

    total_customers = db.query(Customer).filter(Customer.business_id == business.id).count()

    pending_sync_jobs = (
        db.query(SyncJob)
        .filter(
            SyncJob.business_id == business.id,
            SyncJob.status == "pending",
        )
        .count()
    )

    review_requests_pending = (
        db.query(ReviewRequest)
        .filter(ReviewRequest.business_id == business.id, ReviewRequest.status == "pending")
        .count()
    )
    review_requests_copied = (
        db.query(ReviewRequest)
        .filter(ReviewRequest.business_id == business.id, ReviewRequest.status == "copied")
        .count()
    )
    review_requests_sent = (
        db.query(ReviewRequest)
        .filter(ReviewRequest.business_id == business.id, ReviewRequest.status == "sent")
        .count()
    )
    message_outbox_pending = (
        db.query(MessageOutbox)
        .filter(MessageOutbox.business_id == business.id, MessageOutbox.status == "pending")
        .count()
    )
    message_outbox_opened = (
        db.query(MessageOutbox)
        .filter(MessageOutbox.business_id == business.id, MessageOutbox.status == "opened")
        .count()
    )
    message_outbox_sent = (
        db.query(MessageOutbox)
        .filter(MessageOutbox.business_id == business.id, MessageOutbox.status == "sent")
        .count()
    )
    message_outbox_skipped = (
        db.query(MessageOutbox)
        .filter(MessageOutbox.business_id == business.id, MessageOutbox.status == "skipped")
        .count()
    )

    return {
        "business": {
            "id": business.id,
            "slug": business.slug,
            "name": business.name,
            "status": business.status,
        },
        "metrics": {
            "total_bookings": total_bookings,
            "pending_bookings": pending_bookings,
            "upcoming_bookings": upcoming_bookings,
            "active_services": 0 if is_staff else active_services,
            "total_customers": 0 if is_staff else total_customers,
            "pending_sync_jobs": 0 if is_staff else pending_sync_jobs,
            "review_requests_pending": 0 if is_staff else review_requests_pending,
            "review_requests_copied": 0 if is_staff else review_requests_copied,
            "review_requests_sent": 0 if is_staff else review_requests_sent,
            "message_outbox_pending": 0 if is_staff else message_outbox_pending,
            "message_outbox_opened": 0 if is_staff else message_outbox_opened,
            "message_outbox_sent": 0 if is_staff else message_outbox_sent,
            "message_outbox_skipped": 0 if is_staff else message_outbox_skipped,
        },
        "commands": [
            "/panel",
            "/agenda",
            "/clientes",
            "/pendientes",
            "/huecos",
        ],
        "access": {"role": membership.role if membership else "owner", "staff_scope": is_staff},
    }


@router.patch("/bookings/{booking_id}/status")
def update_booking_status(
    business_slug: str,
    booking_id: int,
    payload: BookingStatusUpdate,
    request: Request,
    actor: User = Depends(require_business_access),
    db: Session = Depends(get_db),
):
    allowed_statuses = {
        "requested",
        "pending",
        "confirmed",
        "rejected",
        "completed",
        "cancelled",
        "no_show",
    }

    if payload.status not in allowed_statuses:
        raise HTTPException(
            status_code=400,
            detail="Invalid booking status",
        )

    business = db.query(Business).filter(Business.slug == business_slug).first()

    if business is None:
        raise HTTPException(status_code=404, detail="Business not found")

    booking = (
        db.query(Booking)
        .filter(
            Booking.id == booking_id,
            Booking.business_id == business.id,
        )
        .first()
    )

    if booking is None:
        raise HTTPException(status_code=404, detail="Booking not found")

    ensure_can_manage_booking(db, business_slug=business_slug, booking=booking, user=actor)

    booking.status = payload.status
    review_request = None
    outbox_message = None

    if payload.status == "confirmed":
        outbox_message = create_booking_confirmed_message(db, business=business, booking=booking)
    elif payload.status == "rejected":
        outbox_message = create_booking_rejected_message(db, business=business, booking=booking)

    if payload.status == "completed":
        snapshot_booking_follow_up(booking, booking.service)
        sync_attributed_booking_status(db, booking=booking)
        review_request = get_or_create_review_request(
            db,
            business=business,
            booking=booking,
        )
        if review_request is not None:
            outbox_message = create_review_request_message(
                db,
                business=business,
                booking=booking,
                review_request=review_request,
            )

    growth_engine = GrowthOpportunityService(db)
    if payload.status in {"requested", "pending", "confirmed"}:
        growth_engine.resolve_for_rebooking(booking)
    else:
        growth_engine.evaluate_business(business.id)

    db.commit()
    action = {
        "confirmed": "booking_confirmed",
        "rejected": "booking_rejected",
        "cancelled": "booking_cancelled",
        "completed": "booking_completed",
    }.get(payload.status, "booking_status_changed")
    record_audit(
        db,
        action=action,
        request=request,
        actor=actor,
        business_id=business.id,
        resource_type="booking",
        resource_id=booking.id,
        metadata={"status": payload.status},
    )

    return {
        "ok": True,
        "message": "Booking status updated",
        "booking": {
            "id": booking.id,
            "business_slug": business.slug,
            "status": booking.status,
        },
        "review_request": (
            serialize_review_request(review_request) if review_request is not None else None
        ),
        "review_request_warning": (
            None
            if review_request is not None or payload.status != "completed"
            else "Este negocio todav\u00eda no tiene enlace de rese\u00f1as configurado."
        ),
        "outbox_message": (
            serialize_message_outbox(outbox_message) if outbox_message is not None else None
        ),
    }


@router.get("/message-outbox", dependencies=[Depends(require_business_admin)])
def list_message_outbox(
    business_slug: str,
    status: str | None = Query(default=None),
    message_type: str | None = Query(default=None),
    booking_id: int | None = Query(default=None),
    limit: Annotated[int, Query(ge=1, le=500)] = 200,
    offset: Annotated[int, Query(ge=0)] = 0,
    db: Session = Depends(get_db),
):
    business = db.query(Business).filter(Business.slug == business_slug).first()

    if business is None:
        raise HTTPException(status_code=404, detail="Business not found")

    query = db.query(MessageOutbox).filter(MessageOutbox.business_id == business.id)

    if status:
        query = query.filter(MessageOutbox.status == status)
    if message_type:
        query = query.filter(MessageOutbox.message_type == message_type)
    if booking_id is not None:
        query = query.filter(MessageOutbox.booking_id == booking_id)

    status_order = case(
        (MessageOutbox.status == "pending", 0),
        (MessageOutbox.status == "opened", 1),
        else_=2,
    )
    messages = (
        query.order_by(status_order, MessageOutbox.created_at.desc())
        .offset(offset)
        .limit(limit)
        .all()
    )

    return {
        "business_slug": business.slug,
        "messages": [serialize_message_outbox(message) for message in messages],
    }


def _get_outbox_message(db: Session, *, business_id: int, message_id: int) -> MessageOutbox | None:
    return (
        db.query(MessageOutbox)
        .filter(
            MessageOutbox.id == message_id,
            MessageOutbox.business_id == business_id,
        )
        .first()
    )


@router.patch("/message-outbox/{message_id}/opened", dependencies=[Depends(require_business_admin)])
def open_outbox_message(
    business_slug: str,
    message_id: int,
    db: Session = Depends(get_db),
):
    business = db.query(Business).filter(Business.slug == business_slug).first()

    if business is None:
        raise HTTPException(status_code=404, detail="Business not found")

    message = _get_outbox_message(db, business_id=business.id, message_id=message_id)

    if message is None:
        raise HTTPException(status_code=404, detail="Outbox message not found")

    try:
        mark_opened(message)
    except ValueError as exc:
        errors = {
            "invalid_whatsapp_phone": (
                400,
                "Este cliente no tiene un tel\u00e9fono v\u00e1lido para WhatsApp.",
            ),
            "message_closed": (409, "This outbox message is already closed"),
        }
        status_code, detail = errors.get(str(exc), (400, str(exc)))
        raise HTTPException(status_code=status_code, detail=detail) from exc

    db.commit()
    db.refresh(message)
    return {"ok": True, "message": serialize_message_outbox(message)}


@router.patch("/message-outbox/{message_id}/status", dependencies=[Depends(require_business_admin)])
def update_outbox_message_status(
    business_slug: str,
    message_id: int,
    payload: MessageOutboxStatusUpdate,
    db: Session = Depends(get_db),
):
    if payload.status not in {"sent", "skipped", "failed"}:
        raise HTTPException(status_code=400, detail="Invalid outbox message status")

    business = db.query(Business).filter(Business.slug == business_slug).first()

    if business is None:
        raise HTTPException(status_code=404, detail="Business not found")

    message = _get_outbox_message(db, business_id=business.id, message_id=message_id)

    if message is None:
        raise HTTPException(status_code=404, detail="Outbox message not found")

    if payload.status == "sent":
        mark_sent(message)
    elif payload.status == "skipped":
        mark_skipped(message)
    else:
        message.status = "failed"

    db.commit()
    db.refresh(message)
    return {"ok": True, "message": serialize_message_outbox(message)}


@router.get("/review-requests", dependencies=[Depends(require_business_admin)])
def list_review_requests(
    business_slug: str,
    limit: Annotated[int, Query(ge=1, le=500)] = 200,
    offset: Annotated[int, Query(ge=0)] = 0,
    db: Session = Depends(get_db),
):
    business = db.query(Business).filter(Business.slug == business_slug).first()

    if business is None:
        raise HTTPException(status_code=404, detail="Business not found")

    review_requests = (
        db.query(ReviewRequest)
        .filter(ReviewRequest.business_id == business.id)
        .order_by(ReviewRequest.created_at.desc())
        .offset(offset)
        .limit(limit)
        .all()
    )

    return {
        "business_slug": business.slug,
        "reviews_url_configured": bool((business.reviews_url or "").strip()),
        "review_requests": [serialize_review_request(item) for item in review_requests],
    }


@router.post(
    "/bookings/{booking_id}/review-request", dependencies=[Depends(require_business_admin)]
)
def create_review_request_for_booking(
    business_slug: str,
    booking_id: int,
    db: Session = Depends(get_db),
):
    business = db.query(Business).filter(Business.slug == business_slug).first()

    if business is None:
        raise HTTPException(status_code=404, detail="Business not found")

    booking = (
        db.query(Booking)
        .filter(Booking.id == booking_id, Booking.business_id == business.id)
        .first()
    )

    if booking is None:
        raise HTTPException(status_code=404, detail="Booking not found")

    if booking.status != "completed":
        raise HTTPException(status_code=400, detail="Booking must be completed")

    review_request = get_or_create_review_request(db, business=business, booking=booking)

    if review_request is None:
        raise HTTPException(
            status_code=409,
            detail="Este negocio todav\u00eda no tiene enlace de rese\u00f1as configurado.",
        )

    outbox_message = create_review_request_message(
        db,
        business=business,
        booking=booking,
        review_request=review_request,
    )
    db.commit()
    db.refresh(review_request)
    db.refresh(outbox_message)
    return {
        "ok": True,
        "review_request": serialize_review_request(review_request),
        "outbox_message": serialize_message_outbox(outbox_message),
    }


@router.patch(
    "/review-requests/{review_request_id}/status", dependencies=[Depends(require_business_admin)]
)
def update_review_request_status(
    business_slug: str,
    review_request_id: int,
    payload: ReviewRequestStatusUpdate,
    db: Session = Depends(get_db),
):
    if payload.status not in {"copied", "sent", "skipped"}:
        raise HTTPException(status_code=400, detail="Invalid review request status")

    business = db.query(Business).filter(Business.slug == business_slug).first()

    if business is None:
        raise HTTPException(status_code=404, detail="Business not found")

    review_request = (
        db.query(ReviewRequest)
        .filter(
            ReviewRequest.id == review_request_id,
            ReviewRequest.business_id == business.id,
        )
        .first()
    )

    if review_request is None:
        raise HTTPException(status_code=404, detail="Review request not found")

    review_request.status = payload.status
    now = datetime.utcnow()

    if payload.status == "copied":
        review_request.copied_at = now
    elif payload.status == "sent":
        review_request.sent_at = now

    db.commit()
    db.refresh(review_request)
    return {"ok": True, "review_request": serialize_review_request(review_request)}


@router.patch("/bookings/{booking_id}/reschedule")
def reschedule_booking(
    business_slug: str,
    booking_id: int,
    payload: BookingRescheduleUpdate,
    request: Request,
    actor: User = Depends(require_business_access),
    db: Session = Depends(get_db),
):
    business = db.query(Business).filter(Business.slug == business_slug).first()

    if business is None:
        raise HTTPException(status_code=404, detail="Business not found")

    booking = (
        db.query(Booking)
        .filter(
            Booking.id == booking_id,
            Booking.business_id == business.id,
        )
        .first()
    )

    if booking is None:
        raise HTTPException(status_code=404, detail="Booking not found")

    ensure_can_manage_booking(db, business_slug=business_slug, booking=booking, user=actor)

    try:
        booking = reschedule_existing_booking(
            db,
            booking=booking,
            business_slug=business.slug,
            new_start_datetime=parse_reschedule_start(payload),
            preferred_day_label=payload.preferred_day_label,
        )
    except ValueError as exc:
        errors = {
            "missing_slot": (400, "Missing booking slot"),
            "invalid_start_datetime": (400, "Invalid start datetime"),
            "slot_unavailable": (409, "Ese hueco ya no está disponible"),
            "booking_closed": (400, "Cannot reschedule closed booking"),
            "booking_without_service": (400, "Booking does not have a service"),
        }
        status_code, detail = errors.get(str(exc), (400, str(exc)))
        raise HTTPException(status_code=status_code, detail=detail) from exc

    record_audit(
        db,
        action="booking_rescheduled",
        request=request,
        actor=actor,
        business_id=business.id,
        resource_type="booking",
        resource_id=booking.id,
    )

    return {
        "ok": True,
        "message": "Cita reagendada correctamente",
        "booking": serialize_booking(booking),
        "outbox_message": serialize_message_outbox(
            db.query(MessageOutbox)
            .filter(
                MessageOutbox.booking_id == booking.id,
                MessageOutbox.message_type == "booking_rescheduled",
            )
            .first()
        ),
    }
