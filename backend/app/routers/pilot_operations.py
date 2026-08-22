from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from sqlalchemy.orm import Session

from app.core.audit import record_audit
from app.core.database import get_db
from app.core.security import require_business_access, require_owner
from app.models import Business, PilotBaseline, User
from app.models.business_module import PRODUCT_MODULES
from app.schemas.pilot import ModuleAccessUpdate, PilotBaselineUpdate
from app.services.business_readiness_service import evaluate_business_readiness
from app.services.capability_service import (
    module_capabilities,
    update_business_module,
)
from app.services.pilot_value_service import pilot_value_summary

admin_router = APIRouter(
    prefix="/api/admin/businesses/{business_slug}",
    tags=["pilot-operations"],
    dependencies=[Depends(require_business_access)],
)
owner_router = APIRouter(
    prefix="/api/owner", tags=["pilot-operations"], dependencies=[Depends(require_owner)]
)


def _business_by_slug(db: Session, slug: str) -> Business:
    row = db.query(Business).filter(Business.slug == slug).first()
    if row is None:
        raise HTTPException(status_code=404, detail="Business not found")
    return row


def _business_by_id(db: Session, business_id: int) -> Business:
    row = db.get(Business, business_id)
    if row is None:
        raise HTTPException(status_code=404, detail="Business not found")
    return row


def _value(
    db: Session,
    business: Business,
    period: str,
    date_from: datetime | None,
    date_to: datetime | None,
):
    try:
        return pilot_value_summary(
            db,
            business=business,
            period=period,
            date_from=date_from,
            date_to=date_to,
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail="El periodo de métricas no es válido.") from exc


@admin_router.get("/capabilities")
def get_admin_capabilities(business_slug: str, db: Session = Depends(get_db)):
    business = _business_by_slug(db, business_slug)
    return {"business_id": business.id, "modules": module_capabilities(db, business.id)}


@admin_router.get("/pilot-readiness")
def get_admin_pilot_readiness(business_slug: str, db: Session = Depends(get_db)):
    return evaluate_business_readiness(db, _business_by_slug(db, business_slug))


@admin_router.get("/value-summary")
def get_admin_value_summary(
    business_slug: str,
    period: str = Query(default="30d", pattern=r"^(7d|30d|custom)$"),
    date_from: datetime | None = Query(default=None, alias="from"),
    date_to: datetime | None = Query(default=None, alias="to"),
    db: Session = Depends(get_db),
):
    return _value(db, _business_by_slug(db, business_slug), period, date_from, date_to)


@owner_router.get("/businesses/{business_id}/modules")
def get_owner_modules(business_id: int, db: Session = Depends(get_db)):
    business = _business_by_id(db, business_id)
    return {"business_id": business.id, "modules": module_capabilities(db, business.id)}


@owner_router.patch("/businesses/{business_id}/modules/{module_key}")
def patch_owner_module(
    business_id: int,
    module_key: str,
    payload: ModuleAccessUpdate,
    request: Request,
    actor: User = Depends(require_owner),
    db: Session = Depends(get_db),
):
    business = _business_by_id(db, business_id)
    if module_key not in PRODUCT_MODULES:
        raise HTTPException(status_code=404, detail="Módulo no reconocido")
    before = module_capabilities(db, business.id)[module_key]
    try:
        update_business_module(
            db,
            business_id=business.id,
            module_key=module_key,
            entitled=payload.entitled,
            active=payload.active,
            module_cost_amount=payload.module_cost_amount,
            module_cost_currency=payload.module_cost_currency,
            actor_user_id=actor.id,
        )
    except ValueError as exc:
        messages = {
            "essential_is_required": "Essential es obligatorio en la arquitectura V1.",
            "active_module_requires_entitlement": "El módulo debe estar incluido antes de activarlo.",
        }
        raise HTTPException(status_code=409, detail=messages.get(str(exc), "Cambio no válido")) from exc
    after = module_capabilities(db, business.id)[module_key]
    record_audit(
        db,
        action="business_module_access_updated",
        request=request,
        actor=actor,
        business_id=business.id,
        resource_type="business_module_access",
        resource_id=module_key,
        metadata={
            "module": module_key,
            "before": before,
            "after": after,
            "reason": payload.reason,
        },
        commit=False,
    )
    db.commit()
    return {"ok": True, "business_id": business.id, "module": after}


@owner_router.get("/businesses/{business_id}/pilot-readiness")
def get_owner_pilot_readiness(business_id: int, db: Session = Depends(get_db)):
    return evaluate_business_readiness(db, _business_by_id(db, business_id))


@owner_router.get("/businesses/{business_id}/pilot-baseline")
def get_owner_pilot_baseline(business_id: int, db: Session = Depends(get_db)):
    business = _business_by_id(db, business_id)
    return pilot_value_summary(db, business=business)["baseline"]


@owner_router.put("/businesses/{business_id}/pilot-baseline")
def put_owner_pilot_baseline(
    business_id: int,
    payload: PilotBaselineUpdate,
    request: Request,
    actor: User = Depends(require_owner),
    db: Session = Depends(get_db),
):
    business = _business_by_id(db, business_id)
    row = (
        db.query(PilotBaseline).filter(PilotBaseline.business_id == business.id).first()
    )
    if row is None:
        row = PilotBaseline(business_id=business.id)
        db.add(row)
    for field, value in payload.model_dump().items():
        setattr(row, field, value)
    row.updated_by_user_id = actor.id
    record_audit(
        db,
        action="pilot_baseline_updated",
        request=request,
        actor=actor,
        business_id=business.id,
        resource_type="pilot_baseline",
        resource_id=business.id,
        metadata={"configured_fields": sorted(payload.model_fields_set)},
        commit=False,
    )
    db.commit()
    db.refresh(row)
    return pilot_value_summary(db, business=business)["baseline"]


@owner_router.get("/businesses/{business_id}/pilot-value")
def get_owner_pilot_value(
    business_id: int,
    period: str = Query(default="30d", pattern=r"^(7d|30d|custom)$"),
    date_from: datetime | None = Query(default=None, alias="from"),
    date_to: datetime | None = Query(default=None, alias="to"),
    db: Session = Depends(get_db),
):
    return _value(db, _business_by_id(db, business_id), period, date_from, date_to)


@owner_router.get("/pilot-value")
def list_owner_pilot_value(
    period: str = Query(default="30d", pattern=r"^(7d|30d)$"),
    limit: int = Query(default=100, ge=1, le=200),
    db: Session = Depends(get_db),
):
    businesses = db.query(Business).order_by(Business.id).limit(limit).all()
    return {
        "period": period,
        "businesses": [
            _value(db, business, period, None, None) for business in businesses
        ],
    }
