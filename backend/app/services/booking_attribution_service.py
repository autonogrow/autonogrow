from __future__ import annotations

from datetime import datetime, timedelta, timezone

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.audit import record_audit
from app.models import Booking, BookingAttribution, OpportunityAction
from app.services.opportunity_action_service import (
    invalidate_actions_for_resolved_opportunity,
    sync_action_from_message,
)
from app.services.opportunity_template_service import read_attribution_token

POST_ACTION_ATTRIBUTION_WINDOW = timedelta(days=14)


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _as_utc(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def _compatible(action: OpportunityAction, booking: Booking) -> bool:
    opportunity = action.opportunity
    if (
        action.business_id != booking.business_id
        or action.customer_id != booking.customer_id
    ):
        return False
    if opportunity.type == "service_due":
        return (
            opportunity.source_service_id is not None
            and opportunity.source_service_id == booking.service_id
        )
    return True


def _eligible_sent_action(action: OpportunityAction, booking: Booking) -> bool:
    sync_action_from_message(action)
    sent_at = _as_utc(action.sent_at)
    created_at = _as_utc(booking.created_at)
    return bool(
        action.attribution is None
        and
        action.status in {"sent", "completed"}
        and sent_at is not None
        and created_at is not None
        and sent_at < created_at <= sent_at + POST_ACTION_ATTRIBUTION_WINDOW
        and _compatible(action, booking)
    )


def create_booking_attribution(
    db: Session,
    *,
    action: OpportunityAction,
    booking: Booking,
    method: str,
    actor_user_id: int | None = None,
    now: datetime | None = None,
) -> tuple[BookingAttribution, bool]:
    if method not in {"direct_link", "post_action_window", "manual"}:
        raise ValueError("invalid_attribution_method")
    if not _compatible(action, booking):
        raise ValueError("attribution_context_mismatch")
    existing = (
        db.query(BookingAttribution)
        .filter(
            (BookingAttribution.action_id == action.id)
            | (BookingAttribution.booking_id == booking.id)
        )
        .first()
    )
    if existing is not None:
        if existing.action_id != action.id or existing.booking_id != booking.id:
            raise ValueError("attribution_conflict")
        return existing, False

    current = now or utc_now()
    row = BookingAttribution(
        business_id=booking.business_id,
        opportunity_id=action.opportunity_id,
        action_id=action.id,
        booking_id=booking.id,
        method=method,
        price_amount_snapshot=booking.price_amount_snapshot,
        currency_snapshot=booking.currency_snapshot,
        attributed_at=current,
        completed_at=current if booking.status == "completed" else None,
        created_by_user_id=actor_user_id,
    )
    try:
        with db.begin_nested():
            db.add(row)
            db.flush()
    except IntegrityError:
        existing = (
            db.query(BookingAttribution)
            .filter(
                (BookingAttribution.action_id == action.id)
                | (BookingAttribution.booking_id == booking.id)
            )
            .first()
        )
        if existing is None:
            raise
        if existing.action_id != action.id or existing.booking_id != booking.id:
            raise ValueError("attribution_conflict")
        return existing, False

    action.booking_id = booking.id
    action.status = "completed"
    action.completed_at = current
    opportunity = action.opportunity
    if opportunity.status in {"pending", "actioned"}:
        opportunity.status = "resolved"
        opportunity.resolved_at = current
    invalidate_actions_for_resolved_opportunity(db, opportunity=opportunity, now=current)
    record_audit(
        db,
        action="booking_attributed",
        business_id=booking.business_id,
        resource_type="booking_attribution",
        resource_id=row.id,
        metadata={
            "opportunity_id": opportunity.id,
            "opportunity_action_id": action.id,
            "booking_id": booking.id,
            "method": method,
        },
        commit=False,
    )
    if row.completed_at is not None:
        record_audit(
            db,
            action="attributed_booking_completed",
            business_id=booking.business_id,
            resource_type="booking_attribution",
            resource_id=row.id,
            metadata={"booking_id": booking.id},
            commit=False,
        )
    return row, True


def attribute_new_booking(
    db: Session,
    *,
    booking: Booking,
    attribution_token: str | None = None,
    now: datetime | None = None,
) -> BookingAttribution | None:
    current = now or utc_now()
    if booking.attribution is not None:
        return booking.attribution
    booking_created_at = _as_utc(booking.created_at)
    if booking_created_at is None:
        return None
    if attribution_token:
        token_data = read_attribution_token(attribution_token)
        if token_data is not None:
            action_id, business_id = token_data
            action = (
                db.query(OpportunityAction)
                .filter(
                    OpportunityAction.id == action_id,
                    OpportunityAction.business_id == business_id,
                    OpportunityAction.business_id == booking.business_id,
                )
                .first()
            )
            if action is not None and _eligible_sent_action(action, booking):
                return create_booking_attribution(
                    db,
                    action=action,
                    booking=booking,
                    method="direct_link",
                    now=current,
                )[0]

    candidates = (
        db.query(OpportunityAction)
        .filter(
            OpportunityAction.business_id == booking.business_id,
            OpportunityAction.customer_id == booking.customer_id,
            OpportunityAction.action_type == "contact_customer",
            OpportunityAction.sent_at.is_not(None),
            OpportunityAction.sent_at < booking_created_at,
            OpportunityAction.sent_at
            >= booking_created_at - POST_ACTION_ATTRIBUTION_WINDOW,
        )
        .all()
    )
    eligible = [action for action in candidates if _eligible_sent_action(action, booking)]
    if len(eligible) != 1:
        return None
    return create_booking_attribution(
        db,
        action=eligible[0],
        booking=booking,
        method="post_action_window",
        now=current,
    )[0]


def sync_attributed_booking_status(
    db: Session, *, booking: Booking, now: datetime | None = None
) -> BookingAttribution | None:
    row = booking.attribution
    if row is None or booking.status != "completed" or row.completed_at is not None:
        return row
    current = now or utc_now()
    row.completed_at = current
    row.price_amount_snapshot = (
        row.price_amount_snapshot
        if row.price_amount_snapshot is not None
        else booking.price_amount_snapshot
    )
    row.currency_snapshot = row.currency_snapshot or booking.currency_snapshot
    record_audit(
        db,
        action="attributed_booking_completed",
        business_id=booking.business_id,
        resource_type="booking_attribution",
        resource_id=row.id,
        metadata={"booking_id": booking.id},
        commit=False,
    )
    return row


def serialize_attribution(row: BookingAttribution) -> dict[str, object]:
    return {
        "id": row.id,
        "business_id": row.business_id,
        "opportunity_id": row.opportunity_id,
        "action_id": row.action_id,
        "booking_id": row.booking_id,
        "method": row.method,
        "price_amount_snapshot": (
            str(row.price_amount_snapshot) if row.price_amount_snapshot is not None else None
        ),
        "currency_snapshot": row.currency_snapshot,
        "attributed_at": row.attributed_at.isoformat(),
        "completed_at": row.completed_at.isoformat() if row.completed_at else None,
    }
