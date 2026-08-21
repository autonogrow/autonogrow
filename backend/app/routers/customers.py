from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.security import require_business_admin
from app.models import Business, Customer
from app.schemas.customer import CustomerOut

router = APIRouter(
    prefix="/api/admin/businesses/{business_slug}/customers",
    tags=["customers"],
    dependencies=[Depends(require_business_admin)],
)


@router.get("", response_model=list[CustomerOut])
def list_customers(
    business_slug: str,
    limit: Annotated[int, Query(ge=1, le=200)] = 100,
    offset: Annotated[int, Query(ge=0)] = 0,
    db: Session = Depends(get_db),
):
    business = db.query(Business).filter(Business.slug == business_slug).first()

    if business is None:
        raise HTTPException(status_code=404, detail="Business not found")

    return (
        db.query(Customer)
        .filter(Customer.business_id == business.id)
        .order_by(Customer.created_at.desc())
        .offset(offset)
        .limit(limit)
        .all()
    )
