from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.orm import Session

from app.core.audit import record_audit
from app.core.database import get_db
from app.core.security import require_owner
from app.models import Business, InstagramContent, SocialContentProposal, User
from app.schemas.social_content_generation import (
    EditorialPackageEdit,
    SocialContentGenerateRequest,
    SocialContentRegenerateRequest,
)
from app.services.instagram_content_service import content_or_404, serialize_content
from app.services.social_content_generation_service import (
    generate_from_proposal,
    regenerate_content,
    update_generated_draft,
)

router = APIRouter(
    prefix="/api/admin/businesses/{business_slug}",
    tags=["social-content-generation"],
    dependencies=[Depends(require_owner)],
)


def _business_or_404(db: Session, slug: str) -> Business:
    business = db.query(Business).filter(Business.slug == slug).first()
    if business is None:
        raise HTTPException(status_code=404, detail="Business not found")
    return business


def _proposal_or_404(db: Session, *, business_id: int, proposal_id: int) -> SocialContentProposal:
    query = db.query(SocialContentProposal).filter(
        SocialContentProposal.id == proposal_id,
        SocialContentProposal.business_id == business_id,
    )
    if db.get_bind().dialect.name == "postgresql":
        query = query.with_for_update()
    proposal = query.first()
    if proposal is None:
        raise HTTPException(status_code=404, detail="Social content proposal not found")
    return proposal


def _prefix(slug: str) -> str:
    return f"/api/admin/businesses/{slug}/instagram-content"


def _audit_generation(
    db: Session,
    *,
    request: Request,
    actor: User,
    business_id: int,
    content: InstagramContent,
    action: str,
    metadata: dict,
) -> None:
    record_audit(
        db,
        action=action,
        request=request,
        actor=actor,
        business_id=business_id,
        resource_type="instagram_content",
        resource_id=content.id,
        metadata=metadata,
        commit=False,
    )


@router.post("/social-content-proposals/{proposal_id}/generate", status_code=201)
def generate_social_content(
    business_slug: str,
    proposal_id: int,
    payload: SocialContentGenerateRequest,
    request: Request,
    actor: User = Depends(require_owner),
    db: Session = Depends(get_db),
):
    business = _business_or_404(db, business_slug)
    proposal = _proposal_or_404(db, business_id=business.id, proposal_id=proposal_id)
    content, version, idempotent = generate_from_proposal(
        db,
        proposal=proposal,
        actor=actor,
        requested_format=payload.format,
    )
    _audit_generation(
        db,
        request=request,
        actor=actor,
        business_id=business.id,
        content=content,
        action="social_content_draft_generated",
        metadata={
            "proposal_id": proposal.id,
            "version_id": version.id,
            "idempotent": idempotent,
        },
    )
    db.commit()
    db.refresh(content)
    return {
        "ok": True,
        "idempotent": idempotent,
        "content": serialize_content(db, content, _prefix(business_slug), detailed=True),
    }


@router.post("/instagram-content/contents/{content_id}/regenerate")
def regenerate_social_content(
    business_slug: str,
    content_id: int,
    payload: SocialContentRegenerateRequest,
    request: Request,
    actor: User = Depends(require_owner),
    db: Session = Depends(get_db),
):
    business = _business_or_404(db, business_slug)
    content = content_or_404(db, business.id, content_id, for_update=True)
    version = regenerate_content(
        db,
        content=content,
        actor=actor,
        requested_format=payload.format,
    )
    _audit_generation(
        db,
        request=request,
        actor=actor,
        business_id=business.id,
        content=content,
        action="social_content_draft_regenerated",
        metadata={"proposal_id": content.source_proposal_id, "version_id": version.id},
    )
    db.commit()
    db.refresh(content)
    return {
        "ok": True,
        "content": serialize_content(db, content, _prefix(business_slug), detailed=True),
    }


@router.put("/instagram-content/contents/{content_id}/generated-draft")
def edit_generated_social_content(
    business_slug: str,
    content_id: int,
    payload: EditorialPackageEdit,
    request: Request,
    actor: User = Depends(require_owner),
    db: Session = Depends(get_db),
):
    business = _business_or_404(db, business_slug)
    content = content_or_404(db, business.id, content_id, for_update=True)
    version, changed = update_generated_draft(
        db,
        content=content,
        actor=actor,
        edit=payload,
    )
    if changed:
        _audit_generation(
            db,
            request=request,
            actor=actor,
            business_id=business.id,
            content=content,
            action="social_content_draft_edited",
            metadata={"proposal_id": content.source_proposal_id, "version_id": version.id},
        )
    db.commit()
    db.refresh(content)
    return {
        "ok": True,
        "changed": changed,
        "content": serialize_content(db, content, _prefix(business_slug), detailed=True),
    }
