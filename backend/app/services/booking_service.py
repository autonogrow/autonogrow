import json
import secrets
from datetime import datetime, timedelta
from typing import Any

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.models import Booking, Business, BusinessService, Customer, SyncJob, User
from app.schemas.booking import BookingRequestCreate
from app.services.availability_service import get_available_slots, get_public_bookable_staff
from app.services.booking_attribution_service import attribute_new_booking
from app.services.growth_opportunity_service import (
    GrowthOpportunityService,
)
from app.services.message_outbox_service import (
    create_booking_rescheduled_message,
)


def get_business_by_slug(db: Session, slug: str) -> Business | None:
    return db.query(Business).filter(Business.slug == slug, Business.status == "active").first()


def begin_serialized_booking_write(db: Session) -> None:
    """Serialize SQLite availability-check + write to avoid concurrent double booking."""
    bind = db.get_bind()
    if bind.dialect.name == "sqlite":
        # Dependencies may already have opened a read transaction. It contains no writes.
        db.commit()
        db.execute(text("BEGIN IMMEDIATE"))


def lock_business_schedule(db: Session, business: Business) -> Business:
    """Serialize scheduling mutations per business on PostgreSQL."""

    if db.get_bind().dialect.name != "postgresql":
        return business
    return (
        db.query(Business)
        .filter(Business.id == business.id)
        .populate_existing()
        .with_for_update()
        .one()
    )


def ensure_no_booking_overlap(
    db: Session,
    *,
    business_id: int,
    staff_business_user_id: int | None,
    start_datetime: datetime,
    end_datetime: datetime,
    exclude_booking_id: int | None = None,
) -> None:
    query = db.query(Booking).filter(
        Booking.business_id == business_id,
        Booking.staff_business_user_id == staff_business_user_id,
        Booking.status.in_(("requested", "pending", "confirmed")),
        Booking.start_datetime < end_datetime,
        Booking.end_datetime > start_datetime,
    )
    if exclude_booking_id is not None:
        query = query.filter(Booking.id != exclude_booking_id)
    if db.get_bind().dialect.name == "postgresql":
        query = query.with_for_update()
    if query.first() is not None:
        raise ValueError("slot_unavailable")


def get_or_create_customer(
    db: Session,
    *,
    business_id: int,
    name: str,
    phone: str | None,
    notes: str | None,
) -> Customer:
    clean_phone = phone.strip() if phone else None

    if clean_phone:
        existing = (
            db.query(Customer)
            .filter(Customer.business_id == business_id, Customer.phone == clean_phone)
            .first()
        )

        if existing:
            existing.name = name
            if notes:
                existing.notes = notes
            existing.updated_at = datetime.utcnow()
            db.flush()
            return existing

    customer = Customer(
        business_id=business_id,
        name=name,
        phone=clean_phone,
        notes=notes,
    )

    db.add(customer)
    db.flush()

    return customer


def find_service_by_name(
    db: Session,
    *,
    business_id: int,
    service_name: str,
) -> BusinessService | None:
    return (
        db.query(BusinessService)
        .filter(
            BusinessService.business_id == business_id,
            BusinessService.name == service_name,
            BusinessService.active == True,  # noqa: E712
        )
        .first()
    )


def find_service_by_id(
    db: Session,
    *,
    business_id: int,
    service_id: int,
) -> BusinessService | None:
    return (
        db.query(BusinessService)
        .filter(
            BusinessService.business_id == business_id,
            BusinessService.id == service_id,
            BusinessService.active == True,  # noqa: E712
        )
        .first()
    )


def resolve_service(
    db: Session,
    *,
    business_id: int,
    payload: BookingRequestCreate,
) -> BusinessService | None:
    if payload.service_id is not None:
        return find_service_by_id(
            db,
            business_id=business_id,
            service_id=payload.service_id,
        )

    if payload.service_name:
        return find_service_by_name(
            db,
            business_id=business_id,
            service_name=payload.service_name,
        )

    return None


def parse_booking_start(payload: BookingRequestCreate) -> datetime:
    if payload.start_datetime:
        try:
            return datetime.fromisoformat(payload.start_datetime)
        except ValueError as exc:
            raise ValueError("invalid_start_datetime") from exc

    if payload.preferred_date and payload.preferred_time:
        try:
            return datetime.fromisoformat(f"{payload.preferred_date}T{payload.preferred_time}:00")
        except ValueError as exc:
            raise ValueError("invalid_start_datetime") from exc

    raise ValueError("missing_slot")


def ensure_slot_available(
    db: Session,
    *,
    business_slug: str,
    service_id: int,
    start_datetime: datetime,
    exclude_booking_id: int | None = None,
    staff_business_user_id: int | None = None,
    allow_nonpublic_staff: bool = False,
) -> int | None:
    slots = get_available_slots(
        db,
        business_slug=business_slug,
        service_id=service_id,
        date=start_datetime.date().isoformat(),
        exclude_booking_id=exclude_booking_id,
        staff_business_user_id=staff_business_user_id,
        allow_nonpublic_staff=allow_nonpublic_staff,
    )
    requested_start = start_datetime.replace(second=0, microsecond=0).isoformat()

    selected_slot = next((slot for slot in slots if slot["start"] == requested_start), None)
    if selected_slot is None:
        raise ValueError("slot_unavailable")

    candidate_ids = selected_slot.get("available_staff_ids") or []
    if not candidate_ids:
        return None
    if staff_business_user_id is not None:
        return staff_business_user_id

    # "Cualquiera": least blocking reservations that day, then lowest membership id.
    counts = {
        candidate_id: db.query(Booking)
        .filter(
            Booking.staff_business_user_id == candidate_id,
            Booking.preferred_date == start_datetime.date().isoformat(),
            Booking.status.in_(("requested", "pending", "confirmed")),
        )
        .count()
        for candidate_id in candidate_ids
    }
    return min(candidate_ids, key=lambda candidate_id: (counts[candidate_id], candidate_id))


def serialize_booking(booking: Booking) -> dict[str, Any]:
    staff_display_name = None
    if booking.staff_business_user:
        staff_display_name = (
            booking.staff_business_user.public_name
            or booking.staff_business_user.user.preferred_name
            or booking.staff_business_user.user.name
        )
    return {
        "id": booking.id,
        "customer_name": booking.customer.name,
        "customer_phone": booking.customer.phone,
        "service_id": booking.service_id,
        "service_name": booking.service_name,
        "staff_business_user_id": booking.staff_business_user_id,
        "staff_display_name": staff_display_name,
        "duration_minutes": booking.duration_minutes,
        "price_amount_snapshot": (
            str(booking.price_amount_snapshot)
            if booking.price_amount_snapshot is not None
            else None
        ),
        "currency_snapshot": booking.currency_snapshot,
        "start_datetime": booking.start_datetime.isoformat() if booking.start_datetime else None,
        "end_datetime": booking.end_datetime.isoformat() if booking.end_datetime else None,
        "preferred_date": booking.preferred_date,
        "preferred_day_label": booking.preferred_day_label,
        "preferred_time": booking.preferred_time,
        "notes": booking.notes,
        "internal_notes": booking.internal_notes,
        "status": booking.status,
        "google_sync_status": booking.google_sync_status,
        "created_at": booking.created_at.isoformat() if booking.created_at else None,
    }


def create_booking_request(
    db: Session,
    *,
    business_slug: str,
    payload: BookingRequestCreate,
    current_user: User | None = None,
) -> Booking:
    begin_serialized_booking_write(db)
    business = get_business_by_slug(db, business_slug)

    if business is None:
        raise ValueError("business_not_found")
    business = lock_business_schedule(db, business)

    service = resolve_service(db, business_id=business.id, payload=payload)

    if service is None:
        raise ValueError("service_not_found")

    if not get_public_bookable_staff(db, business.id, service.id):
        raise ValueError("no_staff_available_for_service")

    start_datetime = parse_booking_start(payload)
    duration_minutes = service.duration_minutes or 30
    end_datetime = start_datetime + timedelta(minutes=duration_minutes)

    selected_staff_id = ensure_slot_available(
        db,
        business_slug=business_slug,
        service_id=service.id,
        start_datetime=start_datetime,
        staff_business_user_id=payload.staff_business_user_id,
    )
    ensure_no_booking_overlap(
        db,
        business_id=business.id,
        staff_business_user_id=selected_staff_id,
        start_datetime=start_datetime,
        end_datetime=end_datetime,
    )

    customer = get_or_create_customer(
        db,
        business_id=business.id,
        name=payload.customer_name,
        phone=payload.customer_phone,
        notes=payload.notes,
    )

    booking = Booking(
        business_id=business.id,
        customer_id=customer.id,
        customer_user_id=current_user.id if current_user and current_user.is_active else None,
        customer_email=current_user.email if current_user and current_user.is_active else None,
        public_manage_token=secrets.token_urlsafe(32),
        created_by_user=bool(current_user and current_user.is_active),
        service_id=service.id,
        staff_business_user_id=selected_staff_id,
        service_name=service.name,
        duration_minutes=duration_minutes,
        price_amount_snapshot=service.price_amount,
        currency_snapshot=service.currency,
        follow_up_enabled_snapshot=service.follow_up_enabled,
        follow_up_interval_days_snapshot=(
            service.follow_up_interval_days if service.follow_up_enabled else None
        ),
        follow_up_window_days_snapshot=(
            service.follow_up_window_days if service.follow_up_enabled else 0
        ),
        start_datetime=start_datetime,
        end_datetime=end_datetime,
        preferred_date=start_datetime.date().isoformat(),
        preferred_day_label=payload.preferred_day_label,
        preferred_time=start_datetime.strftime("%H:%M"),
        notes=payload.notes,
        source=payload.source,
        status="requested",
        google_sync_status="pending",
    )

    db.add(booking)
    db.flush()
    attribute_new_booking(
        db,
        booking=booking,
        attribution_token=payload.attribution_token,
    )
    GrowthOpportunityService(db).resolve_for_rebooking(booking)

    sync_payload = {
        "booking_id": booking.id,
        "business_slug": business.slug,
        "business_name": business.name,
        "customer_name": customer.name,
        "customer_phone": customer.phone,
        "service_name": booking.service_name,
        "duration_minutes": booking.duration_minutes,
        "start_datetime": booking.start_datetime.isoformat() if booking.start_datetime else None,
        "end_datetime": booking.end_datetime.isoformat() if booking.end_datetime else None,
        "preferred_date": booking.preferred_date,
        "preferred_day_label": booking.preferred_day_label,
        "preferred_time": booking.preferred_time,
        "notes": booking.notes,
    }

    sync_job = SyncJob(
        business_id=business.id,
        booking_id=booking.id,
        provider="google_calendar",
        operation="create_event",
        status="pending",
        payload_json=json.dumps(sync_payload, ensure_ascii=False),
    )

    db.add(sync_job)
    db.commit()
    db.refresh(booking)

    return booking


def reschedule_existing_booking(
    db: Session,
    *,
    booking: Booking,
    business_slug: str,
    new_start_datetime: datetime,
    preferred_day_label: str | None = None,
) -> Booking:
    begin_serialized_booking_write(db)
    locked_business = lock_business_schedule(db, booking.business)
    if db.get_bind().dialect.name == "postgresql":
        booking = (
            db.query(Booking)
            .filter(Booking.id == booking.id)
            .populate_existing()
            .with_for_update()
            .one()
        )
    if booking.status in {"completed", "rejected", "cancelled", "no_show"}:
        raise ValueError("booking_closed")

    if booking.service_id is None:
        raise ValueError("booking_without_service")

    selected_staff_id = ensure_slot_available(
        db,
        business_slug=business_slug,
        service_id=booking.service_id,
        start_datetime=new_start_datetime,
        exclude_booking_id=booking.id,
        staff_business_user_id=booking.staff_business_user_id,
        allow_nonpublic_staff=True,
    )

    duration_minutes = booking.duration_minutes

    if duration_minutes is None and booking.service and booking.service.duration_minutes:
        duration_minutes = booking.service.duration_minutes

    if duration_minutes is None:
        duration_minutes = 30

    new_end_datetime = new_start_datetime + timedelta(minutes=duration_minutes)
    ensure_no_booking_overlap(
        db,
        business_id=locked_business.id,
        staff_business_user_id=selected_staff_id,
        start_datetime=new_start_datetime,
        end_datetime=new_end_datetime,
        exclude_booking_id=booking.id,
    )

    booking.duration_minutes = duration_minutes
    booking.start_datetime = new_start_datetime
    booking.end_datetime = new_end_datetime
    booking.staff_business_user_id = selected_staff_id
    booking.preferred_date = new_start_datetime.date().isoformat()
    booking.preferred_day_label = preferred_day_label
    booking.preferred_time = new_start_datetime.strftime("%H:%M")
    booking.status = "requested"
    booking.updated_at = datetime.utcnow()

    create_booking_rescheduled_message(
        db,
        business=booking.business,
        booking=booking,
    )

    db.commit()
    db.refresh(booking)

    return booking


def list_bookings_for_business(
    db: Session, *, business_slug: str, staff_business_user_id: int | None = None
) -> list[dict[str, Any]]:
    business = get_business_by_slug(db, business_slug)

    if business is None:
        raise ValueError("business_not_found")

    query = db.query(Booking).filter(Booking.business_id == business.id)
    if staff_business_user_id is not None:
        query = query.filter(Booking.staff_business_user_id == staff_business_user_id)
    bookings = query.order_by(Booking.created_at.desc()).all()

    return [serialize_booking(booking) for booking in bookings]
