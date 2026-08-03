from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import RedirectResponse
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.audit import record_audit
from app.core.database import get_db
from app.core.security import (
    SESSION_COOKIE,
    get_business_membership,
    get_optional_current_user,
    require_business_admin,
    require_owner,
)
from app.models import Business, InstagramOAuthAttempt, User
from app.schemas.channel_onboarding import ChannelDecisionRequest
from app.schemas.instagram_oauth import InstagramOAuthStartRequest
from app.services.channel_control_service import get_channel_control
from app.services.instagram_oauth_service import (
    complete_instagram_oauth_callback,
    decide_instagram_oauth_candidate,
    expire_instagram_oauth_attempts,
    retry_instagram_candidate_webhook,
    safe_instagram_return_path,
    serialize_instagram_oauth_attempt,
    start_instagram_oauth,
)

callback_router = APIRouter(prefix="/api/integrations/instagram", tags=["instagram-login"])
admin_router = APIRouter(
    prefix="/api/admin/businesses/{business_slug}/integrations/instagram",
    tags=["instagram-login"],
)
owner_router = APIRouter(
    prefix="/api/owner/businesses/{business_id}/integrations/instagram/oauth",
    tags=["owner-instagram-login"],
    dependencies=[Depends(require_owner)],
)


def _business_by_slug(db: Session, business_slug: str) -> Business:
    business = db.query(Business).filter(Business.slug == business_slug).first()
    if business is None:
        raise HTTPException(status_code=404, detail="Business not found")
    return business


def _business_by_id(db: Session, business_id: int) -> Business:
    business = db.query(Business).filter(Business.id == business_id).first()
    if business is None:
        raise HTTPException(status_code=404, detail="Business not found")
    return business


def _session_cookie(request: Request) -> str:
    value = request.cookies.get(SESSION_COOKIE, "")
    if not value:
        raise HTTPException(status_code=401, detail="Authentication required")
    return value


@admin_router.post("/oauth/start")
def start_admin_instagram_oauth(
    business_slug: str,
    payload: InstagramOAuthStartRequest,
    request: Request,
    actor: User = Depends(require_business_admin),
    db: Session = Depends(get_db),
):
    business = _business_by_slug(db, business_slug)
    role = "owner"
    if not actor.is_owner:
        membership = get_business_membership(
            db, business_slug=business.slug, user_id=actor.id
        )
        if membership is None or membership.role != "business_admin":
            raise HTTPException(status_code=403, detail="Business administrator access required")
        role = membership.role
    control = get_channel_control(db, business_id=business.id, channel="instagram")
    if control is None:
        raise HTTPException(status_code=404, detail="Instagram access has not been granted")
    attempt, authorization_url = start_instagram_oauth(
        db,
        business=business,
        control=control,
        actor=actor,
        actor_role=role,
        session_token=_session_cookie(request),
        requested_purpose=payload.purpose,
    )
    record_audit(
        db,
        action="instagram_oauth_started",
        request=request,
        actor=actor,
        business_id=business.id,
        resource_type="instagram_oauth_attempt",
        resource_id=attempt.id,
        metadata={"attempt_id": attempt.id, "purpose": attempt.purpose},
        commit=False,
    )
    db.commit()
    return {
        "authorization_url": authorization_url,
        "attempt_id": attempt.id,
        "expires_at": attempt.expires_at.isoformat(),
    }


@owner_router.post("/start")
def start_owner_instagram_oauth(
    business_id: int,
    payload: InstagramOAuthStartRequest,
    request: Request,
    actor: User = Depends(require_owner),
    db: Session = Depends(get_db),
):
    business = _business_by_id(db, business_id)
    control = get_channel_control(db, business_id=business.id, channel="instagram")
    if control is None:
        raise HTTPException(status_code=404, detail="Instagram access has not been granted")
    attempt, authorization_url = start_instagram_oauth(
        db,
        business=business,
        control=control,
        actor=actor,
        actor_role="owner",
        session_token=_session_cookie(request),
        requested_purpose=payload.purpose,
        owner_return=True,
    )
    record_audit(
        db,
        action="instagram_oauth_started",
        request=request,
        actor=actor,
        business_id=business.id,
        resource_type="instagram_oauth_attempt",
        resource_id=attempt.id,
        metadata={"attempt_id": attempt.id, "purpose": attempt.purpose},
        commit=False,
    )
    db.commit()
    return {
        "authorization_url": authorization_url,
        "attempt_id": attempt.id,
        "expires_at": attempt.expires_at.isoformat(),
    }


@callback_router.get("/callback")
def instagram_oauth_callback(
    request: Request,
    state: str = Query(min_length=32, max_length=512),
    code: str | None = Query(default=None, max_length=2048),
    error: str | None = Query(default=None, max_length=120),
    error_reason: str | None = Query(default=None, max_length=120),
    error_description: str | None = Query(default=None, max_length=500),
    actor: User | None = Depends(get_optional_current_user),
    db: Session = Depends(get_db),
):
    # Provider error text is never persisted or reflected.
    del error_reason, error_description
    if actor is None or not actor.is_active:
        raise HTTPException(status_code=401, detail="Authentication required")
    attempt = complete_instagram_oauth_callback(
        db,
        opaque_state=state,
        authorization_code=code,
        provider_denied=error is not None,
        actor=actor,
        session_token=_session_cookie(request),
    )
    record_audit(
        db,
        action=(
            "instagram_oauth_candidate_ready"
            if attempt.status == "candidate_ready"
            else "instagram_oauth_failed"
        ),
        request=request,
        actor=actor,
        business_id=attempt.business_id,
        resource_type="instagram_oauth_attempt",
        resource_id=attempt.id,
        metadata={
            "attempt_id": attempt.id,
            "purpose": attempt.purpose,
            "new_status": attempt.status,
            "safe_error_code": attempt.safe_error_code,
        },
        commit=False,
    )
    db.commit()
    return_path = safe_instagram_return_path(attempt.return_path)
    separator = "&" if "?" in return_path else "?"
    result = "pending_review" if attempt.status == "candidate_ready" else "failed"
    return RedirectResponse(
        url=f"{return_path}{separator}instagram_oauth={result}",
        status_code=303,
    )


@owner_router.get("/candidates")
def list_owner_instagram_oauth_candidates(
    business_id: int,
    actor: User = Depends(require_owner),
    db: Session = Depends(get_db),
):
    require_owner(actor)
    _business_by_id(db, business_id)
    expired = expire_instagram_oauth_attempts(db, business_id=business_id)
    if expired:
        db.commit()
    attempts = (
        db.query(InstagramOAuthAttempt)
        .filter(
            InstagramOAuthAttempt.business_id == business_id,
            InstagramOAuthAttempt.status == "candidate_ready",
        )
        .order_by(InstagramOAuthAttempt.created_at.desc(), InstagramOAuthAttempt.id.desc())
        .all()
    )
    return [serialize_instagram_oauth_attempt(item) for item in attempts]


@owner_router.post("/candidates/{attempt_id}/{decision}")
def decide_owner_instagram_oauth_candidate(
    business_id: int,
    attempt_id: int,
    decision: str,
    payload: ChannelDecisionRequest,
    request: Request,
    actor: User = Depends(require_owner),
    db: Session = Depends(get_db),
):
    require_owner(actor)
    _business_by_id(db, business_id)
    if decision not in {"approve", "reject"}:
        raise HTTPException(status_code=404, detail="Owner decision not supported")
    attempt, integration = decide_instagram_oauth_candidate(
        db,
        business_id=business_id,
        attempt_id=attempt_id,
        actor=actor,
        approve=decision == "approve",
        reason=payload.reason,
    )
    record_audit(
        db,
        action=f"instagram_oauth_candidate_{'approved' if decision == 'approve' else 'rejected'}",
        request=request,
        actor=actor,
        business_id=business_id,
        resource_type="instagram_oauth_attempt",
        resource_id=attempt.id,
        metadata={
            "attempt_id": attempt.id,
            "purpose": attempt.purpose,
            "integration_id": integration.id if integration else None,
            "reason": payload.reason,
        },
        commit=False,
    )
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(
            status_code=409, detail="Instagram account belongs to another business"
        ) from exc
    return {
        "candidate": serialize_instagram_oauth_attempt(attempt),
        "integration_id": integration.id if integration else None,
    }


@owner_router.post("/candidates/{attempt_id}/webhook/retry")
def retry_owner_instagram_candidate_webhook(
    business_id: int,
    attempt_id: int,
    request: Request,
    actor: User = Depends(require_owner),
    db: Session = Depends(get_db),
):
    require_owner(actor)
    _business_by_id(db, business_id)
    attempt = retry_instagram_candidate_webhook(
        db,
        business_id=business_id,
        attempt_id=attempt_id,
    )
    record_audit(
        db,
        action="instagram_webhook_subscription_retried",
        request=request,
        actor=actor,
        business_id=business_id,
        resource_type="instagram_oauth_attempt",
        resource_id=attempt.id,
        metadata={
            "attempt_id": attempt.id,
            "result": attempt.webhook_subscription_status,
            "safe_error_code": attempt.safe_error_code,
        },
        commit=False,
    )
    db.commit()
    return serialize_instagram_oauth_attempt(attempt)
