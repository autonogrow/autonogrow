from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.orm import Session

from app.core.audit import record_audit
from app.core.database import get_db
from app.core.security import (
    get_business_membership,
    require_business_admin,
    require_business_operational_status_by_id,
    require_owner,
)
from app.models import (
    Business,
    BusinessChannelControl,
    BusinessChannelIntegration,
    InstagramOAuthAttempt,
    User,
)
from app.schemas.channel_onboarding import (
    ChannelAccessGrantRequest,
    ChannelCapabilitiesUpdate,
    ChannelDecisionRequest,
    SimulatedConnectionRequest,
)
from app.services.capability_service import require_module_available
from app.services.channel_control_service import (
    approve_channel_connection,
    configure_channel_capabilities,
    get_channel_control,
    grant_channel_access,
    request_simulated_connection,
    serialize_channel_control,
    stop_channel_access,
    validate_controlled_channel,
)
from app.services.instagram_oauth_service import invalidate_instagram_oauth_attempts
from app.services.whatsapp_embedded_signup_service import (
    invalidate_whatsapp_signup_attempts,
)

admin_router = APIRouter(
    prefix="/api/admin/businesses/{business_slug}/channel-onboarding",
    tags=["channel-onboarding"],
)
owner_router = APIRouter(
    prefix="/api/owner/businesses/{business_id}/channel-controls",
    tags=["owner-channel-controls"],
    dependencies=[Depends(require_owner), Depends(require_business_operational_status_by_id)],
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


def _admin_role(db: Session, *, business: Business, actor: User) -> str:
    if actor.is_owner:
        return "owner"
    membership = get_business_membership(
        db,
        business_slug=business.slug,
        user_id=actor.id,
    )
    if membership is None or membership.role != "business_admin":
        raise HTTPException(status_code=403, detail="Business administrator access required")
    return membership.role


def _control_or_404(
    db: Session,
    *,
    business_id: int,
    channel: str,
) -> BusinessChannelControl:
    control = get_channel_control(db, business_id=business_id, channel=channel)
    if control is None:
        raise HTTPException(status_code=404, detail="Channel access has not been granted")
    return control


def _require_channel_module(db: Session, *, business_id: int, channel: str) -> None:
    if validate_controlled_channel(channel) == "instagram":
        require_module_available(db, business_id, "social")


def _audit(
    db: Session,
    *,
    request: Request,
    actor: User,
    business_id: int,
    control: BusinessChannelControl,
    action: str,
    metadata: dict,
) -> None:
    record_audit(
        db,
        action=action,
        request=request,
        actor=actor,
        business_id=business_id,
        resource_type="business_channel_control",
        resource_id=control.id,
        metadata={"channel": control.channel, **metadata},
        commit=False,
    )


def _client_channel_payload(
    db: Session,
    *,
    business_id: int,
    channel: str,
    actor: User,
    actor_role: str,
) -> dict:
    payload = serialize_channel_control(
        get_channel_control(db, business_id=business_id, channel=channel),
        channel=channel,
        actor_is_owner=actor.is_owner,
        actor_role=actor_role,
    )
    if channel != "instagram":
        return payload
    candidate = (
        db.query(InstagramOAuthAttempt)
        .filter(
            InstagramOAuthAttempt.business_id == business_id,
            InstagramOAuthAttempt.status == "candidate_ready",
        )
        .order_by(InstagramOAuthAttempt.created_at.desc(), InstagramOAuthAttempt.id.desc())
        .first()
    )
    integration = (
        db.query(BusinessChannelIntegration)
        .filter(
            BusinessChannelIntegration.business_id == business_id,
            BusinessChannelIntegration.provider == "instagram",
        )
        .first()
    )
    payload.update(
        {
            "connected_account_name": (
                candidate.candidate_external_account_name
                if candidate
                else (integration.external_account_name if integration else None)
            ),
            "oauth_status": (
                "pending_review"
                if candidate
                else (integration.integration_status if integration else None)
            ),
            "reconnect_required": bool(
                integration
                and integration.integration_status
                in {"degraded", "expired", "disconnected", "revoked", "error"}
            ),
        }
    )
    return payload


@admin_router.get("", dependencies=[Depends(require_business_admin)])
def get_business_channel_onboarding(
    business_slug: str,
    actor: User = Depends(require_business_admin),
    db: Session = Depends(get_db),
):
    business = _business_by_slug(db, business_slug)
    role = _admin_role(db, business=business, actor=actor)
    return {
        "business": {"id": business.id, "slug": business.slug, "name": business.name},
        "channels": [
            _client_channel_payload(
                db,
                business_id=business.id,
                channel=channel,
                actor_role=role,
                actor=actor,
            )
            for channel in ("instagram", "whatsapp")
        ],
        "connection_mode": "oauth_primary",
        "accepts_credentials": False,
    }


@admin_router.post("/{channel}/request", dependencies=[Depends(require_business_admin)])
def request_business_channel_connection(
    business_slug: str,
    channel: str,
    payload: SimulatedConnectionRequest,
    request: Request,
    actor: User = Depends(require_business_admin),
    db: Session = Depends(get_db),
):
    business = _business_by_slug(db, business_slug)
    role = _admin_role(db, business=business, actor=actor)
    normalized = validate_controlled_channel(channel)
    _require_channel_module(db, business_id=business.id, channel=normalized)
    control = _control_or_404(db, business_id=business.id, channel=normalized)
    changed = request_simulated_connection(db, control=control, actor=actor, actor_role=role)
    if changed:
        _audit(
            db,
            request=request,
            actor=actor,
            business_id=business.id,
            control=control,
            action="channel_connection_requested",
            metadata={
                "connection_mode": "simulated",
                "connector_policy": control.connector_policy,
                "new_status": control.status,
            },
        )
    db.commit()
    db.refresh(control)
    return serialize_channel_control(
        control,
        channel=normalized,
        actor_is_owner=actor.is_owner,
        actor_role=role,
    )


@owner_router.get("")
def list_owner_channel_controls(
    business_id: int,
    actor: User = Depends(require_owner),
    db: Session = Depends(get_db),
):
    require_owner(actor)
    business = _business_by_id(db, business_id)
    return {
        "business": {"id": business.id, "slug": business.slug, "name": business.name},
        "channels": [
            serialize_channel_control(
                get_channel_control(db, business_id=business.id, channel=channel),
                channel=channel,
                actor_is_owner=True,
                actor_role="owner",
                include_internal=True,
            )
            for channel in ("instagram", "whatsapp")
        ],
        "connection_mode": "oauth_primary",
        "accepts_credentials": False,
    }


@owner_router.put("/{channel}/access")
def grant_owner_channel_access(
    business_id: int,
    channel: str,
    payload: ChannelAccessGrantRequest,
    request: Request,
    actor: User = Depends(require_owner),
    db: Session = Depends(get_db),
):
    require_owner(actor)
    _business_by_id(db, business_id)
    _require_channel_module(db, business_id=business_id, channel=channel)
    control, previous_status = grant_channel_access(
        db,
        business_id=business_id,
        channel=channel,
        connector_policy=payload.connector_policy,
        actor=actor,
        reason=payload.reason,
    )
    _audit(
        db,
        request=request,
        actor=actor,
        business_id=business_id,
        control=control,
        action="channel_access_granted",
        metadata={
            "old_status": previous_status,
            "new_status": control.status,
            "connector_policy": control.connector_policy,
            "reason": payload.reason,
        },
    )
    db.commit()
    db.refresh(control)
    return serialize_channel_control(
        control,
        channel=control.channel,
        actor_is_owner=True,
        actor_role="owner",
        include_internal=True,
    )


@owner_router.post("/{channel}/request")
def request_owner_channel_connection(
    business_id: int,
    channel: str,
    payload: SimulatedConnectionRequest,
    request: Request,
    actor: User = Depends(require_owner),
    db: Session = Depends(get_db),
):
    require_owner(actor)
    _business_by_id(db, business_id)
    _require_channel_module(db, business_id=business_id, channel=channel)
    control = _control_or_404(db, business_id=business_id, channel=channel)
    changed = request_simulated_connection(db, control=control, actor=actor, actor_role="owner")
    if changed:
        _audit(
            db,
            request=request,
            actor=actor,
            business_id=business_id,
            control=control,
            action="channel_connection_requested",
            metadata={"connection_mode": "simulated", "new_status": control.status},
        )
    db.commit()
    db.refresh(control)
    return serialize_channel_control(
        control,
        channel=control.channel,
        actor_is_owner=True,
        actor_role="owner",
        include_internal=True,
    )


@owner_router.post("/{channel}/approve")
def approve_owner_channel_connection(
    business_id: int,
    channel: str,
    payload: ChannelDecisionRequest,
    request: Request,
    actor: User = Depends(require_owner),
    db: Session = Depends(get_db),
):
    require_owner(actor)
    _business_by_id(db, business_id)
    _require_channel_module(db, business_id=business_id, channel=channel)
    control = _control_or_404(db, business_id=business_id, channel=channel)
    if control.channel == "instagram" and control.connection_mode == "oauth":
        raise HTTPException(
            status_code=409,
            detail="Approve the reviewed Instagram OAuth candidate instead",
        )
    if control.channel == "whatsapp" and control.connection_mode == "embedded_signup":
        raise HTTPException(
            status_code=409,
            detail="Approve the reviewed WhatsApp Embedded Signup candidate instead",
        )
    old_status = control.status
    approve_channel_connection(db, control=control, actor=actor, reason=payload.reason)
    _audit(
        db,
        request=request,
        actor=actor,
        business_id=business_id,
        control=control,
        action="channel_connection_approved",
        metadata={
            "old_status": old_status,
            "new_status": control.status,
            "integrated_delivery_enabled": False,
            "automation_enabled": False,
            "reason": payload.reason,
        },
    )
    db.commit()
    db.refresh(control)
    return serialize_channel_control(
        control,
        channel=control.channel,
        actor_is_owner=True,
        actor_role="owner",
        include_internal=True,
    )


@owner_router.patch("/{channel}/capabilities")
def update_owner_channel_capabilities(
    business_id: int,
    channel: str,
    payload: ChannelCapabilitiesUpdate,
    request: Request,
    actor: User = Depends(require_owner),
    db: Session = Depends(get_db),
):
    require_owner(actor)
    _business_by_id(db, business_id)
    _require_channel_module(db, business_id=business_id, channel=channel)
    control = _control_or_404(db, business_id=business_id, channel=channel)
    old_values = {
        "integrated_delivery_enabled": control.integrated_delivery_enabled,
        "automation_enabled": control.automation_enabled,
    }
    configure_channel_capabilities(
        db,
        control=control,
        actor=actor,
        integrated_delivery_enabled=payload.integrated_delivery_enabled,
        automation_enabled=payload.automation_enabled,
        reason=payload.reason,
    )
    _audit(
        db,
        request=request,
        actor=actor,
        business_id=business_id,
        control=control,
        action="channel_capabilities_updated",
        metadata={
            "old_values": old_values,
            "new_values": {
                "integrated_delivery_enabled": control.integrated_delivery_enabled,
                "automation_enabled": control.automation_enabled,
            },
            "reason": payload.reason,
        },
    )
    db.commit()
    db.refresh(control)
    return serialize_channel_control(
        control,
        channel=control.channel,
        actor_is_owner=True,
        actor_role="owner",
        include_internal=True,
    )


@owner_router.post("/{channel}/{action}")
def stop_owner_channel_access(
    business_id: int,
    channel: str,
    action: str,
    payload: ChannelDecisionRequest,
    request: Request,
    actor: User = Depends(require_owner),
    db: Session = Depends(get_db),
):
    require_owner(actor)
    _business_by_id(db, business_id)
    control = _control_or_404(db, business_id=business_id, channel=channel)
    old_status = control.status
    stop_channel_access(
        db,
        control=control,
        actor=actor,
        action=action,
        reason=payload.reason,
    )
    cancelled_attempts = 0
    if control.channel == "instagram":
        cancelled_attempts = invalidate_instagram_oauth_attempts(
            db,
            business_id=business_id,
            safe_code=f"channel_{action}",
        )
    elif control.channel == "whatsapp":
        cancelled_attempts = invalidate_whatsapp_signup_attempts(
            db,
            business_id=business_id,
            safe_code=f"channel_{action}",
        )
    _audit(
        db,
        request=request,
        actor=actor,
        business_id=business_id,
        control=control,
        action={"suspend": "channel_access_suspended", "revoke": "channel_access_revoked"}.get(
            action,
            "channel_access_changed",
        ),
        metadata={
            "old_status": old_status,
            "new_status": control.status,
            "integrated_delivery_enabled": False,
            "automation_enabled": False,
            "reason": payload.reason,
            "cancelled_oauth_attempts": cancelled_attempts,
        },
    )
    db.commit()
    db.refresh(control)
    return serialize_channel_control(
        control,
        channel=control.channel,
        actor_is_owner=True,
        actor_role="owner",
        include_internal=True,
    )
