import secrets
from datetime import date, datetime, time, timedelta

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import or_, select
from sqlalchemy.orm import Session, joinedload

from app.core.audit import record_audit
from app.core.database import get_db
from app.core.security import get_current_user
from app.models import Booking, Customer, CustomerAccountLink, User
from app.services.customer_identity_service import (
    link_customer_account,
    normalize_instagram_username,
    normalize_phone,
)

router = APIRouter(prefix="/api/customer", tags=["customer"])
ACTIVE_BOOKING_STATUSES = ("requested", "pending", "confirmed")


class CustomerProfileUpdate(BaseModel):
    phone: str | None = Field(default=None, max_length=40)
    preferred_name: str | None = Field(default=None, max_length=200)
    instagram_username: str | None = Field(default=None, max_length=200)

    @field_validator("phone", "preferred_name", "instagram_username", mode="before")
    @classmethod
    def clean_optional(cls, value):
        return value.strip() or None if isinstance(value, str) else value


class BookingClaimRequest(BaseModel):
    booking_id: int = Field(gt=0)
    manage_token: str = Field(min_length=20, max_length=255)


def serialize_profile(user: User) -> dict:
    return {
        "id": user.id,
        "email": user.email,
        "email_verified": user.email_verified,
        "name": user.name,
        "preferred_name": user.preferred_name,
        "picture_url": user.picture_url,
        "phone": user.phone,
        "phone_normalized": user.phone_normalized,
        "phone_verified": user.phone_verified,
        "instagram_username": user.instagram_username,
        "instagram_verified": user.instagram_verified,
    }


def serialize_customer_booking(item: Booking) -> dict:
    return {
        "id": item.id,
        "business_slug": item.business.slug,
        "business_name": item.business.name,
        "business_logo_url": item.business.logo_url,
        "business_primary_color": item.business.primary_color,
        "service_id": item.service_id,
        "service_name": item.service_name,
        "start_datetime": item.start_datetime.isoformat() if item.start_datetime else None,
        "end_datetime": item.end_datetime.isoformat() if item.end_datetime else None,
        "status": item.status,
        "address": item.business.address,
        "maps_url": item.business.maps_url,
        "phone": item.business.phone,
        "can_manage": False,
    }


def owned_booking_filter(user: User):
    linked_customer_ids = select(CustomerAccountLink.customer_id).where(
        CustomerAccountLink.user_id == user.id
    )
    clauses = [
        Booking.customer_user_id == user.id,
        Booking.customer_id.in_(linked_customer_ids),
    ]
    if user.email_verified:
        clauses.append(Booking.customer_email == user.email)
    return or_(*clauses)


def booking_query(db: Session, user: User):
    return (
        db.query(Booking)
        .options(joinedload(Booking.business))
        .filter(owned_booking_filter(user))
    )


def resolve_range(from_date: date | None, to_date: date | None) -> tuple[date, date]:
    today = date.today()
    start = from_date or today.replace(day=1)
    end = to_date or min(start + timedelta(days=41), today + timedelta(days=62))
    if end < start or (end - start).days > 62:
        raise HTTPException(status_code=422, detail="El rango debe estar entre 0 y 62 días")
    return start, end


@router.get("/profile")
def customer_profile(user: User = Depends(get_current_user)):
    return serialize_profile(user)


@router.patch("/profile")
def update_customer_profile(
    payload: CustomerProfileUpdate,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    changes = payload.model_dump(exclude_unset=True)
    if "preferred_name" in changes:
        user.preferred_name = changes["preferred_name"]
    if "phone" in changes:
        raw_phone = changes["phone"]
        normalized = normalize_phone(raw_phone, region="ES")
        if raw_phone and normalized is None:
            raise HTTPException(status_code=422, detail="Introduce un teléfono válido")
        if normalized != user.phone_normalized:
            user.phone_verified = False
        user.phone = raw_phone
        user.phone_normalized = normalized
    if "instagram_username" in changes:
        raw_instagram = changes["instagram_username"]
        normalized_instagram = normalize_instagram_username(raw_instagram)
        if raw_instagram and normalized_instagram is None:
            raise HTTPException(status_code=422, detail="Introduce un usuario de Instagram válido")
        if normalized_instagram != user.instagram_username:
            user.instagram_verified = False
            user.instagram_provider_user_id = None
        user.instagram_username = normalized_instagram
    if {"preferred_name", "phone"} & changes.keys():
        linked_customers = (
            db.query(Customer)
            .join(CustomerAccountLink, CustomerAccountLink.customer_id == Customer.id)
            .filter(CustomerAccountLink.user_id == user.id)
            .all()
        )
        for customer in linked_customers:
            if "preferred_name" in changes:
                customer.name = user.preferred_name or user.name or customer.name
            if "phone" in changes:
                raw_collision = (
                    db.query(Customer.id)
                    .filter(
                        Customer.business_id == customer.business_id,
                        Customer.id != customer.id,
                        Customer.phone == user.phone,
                    )
                    .first()
                    if user.phone
                    else None
                )
                customer.phone = None if raw_collision else user.phone
                customer.phone_normalized = user.phone_normalized
            customer.email = user.email
            customer.updated_at = datetime.utcnow()
    db.commit()
    db.refresh(user)
    return {"ok": True, "profile": serialize_profile(user)}


@router.get("/home")
def customer_home(
    from_date: date | None = Query(default=None, alias="from"),
    to_date: date | None = Query(default=None, alias="to"),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    start, end = resolve_range(from_date, to_date)
    now = datetime.now()
    upcoming = (
        booking_query(db, user)
        .filter(
            Booking.status.in_(ACTIVE_BOOKING_STATUSES),
            Booking.start_datetime >= now,
        )
        .order_by(Booking.start_datetime.asc())
        .first()
    )
    recent = (
        booking_query(db, user)
        .filter(
            Booking.start_datetime < now,
            Booking.status == "completed",
        )
        .order_by(Booking.start_datetime.desc())
        .limit(3)
        .all()
    )
    range_start = datetime.combine(start, time.min)
    range_end = datetime.combine(end + timedelta(days=1), time.min)
    calendar_bookings = (
        booking_query(db, user)
        .filter(
            Booking.start_datetime >= range_start,
            Booking.start_datetime < range_end,
        )
        .order_by(Booking.start_datetime.asc())
        .all()
    )
    today_start = datetime.combine(date.today(), time.min)
    today_count = (
        booking_query(db, user)
        .filter(
            Booking.status.in_(ACTIVE_BOOKING_STATUSES),
            Booking.start_datetime >= today_start,
            Booking.start_datetime < today_start + timedelta(days=1),
        )
        .count()
    )
    return {
        "profile": serialize_profile(user),
        "range": {"from": start.isoformat(), "to": end.isoformat()},
        "next_booking": serialize_customer_booking(upcoming) if upcoming else None,
        "recent_services": [serialize_customer_booking(item) for item in recent],
        "bookings": [serialize_customer_booking(item) for item in calendar_bookings],
        "today_count": today_count,
    }


@router.get("/bookings")
def customer_bookings(
    from_date: date | None = Query(default=None, alias="from"),
    to_date: date | None = Query(default=None, alias="to"),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    start, end = resolve_range(from_date, to_date)
    items = (
        booking_query(db, user)
        .filter(
            Booking.start_datetime >= datetime.combine(start, time.min),
            Booking.start_datetime < datetime.combine(end + timedelta(days=1), time.min),
        )
        .order_by(Booking.start_datetime.asc())
        .all()
    )
    return {"bookings": [serialize_customer_booking(item) for item in items]}


@router.post("/claim-booking")
def claim_guest_booking(
    payload: BookingClaimRequest,
    request: Request,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    booking = (
        db.query(Booking)
        .options(joinedload(Booking.customer))
        .filter(Booking.id == payload.booking_id)
        .first()
    )
    if booking is None:
        raise HTTPException(status_code=404, detail="La reserva no está disponible")
    stored_token = booking.public_manage_token
    if not stored_token or not secrets.compare_digest(stored_token, payload.manage_token):
        raise HTTPException(status_code=404, detail="La reserva no está disponible")
    if booking.customer_user_id not in {None, user.id}:
        raise HTTPException(status_code=409, detail="La reserva ya pertenece a otra cuenta")
    try:
        link_customer_account(
            db,
            user=user,
            customer=booking.customer,
            method="explicit_booking_claim",
        )
    except ValueError as exc:
        raise HTTPException(
            status_code=409,
            detail="No podemos vincular esta reserva automáticamente. Contacta con soporte.",
        ) from exc
    booking.customer_user_id = user.id
    booking.customer_email = user.email
    if not user.phone and booking.customer.phone:
        user.phone = booking.customer.phone
        user.phone_normalized = booking.customer.phone_normalized
    db.commit()
    record_audit(
        db,
        action="customer_booking_claimed",
        request=request,
        actor=user,
        business_id=booking.business_id,
        resource_type="booking",
        resource_id=booking.id,
    )
    return {"ok": True}
