from dataclasses import dataclass
from datetime import datetime

from fastapi import Request
from sqlalchemy.orm import Session

from app.core.audit import record_audit
from app.core.security import ensure_can_manage_booking
from app.models import Booking, Business, MessageOutbox, ReviewRequest, User
from app.services.availability_service import (
    get_booking_interval,
    get_operational_business_now,
)
from app.services.booking_attribution_service import sync_attributed_booking_status
from app.services.booking_manage_token_service import (
    TERMINAL_BOOKING_STATUSES,
    revoke_booking_manage_token,
)
from app.services.booking_service import (
    begin_serialized_booking_write,
    lock_business_schedule,
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
)
from app.services.review_request_service import (
    ReviewRequestLifecycleError,
    get_or_create_review_request,
)

BOOKING_STATUSES = {
    "requested",
    "pending",
    "confirmed",
    "rejected",
    "completed",
    "cancelled",
    "no_show",
}
BOOKING_STATUS_TRANSITIONS = {
    "requested": {"confirmed", "rejected"},
    "pending": {"confirmed", "rejected"},
    "confirmed": {"completed", "no_show", "cancelled"},
    "completed": set(),
    "no_show": set(),
    "cancelled": set(),
    "rejected": set(),
}


class BookingStatusTransitionError(ValueError):
    pass


@dataclass
class BookingStatusTransitionResult:
    booking: Booking
    changed: bool
    review_request: ReviewRequest | None = None
    outbox_message: MessageOutbox | None = None


def effective_booking_end(booking: Booking) -> datetime | None:
    interval = get_booking_interval(booking)
    return interval[1] if interval is not None else None


def is_booking_request_expired(booking: Booking, *, now: datetime) -> bool:
    ends_at = effective_booking_end(booking)
    return bool(
        booking.status in {"requested", "pending"} and ends_at is not None and ends_at < now
    )


def list_booking_close_tasks(
    db: Session,
    *,
    business: Business,
    staff_business_user_id: int | None = None,
    now: datetime | None = None,
) -> list[dict]:
    operational_now = (
        get_operational_business_now(db, business.id)
        if now is None
        else (
            get_operational_business_now(db, business.id, now=now)
            if now.tzinfo is not None
            else now
        )
    )
    query = db.query(Booking).filter(
        Booking.business_id == business.id,
        Booking.status == "confirmed",
    )
    if staff_business_user_id is not None:
        query = query.filter(Booking.staff_business_user_id == staff_business_user_id)

    tasks: list[tuple[datetime, dict]] = []
    for booking in query.all():
        ends_at = effective_booking_end(booking)
        if ends_at is None or ends_at >= operational_now:
            continue
        serialized = serialize_booking(booking, operational_now=operational_now)
        serialized["effective_end_datetime"] = ends_at.isoformat()
        tasks.append((ends_at, serialized))
    return [item for _ends_at, item in sorted(tasks, key=lambda task: (task[0], task[1]["id"]))]


def _audit_action(status: str) -> str:
    return {
        "confirmed": "booking_confirmed",
        "rejected": "booking_rejected",
        "cancelled": "booking_cancelled",
        "completed": "booking_completed",
    }.get(status, "booking_status_changed")


def transition_booking_status(
    db: Session,
    *,
    business_slug: str,
    booking_id: int,
    target_status: str,
    actor: User,
    request: Request,
    now: datetime | None = None,
) -> BookingStatusTransitionResult:
    if target_status not in BOOKING_STATUSES:
        raise BookingStatusTransitionError("invalid_status")

    begin_serialized_booking_write(db)
    try:
        business = db.query(Business).filter(Business.slug == business_slug).first()
        if business is None:
            raise BookingStatusTransitionError("business_not_found")
        business = lock_business_schedule(db, business)

        booking_query = db.query(Booking).filter(
            Booking.id == booking_id,
            Booking.business_id == business.id,
        )
        if db.get_bind().dialect.name == "postgresql":
            booking_query = booking_query.populate_existing().with_for_update()
        booking = booking_query.first()
        if booking is None:
            raise BookingStatusTransitionError("booking_not_found")

        ensure_can_manage_booking(
            db,
            business_slug=business_slug,
            booking=booking,
            user=actor,
        )
        previous_status = booking.status
        if previous_status == target_status:
            db.commit()
            return BookingStatusTransitionResult(booking=booking, changed=False)

        if target_status not in BOOKING_STATUS_TRANSITIONS.get(previous_status, set()):
            raise BookingStatusTransitionError("invalid_transition")

        operational_now = (
            get_operational_business_now(db, business.id)
            if now is None
            else (
                get_operational_business_now(db, business.id, now=now)
                if now.tzinfo is not None
                else now
            )
        )
        if target_status == "confirmed":
            if booking.staff_business_user_id is None:
                raise BookingStatusTransitionError("booking_without_staff")
            if is_booking_request_expired(booking, now=operational_now):
                raise BookingStatusTransitionError("booking_request_expired")

        booking.status = target_status
        token_revoked = target_status in TERMINAL_BOOKING_STATUSES and revoke_booking_manage_token(
            booking, now=operational_now
        )
        review_request = None
        outbox_message = None
        if target_status == "confirmed":
            outbox_message = create_booking_confirmed_message(
                db, business=business, booking=booking
            )
        elif target_status == "rejected":
            outbox_message = create_booking_rejected_message(db, business=business, booking=booking)
        elif target_status == "completed":
            snapshot_booking_follow_up(booking, booking.service)
            sync_attributed_booking_status(db, booking=booking)
            try:
                review_request = get_or_create_review_request(
                    db,
                    business=business,
                    booking=booking,
                )
            except ReviewRequestLifecycleError as exc:
                raise BookingStatusTransitionError(str(exc)) from exc
            if review_request is not None and review_request.booking_id == booking.id:
                outbox_message = create_review_request_message(
                    db,
                    business=business,
                    review_request=review_request,
                )

        growth_engine = GrowthOpportunityService(db)
        if target_status in {"requested", "pending", "confirmed"}:
            growth_engine.resolve_for_rebooking(booking)
        else:
            growth_engine.evaluate_business(business.id)

        if token_revoked:
            record_audit(
                db,
                action="manage_token_revoked",
                request=request,
                actor=actor,
                business_id=business.id,
                resource_type="booking",
                resource_id=booking.id,
                metadata={"reason": f"booking_{target_status}"},
                commit=False,
            )

        record_audit(
            db,
            action=_audit_action(target_status),
            request=request,
            actor=actor,
            business_id=business.id,
            resource_type="booking",
            resource_id=booking.id,
            metadata={"from_status": previous_status, "status": target_status},
            commit=False,
        )
        db.commit()
        db.refresh(booking)
        return BookingStatusTransitionResult(
            booking=booking,
            changed=True,
            review_request=review_request,
            outbox_message=outbox_message,
        )
    except Exception:
        db.rollback()
        raise
