from __future__ import annotations

import json
from datetime import datetime, timezone
from decimal import Decimal

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from sqlalchemy.orm import Session

from app.core.audit import record_audit
from app.core.database import get_db
from app.core.security import require_owner
from app.models import (
    Business,
    SocialIdeaReview,
    SocialPromotion,
    SocialPromotionRevision,
    User,
)
from app.schemas.social_content_workflow import (
    SocialIdeaAdminReviewRequest,
    SocialPromotionProposalRequest,
)
from app.services.capability_service import require_module_available
from app.services.instagram_content_service import serialize_content
from app.services.social_content_generation_service import generate_from_proposal
from app.services.social_content_intelligence_service import serialize_social_content_proposal
from app.services.social_production_readiness_service import production_readiness

router = APIRouter(
    prefix="/api/owner/businesses/{business_id}/social-content",
    tags=["owner-social-content-workflow"],
    dependencies=[Depends(require_owner)],
)


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _business_or_404(db: Session, business_id: int) -> Business:
    business = db.get(Business, business_id)
    if business is None:
        raise HTTPException(status_code=404, detail="Business not found")
    require_module_available(db, business.id, "social")
    return business


def _review_or_404(
    db: Session, *, business_id: int, review_id: int, lock: bool = False
) -> SocialIdeaReview:
    query = db.query(SocialIdeaReview).filter(
        SocialIdeaReview.id == review_id,
        SocialIdeaReview.business_id == business_id,
    )
    if lock and db.get_bind().dialect.name == "postgresql":
        query = query.with_for_update()
    review = query.first()
    if review is None:
        raise HTTPException(status_code=404, detail="Idea review not found")
    return review


def _serialize_revision(revision: SocialPromotionRevision) -> dict[str, object]:
    return {
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
        "proposed_at": revision.proposed_at.isoformat(),
        "owner_decided_at": (
            revision.owner_decided_at.isoformat() if revision.owner_decided_at else None
        ),
        "owner_note": revision.owner_note,
    }


def _serialize_promotion(promotion: SocialPromotion | None) -> dict[str, object] | None:
    if promotion is None:
        return None
    return {
        "id": promotion.id,
        "status": promotion.status,
        "service_id": promotion.service_id,
        "requested_at": promotion.requested_at.isoformat(),
        "revisions": [_serialize_revision(item) for item in promotion.revisions],
    }


def serialize_idea_review(db: Session, review: SocialIdeaReview) -> dict[str, object]:
    proposal = review.proposal
    return {
        "id": review.id,
        "business_id": review.business_id,
        "status": review.status,
        "owner_intent": review.owner_intent,
        "owner_accepted_at": review.owner_accepted_at.isoformat(),
        "presentation": json.loads(review.presentation_json),
        "template_version": review.template_version,
        "admin_reviewed_at": (
            review.admin_reviewed_at.isoformat() if review.admin_reviewed_at else None
        ),
        "admin_note": review.admin_note,
        "adjustments": json.loads(review.adjustments_json) if review.adjustments_json else {},
        "proposal": serialize_social_content_proposal(proposal),
        "production_readiness": production_readiness(
            db, business_id=review.business_id, proposal=proposal
        ),
        "promotion": _serialize_promotion(review.promotion),
    }


@router.get("/idea-reviews")
def list_idea_reviews(
    business_id: int,
    status: str | None = Query(default=None),
    db: Session = Depends(get_db),
):
    _business_or_404(db, business_id)
    allowed = {"pending", "approved", "changes_requested", "rejected"}
    if status is not None and status not in allowed:
        raise HTTPException(status_code=422, detail="Unsupported idea review status")
    query = db.query(SocialIdeaReview).filter(SocialIdeaReview.business_id == business_id)
    if status:
        query = query.filter(SocialIdeaReview.status == status)
    rows = query.order_by(SocialIdeaReview.created_at.desc(), SocialIdeaReview.id.desc()).all()
    return {"reviews": [serialize_idea_review(db, row) for row in rows]}


def _approved_promotion_context(review: SocialIdeaReview) -> dict[str, object] | None:
    promotion = review.promotion
    if promotion is None:
        return None
    approved = next(
        (item for item in reversed(promotion.revisions) if item.status == "owner_approved"),
        None,
    )
    if approved is None:
        return None
    return _serialize_revision(approved)


@router.post("/idea-reviews/{review_id}/decision")
def review_social_idea(
    business_id: int,
    review_id: int,
    payload: SocialIdeaAdminReviewRequest,
    request: Request,
    actor: User = Depends(require_owner),
    db: Session = Depends(get_db),
):
    _business_or_404(db, business_id)
    review = _review_or_404(db, business_id=business_id, review_id=review_id, lock=True)
    proposal = review.proposal
    adjustments = {
        key: value
        for key, value in {
            "format": payload.format,
            "objective": payload.objective,
            "recommended_cta": payload.cta,
            "angle_code": payload.angle,
        }.items()
        if value is not None
    }
    now = _now()
    if payload.decision == "adjust":
        review.adjustments_json = json.dumps(
            adjustments, ensure_ascii=False, sort_keys=True, separators=(",", ":")
        )
        review.admin_reviewed_by_user_id = actor.id
        review.admin_reviewed_at = now
        review.admin_note = payload.note
        review.updated_at = now
        db.commit()
        record_audit(
            db,
            action="social_idea_autonogrow_admin_adjusted",
            request=request,
            actor=actor,
            business_id=business_id,
            resource_type="social_idea_review",
            resource_id=review.id,
            metadata={"proposal_id": proposal.id, "adjusted_fields": sorted(adjustments)},
        )
        return {"ok": True, "generated": False, "review": serialize_idea_review(db, review)}
    if payload.decision == "reject":
        if review.status == "rejected":
            return {"ok": True, "idempotent": True, "review": serialize_idea_review(db, review)}
        if review.status == "approved" and proposal.generated_content is not None:
            raise HTTPException(status_code=409, detail="Generated content must use content review")
        review.status = "rejected"
        review.admin_reviewed_by_user_id = actor.id
        review.admin_reviewed_at = now
        review.admin_note = payload.note
        review.updated_at = now
        db.commit()
        record_audit(
            db,
            action="social_idea_autonogrow_admin_rejected",
            request=request,
            actor=actor,
            business_id=business_id,
            resource_type="social_idea_review",
            resource_id=review.id,
            metadata={"proposal_id": proposal.id},
        )
        return {"ok": True, "generated": False, "review": serialize_idea_review(db, review)}

    promotion_context = _approved_promotion_context(review)
    if review.owner_intent == "promotion" and promotion_context is None:
        review.status = "approved"
        review.admin_reviewed_by_user_id = actor.id
        review.admin_reviewed_at = now
        review.admin_note = payload.note
        review.updated_at = now
        record_audit(
            db,
            action="social_idea_autonogrow_admin_approved",
            request=request,
            actor=actor,
            business_id=business_id,
            resource_type="social_idea_review",
            resource_id=review.id,
            metadata={"proposal_id": proposal.id, "waiting_for_promotion": True},
            commit=False,
        )
        db.commit()
        return {
            "ok": True,
            "generated": False,
            "waiting_for_promotion": True,
            "review": serialize_idea_review(db, review),
        }
    if review.status == "approved" and proposal.generated_content is not None:
        return {
            "ok": True,
            "idempotent": True,
            "generated": True,
            "review": serialize_idea_review(db, review),
        }
    approved_context = json.loads(review.owner_context_json)
    approved_context["admin_adjustments"] = adjustments or (
        json.loads(review.adjustments_json) if review.adjustments_json else {}
    )
    effective_adjustments = approved_context["admin_adjustments"]
    for target, source in (
        ("objective", "objective"),
        ("recommended_cta", "recommended_cta"),
        ("angle_code", "angle_code"),
    ):
        if source in effective_adjustments:
            approved_context[target] = effective_adjustments[source]
    if promotion_context is not None:
        approved_context["promotion"] = promotion_context
    proposal.accepted_context_json = json.dumps(
        approved_context, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    )
    review.status = "approved"
    review.admin_reviewed_by_user_id = actor.id
    review.admin_reviewed_at = now
    review.admin_note = payload.note
    review.updated_at = now
    db.flush()
    requested_format = adjustments.get("format")
    if requested_format is None and review.adjustments_json:
        requested_format = json.loads(review.adjustments_json).get("format")
    content, version, idempotent = generate_from_proposal(
        db,
        proposal=proposal,
        actor=actor,
        requested_format=requested_format,
    )
    db.flush()
    record_audit(
        db,
        action="social_idea_autonogrow_admin_approved",
        request=request,
        actor=actor,
        business_id=business_id,
        resource_type="social_idea_review",
        resource_id=review.id,
        metadata={
            "proposal_id": proposal.id,
            "content_id": content.id,
            "version_id": version.id,
            "idempotent": idempotent,
        },
        commit=False,
    )
    record_audit(
        db,
        action="social_content_draft_generated",
        request=request,
        actor=actor,
        business_id=business_id,
        resource_type="instagram_content",
        resource_id=content.id,
        metadata={
            "proposal_id": proposal.id,
            "idea_review_id": review.id,
            "version_id": version.id,
            "generator_version": version.generator_version,
            "idempotent": idempotent,
        },
        commit=False,
    )
    db.commit()
    return {
        "ok": True,
        "generated": True,
        "idempotent": idempotent,
        "review": serialize_idea_review(db, review),
        "content": serialize_content(
            db,
            content,
            f"/api/owner/businesses/{business_id}/instagram-content",
            detailed=True,
        ),
    }


@router.post("/idea-reviews/{review_id}/promotion", status_code=201)
def propose_social_promotion(
    business_id: int,
    review_id: int,
    payload: SocialPromotionProposalRequest,
    request: Request,
    actor: User = Depends(require_owner),
    db: Session = Depends(get_db),
):
    _business_or_404(db, business_id)
    review = _review_or_404(db, business_id=business_id, review_id=review_id, lock=True)
    promotion = review.promotion
    if promotion is None or review.owner_intent != "promotion":
        raise HTTPException(status_code=409, detail="Business Owner did not request a promotion")
    if promotion.service is None or promotion.service.price_amount is None:
        raise HTTPException(status_code=409, detail="The service has no configured regular price")
    if Decimal(promotion.service.price_amount) != payload.regular_price:
        raise HTTPException(status_code=409, detail="Regular price no longer matches the service")
    if promotion.service.currency.upper() != payload.currency:
        raise HTTPException(status_code=409, detail="Currency no longer matches the service")
    for previous in promotion.revisions:
        if previous.status == "proposed":
            previous.status = "superseded"
    now = _now()
    revision = SocialPromotionRevision(
        promotion=promotion,
        revision_number=len(promotion.revisions) + 1,
        status="proposed",
        discount_type=payload.discount_type,
        discount_value=payload.discount_value,
        regular_price=payload.regular_price,
        promotional_price=payload.promotional_price,
        currency=payload.currency,
        valid_from=payload.valid_from,
        valid_until=payload.valid_until,
        days_json=json.dumps(payload.days, separators=(",", ":")),
        scope=payload.scope,
        proposed_by_user_id=actor.id,
        proposed_at=now,
        created_at=now,
    )
    db.add(revision)
    promotion.status = "proposed"
    promotion.updated_at = now
    db.flush()
    record_audit(
        db,
        action="social_promotion_autonogrow_admin_proposed",
        request=request,
        actor=actor,
        business_id=business_id,
        resource_type="social_promotion_revision",
        resource_id=revision.id,
        metadata={"promotion_id": promotion.id, "idea_review_id": review.id},
        commit=False,
    )
    db.commit()
    return {"ok": True, "promotion": _serialize_promotion(promotion)}
