from __future__ import annotations

from datetime import datetime, timezone

from fastapi import HTTPException
from sqlalchemy.orm import Session

from app.core.config import Settings, get_settings
from app.models import BusinessChannelControl, User
from app.models.business_channel_control import (
    CHANNEL_CONNECTOR_POLICIES,
    CONTROLLED_CHANNELS,
)


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def validate_controlled_channel(channel: str) -> str:
    normalized = channel.strip().lower()
    if normalized not in CONTROLLED_CHANNELS:
        raise HTTPException(status_code=404, detail="Channel not supported for onboarding")
    return normalized


def get_channel_control(
    db: Session,
    *,
    business_id: int,
    channel: str,
) -> BusinessChannelControl | None:
    normalized = validate_controlled_channel(channel)
    return (
        db.query(BusinessChannelControl)
        .filter(
            BusinessChannelControl.business_id == business_id,
            BusinessChannelControl.channel == normalized,
        )
        .first()
    )


def serialize_channel_control(
    control: BusinessChannelControl | None,
    *,
    channel: str,
    actor_is_owner: bool = False,
    actor_role: str | None = None,
    include_internal: bool = False,
) -> dict:
    normalized = validate_controlled_channel(channel)
    if control is None:
        return {
            "id": None,
            "channel": normalized,
            "status": "not_allowed",
            "connector_policy": None,
            "connection_mode": "simulated",
            "request_allowed": False,
            "can_request": False,
            "integrated_delivery_enabled": False,
            "automation_enabled": False,
            "requested_at": None,
            "approved_at": None,
            "suspended_at": None,
            "revoked_at": None,
            "last_reason": None,
            "updated_at": None,
        }
    request_allowed = control.status == "available"
    can_request = request_allowed and (
        actor_is_owner
        or (actor_role == "business_admin" and control.connector_policy == "business_admin")
    )
    return {
        "id": control.id,
        "channel": control.channel,
        "status": control.status,
        "connector_policy": control.connector_policy,
        "connection_mode": control.connection_mode,
        "request_allowed": request_allowed,
        "can_request": can_request,
        "integrated_delivery_enabled": control.integrated_delivery_enabled,
        "automation_enabled": control.automation_enabled,
        "requested_at": control.requested_at,
        "approved_at": control.approved_at,
        "suspended_at": control.suspended_at,
        "revoked_at": control.revoked_at,
        "last_reason": control.last_reason if include_internal else None,
        "updated_at": control.updated_at,
    }


def grant_channel_access(
    db: Session,
    *,
    business_id: int,
    channel: str,
    connector_policy: str,
    actor: User,
    reason: str,
) -> tuple[BusinessChannelControl, str | None]:
    normalized = validate_controlled_channel(channel)
    if connector_policy not in CHANNEL_CONNECTOR_POLICIES:
        raise HTTPException(status_code=422, detail="Invalid connector policy")
    control = get_channel_control(db, business_id=business_id, channel=normalized)
    previous_status = control.status if control is not None else None
    if control is None:
        control = BusinessChannelControl(
            business_id=business_id,
            channel=normalized,
            status="available",
            connector_policy=connector_policy,
            created_by_user_id=actor.id,
        )
        db.add(control)
    else:
        control.connector_policy = connector_policy
        if control.status in {"suspended", "revoked"}:
            control.status = "available"
            control.requested_by_user_id = None
            control.requested_at = None
            control.approved_by_user_id = None
            control.approved_at = None
            control.suspended_at = None
            control.revoked_at = None
            control.integrated_delivery_enabled = False
            control.automation_enabled = False
            control.connection_mode = "simulated"
    control.updated_by_user_id = actor.id
    if normalized == "instagram":
        control.connection_mode = "oauth"
    control.last_reason = reason
    db.flush()
    return control, previous_status


def request_simulated_connection(
    db: Session,
    *,
    control: BusinessChannelControl,
    actor: User,
    actor_role: str | None,
    settings: Settings | None = None,
) -> bool:
    settings = settings or get_settings()
    if control.channel == "instagram" and not (
        settings.app_env == "test" and settings.instagram_simulated_onboarding_test_only
    ):
        raise HTTPException(
            status_code=410,
            detail="Instagram simulation is disabled; use Instagram Login",
        )
    if control.status == "pending_approval" and control.requested_by_user_id == actor.id:
        return False
    if control.status != "available":
        raise HTTPException(status_code=409, detail="Channel is not available for connection")
    if not actor.is_owner and not (
        actor_role == "business_admin" and control.connector_policy == "business_admin"
    ):
        raise HTTPException(status_code=403, detail="You cannot connect assets for this channel")
    control.status = "pending_approval"
    control.connection_mode = "simulated"
    control.requested_by_user_id = actor.id
    control.requested_at = utc_now()
    control.approved_by_user_id = None
    control.approved_at = None
    control.integrated_delivery_enabled = False
    control.automation_enabled = False
    control.updated_by_user_id = actor.id
    control.last_reason = "Simulated connection requested"
    db.flush()
    return True


def approve_channel_connection(
    db: Session,
    *,
    control: BusinessChannelControl,
    actor: User,
    reason: str,
) -> None:
    if control.status != "pending_approval":
        raise HTTPException(status_code=409, detail="Channel is not pending approval")
    control.status = "approved"
    control.approved_by_user_id = actor.id
    control.approved_at = utc_now()
    control.integrated_delivery_enabled = False
    control.automation_enabled = False
    control.updated_by_user_id = actor.id
    control.last_reason = reason
    db.flush()


def configure_channel_capabilities(
    db: Session,
    *,
    control: BusinessChannelControl,
    actor: User,
    integrated_delivery_enabled: bool | None,
    automation_enabled: bool | None,
    reason: str,
) -> None:
    if control.status != "approved":
        raise HTTPException(status_code=409, detail="Channel must be approved first")
    if integrated_delivery_enabled is None and automation_enabled is None:
        raise HTTPException(status_code=422, detail="At least one capability must be provided")
    if integrated_delivery_enabled is not None:
        control.integrated_delivery_enabled = integrated_delivery_enabled
    if automation_enabled is not None:
        control.automation_enabled = automation_enabled
    control.updated_by_user_id = actor.id
    control.last_reason = reason
    db.flush()


def stop_channel_access(
    db: Session,
    *,
    control: BusinessChannelControl,
    actor: User,
    action: str,
    reason: str,
) -> None:
    if action not in {"suspend", "revoke"}:
        raise HTTPException(status_code=422, detail="Invalid channel control action")
    if control.status == "revoked":
        raise HTTPException(status_code=409, detail="Channel access is already revoked")
    now = utc_now()
    control.status = "suspended" if action == "suspend" else "revoked"
    control.integrated_delivery_enabled = False
    control.automation_enabled = False
    control.suspended_at = now if action == "suspend" else control.suspended_at
    control.revoked_at = now if action == "revoke" else None
    control.updated_by_user_id = actor.id
    control.last_reason = reason
    db.flush()


def integrated_delivery_is_authorized(
    db: Session,
    *,
    business_id: int,
    channel: str,
) -> bool:
    if channel not in CONTROLLED_CHANNELS:
        return True
    control = get_channel_control(db, business_id=business_id, channel=channel)
    if control is None:
        # Existing integrations predate Sprint 4A. Migration 07 backfills their
        # controls; this fallback keeps isolated legacy/test databases operable.
        return True
    return control.status == "approved" and control.integrated_delivery_enabled


def channel_automation_is_authorized(
    db: Session,
    *,
    business_id: int,
    channel: str,
) -> bool:
    if channel not in CONTROLLED_CHANNELS:
        return True
    control = get_channel_control(db, business_id=business_id, channel=channel)
    if control is None:
        return True
    return control.status == "approved" and control.automation_enabled
