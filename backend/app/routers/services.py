from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.security import require_business_admin
from app.models import Business, BusinessService
from app.schemas.service import ServiceCreate, ServiceOut

router = APIRouter(prefix="/api/businesses/{business_slug}/services", tags=["services"])


def get_business_or_404(db: Session, business_slug: str) -> Business:
    business = (
        db.query(Business)
        .filter(Business.slug == business_slug, Business.status == "active")
        .first()
    )

    if business is None:
        raise HTTPException(status_code=404, detail="Business not found")

    return business


@router.get("", response_model=list[ServiceOut])
def list_services(business_slug: str, db: Session = Depends(get_db)):
    business = get_business_or_404(db, business_slug)

    services = (
        db.query(BusinessService)
        .filter(BusinessService.business_id == business.id, BusinessService.active == True)  # noqa: E712
        .order_by(BusinessService.id.asc())
        .all()
    )

    return [
        {
            "id": service.id,
            "business_slug": business.slug,
            "name": service.name,
            "description": service.description,
            "price_text": service.price_text,
            "duration_text": service.duration_text,
            "duration_minutes": service.duration_minutes,
            "active": service.active,
        }
        for service in services
    ]


@router.post("", response_model=ServiceOut, status_code=201, dependencies=[Depends(require_business_admin)])
def create_service(
    business_slug: str,
    payload: ServiceCreate,
    db: Session = Depends(get_db),
):
    business = get_business_or_404(db, business_slug)

    service = BusinessService(
        business_id=business.id,
        **payload.model_dump(),
    )

    db.add(service)
    db.commit()
    db.refresh(service)

    return service
