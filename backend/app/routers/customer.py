from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import or_
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.security import get_current_user
from app.models import Booking, User


router = APIRouter(prefix="/api/customer", tags=["customer"])


class CustomerProfileUpdate(BaseModel):
    phone: str | None = Field(default=None, max_length=40)
    preferred_name: str | None = Field(default=None, max_length=200)

    @field_validator("phone", "preferred_name", mode="before")
    @classmethod
    def clean_optional(cls, value):
        return value.strip() or None if isinstance(value, str) else value


def serialize_profile(user: User) -> dict:
    return {
        "id": user.id,
        "email": user.email,
        "name": user.name,
        "preferred_name": user.preferred_name,
        "picture_url": user.picture_url,
        "phone": user.phone,
    }


@router.get("/profile")
def customer_profile(user: User = Depends(get_current_user)):
    return serialize_profile(user)


@router.patch("/profile")
def update_customer_profile(
    payload: CustomerProfileUpdate,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    for field, value in payload.model_dump(exclude_unset=True).items():
        setattr(user, field, value)
    db.commit()
    db.refresh(user)
    return {"ok": True, "profile": serialize_profile(user)}


@router.get("/bookings")
def customer_bookings(
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    bookings = (
        db.query(Booking)
        .filter(or_(Booking.customer_user_id == user.id, Booking.customer_email == user.email))
        .order_by(Booking.start_datetime.desc(), Booking.created_at.desc())
        .all()
    )
    return {
        "bookings": [
            {
                "id": item.id,
                "business_slug": item.business.slug,
                "business_name": item.business.name,
                "service_name": item.service_name,
                "start_datetime": item.start_datetime.isoformat() if item.start_datetime else None,
                "end_datetime": item.end_datetime.isoformat() if item.end_datetime else None,
                "status": item.status,
                "address": item.business.address,
                "maps_url": item.business.maps_url,
                "phone": item.business.phone,
                "can_manage": False,
            }
            for item in bookings
        ]
    }
