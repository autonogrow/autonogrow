from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.audit import record_audit
from app.core.database import get_db
from app.core.security import (
    SESSION_COOKIE,
    get_business_membership,
    require_business_admin,
    require_business_operational_status_by_id,
    require_owner,
)
from app.models import Business, User, WhatsAppEmbeddedSignupAttempt
from app.schemas.channel_onboarding import ChannelDecisionRequest
from app.schemas.whatsapp_embedded_signup import (
    WhatsAppEmbeddedSignupCompleteRequest,
    WhatsAppEmbeddedSignupStartRequest,
)
from app.services.channel_control_service import get_channel_control
from app.services.whatsapp_embedded_signup_service import (
    complete_whatsapp_embedded_signup,
    decide_whatsapp_signup_candidate,
    expire_whatsapp_signup_attempts,
    retry_whatsapp_candidate_setup,
    serialize_whatsapp_signup_attempt,
    start_whatsapp_embedded_signup,
)

admin_router = APIRouter(
    prefix="/api/admin/businesses/{business_slug}/integrations/whatsapp/embedded-signup",
    tags=["whatsapp-embedded-signup"],
    dependencies=[Depends(require_business_admin)],
)
owner_router = APIRouter(
    prefix="/api/owner/businesses/{business_id}/integrations/whatsapp/embedded-signup",
    tags=["owner-whatsapp-embedded-signup"],
    dependencies=[Depends(require_owner), Depends(require_business_operational_status_by_id)],
)


def _business_by_slug(db: Session, business_slug: str) -> Business:
    business = db.query(Business).filter(Business.slug == business_slug).first()
    if business is None:
        raise HTTPException(status_code=404, detail="Business not found")
    return business


def _business_by_id(db: Session, business_id: int) -> Business:
    business = db.get(Business, business_id)
    if business is None:
        raise HTTPException(status_code=404, detail="Business not found")
    return business


def _session_cookie(request: Request) -> str:
    value = request.cookies.get(SESSION_COOKIE, "")
    if not value:
        raise HTTPException(status_code=401, detail="Authentication required")
    return value


def _admin_role(db: Session, *, business: Business, actor: User) -> str:
    if actor.is_owner:
        return "owner"
    membership = get_business_membership(db, business_slug=business.slug, user_id=actor.id)
    if membership is None or membership.role != "business_admin":
        raise HTTPException(status_code=403, detail="Business administrator access required")
    return membership.role


def _start(
    db: Session,
    *,
    business: Business,
    actor: User,
    actor_role: str,
    payload: WhatsAppEmbeddedSignupStartRequest,
    request: Request,
) -> dict:
    control = get_channel_control(db, business_id=business.id, channel="whatsapp")
    if control is None:
        raise HTTPException(status_code=404, detail="WhatsApp access has not been granted")
    attempt, state, public_configuration = start_whatsapp_embedded_signup(
        db,
        business=business,
        control=control,
        actor=actor,
        actor_role=actor_role,
        session_token=_session_cookie(request),
        requested_purpose=payload.purpose,
    )
    record_audit(
        db,
        action="whatsapp_embedded_signup_started",
        request=request,
        actor=actor,
        business_id=business.id,
        resource_type="whatsapp_embedded_signup_attempt",
        resource_id=attempt.id,
        metadata={"attempt_id": attempt.id, "purpose": attempt.purpose},
        commit=False,
    )
    if attempt.purpose != "initial_connection":
        record_audit(
            db,
            action="reconnection_requested",
            request=request,
            actor=actor,
            business_id=business.id,
            resource_type="whatsapp_embedded_signup_attempt",
            resource_id=attempt.id,
            metadata={"channel": "whatsapp", "attempt_id": attempt.id},
            commit=False,
        )
    db.commit()
    return {
        "attempt_id": attempt.id,
        "state": state,
        "expires_at": attempt.expires_at.isoformat(),
        "public_configuration": public_configuration,
    }


@admin_router.post("/start")
def start_admin_whatsapp_embedded_signup(
    business_slug: str,
    payload: WhatsAppEmbeddedSignupStartRequest,
    request: Request,
    actor: User = Depends(require_business_admin),
    db: Session = Depends(get_db),
):
    business = _business_by_slug(db, business_slug)
    return _start(
        db,
        business=business,
        actor=actor,
        actor_role=_admin_role(db, business=business, actor=actor),
        payload=payload,
        request=request,
    )


@admin_router.post("/complete")
def complete_admin_whatsapp_embedded_signup(
    business_slug: str,
    payload: WhatsAppEmbeddedSignupCompleteRequest,
    request: Request,
    actor: User = Depends(require_business_admin),
    db: Session = Depends(get_db),
):
    business = _business_by_slug(db, business_slug)
    _admin_role(db, business=business, actor=actor)
    attempt = complete_whatsapp_embedded_signup(
        db,
        business_id=business.id,
        opaque_state=payload.state,
        authorization_code=payload.code,
        event_type=payload.event_type,
        event_name=payload.event_name,
        meta_business_id=payload.meta_business_id,
        waba_id=payload.waba_id,
        phone_number_id=payload.phone_number_id,
        actor=actor,
        session_token=_session_cookie(request),
    )
    record_audit(
        db,
        action=f"whatsapp_embedded_signup_{attempt.status}",
        request=request,
        actor=actor,
        business_id=business.id,
        resource_type="whatsapp_embedded_signup_attempt",
        resource_id=attempt.id,
        metadata={
            "attempt_id": attempt.id,
            "purpose": attempt.purpose,
            "status": attempt.status,
            "safe_error_code": attempt.safe_error_code,
        },
        commit=False,
    )
    db.commit()
    return serialize_whatsapp_signup_attempt(attempt)


@owner_router.post("/start")
def start_owner_whatsapp_embedded_signup(
    business_id: int,
    payload: WhatsAppEmbeddedSignupStartRequest,
    request: Request,
    actor: User = Depends(require_owner),
    db: Session = Depends(get_db),
):
    return _start(
        db,
        business=_business_by_id(db, business_id),
        actor=actor,
        actor_role="owner",
        payload=payload,
        request=request,
    )


@owner_router.get("/candidates")
def list_owner_whatsapp_candidates(
    business_id: int,
    limit: Annotated[int, Query(ge=1, le=200)] = 100,
    actor: User = Depends(require_owner),
    db: Session = Depends(get_db),
):
    del actor
    _business_by_id(db, business_id)
    expired = expire_whatsapp_signup_attempts(db, business_id=business_id)
    if expired:
        db.commit()
    attempts = (
        db.query(WhatsAppEmbeddedSignupAttempt)
        .filter(
            WhatsAppEmbeddedSignupAttempt.business_id == business_id,
            WhatsAppEmbeddedSignupAttempt.status == "candidate_ready",
        )
        .order_by(
            WhatsAppEmbeddedSignupAttempt.created_at.desc(),
            WhatsAppEmbeddedSignupAttempt.id.desc(),
        )
        .limit(limit)
        .all()
    )
    return [serialize_whatsapp_signup_attempt(item) for item in attempts]


@owner_router.post("/candidates/{attempt_id}/{decision}")
def decide_owner_whatsapp_candidate(
    business_id: int,
    attempt_id: int,
    decision: str,
    payload: ChannelDecisionRequest,
    request: Request,
    actor: User = Depends(require_owner),
    db: Session = Depends(get_db),
):
    _business_by_id(db, business_id)
    if decision not in {"approve", "reject"}:
        raise HTTPException(status_code=404, detail="Owner decision not supported")
    attempt, integration = decide_whatsapp_signup_candidate(
        db,
        business_id=business_id,
        attempt_id=attempt_id,
        actor=actor,
        approve=decision == "approve",
        reason=payload.reason,
    )
    record_audit(
        db,
        action=f"whatsapp_candidate_{'approved' if decision == 'approve' else 'rejected'}",
        request=request,
        actor=actor,
        business_id=business_id,
        resource_type="whatsapp_embedded_signup_attempt",
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
            status_code=409, detail="WhatsApp assets belong to another account"
        ) from exc
    return {
        "candidate": serialize_whatsapp_signup_attempt(attempt),
        "integration_id": integration.id if integration else None,
    }


@owner_router.post("/candidates/{attempt_id}/setup/retry")
def retry_owner_whatsapp_candidate_setup(
    business_id: int,
    attempt_id: int,
    request: Request,
    actor: User = Depends(require_owner),
    db: Session = Depends(get_db),
):
    _business_by_id(db, business_id)
    attempt = retry_whatsapp_candidate_setup(db, business_id=business_id, attempt_id=attempt_id)
    record_audit(
        db,
        action="whatsapp_candidate_setup_retried",
        request=request,
        actor=actor,
        business_id=business_id,
        resource_type="whatsapp_embedded_signup_attempt",
        resource_id=attempt.id,
        metadata={
            "attempt_id": attempt.id,
            "app_subscription_status": attempt.app_subscription_status,
            "phone_registration_status": attempt.phone_registration_status,
            "safe_error_code": attempt.safe_error_code,
        },
        commit=False,
    )
    db.commit()
    return serialize_whatsapp_signup_attempt(attempt)
