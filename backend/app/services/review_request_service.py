from typing import Any

from sqlalchemy.orm import Session

from app.models import Booking, Business, ReviewRequest


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
    existing = (
        db.query(ReviewRequest)
        .filter(ReviewRequest.booking_id == booking.id)
        .first()
    )

    if existing is not None:
        return existing

    reviews_url = (business.reviews_url or "").strip()

    if not reviews_url:
        return None

    review_request = ReviewRequest(
        business_id=business.id,
        booking_id=booking.id,
        customer_name=booking.customer.name,
        customer_phone=booking.customer.phone,
        reviews_url=reviews_url,
        message=build_review_message(reviews_url),
        status="pending",
    )
    db.add(review_request)
    db.flush()
    return review_request


def serialize_review_request(review_request: ReviewRequest) -> dict[str, Any]:
    return {
        "id": review_request.id,
        "business_id": review_request.business_id,
        "booking_id": review_request.booking_id,
        "customer_name": review_request.customer_name,
        "customer_phone": review_request.customer_phone,
        "reviews_url": review_request.reviews_url,
        "message": review_request.message,
        "status": review_request.status,
        "created_at": review_request.created_at.isoformat() if review_request.created_at else None,
        "copied_at": review_request.copied_at.isoformat() if review_request.copied_at else None,
        "sent_at": review_request.sent_at.isoformat() if review_request.sent_at else None,
    }
