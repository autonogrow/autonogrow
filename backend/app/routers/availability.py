from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.models import Business
from app.services.availability_service import (
    build_availability,
    build_calendar_days,
    get_available_slots,
    get_or_create_availability_settings,
    serialize_settings,
)

router = APIRouter(prefix="/api/businesses/{business_slug}", tags=["availability"])


@router.get("/availability-settings")
def public_availability_settings(
    business_slug: str,
    db: Session = Depends(get_db),
):
    business = db.query(Business).filter(
        Business.slug == business_slug,
        Business.status == "active",
    ).first()
    if business is None:
        raise HTTPException(status_code=404, detail="Business not found")
    settings = get_or_create_availability_settings(db, business)
    db.commit()
    db.refresh(settings)
    return serialize_settings(business, settings)


@router.get("/availability")
def get_availability(
    business_slug: str,
    days_ahead: int = Query(default=14, ge=1, le=60),
    db: Session = Depends(get_db),
):
    try:
        return build_availability(
            db,
            business_slug=business_slug,
            days_ahead=days_ahead,
        )
    except ValueError as exc:
        if str(exc) == "business_not_found":
            raise HTTPException(status_code=404, detail="Business not found") from exc
        raise


@router.get("/available-slots")
def list_available_slots(
    business_slug: str,
    service_id: int = Query(..., ge=1),
    date: str = Query(..., pattern=r"^\d{4}-\d{2}-\d{2}$"),
    exclude_booking_id: int | None = Query(default=None, ge=1),
    db: Session = Depends(get_db),
):
    try:
        return {
            "business_slug": business_slug,
            "service_id": service_id,
            "date": date,
            "slots": get_available_slots(
                db,
                business_slug=business_slug,
                service_id=service_id,
                date=date,
                exclude_booking_id=exclude_booking_id,
            ),
        }
    except ValueError as exc:
        if str(exc) == "business_not_found":
            raise HTTPException(status_code=404, detail="Business not found") from exc
        if str(exc) == "service_not_found":
            raise HTTPException(status_code=404, detail="Service not found") from exc
        if str(exc) == "invalid_date":
            raise HTTPException(status_code=400, detail="Invalid date") from exc
        raise


@router.get("/calendar-days")
def list_calendar_days(
    business_slug: str,
    date_from: str = Query(..., alias="from", pattern=r"^\d{4}-\d{2}-\d{2}$"),
    date_to: str = Query(..., alias="to", pattern=r"^\d{4}-\d{2}-\d{2}$"),
    service_id: int | None = Query(default=None, ge=1),
    db: Session = Depends(get_db),
):
    try:
        return {
            "business_slug": business_slug,
            "from": date_from,
            "to": date_to,
            "service_id": service_id,
            "days": build_calendar_days(
                db,
                business_slug=business_slug,
                date_from=date_from,
                date_to=date_to,
                service_id=service_id,
            ),
        }
    except ValueError as exc:
        if str(exc) == "business_not_found":
            raise HTTPException(status_code=404, detail="Business not found") from exc
        if str(exc) == "service_not_found":
            raise HTTPException(status_code=404, detail="Service not found") from exc
        if str(exc) in {"invalid_date", "invalid_date_range"}:
            raise HTTPException(status_code=400, detail="Invalid date range") from exc
        raise
