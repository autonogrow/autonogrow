from __future__ import annotations

import json
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from sqlalchemy.orm import Session

from app.core.audit import record_audit
from app.core.database import get_db
from app.core.security import require_tenant_business_admin
from app.models import (
    AuditLog,
    Business,
    BusinessGrowthSignal,
    BusinessService,
    SocialContentProposal,
    SocialIdeaReview,
    SocialPromotion,
    SocialPromotionRevision,
    User,
)
from app.models.social_content_proposal import (
    SOCIAL_CONTENT_FORMATS,
    SOCIAL_PROPOSAL_OBJECTIVES,
    SOCIAL_PROPOSAL_PRIORITIES,
    SOCIAL_PROPOSAL_STATUSES,
    SOCIAL_PROPOSAL_TYPES,
)
from app.schemas.social_content_workflow import (
    SocialIdeaAcceptRequest,
    SocialPromotionDecisionRequest,
)
from app.services.capability_service import require_social_access
from app.services.social_content_intelligence_service import (
    acceptance_snapshot,
    serialize_social_content_proposal,
)
from app.services.social_content_presentation_service import (
    present_social_content_proposal,
)

router = APIRouter(
    prefix="/api/admin/businesses/{business_slug}",
    tags=["social-content-intelligence"],
    dependencies=[Depends(require_social_access), Depends(require_tenant_business_admin)],
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


def _promotion_eligible(db: Session, row: SocialContentProposal) -> bool:
    if row.service_id is None:
        return False
    signal_types = {link.signal.type for link in row.signal_links}
    if "service_demand_drop" not in signal_types:
        return False
    return (
        db.query(BusinessGrowthSignal.id)
        .filter(
            BusinessGrowthSignal.business_id == row.business_id,
            BusinessGrowthSignal.status == "active",
            BusinessGrowthSignal.type == "low_future_occupancy",
        )
        .first()
        is not None
    )


def _serialize_owner_idea(db: Session, row: SocialContentProposal) -> dict:
    payload = serialize_social_content_proposal(row)
    review = row.idea_review
    payload["presentation"] = present_social_content_proposal(row).as_dict()
    payload["owner_first"] = review is not None
    payload["legacy_accepted"] = row.status == "accepted" and review is None
    payload["owner_state"] = (
        "new"
        if row.status == "active"
        else "dismissed"
        if row.status == "dismissed"
        else "legacy_accepted"
        if review is None
        else "pending_admin"
        if review.status == "pending"
        else "preparing_content"
        if review.status == "approved" and row.generated_content is not None
        else review.status
    )
    payload["promotion_eligible"] = _promotion_eligible(db, row)
    payload["idea_review"] = (
        {
            "id": review.id,
            "status": review.status,
            "owner_intent": review.owner_intent,
            "promotion": (
                {
                    "id": review.promotion.id,
                    "status": review.promotion.status,
                    "revisions": [
                        {
                            "id": revision.id,
                            "revision_number": revision.revision_number,
                            "status": revision.status,
                            "discount_type": revision.discount_type,
                            "discount_value": str(revision.discount_value),
                            "regular_price": str(revision.regular_price),
                            "promotional_price": str(revision.promotional_price),
                            "currency": revision.currency,
                            "valid_from": revision.valid_from.isoformat(),
                            "valid_until": revision.valid_until.isoformat(),
                            "days": json.loads(revision.days_json),
                            "scope": revision.scope,
                        }
                        for revision in review.promotion.revisions
                    ],
                }
                if review.promotion
                else None
            ),
        }
        if review
        else None
    )
    return payload


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
        "proposals": [_serialize_owner_idea(db, row) for row in rows],
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
        "proposal": _serialize_owner_idea(
            db, _proposal_or_404(db, business_id=business.id, proposal_id=proposal_id)
        )
    }


@router.post("/social-content-proposals/{proposal_id}/seen")
def mark_social_content_proposal_seen(
    business_slug: str,
    proposal_id: int,
    request: Request,
    actor: User = Depends(require_tenant_business_admin),
    db: Session = Depends(get_db),
):
    business = _business_or_404(db, business_slug)
    row = _proposal_or_404(db, business_id=business.id, proposal_id=proposal_id)
    exists = (
        db.query(AuditLog.id)
        .filter(
            AuditLog.action == "social_idea_business_owner_seen",
            AuditLog.business_id == business.id,
            AuditLog.actor_user_id == actor.id,
            AuditLog.resource_type == "social_content_proposal",
            AuditLog.resource_id == str(row.id),
        )
        .first()
        is not None
    )
    if not exists:
        record_audit(
            db,
            action="social_idea_business_owner_seen",
            request=request,
            actor=actor,
            business_id=business.id,
            resource_type="social_content_proposal",
            resource_id=row.id,
            metadata={"status": row.status},
        )
    return {"ok": True, "idempotent": exists}


@router.post("/social-content-proposals/{proposal_id}/dismiss")
def dismiss_social_content_proposal(
    business_slug: str,
    proposal_id: int,
    request: Request,
    actor: User = Depends(require_tenant_business_admin),
    db: Session = Depends(get_db),
):
    business = _business_or_404(db, business_slug)
    row = _proposal_or_404(
        db, business_id=business.id, proposal_id=proposal_id, lock=True
    )
    if row.status == "dismissed":
        return {"ok": True, "idempotent": True, "proposal": _serialize_owner_idea(db, row)}
    if row.status != "active":
        raise HTTPException(status_code=409, detail="Only an active proposal can be dismissed")
    row.status = "dismissed"
    row.dismissed_at = _now()
    row.updated_at = row.dismissed_at
    db.commit()
    db.refresh(row)
    record_audit(
        db,
        action="social_idea_business_owner_dismissed",
        request=request,
        actor=actor,
        business_id=business.id,
        resource_type="social_content_proposal",
        resource_id=row.id,
        metadata={"type": row.proposal_type, "service_id": row.service_id},
    )
    return {"ok": True, "idempotent": False, "proposal": _serialize_owner_idea(db, row)}


@router.post("/social-content-proposals/{proposal_id}/accept")
def accept_social_content_proposal(
    business_slug: str,
    proposal_id: int,
    payload: SocialIdeaAcceptRequest,
    request: Request,
    actor: User = Depends(require_tenant_business_admin),
    db: Session = Depends(get_db),
):
    business = _business_or_404(db, business_slug)
    row = _proposal_or_404(
        db, business_id=business.id, proposal_id=proposal_id, lock=True
    )
    if row.status == "accepted":
        if row.idea_review is None:
            raise HTTPException(
                status_code=409,
                detail="This legacy acceptance has no Business Owner evidence",
            )
        return {"ok": True, "idempotent": True, "proposal": _serialize_owner_idea(db, row)}
    if row.status != "active":
        raise HTTPException(status_code=409, detail="Only an active proposal can be accepted")
    promotion_eligible = _promotion_eligible(db, row)
    if payload.intent == "promotion" and not promotion_eligible:
        raise HTTPException(
            status_code=409,
            detail="This opportunity does not support a promotion study",
        )
    now = _now()
    row.accepted_context_json = acceptance_snapshot(row)
    row.status = "accepted"
    row.accepted_at = now
    row.accepted_by_user_id = actor.id
    row.updated_at = now
    presentation = present_social_content_proposal(row)
    review = SocialIdeaReview(
        business_id=business.id,
        proposal=row,
        status="pending",
        owner_intent=payload.intent,
        owner_accepted_by_user_id=actor.id,
        owner_accepted_at=now,
        owner_context_json=row.accepted_context_json,
        presentation_json=json.dumps(
            presentation.as_dict(), ensure_ascii=False, sort_keys=True, separators=(",", ":")
        ),
        template_version=presentation.template_version,
        created_at=now,
        updated_at=now,
    )
    db.add(review)
    db.flush()
    if payload.intent == "promotion":
        db.add(
            SocialPromotion(
                business_id=business.id,
                idea_review_id=review.id,
                service_id=row.service_id,
                status="requested",
                requested_by_user_id=actor.id,
                requested_at=now,
                created_at=now,
                updated_at=now,
            )
        )
    db.commit()
    db.refresh(row)
    record_audit(
        db,
        action="social_idea_business_owner_accepted",
        request=request,
        actor=actor,
        business_id=business.id,
        resource_type="social_content_proposal",
        resource_id=row.id,
        metadata={
            "type": row.proposal_type,
            "service_id": row.service_id,
            "idea_review_id": review.id,
            "owner_intent": payload.intent,
        },
    )
    if payload.intent == "promotion":
        record_audit(
            db,
            action="social_promotion_business_owner_requested",
            request=request,
            actor=actor,
            business_id=business.id,
            resource_type="social_idea_review",
            resource_id=review.id,
            metadata={"proposal_id": row.id, "service_id": row.service_id},
        )
    return {"ok": True, "idempotent": False, "proposal": _serialize_owner_idea(db, row)}


@router.post("/social-content-proposals/{proposal_id}/promotion/decision")
def decide_social_promotion(
    business_slug: str,
    proposal_id: int,
    payload: SocialPromotionDecisionRequest,
    request: Request,
    actor: User = Depends(require_tenant_business_admin),
    db: Session = Depends(get_db),
):
    business = _business_or_404(db, business_slug)
    row = _proposal_or_404(
        db, business_id=business.id, proposal_id=proposal_id, lock=True
    )
    review = row.idea_review
    promotion = review.promotion if review else None
    if promotion is None:
        raise HTTPException(status_code=404, detail="Promotion request not found")
    revision = (
        db.query(SocialPromotionRevision)
        .filter(
            SocialPromotionRevision.id == payload.revision_id,
            SocialPromotionRevision.promotion_id == promotion.id,
        )
        .first()
    )
    if revision is None:
        raise HTTPException(status_code=404, detail="Promotion revision not found")
    if revision.status in {"owner_approved", "owner_rejected"}:
        expected = "owner_approved" if payload.decision == "approve" else "owner_rejected"
        if revision.status != expected:
            raise HTTPException(status_code=409, detail="Promotion already has another decision")
        return {"ok": True, "idempotent": True, "promotion_id": promotion.id}
    if revision.status != "proposed" or revision is not promotion.revisions[-1]:
        raise HTTPException(status_code=409, detail="Only the current proposal can be decided")
    now = _now()
    revision.status = "owner_approved" if payload.decision == "approve" else "owner_rejected"
    revision.owner_decided_by_user_id = actor.id
    revision.owner_decided_at = now
    revision.owner_note = payload.note
    promotion.status = revision.status
    promotion.updated_at = now
    db.commit()
    record_audit(
        db,
        action=(
            "social_promotion_business_owner_approved"
            if payload.decision == "approve"
            else "social_promotion_business_owner_rejected"
        ),
        request=request,
        actor=actor,
        business_id=business.id,
        resource_type="social_promotion_revision",
        resource_id=revision.id,
        metadata={"proposal_id": row.id, "promotion_id": promotion.id},
    )
    return {"ok": True, "idempotent": False, "promotion_id": promotion.id}
