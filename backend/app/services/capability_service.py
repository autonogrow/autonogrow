from __future__ import annotations

from decimal import Decimal
from typing import Iterable

from fastapi import Depends, HTTPException
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.security import require_business_access
from app.models import (
    Business,
    BusinessModuleAccess,
    ChannelOutboxMessage,
    ConversationMessage,
    InstagramPublishJob,
    MetaIntegrationJob,
    User,
)
from app.models.business_module import PRODUCT_MODULES

MODULE_UNAVAILABLE_DETAIL = "Este módulo no está disponible para este negocio."
MODULE_UNAVAILABLE_CODE = "module_not_available"


def _missing_configuration(module_key: str) -> dict[str, object]:
    """Represent absent commercial configuration without inferring access."""
    return {
        "module": module_key,
        "entitled": False,
        "active": False,
        "available": False,
        "configuration_source": "missing_configuration",
        "module_cost": None,
    }


def module_capabilities(db: Session, business_id: int) -> dict[str, dict[str, object]]:
    rows = {
        row.module_key: row
        for row in db.query(BusinessModuleAccess)
        .filter(BusinessModuleAccess.business_id == business_id)
        .all()
    }
    result: dict[str, dict[str, object]] = {}
    for module_key in PRODUCT_MODULES:
        row = rows.get(module_key)
        if row is None:
            result[module_key] = _missing_configuration(module_key)
            continue
        result[module_key] = {
            "module": module_key,
            "entitled": row.entitled,
            "active": row.active,
            "available": bool(row.entitled and row.active),
            "configuration_source": "business_module_access",
            "module_cost": (
                {
                    "amount": str(row.module_cost_amount),
                    "currency": row.module_cost_currency,
                    "period": row.module_cost_period,
                }
                if row.module_cost_amount is not None
                else None
            ),
        }
    return result


def module_is_available(db: Session, business_id: int, module_key: str) -> bool:
    if module_key not in PRODUCT_MODULES:
        return False
    row = (
        db.query(BusinessModuleAccess)
        .filter(
            BusinessModuleAccess.business_id == business_id,
            BusinessModuleAccess.module_key == module_key,
        )
        .first()
    )
    return bool(row and row.entitled and row.active)


def require_module_available(db: Session, business_id: int, module_key: str) -> None:
    if not module_is_available(db, business_id, module_key):
        raise HTTPException(
            status_code=403,
            detail={"code": MODULE_UNAVAILABLE_CODE, "message": MODULE_UNAVAILABLE_DETAIL},
        )


def freeze_module_jobs(db: Session, *, business_id: int, module_key: str) -> dict[str, int]:
    """Stop safely recoverable work so a later upgrade cannot revive stale actions."""
    outbox_rows: list[ChannelOutboxMessage] = []
    publication_rows: list[InstagramPublishJob] = []
    meta_rows: list[MetaIntegrationJob] = []
    if module_key == "social":
        outbox_rows.extend(
            db.query(ChannelOutboxMessage)
            .filter(
                ChannelOutboxMessage.business_id == business_id,
                ChannelOutboxMessage.channel == "instagram",
                ChannelOutboxMessage.status.in_(("pending", "retry", "processing")),
            )
            .all()
        )
        publication_rows = (
            db.query(InstagramPublishJob)
            .filter(
                InstagramPublishJob.business_id == business_id,
                InstagramPublishJob.status.in_(
                    ("queued", "retry_wait", "claimed", "simulating_publish")
                ),
            )
            .all()
        )
        meta_rows = (
            db.query(MetaIntegrationJob)
            .filter(
                MetaIntegrationJob.business_id == business_id,
                MetaIntegrationJob.job_type.in_(("instagram_media_sync", "retry_subscription")),
                MetaIntegrationJob.status.in_(("queued", "retry", "processing")),
            )
            .all()
        )
    elif module_key == "growth":
        outbox_rows = (
            db.query(ChannelOutboxMessage)
            .join(
                ConversationMessage,
                ConversationMessage.id == ChannelOutboxMessage.conversation_message_id,
            )
            .filter(
                ChannelOutboxMessage.business_id == business_id,
                ChannelOutboxMessage.status.in_(("pending", "retry", "processing")),
                ConversationMessage.opportunity_action.has(),
            )
            .all()
        )

    for row in {item.id: item for item in outbox_rows}.values():
        row.status = "blocked"
        row.next_retry_at = None
        row.locked_by = None
        row.lock_expires_at = None
        row.last_error_code = MODULE_UNAVAILABLE_CODE
        row.safe_error_message = MODULE_UNAVAILABLE_DETAIL
        if row.conversation_message_id:
            message = db.get(ConversationMessage, row.conversation_message_id)
            if message is not None and message.delivery_status not in {"sent", "delivered"}:
                message.delivery_status = "blocked"
    for row in publication_rows:
        row.status = "action_required"
        row.provider_status = MODULE_UNAVAILABLE_CODE
        row.provider_error_code = MODULE_UNAVAILABLE_CODE
        row.safe_error_message = MODULE_UNAVAILABLE_DETAIL
        row.claimed_at = None
        row.claim_expires_at = None
        row.claimed_by = None
        row.next_attempt_at = None
    for row in meta_rows:
        row.status = "failed"
        row.next_retry_at = None
        row.locked_by = None
        row.lock_expires_at = None
        row.last_error_code = MODULE_UNAVAILABLE_CODE
        row.safe_error_message = MODULE_UNAVAILABLE_DETAIL
    db.flush()
    return {
        "outbox_blocked": len({item.id for item in outbox_rows}),
        "publications_held": len(publication_rows),
        "meta_jobs_stopped": len(meta_rows),
    }


def configure_business_modules(
    db: Session,
    *,
    business_id: int,
    enabled_modules: Iterable[str],
    actor_user_id: int | None,
) -> list[BusinessModuleAccess]:
    selected = set(enabled_modules)
    if not selected <= set(PRODUCT_MODULES):
        raise ValueError("invalid_product_module")
    selected.add("essential")
    existing = {
        row.module_key: row
        for row in db.query(BusinessModuleAccess)
        .filter(BusinessModuleAccess.business_id == business_id)
        .all()
    }
    rows: list[BusinessModuleAccess] = []
    for module_key in PRODUCT_MODULES:
        row = existing.get(module_key)
        if row is None:
            row = BusinessModuleAccess(business_id=business_id, module_key=module_key)
            db.add(row)
        enabled = module_key in selected
        row.entitled = enabled
        row.active = enabled
        row.updated_by_user_id = actor_user_id
        rows.append(row)
    db.flush()
    return rows


def update_business_module(
    db: Session,
    *,
    business_id: int,
    module_key: str,
    entitled: bool,
    active: bool,
    module_cost_amount: Decimal | None,
    module_cost_currency: str | None,
    actor_user_id: int,
) -> BusinessModuleAccess:
    if module_key not in PRODUCT_MODULES:
        raise ValueError("invalid_product_module")
    if module_key == "essential" and (not entitled or not active):
        raise ValueError("essential_is_required")
    if active and not entitled:
        raise ValueError("active_module_requires_entitlement")
    row = (
        db.query(BusinessModuleAccess)
        .filter(
            BusinessModuleAccess.business_id == business_id,
            BusinessModuleAccess.module_key == module_key,
        )
        .first()
    )
    if row is None:
        row = BusinessModuleAccess(business_id=business_id, module_key=module_key)
        db.add(row)
    was_available = bool(row.entitled and row.active)
    row.entitled = entitled
    row.active = active
    row.module_cost_amount = module_cost_amount
    row.module_cost_currency = module_cost_currency if module_cost_amount is not None else None
    row.updated_by_user_id = actor_user_id
    db.flush()
    if was_available and not (entitled and active):
        freeze_module_jobs(db, business_id=business_id, module_key=module_key)
    return row


def _business_for_capability(db: Session, business_slug: str) -> Business:
    business = db.query(Business).filter(Business.slug == business_slug).first()
    if business is None:
        raise HTTPException(status_code=404, detail="Business not found")
    return business


def require_growth_access(
    business_slug: str,
    _actor: User = Depends(require_business_access),
    db: Session = Depends(get_db),
) -> None:
    business = _business_for_capability(db, business_slug)
    require_module_available(db, business.id, "growth")


def require_social_access(
    business_slug: str,
    _actor: User = Depends(require_business_access),
    db: Session = Depends(get_db),
) -> None:
    business = _business_for_capability(db, business_slug)
    require_module_available(db, business.id, "social")
