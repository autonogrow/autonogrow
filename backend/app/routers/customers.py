from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import or_
from sqlalchemy.orm import Session, joinedload

from app.core.database import get_db
from app.core.security import require_business_admin
from app.models import Business, Customer
from app.schemas.customer import CustomerSearchOut

router = APIRouter(
    prefix="/api/admin/businesses/{business_slug}/customers",
    tags=["customers"],
    dependencies=[Depends(require_business_admin)],
)


@router.get("", response_model=list[CustomerSearchOut])
def list_customers(
    business_slug: str,
    q: Annotated[str | None, Query(max_length=200)] = None,
    limit: Annotated[int, Query(ge=1, le=200)] = 100,
    offset: Annotated[int, Query(ge=0)] = 0,
    db: Session = Depends(get_db),
):
    business = db.query(Business).filter(Business.slug == business_slug).first()

    if business is None:
        raise HTTPException(status_code=404, detail="Business not found")

    query = (
        db.query(Customer)
        .options(joinedload(Customer.account_link))
        .filter(Customer.business_id == business.id)
    )
    if q and q.strip():
        pattern = f"%{q.strip()}%"
        query = query.filter(
            or_(
                Customer.name.ilike(pattern),
                Customer.phone.ilike(pattern),
                Customer.phone_normalized.ilike(pattern),
            )
        )
    rows = (
        query.order_by(Customer.created_at.desc())
        .offset(offset)
        .limit(limit)
        .all()
    )
    return [
        {
            "id": customer.id,
            "customer_id": customer.id,
            "name": customer.name,
            "phone": customer.phone,
            "phone_normalized": customer.phone_normalized,
            "email": customer.email,
            "status": customer.status,
            "notes": customer.notes,
            "memory_eligible": bool(customer.account_link),
        }
        for customer in rows
    ]
