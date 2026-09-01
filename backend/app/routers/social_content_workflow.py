from __future__ import annotations

import json
from datetime import datetime, timezone
from decimal import Decimal

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from sqlalchemy import or_
from sqlalchemy.orm import Session

from app.core.audit import record_audit
from app.core.database import get_db
from app.core.security import require_business_operational_status_by_id, require_owner
from app.models import (
    Business,
    BusinessGrowthSignal,
    SocialContentProposal,
    SocialIdeaReview,
    SocialPromotion,
    SocialPromotionRevision,
    User,
)
from app.schemas.social_content_workflow import (
    SocialIdeaAdminReviewRequest,
    SocialIdeaPostponeRequest,
    SocialIdeaPrepareRequest,
    SocialPromotionProposalRequest,
)
from app.services.capability_service import require_module_available
from app.services.instagram_content_service import serialize_content
from app.services.social_content_generation_service import generate_from_proposal
from app.services.social_content_intelligence_service import (
    acceptance_snapshot,
    serialize_social_content_proposal,
)
from app.services.social_content_presentation_service import present_social_content_proposal
from app.services.social_production_readiness_service import production_readiness

router = APIRouter(
    prefix="/api/owner/businesses/{business_id}/social-content",
    tags=["owner-social-content-workflow"],
    dependencies=[Depends(require_owner), Depends(require_business_operational_status_by_id)],
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


def _proposal_or_404(
    db: Session, *, business_id: int, proposal_id: int, lock: bool = False
) -> SocialContentProposal:
    query = db.query(SocialContentProposal).filter(
        SocialContentProposal.id == proposal_id,
        SocialContentProposal.business_id == business_id,
    )
    if lock and db.get_bind().dialect.name == "postgresql":
        query = query.with_for_update()
    proposal = query.first()
    if proposal is None:
        raise HTTPException(status_code=404, detail="Social content proposal not found")
    return proposal


def _promotion_eligible(db: Session, proposal: SocialContentProposal) -> bool:
    if proposal.service_id is None:
        return False
    if "service_demand_drop" not in {link.signal.type for link in proposal.signal_links}:
        return False
    return (
        db.query(BusinessGrowthSignal.id)
        .filter(
            BusinessGrowthSignal.business_id == proposal.business_id,
            BusinessGrowthSignal.status == "active",
            BusinessGrowthSignal.type == "low_future_occupancy",
        )
        .first()
        is not None
    )


def _serialize_owner_idea(proposal: SocialContentProposal) -> dict[str, object]:
    promotion = proposal.idea_review.promotion if proposal.idea_review else None
    return {
        **serialize_social_content_proposal(proposal),
        "business_name": proposal.business.name,
        "presentation": present_social_content_proposal(proposal).as_dict(),
        "promotion_eligible": False,
        "operator_postponed_until": (
            proposal.operator_postponed_until.isoformat()
            if proposal.operator_postponed_until
            else None
        ),
        "legacy_p12": proposal.idea_review is not None,
        "idea_review_id": proposal.idea_review.id if proposal.idea_review else None,
        "promotion": _serialize_promotion(promotion),
    }


@router.get("/ideas")
def list_owner_social_ideas(
    business_id: int,
    limit: int = Query(default=100, ge=1, le=250),
    db: Session = Depends(get_db),
):
    _business_or_404(db, business_id)
    now = _now()
    rows = (
        db.query(SocialContentProposal)
        .filter(
            SocialContentProposal.business_id == business_id,
            SocialContentProposal.status.in_({"active", "accepted"}),
            SocialContentProposal.expires_at > now,
            ~SocialContentProposal.generated_content.has(),
            or_(
                SocialContentProposal.operator_postponed_until.is_(None),
                SocialContentProposal.operator_postponed_until <= now,
            ),
        )
        .order_by(
            SocialContentProposal.priority_score.desc(),
            SocialContentProposal.detected_at.desc(),
        )
        .limit(limit)
        .all()
    )
    ideas = []
    for proposal in rows:
        item = _serialize_owner_idea(proposal)
        item["promotion_eligible"] = _promotion_eligible(db, proposal)
        ideas.append(item)
    return {"ideas": ideas}


@router.post("/ideas/{proposal_id}/prepare")
def prepare_owner_social_idea(
    business_id: int,
    proposal_id: int,
    payload: SocialIdeaPrepareRequest,
    request: Request,
    actor: User = Depends(require_owner),
    db: Session = Depends(get_db),
):
    _business_or_404(db, business_id)
    proposal = _proposal_or_404(
        db, business_id=business_id, proposal_id=proposal_id, lock=True
    )
    now = _now()
    if proposal.generated_content is not None:
        content = proposal.generated_content
        return {
            "ok": True,
            "idempotent": True,
            "waiting_for_business": False,
            "production_readiness": production_readiness(
                db, business_id=business_id, proposal=proposal
            ),
            "content": serialize_content(
                db,
                content,
                f"/api/owner/businesses/{business_id}/instagram-content",
                detailed=True,
            ),
        }
    if proposal.status not in {"active", "accepted"} or proposal.expires_at <= now:
        raise HTTPException(status_code=409, detail="This idea is no longer available")
    if proposal.accepted_context_json is None:
        proposal.accepted_context_json = acceptance_snapshot(proposal)
    if proposal.status == "active":
        proposal.status = "accepted"
        proposal.accepted_at = now
        proposal.accepted_by_user_id = actor.id
    proposal.operator_postponed_until = None
    proposal.updated_at = now

    if payload.intent == "promotion":
        if not _promotion_eligible(db, proposal):
            raise HTTPException(
                status_code=409,
                detail="This opportunity does not support a promotion study",
            )
        review = proposal.idea_review
        if review is not None and review.owner_intent != "promotion":
            raise HTTPException(
                status_code=409,
                detail="This legacy idea cannot be reinterpreted as a promotion",
            )
        if review is None:
            presentation = present_social_content_proposal(proposal)
            review = SocialIdeaReview(
                business_id=business_id,
                proposal=proposal,
                status="approved",
                owner_intent="promotion",
                owner_accepted_by_user_id=actor.id,
                owner_accepted_at=now,
                owner_context_json=proposal.accepted_context_json,
                presentation_json=json.dumps(
                    presentation.as_dict(),
                    ensure_ascii=False,
                    sort_keys=True,
                    separators=(",", ":"),
                ),
                template_version=presentation.template_version,
                admin_reviewed_by_user_id=actor.id,
                admin_reviewed_at=now,
                admin_note="Operational promotion request",
                created_at=now,
                updated_at=now,
            )
            db.add(review)
            db.flush()
        promotion = review.promotion
        created = promotion is None
        if promotion is None:
            promotion = SocialPromotion(
                business_id=business_id,
                idea_review_id=review.id,
                service_id=proposal.service_id,
                status="requested",
                requested_by_user_id=actor.id,
                requested_at=now,
                created_at=now,
                updated_at=now,
            )
            db.add(promotion)
            db.flush()
        record_audit(
            db,
            action="promotion_requested_for_business",
            request=request,
            actor=actor,
            business_id=business_id,
            resource_type="social_promotion",
            resource_id=promotion.id,
            metadata={"proposal_id": proposal.id, "service_id": proposal.service_id},
            commit=False,
        )
        db.commit()
        return {
            "ok": True,
            "idempotent": not created,
            "waiting_for_business": True,
            "production_readiness": production_readiness(
                db, business_id=business_id, proposal=proposal
            ),
            "promotion": _serialize_promotion(promotion),
        }

    existing_promotion = proposal.idea_review.promotion if proposal.idea_review else None
    if existing_promotion is not None and existing_promotion.status != "owner_approved":
        raise HTTPException(
            status_code=409,
            detail="Promotion requires a decision by the business before content preparation",
        )
    content, version, idempotent = generate_from_proposal(
        db,
        proposal=proposal,
        actor=actor,
        requested_format=payload.format,
    )
    record_audit(
        db,
        action="idea_owner_prepared",
        request=request,
        actor=actor,
        business_id=business_id,
        resource_type="social_content_proposal",
        resource_id=proposal.id,
        metadata={"content_id": content.id, "version_id": version.id},
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
            "version_id": version.id,
            "generator_version": version.generator_version,
            "idempotent": idempotent,
        },
        commit=False,
    )
    db.commit()
    return {
        "ok": True,
        "idempotent": idempotent,
        "waiting_for_business": False,
        "production_readiness": production_readiness(
            db, business_id=business_id, proposal=proposal
        ),
        "content": serialize_content(
            db,
            content,
            f"/api/owner/businesses/{business_id}/instagram-content",
            detailed=True,
        ),
    }


@router.post("/ideas/{proposal_id}/postpone")
def postpone_owner_social_idea(
    business_id: int,
    proposal_id: int,
    payload: SocialIdeaPostponeRequest,
    request: Request,
    actor: User = Depends(require_owner),
    db: Session = Depends(get_db),
):
    _business_or_404(db, business_id)
    proposal = _proposal_or_404(
        db, business_id=business_id, proposal_id=proposal_id, lock=True
    )
    now = _now()
    until = payload.until if payload.until.tzinfo else payload.until.replace(tzinfo=timezone.utc)
    if until <= now:
        raise HTTPException(status_code=422, detail="Postponement must be in the future")
    if proposal.generated_content is not None or proposal.status not in {"active", "accepted"}:
        raise HTTPException(status_code=409, detail="This idea cannot be postponed")
    proposal.operator_postponed_until = until
    proposal.updated_at = now
    record_audit(
        db,
        action="idea_owner_postponed",
        request=request,
        actor=actor,
        business_id=business_id,
        resource_type="social_content_proposal",
        resource_id=proposal.id,
        metadata={"until": until.isoformat()},
        commit=False,
    )
    db.commit()
    return {"ok": True, "postponed_until": until.isoformat()}


@router.post("/ideas/{proposal_id}/discard")
def discard_owner_social_idea(
    business_id: int,
    proposal_id: int,
    request: Request,
    actor: User = Depends(require_owner),
    db: Session = Depends(get_db),
):
    _business_or_404(db, business_id)
    proposal = _proposal_or_404(
        db, business_id=business_id, proposal_id=proposal_id, lock=True
    )
    if proposal.status == "dismissed":
        return {"ok": True, "idempotent": True}
    if proposal.generated_content is not None or proposal.status not in {"active", "accepted"}:
        raise HTTPException(status_code=409, detail="This idea cannot be discarded")
    now = _now()
    proposal.status = "dismissed"
    proposal.dismissed_at = now
    proposal.operator_postponed_until = None
    proposal.updated_at = now
    record_audit(
        db,
        action="idea_owner_dismissed",
        request=request,
        actor=actor,
        business_id=business_id,
        resource_type="social_content_proposal",
        resource_id=proposal.id,
        metadata={"signal_ids": [link.signal_id for link in proposal.signal_links]},
        commit=False,
    )
    db.commit()
    return {"ok": True, "idempotent": False}


def _serialize_revision(revision: SocialPromotionRevision) -> dict[str, object]:
    return {
        "id": revision.id,
        "revision_number": revision.revision_number,
        "status": (
            "business_approved"
            if revision.status == "owner_approved"
            else "business_rejected"
            if revision.status == "owner_rejected"
            else revision.status
        ),
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
        "status": (
            "business_approved"
            if promotion.status == "owner_approved"
            else "business_rejected"
            if promotion.status == "owner_rejected"
            else promotion.status
        ),
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
