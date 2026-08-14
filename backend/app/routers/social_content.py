from __future__ import annotations

import json
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from sqlalchemy.orm import Session

from app.core.audit import record_audit
from app.core.database import get_db
from app.core.security import require_business_access
from app.models import Business, BusinessService, SocialContentProposal, User
from app.models.social_content_proposal import (
    SOCIAL_CONTENT_FORMATS,
    SOCIAL_PROPOSAL_OBJECTIVES,
    SOCIAL_PROPOSAL_PRIORITIES,
    SOCIAL_PROPOSAL_STATUSES,
    SOCIAL_PROPOSAL_TYPES,
)
from app.services.social_content_intelligence_service import (
    acceptance_snapshot,
    serialize_social_content_proposal,
)

router = APIRouter(
    prefix="/api/admin/businesses/{business_slug}",
    tags=["social-content-intelligence"],
    dependencies=[Depends(require_business_access)],
)


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _business_or_404(db: Session, slug: str) -> Business:
    row = db.query(Business).filter(Business.slug == slug).first()
    if row is None:
        raise HTTPException(status_code=404, detail="Business not found")
    return row


def _proposal_or_404(
    db: Session, *, business_id: int, proposal_id: int, lock: bool = False
) -> SocialContentProposal:
    query = db.query(SocialContentProposal).filter(
        SocialContentProposal.id == proposal_id,
        SocialContentProposal.business_id == business_id,
    )
    if lock and db.get_bind().dialect.name == "postgresql":
        query = query.with_for_update()
    row = query.first()
    if row is None:
        raise HTTPException(status_code=404, detail="Social content proposal not found")
    return row


def _service_or_422(db: Session, *, business_id: int, service_id: int) -> None:
    exists = (
        db.query(BusinessService.id)
        .filter(
            BusinessService.id == service_id,
            BusinessService.business_id == business_id,
        )
        .first()
    )
    if exists is None:
        raise HTTPException(status_code=422, detail="Service does not belong to this business")


@router.get("/social-content-proposals")
def list_social_content_proposals(
    business_slug: str,
    status: str | None = Query(default=None),
    objective: str | None = Query(default=None),
    type: str | None = Query(default=None),  # noqa: A002
    service_id: int | None = Query(default=None, alias="service"),
    priority: str | None = Query(default=None),
    limit: int = Query(default=100, ge=1, le=250),
    db: Session = Depends(get_db),
):
    business = _business_or_404(db, business_slug)
    if status is not None and status not in SOCIAL_PROPOSAL_STATUSES:
        raise HTTPException(status_code=422, detail="Unsupported proposal status")
    if objective is not None and objective not in SOCIAL_PROPOSAL_OBJECTIVES:
        raise HTTPException(status_code=422, detail="Unsupported proposal objective")
    if type is not None and type not in SOCIAL_PROPOSAL_TYPES:
        raise HTTPException(status_code=422, detail="Unsupported proposal type")
    if priority is not None and priority not in SOCIAL_PROPOSAL_PRIORITIES:
        raise HTTPException(status_code=422, detail="Unsupported proposal priority")
    if service_id is not None:
        _service_or_422(db, business_id=business.id, service_id=service_id)
    query = db.query(SocialContentProposal).filter(
        SocialContentProposal.business_id == business.id
    )
    if status:
        query = query.filter(SocialContentProposal.status == status)
    if objective:
        query = query.filter(SocialContentProposal.objective == objective)
    if type:
        query = query.filter(SocialContentProposal.proposal_type == type)
    if service_id is not None:
        query = query.filter(SocialContentProposal.service_id == service_id)
    if priority:
        query = query.filter(SocialContentProposal.priority == priority)
    rows = (
        query.order_by(
            SocialContentProposal.priority_score.desc(),
            SocialContentProposal.detected_at.desc(),
            SocialContentProposal.id.desc(),
        )
        .limit(limit)
        .all()
    )
    return {
        "business_slug": business.slug,
        "proposals": [serialize_social_content_proposal(row) for row in rows],
    }


@router.get("/social-content-proposals-summary")
def social_content_proposals_summary(
    business_slug: str, db: Session = Depends(get_db)
):
    business = _business_or_404(db, business_slug)
    rows = (
        db.query(SocialContentProposal)
        .filter(
            SocialContentProposal.business_id == business.id,
            SocialContentProposal.status == "active",
        )
        .all()
    )
    by_format = {item: 0 for item in SOCIAL_CONTENT_FORMATS}
    for row in rows:
        for item in json.loads(row.recommended_formats_json):
            if item in by_format:
                by_format[item] += 1
    return {
        "business_slug": business.slug,
        "active_count": len(rows),
        "high_priority_count": sum(1 for row in rows if row.priority == "high"),
        "by_objective": {
            item: sum(1 for row in rows if row.objective == item)
            for item in SOCIAL_PROPOSAL_OBJECTIVES
        },
        "by_format": by_format,
        "last_detected_at": max((row.detected_at for row in rows), default=None),
    }


@router.get("/social-content-proposals/{proposal_id}")
def get_social_content_proposal(
    business_slug: str, proposal_id: int, db: Session = Depends(get_db)
):
    business = _business_or_404(db, business_slug)
    return {
        "proposal": serialize_social_content_proposal(
            _proposal_or_404(db, business_id=business.id, proposal_id=proposal_id)
        )
    }


@router.post("/social-content-proposals/{proposal_id}/dismiss")
def dismiss_social_content_proposal(
    business_slug: str,
    proposal_id: int,
    request: Request,
    actor: User = Depends(require_business_access),
    db: Session = Depends(get_db),
):
    business = _business_or_404(db, business_slug)
    row = _proposal_or_404(
        db, business_id=business.id, proposal_id=proposal_id, lock=True
    )
    if row.status == "dismissed":
        return {"ok": True, "idempotent": True, "proposal": serialize_social_content_proposal(row)}
    if row.status != "active":
        raise HTTPException(status_code=409, detail="Only an active proposal can be dismissed")
    row.status = "dismissed"
    row.dismissed_at = _now()
    row.updated_at = row.dismissed_at
    db.commit()
    db.refresh(row)
    record_audit(
        db,
        action="social_content_proposal_dismissed",
        request=request,
        actor=actor,
        business_id=business.id,
        resource_type="social_content_proposal",
        resource_id=row.id,
        metadata={"type": row.proposal_type, "service_id": row.service_id},
    )
    return {"ok": True, "idempotent": False, "proposal": serialize_social_content_proposal(row)}


@router.post("/social-content-proposals/{proposal_id}/accept")
def accept_social_content_proposal(
    business_slug: str,
    proposal_id: int,
    request: Request,
    actor: User = Depends(require_business_access),
    db: Session = Depends(get_db),
):
    business = _business_or_404(db, business_slug)
    row = _proposal_or_404(
        db, business_id=business.id, proposal_id=proposal_id, lock=True
    )
    if row.status == "accepted":
        return {"ok": True, "idempotent": True, "proposal": serialize_social_content_proposal(row)}
    if row.status != "active":
        raise HTTPException(status_code=409, detail="Only an active proposal can be accepted")
    now = _now()
    row.accepted_context_json = acceptance_snapshot(row)
    row.status = "accepted"
    row.accepted_at = now
    row.accepted_by_user_id = actor.id
    row.updated_at = now
    db.commit()
    db.refresh(row)
    record_audit(
        db,
        action="social_content_proposal_accepted",
        request=request,
        actor=actor,
        business_id=business.id,
        resource_type="social_content_proposal",
        resource_id=row.id,
        metadata={"type": row.proposal_type, "service_id": row.service_id},
    )
    return {"ok": True, "idempotent": False, "proposal": serialize_social_content_proposal(row)}
