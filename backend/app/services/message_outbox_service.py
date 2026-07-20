import re
from datetime import date, datetime, timedelta
from typing import Any
from urllib.parse import quote
from zoneinfo import ZoneInfo

from sqlalchemy.orm import Session

from app.models import Booking, Business, MessageOutbox, ReviewRequest


MADRID_TIMEZONE = ZoneInfo("Europe/Madrid")
SPANISH_WEEKDAYS = (
    "lunes",
    "martes",
    "miércoles",
    "jueves",
    "viernes",
    "sábado",
    "domingo",
)
SPANISH_MONTHS = (
    "enero",
    "febrero",
    "marzo",
    "abril",
    "mayo",
    "junio",
    "julio",
    "agosto",
    "septiembre",
    "octubre",
    "noviembre",
    "diciembre",
)


def normalize_whatsapp_phone(phone: str | None) -> str:
    digits = re.sub(r"\D", "", phone or "")

    if digits.startswith("00"):
        digits = digits[2:]

    if not 8 <= len(digits) <= 15 or digits.startswith("0"):
        raise ValueError("invalid_whatsapp_phone")

    return digits


def build_whatsapp_url(phone: str | None, message: str) -> str:
    normalized_phone = normalize_whatsapp_phone(phone)
    return f"https://wa.me/{normalized_phone}?text={quote(message, safe='')}"


def _booking_local_date_and_time(booking: Booking) -> tuple[date | None, str | None]:
    if booking.start_datetime:
        return booking.start_datetime.date(), booking.start_datetime.strftime("%H:%M")

    target_date = None
    if booking.preferred_date:
        try:
            target_date = date.fromisoformat(booking.preferred_date)
        except ValueError:
            pass

    return target_date, booking.preferred_time


def format_whatsapp_datetime(
    booking: Booking,
    *,
    now: datetime | None = None,
) -> str:
    target_date, target_time = _booking_local_date_and_time(booking)
    if target_date is None:
        return "en la fecha indicada" + (f" a las {target_time}" if target_time else "")

    local_now = now or datetime.now(MADRID_TIMEZONE)
    if local_now.tzinfo is not None:
        local_now = local_now.astimezone(MADRID_TIMEZONE)
    today = local_now.date()
    days_until_next_monday = (7 - today.weekday()) % 7
    if days_until_next_monday == 0:
        days_until_next_monday = 7
    next_monday = today + timedelta(days=days_until_next_monday)

    if target_date == next_monday:
        natural_date = "el próximo lunes"
    else:
        natural_date = (
            f"el {SPANISH_WEEKDAYS[target_date.weekday()]} "
            f"{target_date.day} de {SPANISH_MONTHS[target_date.month - 1]}"
        )
        if target_date.year != today.year:
            natural_date += f" de {target_date.year}"

    return natural_date + (f" a las {target_time}" if target_time else "")


def create_message_if_not_exists(
    db: Session,
    *,
    business: Business,
    booking: Booking,
    message_type: str,
    message: str,
    review_request: ReviewRequest | None = None,
) -> MessageOutbox:
    existing = (
        db.query(MessageOutbox)
        .filter(
            MessageOutbox.business_id == business.id,
            MessageOutbox.booking_id == booking.id,
            MessageOutbox.message_type == message_type,
        )
        .first()
    )

    if existing is not None:
        return existing

    try:
        whatsapp_url = build_whatsapp_url(booking.customer.phone, message)
    except ValueError:
        whatsapp_url = None

    outbox_message = MessageOutbox(
        business_id=business.id,
        booking_id=booking.id,
        review_request_id=review_request.id if review_request else None,
        customer_name=booking.customer.name,
        customer_phone=booking.customer.phone,
        channel="whatsapp",
        message_type=message_type,
        message=message,
        whatsapp_url=whatsapp_url,
        status="pending",
    )
    db.add(outbox_message)
    db.flush()
    return outbox_message


def create_booking_requested_message(
    db: Session, *, business: Business, booking: Booking
) -> MessageOutbox:
    natural_datetime = format_whatsapp_datetime(booking)
    message = (
        f"Hola {booking.customer.name},\n"
        f"Hemos recibido tu solicitud de cita para {booking.service_name} "
        f"{natural_datetime}.\n"
        "Te avisaremos cuando el negocio la confirme."
    )
    return create_message_if_not_exists(
        db, business=business, booking=booking, message_type="booking_requested", message=message
    )


def create_booking_confirmed_message(
    db: Session, *, business: Business, booking: Booking
) -> MessageOutbox:
    natural_datetime = format_whatsapp_datetime(booking)
    message = (
        f"Hola {booking.customer.name},\n"
        f"Tu cita para {booking.service_name} queda confirmada para {natural_datetime}.\n"
        "Te esperamos."
    )
    return create_message_if_not_exists(
        db, business=business, booking=booking, message_type="booking_confirmed", message=message
    )


def create_booking_rejected_message(
    db: Session, *, business: Business, booking: Booking
) -> MessageOutbox:
    natural_datetime = format_whatsapp_datetime(booking)
    message = (
        f"Hola {booking.customer.name},\n"
        f"Lo sentimos, no podemos aceptar la cita para {booking.service_name} "
        f"{natural_datetime}.\n"
        "Puedes elegir otro hueco disponible desde nuestra p\u00e1gina."
    )
    return create_message_if_not_exists(
        db, business=business, booking=booking, message_type="booking_rejected", message=message
    )


def create_booking_rescheduled_message(
    db: Session, *, business: Business, booking: Booking
) -> MessageOutbox:
    natural_datetime = format_whatsapp_datetime(booking)
    message = (
        f"Hola {booking.customer.name},\n"
        f"Tu cita para {booking.service_name} ha sido reagendada para {natural_datetime}.\n"
        "Te esperamos."
    )
    return create_message_if_not_exists(
        db, business=business, booking=booking, message_type="booking_rescheduled", message=message
    )


def create_review_request_message(
    db: Session,
    *,
    business: Business,
    booking: Booking,
    review_request: ReviewRequest,
) -> MessageOutbox:
    return create_message_if_not_exists(
        db,
        business=business,
        booking=booking,
        message_type="booking_completed_review",
        message=review_request.message,
        review_request=review_request,
    )


def mark_opened(message: MessageOutbox) -> MessageOutbox:
    if not message.whatsapp_url:
        raise ValueError("invalid_whatsapp_phone")
    if message.status not in {"pending", "opened"}:
        raise ValueError("message_closed")

    message.status = "opened"
    if message.opened_at is None:
        message.opened_at = datetime.utcnow()
    return message


def mark_sent(message: MessageOutbox) -> MessageOutbox:
    message.status = "sent"
    if message.sent_at is None:
        message.sent_at = datetime.utcnow()
    return message


def mark_skipped(message: MessageOutbox) -> MessageOutbox:
    message.status = "skipped"
    if message.skipped_at is None:
        message.skipped_at = datetime.utcnow()
    return message


def serialize_message_outbox(message: MessageOutbox) -> dict[str, Any]:
    return {
        "id": message.id,
        "business_id": message.business_id,
        "booking_id": message.booking_id,
        "review_request_id": message.review_request_id,
        "customer_name": message.customer_name,
        "customer_phone": message.customer_phone,
        "channel": message.channel,
        "message_type": message.message_type,
        "message": message.message,
        "whatsapp_url": message.whatsapp_url,
        "status": message.status,
        "created_at": message.created_at.isoformat() if message.created_at else None,
        "opened_at": message.opened_at.isoformat() if message.opened_at else None,
        "sent_at": message.sent_at.isoformat() if message.sent_at else None,
        "skipped_at": message.skipped_at.isoformat() if message.skipped_at else None,
    }
