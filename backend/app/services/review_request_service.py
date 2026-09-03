from datetime import datetime
from typing import Any

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.models import Booking, Business, ReviewRequest

REVIEW_REQUEST_STATUSES = frozenset({"pending", "copied", "sent", "skipped"})
REVIEW_REQUEST_TERMINAL_STATUSES = frozenset({"sent", "skipped"})
REVIEW_REQUEST_TRANSITIONS = {
    "pending": frozenset({"copied", "sent", "skipped"}),
    "copied": frozenset({"sent", "skipped"}),
    "sent": frozenset(),
    "skipped": frozenset(),
}


class ReviewRequestLifecycleError(ValueError):
    pass


def build_review_message(reviews_url: str) -> str:
    return (
        "Gracias por venir hoy.\n"
        "Si te apetece, puedes dejarnos una rese\u00f1a en Google desde aqu\u00ed:\n"
        f"{reviews_url}\n\n"
        "Nos ayuda mucho a seguir creciendo."
    )


def get_or_create_review_request(
    db: Session,
    *,
    business: Business,
    booking: Booking,
) -> ReviewRequest | None:
    customer = booking.customer
    if (
        booking.customer_id is None
        or customer is None
        or customer.business_id != business.id
        or booking.business_id != business.id
    ):
        raise ReviewRequestLifecycleError("booking_without_stable_customer")

    def find_customer_cycle() -> ReviewRequest | None:
        return (
            db.query(ReviewRequest)
            .filter(
                ReviewRequest.business_id == business.id,
                ReviewRequest.customer_id == booking.customer_id,
                ReviewRequest.is_customer_cycle_anchor.is_(True),
            )
            .order_by(ReviewRequest.created_at, ReviewRequest.id)
            .first()
        )

    existing = find_customer_cycle()

    if existing is not None:
        return existing

    reviews_url = (business.reviews_url or "").strip()

    if not reviews_url:
        return None

    review_request = ReviewRequest(
        business_id=business.id,
        booking_id=booking.id,
        customer_id=customer.id,
        is_customer_cycle_anchor=True,
        customer_name=customer.name,
        customer_phone=customer.phone,
        reviews_url=reviews_url,
        message=build_review_message(reviews_url),
        status="pending",
    )
    try:
        with db.begin_nested():
            db.add(review_request)
            db.flush()
    except IntegrityError:
        # A concurrent Booking or POST may have created the customer cycle while
        # this transaction was waiting on the unique partial index.
        existing = find_customer_cycle()
        if existing is None:
            raise
        return existing
    return review_request


def transition_review_request_status(
    review_request: ReviewRequest,
    target_status: str,
) -> ReviewRequest:
    if target_status not in REVIEW_REQUEST_STATUSES:
        raise ReviewRequestLifecycleError("invalid_review_request_status")
    if review_request.status == target_status:
        return review_request
    if target_status not in REVIEW_REQUEST_TRANSITIONS.get(review_request.status, frozenset()):
        raise ReviewRequestLifecycleError("invalid_review_request_transition")

    review_request.status = target_status
    now = datetime.utcnow()
    if target_status == "copied" and review_request.copied_at is None:
        review_request.copied_at = now
    elif target_status == "sent" and review_request.sent_at is None:
        review_request.sent_at = now
    return review_request


def serialize_review_request(review_request: ReviewRequest) -> dict[str, Any]:
    return {
        "id": review_request.id,
        "business_id": review_request.business_id,
        "booking_id": review_request.booking_id,
        "customer_id": review_request.customer_id,
        "customer_name": review_request.customer_name,
        "customer_phone": review_request.customer_phone,
        "reviews_url": review_request.reviews_url,
        "message": review_request.message,
        "status": review_request.status,
        "created_at": review_request.created_at.isoformat() if review_request.created_at else None,
        "copied_at": review_request.copied_at.isoformat() if review_request.copied_at else None,
        "sent_at": review_request.sent_at.isoformat() if review_request.sent_at else None,
    }
