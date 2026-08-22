from __future__ import annotations

from decimal import Decimal
from typing import Iterable

from fastapi import Depends, HTTPException
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.security import require_business_access
from app.models import Business, BusinessModuleAccess, User
from app.models.business_module import PRODUCT_MODULES

MODULE_UNAVAILABLE_DETAIL = "Este módulo no está disponible para este negocio."


def _legacy_default(module_key: str) -> dict[str, object]:
    """Keep create_all fixtures and pre-migration local data backward compatible.

    The migration materializes these defaults for every real business. New onboarding also
    materializes the Owner selection, so missing rows are only a compatibility boundary.
    """

    return {
        "module": module_key,
        "entitled": True,
        "active": True,
        "available": True,
        "configuration_source": "legacy_default",
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
    legacy_business = not rows
    for module_key in PRODUCT_MODULES:
        row = rows.get(module_key)
        if row is None:
            result[module_key] = (
                _legacy_default(module_key)
                if legacy_business
                else {
                    "module": module_key,
                    "entitled": False,
                    "active": False,
                    "available": False,
                    "configuration_source": "missing_configuration",
                    "module_cost": None,
                }
            )
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
    rows = (
        db.query(BusinessModuleAccess)
        .filter(BusinessModuleAccess.business_id == business_id)
        .all()
    )
    if not rows:
        return True
    row = next((item for item in rows if item.module_key == module_key), None)
    return bool(row and row.entitled and row.active)


def require_module_available(db: Session, business_id: int, module_key: str) -> None:
    if not module_is_available(db, business_id, module_key):
        raise HTTPException(
            status_code=403,
            detail={"code": "module_not_available", "message": MODULE_UNAVAILABLE_DETAIL},
        )


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
    row.entitled = entitled
    row.active = active
    row.module_cost_amount = module_cost_amount
    row.module_cost_currency = module_cost_currency if module_cost_amount is not None else None
    row.updated_by_user_id = actor_user_id
    db.flush()
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
