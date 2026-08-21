from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.core.audit import record_audit
from app.core.database import get_db
from app.core.security import (
    get_current_user,
    get_optional_current_user,
    require_booking_business_access,
)
from app.models import Booking, MessageOutbox, User
from app.schemas.booking import BookingRequestCreate
from app.services.booking_service import (
    create_booking_request,
    reschedule_existing_booking,
    serialize_booking,
)
from app.services.message_outbox_service import serialize_message_outbox

router = APIRouter(tags=["bookings"])


class BookingRescheduleRequest(BaseModel):
    start_datetime: str | None = None
    preferred_date: str | None = None
    preferred_day_label: str | None = None
    preferred_time: str | None = None


def map_booking_error(exc: ValueError) -> HTTPException:
    errors = {
        "business_not_found": (404, "Business not found"),
        "service_not_found": (404, "Service not found"),
        "staff_not_found": (404, "Staff member not found"),
        "no_bookable_staff": (409, "No hay profesionales disponibles para reserva online."),
        "missing_slot": (400, "Missing booking slot"),
        "invalid_start_datetime": (400, "Invalid start_datetime"),
        "slot_unavailable": (409, "Ese hueco ya no está disponible"),
        "booking_closed": (400, "Cannot reschedule closed booking"),
        "booking_without_service": (400, "Booking does not have a service"),
        "invalid_phone": (422, "El teléfono no es válido para el país del negocio"),
        "identity_conflict": (409, "No se pudo vincular la identidad de forma segura"),
    }
    status_code, detail = errors.get(str(exc), (400, str(exc)))
    return HTTPException(status_code=status_code, detail=detail)


def parse_reschedule_start(payload: BookingRescheduleRequest) -> datetime:
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


@router.post("/api/businesses/{business_slug}/booking-requests", status_code=201)
def create_booking_request_legacy(
    business_slug: str,
    payload: BookingRequestCreate,
    db: Session = Depends(get_db),
    current_user: User | None = Depends(get_optional_current_user),
):
    return create_booking_response(db, business_slug, payload, current_user)


@router.post("/api/businesses/{business_slug}/bookings", status_code=201)
def create_booking(
    business_slug: str,
    payload: BookingRequestCreate,
    db: Session = Depends(get_db),
    current_user: User | None = Depends(get_optional_current_user),
):
    return create_booking_response(db, business_slug, payload, current_user)


def create_booking_response(
    db: Session,
    business_slug: str,
    payload: BookingRequestCreate,
    current_user: User | None,
):
    try:
        booking = create_booking_request(
            db,
            business_slug=business_slug,
            payload=payload,
            current_user=current_user,
        )
    except ValueError as exc:
        if str(exc) in {
            "no_staff_available_for_service",
            "staff_not_available_for_service",
        }:
            messages = {
                "no_staff_available_for_service": (
                    "No hay profesionales disponibles para este servicio."
                ),
                "staff_not_available_for_service": (
                    "El profesional seleccionado no está disponible para este servicio."
                ),
            }
            return JSONResponse(
                status_code=409,
                content={"detail": str(exc), "message": messages[str(exc)]},
            )
        raise map_booking_error(exc) from exc

    return {
        "ok": True,
        "message": "Cita creada correctamente",
        "booking": serialize_booking(booking),
        "booking_manage_token": booking.public_manage_token,
        "linked_to_account": bool(current_user and current_user.is_active),
    }


@router.patch(
    "/api/bookings/{booking_id}/reschedule", dependencies=[Depends(require_booking_business_access)]
)
@router.post(
    "/api/bookings/{booking_id}/reschedule", dependencies=[Depends(require_booking_business_access)]
)
def reschedule_booking(
    booking_id: int,
    payload: BookingRescheduleRequest,
    request: Request,
    actor: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    booking = db.query(Booking).filter(Booking.id == booking_id).first()

    if booking is None:
        raise HTTPException(status_code=404, detail="Booking not found")

    try:
        booking = reschedule_existing_booking(
            db,
            booking=booking,
            business_slug=booking.business.slug,
            new_start_datetime=parse_reschedule_start(payload),
            preferred_day_label=payload.preferred_day_label,
        )
    except ValueError as exc:
        raise map_booking_error(exc) from exc

    record_audit(
        db,
        action="booking_rescheduled",
        request=request,
        actor=actor,
        business_id=booking.business_id,
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
