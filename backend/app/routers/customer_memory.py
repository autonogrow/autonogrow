from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from sqlalchemy.orm import Session

from app.core.audit import record_audit
from app.core.database import get_db
from app.core.security import require_business_access
from app.models import Business, Customer, CustomerMemoryItem, User
from app.models.customer_memory import MEMORY_STATUSES
from app.schemas.customer_memory import (
    CustomerMemoryCreate,
    CustomerMemoryReplacement,
    CustomerMemoryUpdate,
)
from app.services.customer_memory_service import CustomerMemoryService, serialize_memory_item

router = APIRouter(
    prefix="/api/admin/businesses/{business_slug}",
    tags=["customer-memory"],
    dependencies=[Depends(require_business_access)],
)


def business_or_404(db: Session, business_slug: str) -> Business:
    business = db.query(Business).filter(Business.slug == business_slug).first()
    if business is None:
        raise HTTPException(status_code=404, detail="Business not found")
    return business


def customer_or_404(db: Session, *, business_id: int, customer_id: int) -> Customer:
    customer = (
        db.query(Customer)
        .filter(Customer.id == customer_id, Customer.business_id == business_id)
        .first()
    )
    if customer is None:
        raise HTTPException(status_code=404, detail="Customer not found")
    return customer


def memory_or_404(
    db: Session, *, business_id: int, memory_id: int
) -> CustomerMemoryItem:
    row = (
        db.query(CustomerMemoryItem)
        .filter(
            CustomerMemoryItem.id == memory_id,
            CustomerMemoryItem.business_id == business_id,
        )
        .first()
    )
    if row is None:
        raise HTTPException(status_code=404, detail="Customer memory not found")
    return row


def memory_error(error: ValueError) -> HTTPException:
    messages = {
        "memory_content_required": (422, "Memory content is required"),
        "memory_contains_credentials": (
            422,
            "Customer memory cannot contain passwords, credentials or technical secrets",
        ),
        "memory_contains_payment_card": (
            422,
            "Customer memory cannot contain full payment card numbers",
        ),
        "memory_expiration_must_be_future": (422, "Expiration must be in the future"),
        "memory_to_supersede_not_found": (404, "Memory to supersede not found"),
        "memory_to_supersede_not_active": (409, "Only active memory can be superseded"),
        "memory_replacement_key_mismatch": (
            409,
            "A replacement must keep the same category and structured key",
        ),
        "memory_not_active": (409, "Only active memory can be modified"),
        "memory_already_deleted": (409, "Memory is already deleted"),
    }
    status_code, detail = messages.get(str(error), (422, "Invalid customer memory"))
    return HTTPException(status_code=status_code, detail=detail)


def audit_memory(
    db: Session,
    *,
    action: str,
    request: Request,
    actor: User,
    row: CustomerMemoryItem,
    extra: dict | None = None,
) -> None:
    metadata = {
        "customer_id": row.customer_id,
        "category": row.category,
        "key": row.key,
        "source_type": row.source_type,
        "is_sensitive": row.is_sensitive,
    }
    metadata.update(extra or {})
    record_audit(
        db,
        action=action,
        request=request,
        actor=actor,
        business_id=row.business_id,
        resource_type="customer_memory_item",
        resource_id=row.id,
        metadata=metadata,
        commit=False,
    )


@router.get("/customers/{customer_id}/memory")
def list_customer_memory(
    business_slug: str,
    customer_id: int,
    status: str = Query(default="active"),
    db: Session = Depends(get_db),
):
    business = business_or_404(db, business_slug)
    customer_or_404(db, business_id=business.id, customer_id=customer_id)
    if status != "all" and status not in MEMORY_STATUSES:
        raise HTTPException(status_code=422, detail="Invalid memory status")
    rows = CustomerMemoryService(db).list_items(
        business_id=business.id,
        customer_id=customer_id,
        status=None if status == "all" else status,
    )
    serialized = [serialize_memory_item(row) for row in rows]
    db.commit()
    return {
        "business_slug": business.slug,
        "customer_id": customer_id,
        "status": status,
        "items": serialized,
    }


@router.post("/customers/{customer_id}/memory", status_code=201)
def create_customer_memory(
    business_slug: str,
    customer_id: int,
    payload: CustomerMemoryCreate,
    request: Request,
    actor: User = Depends(require_business_access),
    db: Session = Depends(get_db),
):
    business = business_or_404(db, business_slug)
    customer_or_404(db, business_id=business.id, customer_id=customer_id)
    try:
        row, superseded = CustomerMemoryService(db).create_manual(
            business_id=business.id,
            customer_id=customer_id,
            category=payload.category,
            key=payload.key,
            value=payload.value,
            created_by_user_id=actor.id,
            is_sensitive=payload.is_sensitive,
            expires_at=payload.expires_at,
            supersedes_id=payload.supersedes_id,
        )
    except ValueError as error:
        raise memory_error(error) from error
    audit_memory(
        db,
        action="customer_memory_created",
        request=request,
        actor=actor,
        row=row,
    )
    if superseded is not None:
        audit_memory(
            db,
            action="customer_memory_superseded",
            request=request,
            actor=actor,
            row=superseded,
            extra={"superseded_by_id": row.id},
        )
    db.commit()
    db.refresh(row)
    return {"ok": True, "memory": serialize_memory_item(row)}


@router.get("/customers/{customer_id}/memory-summary")
def get_customer_memory_summary(
    business_slug: str,
    customer_id: int,
    db: Session = Depends(get_db),
):
    business = business_or_404(db, business_slug)
    customer = customer_or_404(db, business_id=business.id, customer_id=customer_id)
    summary = CustomerMemoryService(db).summary(
        business_id=business.id, customer_id=customer_id
    )
    db.commit()
    return {
        "business_slug": business.slug,
        "customer": {"id": customer.id, "name": customer.name},
        **summary,
    }


@router.patch("/customer-memory/{memory_id}")
def update_customer_memory(
    business_slug: str,
    memory_id: int,
    payload: CustomerMemoryUpdate,
    request: Request,
    actor: User = Depends(require_business_access),
    db: Session = Depends(get_db),
):
    business = business_or_404(db, business_slug)
    row = memory_or_404(db, business_id=business.id, memory_id=memory_id)
    fields = payload.model_fields_set
    try:
        CustomerMemoryService(db).update_manual(
            row,
            value=payload.value,
            is_sensitive=payload.is_sensitive,
            expires_at=payload.expires_at,
            expires_at_set="expires_at" in fields,
        )
    except ValueError as error:
        raise memory_error(error) from error
    audit_memory(
        db,
        action="customer_memory_updated",
        request=request,
        actor=actor,
        row=row,
        extra={"changed_fields": sorted(fields)},
    )
    db.commit()
    db.refresh(row)
    return {"ok": True, "memory": serialize_memory_item(row)}


@router.post("/customer-memory/{memory_id}/supersede", status_code=201)
def supersede_customer_memory(
    business_slug: str,
    memory_id: int,
    payload: CustomerMemoryReplacement,
    request: Request,
    actor: User = Depends(require_business_access),
    db: Session = Depends(get_db),
):
    business = business_or_404(db, business_slug)
    previous = memory_or_404(db, business_id=business.id, memory_id=memory_id)
    try:
        row, _ = CustomerMemoryService(db).create_manual(
            business_id=business.id,
            customer_id=previous.customer_id,
            category=previous.category,
            key=previous.key,
            value=payload.value,
            created_by_user_id=actor.id,
            is_sensitive=(
                previous.is_sensitive
                if payload.is_sensitive is None
                else payload.is_sensitive
            ),
            expires_at=payload.expires_at,
            supersedes_id=previous.id,
        )
    except ValueError as error:
        raise memory_error(error) from error
    audit_memory(
        db,
        action="customer_memory_created",
        request=request,
        actor=actor,
        row=row,
        extra={"replaces_id": previous.id},
    )
    audit_memory(
        db,
        action="customer_memory_superseded",
        request=request,
        actor=actor,
        row=previous,
        extra={"superseded_by_id": row.id},
    )
    db.commit()
    db.refresh(row)
    return {"ok": True, "memory": serialize_memory_item(row)}


@router.post("/customer-memory/{memory_id}/obsolete")
def mark_customer_memory_obsolete(
    business_slug: str,
    memory_id: int,
    request: Request,
    actor: User = Depends(require_business_access),
    db: Session = Depends(get_db),
):
    business = business_or_404(db, business_slug)
    row = memory_or_404(db, business_id=business.id, memory_id=memory_id)
    try:
        CustomerMemoryService(db).mark_obsolete(row)
    except ValueError as error:
        raise memory_error(error) from error
    audit_memory(
        db,
        action="customer_memory_superseded",
        request=request,
        actor=actor,
        row=row,
    )
    db.commit()
    return {"ok": True, "memory": serialize_memory_item(row)}


@router.delete("/customer-memory/{memory_id}")
def delete_customer_memory(
    business_slug: str,
    memory_id: int,
    request: Request,
    actor: User = Depends(require_business_access),
    db: Session = Depends(get_db),
):
    business = business_or_404(db, business_slug)
    row = memory_or_404(db, business_id=business.id, memory_id=memory_id)
    try:
        CustomerMemoryService(db).soft_delete(row)
    except ValueError as error:
        raise memory_error(error) from error
    audit_memory(
        db,
        action="customer_memory_deleted",
        request=request,
        actor=actor,
        row=row,
    )
    db.commit()
    return {"ok": True}
