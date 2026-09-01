from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from sqlalchemy.orm import Session

from app.core.audit import record_audit
from app.core.database import get_db
from app.core.security import require_owner
from app.models import Business, User
from app.schemas.business import BusinessCreate, BusinessOut
from app.services.capability_service import configure_business_modules

router = APIRouter(prefix="/api/businesses", tags=["businesses"])


@router.get("", response_model=list[BusinessOut])
def list_businesses(
    limit: Annotated[int, Query(ge=1, le=200)] = 100,
    offset: Annotated[int, Query(ge=0)] = 0,
    db: Session = Depends(get_db),
):
    return (
        db.query(Business)
        .filter(Business.status == "active")
        .order_by(Business.id.asc())
        .offset(offset)
        .limit(limit)
        .all()
    )


@router.get("/{slug}", response_model=BusinessOut)
def get_business(slug: str, db: Session = Depends(get_db)):
    business = db.query(Business).filter(Business.slug == slug, Business.status == "active").first()

    if business is None:
        raise HTTPException(status_code=404, detail="Business not found")

    return business


@router.post("", response_model=BusinessOut, status_code=201)
def create_business(
    payload: BusinessCreate,
    request: Request,
    actor: User = Depends(require_owner),
    db: Session = Depends(get_db),
):
    existing = db.query(Business).filter(Business.slug == payload.slug).first()

    if existing:
        raise HTTPException(status_code=409, detail="Business slug already exists")

    business = Business(status="configuration_pending", **payload.model_dump())
    db.add(business)
    db.flush()
    configure_business_modules(
        db,
        business_id=business.id,
        enabled_modules=("essential", "growth", "social"),
        actor_user_id=actor.id,
    )
    db.commit()
    db.refresh(business)
    record_audit(
        db,
        action="business_created",
        request=request,
        actor=actor,
        business_id=business.id,
        resource_type="business",
        resource_id=business.id,
    )

    return business
