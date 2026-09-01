from __future__ import annotations

import json

from fastapi import APIRouter, Depends, HTTPException, Request
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
from app.models import (
    Business,
    BusinessChannelIntegration,
    MetaIntegrationJob,
    User,
)
from app.services.capability_service import require_module_available
from app.services.channel_control_service import get_channel_control
from app.services.instagram_oauth_service import start_instagram_oauth
from app.services.meta_integration_job_service import (
    enqueue_meta_integration_job,
    integration_health_metadata,
    serialize_integration_health,
    serialize_meta_integration_job,
)
from app.services.whatsapp_embedded_signup_service import start_whatsapp_embedded_signup

owner_router = APIRouter(
    prefix="/api/owner/businesses/{business_id}/channels",
    tags=["meta-integration-health"],
    dependencies=[Depends(require_owner), Depends(require_business_operational_status_by_id)],
)
admin_router = APIRouter(
    prefix="/api/admin/businesses/{business_slug}/channels",
    tags=["meta-integration-health"],
    dependencies=[Depends(require_business_admin)],
)

SUPPORTED_CHANNELS = {"instagram", "whatsapp"}


def _business_by_id(db: Session, business_id: int) -> Business:
    business = db.get(Business, business_id)
    if business is None:
        raise HTTPException(status_code=404, detail="Business not found")
    return business


def _business_by_slug(db: Session, business_slug: str) -> Business:
    business = db.query(Business).filter(Business.slug == business_slug).first()
    if business is None:
        raise HTTPException(status_code=404, detail="Business not found")
    return business


def _admin_role(db: Session, *, business: Business, actor: User) -> str:
    if actor.is_owner:
        return "owner"
    membership = get_business_membership(db, business_slug=business.slug, user_id=actor.id)
    if membership is None or membership.role != "business_admin":
        raise HTTPException(status_code=403, detail="Business administrator access required")
    return membership.role


def _session_cookie(request: Request) -> str:
    value = request.cookies.get(SESSION_COOKIE, "")
    if not value:
        raise HTTPException(status_code=401, detail="Authentication required")
    return value


def _channel(value: str) -> str:
    normalized = value.strip().lower()
    if normalized not in SUPPORTED_CHANNELS:
        raise HTTPException(status_code=404, detail="Channel not supported")
    return normalized


def _integration(db: Session, *, business_id: int, channel: str) -> BusinessChannelIntegration:
    normalized = _channel(channel)
    integration = (
        db.query(BusinessChannelIntegration)
        .filter(
            BusinessChannelIntegration.business_id == business_id,
            BusinessChannelIntegration.channel == normalized,
            BusinessChannelIntegration.provider == normalized,
        )
        .first()
    )
    if integration is None:
        raise HTTPException(status_code=404, detail="Channel integration not found")
    return integration


def _health_list(db: Session, *, business: Business, include_internal: bool) -> dict:
    integrations = (
        db.query(BusinessChannelIntegration)
        .filter(
            BusinessChannelIntegration.business_id == business.id,
            BusinessChannelIntegration.channel.in_(SUPPORTED_CHANNELS),
        )
        .order_by(BusinessChannelIntegration.channel)
        .all()
    )
    return {
        "business": {"id": business.id, "slug": business.slug, "name": business.name},
        "channels": [
            serialize_integration_health(
                integration,
                control=get_channel_control(
                    db, business_id=business.id, channel=integration.channel
                ),
                include_internal=include_internal,
            )
            for integration in integrations
        ],
    }


def _queue(
    db: Session,
    *,
    integration: BusinessChannelIntegration,
    job_type: str,
    origin: str,
    actor: User,
) -> dict:
    job, created = enqueue_meta_integration_job(
        db,
        business_id=integration.business_id,
        integration_id=integration.id,
        job_type=job_type,
        origin=origin,
        actor_user_id=actor.id,
    )
    db.commit()
    return {"queued": True, "created": created, "job": serialize_meta_integration_job(job)}


@owner_router.get("/health")
def owner_health(
    business_id: int,
    actor: User = Depends(require_owner),
    db: Session = Depends(get_db),
):
    del actor
    return _health_list(db, business=_business_by_id(db, business_id), include_internal=True)


@admin_router.get("/health")
def admin_health(
    business_slug: str,
    actor: User = Depends(require_business_admin),
    db: Session = Depends(get_db),
):
    business = _business_by_slug(db, business_slug)
    _admin_role(db, business=business, actor=actor)
    return _health_list(db, business=business, include_internal=False)


@owner_router.post("/{channel}/health-check", status_code=202)
def owner_health_check(
    business_id: int,
    channel: str,
    actor: User = Depends(require_owner),
    db: Session = Depends(get_db),
):
    _business_by_id(db, business_id)
    return _queue(
        db,
        integration=_integration(db, business_id=business_id, channel=channel),
        job_type="health_check",
        origin="owner",
        actor=actor,
    )


@admin_router.post("/{channel}/health-check", status_code=202)
def admin_health_check(
    business_slug: str,
    channel: str,
    actor: User = Depends(require_business_admin),
    db: Session = Depends(get_db),
):
    business = _business_by_slug(db, business_slug)
    _admin_role(db, business=business, actor=actor)
    control = get_channel_control(db, business_id=business.id, channel=_channel(channel))
    if control is None or control.status not in {"available", "approved"}:
        raise HTTPException(status_code=403, detail="Channel health check is not allowed")
    return _queue(
        db,
        integration=_integration(db, business_id=business.id, channel=channel),
        job_type="health_check",
        origin="admin",
        actor=actor,
    )


@owner_router.post("/{channel}/retry-subscription", status_code=202)
def owner_retry_subscription(
    business_id: int,
    channel: str,
    actor: User = Depends(require_owner),
    db: Session = Depends(get_db),
):
    business = _business_by_id(db, business_id)
    if _channel(channel) == "instagram":
        require_module_available(db, business.id, "social")
    return _queue(
        db,
        integration=_integration(db, business_id=business_id, channel=channel),
        job_type="retry_subscription",
        origin="owner",
        actor=actor,
    )


def _request_reconnection(
    db: Session,
    *,
    business: Business,
    channel: str,
    actor: User,
    actor_role: str,
    request: Request,
    owner_return: bool,
) -> dict:
    normalized = _channel(channel)
    if normalized == "instagram":
        require_module_available(db, business.id, "social")
    integration = _integration(db, business_id=business.id, channel=normalized)
    control = get_channel_control(db, business_id=business.id, channel=normalized)
    if control is None:
        raise HTTPException(status_code=404, detail="Channel access has not been granted")
    if normalized == "instagram":
        instagram_attempt, authorization_url = start_instagram_oauth(
            db,
            business=business,
            control=control,
            actor=actor,
            actor_role=actor_role,
            session_token=_session_cookie(request),
            requested_purpose="reconnect",
            owner_return=owner_return,
        )
        attempt_id = instagram_attempt.id
        response = {
            "channel": normalized,
            "attempt_id": attempt_id,
            "authorization_url": authorization_url,
            "expires_at": instagram_attempt.expires_at,
        }
    else:
        whatsapp_attempt, state, public_configuration = start_whatsapp_embedded_signup(
            db,
            business=business,
            control=control,
            actor=actor,
            actor_role=actor_role,
            session_token=_session_cookie(request),
            requested_purpose="reconnect",
        )
        attempt_id = whatsapp_attempt.id
        response = {
            "channel": normalized,
            "attempt_id": attempt_id,
            "state": state,
            "expires_at": whatsapp_attempt.expires_at,
            "public_configuration": public_configuration,
        }
    health_metadata = integration_health_metadata(integration)
    health_metadata["reconnection_required"] = True
    integration.health_metadata_json = json.dumps(health_metadata, sort_keys=True)
    record_audit(
        db,
        action="reconnection_requested",
        request=request,
        actor=actor,
        business_id=business.id,
        resource_type="business_channel_integration",
        resource_id=integration.id,
        metadata={"channel": normalized, "attempt_id": attempt_id},
        commit=False,
    )
    db.commit()
    return response


@owner_router.post("/{channel}/request-reconnection")
def owner_request_reconnection(
    business_id: int,
    channel: str,
    request: Request,
    actor: User = Depends(require_owner),
    db: Session = Depends(get_db),
):
    return _request_reconnection(
        db,
        business=_business_by_id(db, business_id),
        channel=channel,
        actor=actor,
        actor_role="owner",
        request=request,
        owner_return=True,
    )


@admin_router.post("/{channel}/reconnect")
def admin_request_reconnection(
    business_slug: str,
    channel: str,
    request: Request,
    actor: User = Depends(require_business_admin),
    db: Session = Depends(get_db),
):
    business = _business_by_slug(db, business_slug)
    return _request_reconnection(
        db,
        business=business,
        channel=channel,
        actor=actor,
        actor_role=_admin_role(db, business=business, actor=actor),
        request=request,
        owner_return=actor.is_owner,
    )


@owner_router.get("/jobs")
def owner_recent_jobs(
    business_id: int,
    actor: User = Depends(require_owner),
    db: Session = Depends(get_db),
):
    del actor
    _business_by_id(db, business_id)
    jobs = (
        db.query(MetaIntegrationJob)
        .filter(MetaIntegrationJob.business_id == business_id)
        .order_by(MetaIntegrationJob.created_at.desc(), MetaIntegrationJob.id.desc())
        .limit(100)
        .all()
    )
    return {"jobs": [serialize_meta_integration_job(job) for job in jobs]}
