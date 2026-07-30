from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.orm import Session

from app.core.audit import record_audit
from app.core.database import get_db
from app.core.security import require_owner
from app.models import Business, User
from app.schemas.business import BusinessCreate, BusinessOut

router = APIRouter(prefix="/api/businesses", tags=["businesses"])


@router.get("", response_model=list[BusinessOut])
def list_businesses(db: Session = Depends(get_db)):
    return (
        db.query(Business)
        .filter(Business.status == "active")
        .order_by(Business.id.asc())
        .all()
    )


@router.get("/{slug}", response_model=BusinessOut)
def get_business(slug: str, db: Session = Depends(get_db)):
    business = (
        db.query(Business)
        .filter(Business.slug == slug, Business.status == "active")
        .first()
    )

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

    business = Business(**payload.model_dump())
    db.add(business)
    db.commit()
    db.refresh(business)
    record_audit(db, action="business_created", request=request, actor=actor, business_id=business.id, resource_type="business", resource_id=business.id)

    return business
