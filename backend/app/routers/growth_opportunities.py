from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.audit import record_audit
from app.core.database import get_db
from app.core.security import require_business_access
from app.models import (
    Booking,
    Business,
    BusinessService,
    Customer,
    CustomerOpportunity,
    ScheduledCustomerFollowUp,
    User,
)
from app.schemas.customer_opportunity import OpportunityStatusUpdate, ScheduledFollowUpCreate
from app.services.growth_opportunity_service import (
    GrowthOpportunityService,
    as_utc,
    manual_followup_dedupe_key,
    serialize_opportunity,
    serialize_scheduled_followup,
    utc_now,
)

router = APIRouter(
    prefix="/api/admin/businesses/{business_slug}",
    tags=["growth-opportunities"],
    dependencies=[Depends(require_business_access)],
)


def business_or_404(db: Session, business_slug: str) -> Business:
    business = db.query(Business).filter(Business.slug == business_slug).first()
    if business is None:
        raise HTTPException(status_code=404, detail="Business not found")
    return business


def opportunity_or_404(
    db: Session, *, business_id: int, opportunity_id: int
) -> CustomerOpportunity:
    row = (
        db.query(CustomerOpportunity)
        .filter(
            CustomerOpportunity.id == opportunity_id,
            CustomerOpportunity.business_id == business_id,
        )
        .first()
    )
    if row is None:
        raise HTTPException(status_code=404, detail="Opportunity not found")
    return row


@router.get("/opportunities")
def list_opportunities(
    business_slug: str,
    status: str | None = Query(default=None),
    type: str | None = Query(default=None),  # noqa: A002
    customer_id: int | None = Query(default=None),
    due_from: datetime | None = Query(default=None),
    due_to: datetime | None = Query(default=None),
    limit: int = Query(default=100, ge=1, le=250),
    db: Session = Depends(get_db),
):
    business = business_or_404(db, business_slug)
    query = db.query(CustomerOpportunity).filter(
        CustomerOpportunity.business_id == business.id
    )
    if status:
        query = query.filter(CustomerOpportunity.status == status)
    if type:
        query = query.filter(CustomerOpportunity.type == type)
    if customer_id is not None:
        query = query.filter(CustomerOpportunity.customer_id == customer_id)
    if due_from is not None:
        query = query.filter(CustomerOpportunity.due_at >= as_utc(due_from))
    if due_to is not None:
        query = query.filter(CustomerOpportunity.due_at <= as_utc(due_to))
    rows = query.order_by(
        CustomerOpportunity.due_at.desc(), CustomerOpportunity.id.desc()
    ).limit(limit).all()
    return {
        "business_slug": business.slug,
        "pending_count": db.query(CustomerOpportunity)
        .filter(
            CustomerOpportunity.business_id == business.id,
            CustomerOpportunity.status == "pending",
        )
        .count(),
        "opportunities": [serialize_opportunity(row) for row in rows],
    }


@router.get("/opportunities/{opportunity_id}")
def get_opportunity(
    business_slug: str,
    opportunity_id: int,
    db: Session = Depends(get_db),
):
    business = business_or_404(db, business_slug)
    return {
        "opportunity": serialize_opportunity(
            opportunity_or_404(
                db, business_id=business.id, opportunity_id=opportunity_id
            )
        )
    }


def transition_opportunity(
    business_slug: str,
    opportunity_id: int,
    payload: OpportunityStatusUpdate,
    request: Request,
    actor: User,
    db: Session,
):
    if payload.status not in {"actioned", "dismissed"}:
        raise HTTPException(status_code=400, detail="Unsupported opportunity transition")
    business = business_or_404(db, business_slug)
    row = opportunity_or_404(db, business_id=business.id, opportunity_id=opportunity_id)
    allowed = {
        "pending": {"actioned", "dismissed"},
        "actioned": {"dismissed"},
        "dismissed": set(),
        "resolved": set(),
        "expired": set(),
    }
    if payload.status not in allowed[row.status]:
        raise HTTPException(status_code=409, detail="Invalid opportunity state transition")
    now = utc_now()
    row.status = payload.status
    if payload.status == "actioned":
        row.actioned_at = now
    else:
        row.dismissed_at = now
    db.commit()
    db.refresh(row)
    record_audit(
        db,
        action=f"growth_opportunity_{payload.status}",
        request=request,
        actor=actor,
        business_id=business.id,
        resource_type="customer_opportunity",
        resource_id=row.id,
        metadata={"type": row.type},
    )
    return {"ok": True, "opportunity": serialize_opportunity(row)}


@router.patch("/opportunities/{opportunity_id}/status")
def update_opportunity_status(
    business_slug: str,
    opportunity_id: int,
    payload: OpportunityStatusUpdate,
    request: Request,
    actor: User = Depends(require_business_access),
    db: Session = Depends(get_db),
):
    return transition_opportunity(
        business_slug, opportunity_id, payload, request, actor, db
    )


@router.post("/opportunities/{opportunity_id}/dismiss")
def dismiss_opportunity(
    business_slug: str,
    opportunity_id: int,
    request: Request,
    actor: User = Depends(require_business_access),
    db: Session = Depends(get_db),
):
    return transition_opportunity(
        business_slug,
        opportunity_id,
        OpportunityStatusUpdate(status="dismissed"),
        request,
        actor,
        db,
    )


@router.post("/opportunities/{opportunity_id}/actioned")
def mark_opportunity_actioned(
    business_slug: str,
    opportunity_id: int,
    request: Request,
    actor: User = Depends(require_business_access),
    db: Session = Depends(get_db),
):
    return transition_opportunity(
        business_slug,
        opportunity_id,
        OpportunityStatusUpdate(status="actioned"),
        request,
        actor,
        db,
    )


def validate_followup_relations(
    db: Session, *, business_id: int, payload: ScheduledFollowUpCreate
) -> tuple[Customer, Booking | None, BusinessService | None]:
    customer = (
        db.query(Customer)
        .filter(Customer.id == payload.customer_id, Customer.business_id == business_id)
        .first()
    )
    if customer is None:
        raise HTTPException(status_code=404, detail="Customer not found")
    booking = None
    if payload.booking_id is not None:
        booking = (
            db.query(Booking)
            .filter(Booking.id == payload.booking_id, Booking.business_id == business_id)
            .first()
        )
        if booking is None or booking.customer_id != customer.id:
            raise HTTPException(status_code=400, detail="Booking does not belong to customer")
    service = None
    if payload.service_id is not None:
        service = (
            db.query(BusinessService)
            .filter(
                BusinessService.id == payload.service_id,
                BusinessService.business_id == business_id,
            )
            .first()
        )
        if service is None:
            raise HTTPException(status_code=404, detail="Service not found")
        if booking is not None and booking.service_id not in {None, service.id}:
            raise HTTPException(status_code=400, detail="Service does not match booking")
    return customer, booking, service


@router.post("/scheduled-followups", status_code=201)
def create_scheduled_followup(
    business_slug: str,
    payload: ScheduledFollowUpCreate,
    request: Request,
    actor: User = Depends(require_business_access),
    db: Session = Depends(get_db),
):
    business = business_or_404(db, business_slug)
    validate_followup_relations(db, business_id=business.id, payload=payload)
    due_at = as_utc(payload.due_at)
    assert due_at is not None
    key = manual_followup_dedupe_key(
        customer_id=payload.customer_id,
        due_at=due_at,
        booking_id=payload.booking_id,
        service_id=payload.service_id,
    )
    row = (
        db.query(ScheduledCustomerFollowUp)
        .filter(
            ScheduledCustomerFollowUp.business_id == business.id,
            ScheduledCustomerFollowUp.dedupe_key == key,
        )
        .first()
    )
    created = row is None
    if row is None:
        row = ScheduledCustomerFollowUp(
            business_id=business.id,
            customer_id=payload.customer_id,
            booking_id=payload.booking_id,
            service_id=payload.service_id,
            created_by_user_id=actor.id,
            due_at=due_at,
            note=payload.note,
            dedupe_key=key,
        )
        try:
            with db.begin_nested():
                db.add(row)
                db.flush()
        except IntegrityError:
            row = (
                db.query(ScheduledCustomerFollowUp)
                .filter(
                    ScheduledCustomerFollowUp.business_id == business.id,
                    ScheduledCustomerFollowUp.dedupe_key == key,
                )
                .one()
            )
            created = False
    if due_at <= utc_now() and row.status == "scheduled":
        GrowthOpportunityService(db).evaluate_business(business.id)
    db.commit()
    db.refresh(row)
    record_audit(
        db,
        action="scheduled_customer_followup_created" if created else "scheduled_customer_followup_reused",
        request=request,
        actor=actor,
        business_id=business.id,
        resource_type="scheduled_customer_followup",
        resource_id=row.id,
    )
    return {"ok": True, "created": created, "followup": serialize_scheduled_followup(row)}


@router.post("/scheduled-followups/{followup_id}/cancel")
def cancel_scheduled_followup(
    business_slug: str,
    followup_id: int,
    request: Request,
    actor: User = Depends(require_business_access),
    db: Session = Depends(get_db),
):
    business = business_or_404(db, business_slug)
    row = (
        db.query(ScheduledCustomerFollowUp)
        .filter(
            ScheduledCustomerFollowUp.id == followup_id,
            ScheduledCustomerFollowUp.business_id == business.id,
        )
        .first()
    )
    if row is None:
        raise HTTPException(status_code=404, detail="Scheduled follow-up not found")
    if row.status != "scheduled":
        raise HTTPException(status_code=409, detail="Scheduled follow-up is already closed")
    now = utc_now()
    row.status = "cancelled"
    row.cancelled_at = now
    if row.opportunity and row.opportunity.status in {"pending", "actioned"}:
        row.opportunity.status = "dismissed"
        row.opportunity.dismissed_at = now
    db.commit()
    db.refresh(row)
    record_audit(
        db,
        action="scheduled_customer_followup_cancelled",
        request=request,
        actor=actor,
        business_id=business.id,
        resource_type="scheduled_customer_followup",
        resource_id=row.id,
    )
    return {"ok": True, "followup": serialize_scheduled_followup(row)}
