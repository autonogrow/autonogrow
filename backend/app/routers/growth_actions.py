from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session

from app.core.audit import record_audit
from app.core.database import get_db
from app.core.security import require_business_access, require_business_admin
from app.models import (
    Booking,
    Business,
    CustomerOpportunity,
    OpportunityAction,
    User,
)
from app.schemas.opportunity_action import (
    ManualBookingAttributionCreate,
    OpportunityActionPrepare,
    OpportunityActionUpdate,
)
from app.services.booking_attribution_service import (
    create_booking_attribution,
    serialize_attribution,
)
from app.services.conversation_automation_service import ensure_automation_configuration
from app.services.conversation_automation_state_service import apply_human_reply_pause
from app.services.conversation_service import (
    ConversationDeliveryUnavailable,
    conversation_delivery_capabilities,
    send_outbound_message,
)
from app.services.growth_metrics_service import growth_metrics
from app.services.opportunity_action_service import (
    OpportunityActionService,
    build_action_assisted_whatsapp_url,
    invalidate_actions_for_resolved_opportunity,
    serialize_action,
    sync_action_from_message,
    utc_now,
)

router = APIRouter(
    prefix="/api/admin/businesses/{business_slug}",
    tags=["growth-actions"],
    dependencies=[Depends(require_business_access)],
)


def business_or_404(db: Session, business_slug: str) -> Business:
    row = db.query(Business).filter(Business.slug == business_slug).first()
    if row is None:
        raise HTTPException(status_code=404, detail="Business not found")
    return row


def opportunity_or_404(
    db: Session, *, business_id: int, opportunity_id: int, lock: bool = False
) -> CustomerOpportunity:
    query = db.query(CustomerOpportunity).filter(
        CustomerOpportunity.id == opportunity_id,
        CustomerOpportunity.business_id == business_id,
    )
    if lock and db.get_bind().dialect.name == "postgresql":
        query = query.with_for_update()
    row = query.first()
    if row is None:
        raise HTTPException(status_code=404, detail="Opportunity not found")
    return row


def action_or_404(
    db: Session, *, business_id: int, action_id: int, lock: bool = False
) -> OpportunityAction:
    query = db.query(OpportunityAction).filter(
        OpportunityAction.id == action_id,
        OpportunityAction.business_id == business_id,
    )
    if lock and db.get_bind().dialect.name == "postgresql":
        query = query.with_for_update()
    row = query.first()
    if row is None:
        raise HTTPException(status_code=404, detail="Opportunity action not found")
    return row


def _action_error(error: ValueError) -> HTTPException:
    mapping = {
        "opportunity_not_actionable": (409, "La oportunidad ya no está pendiente."),
        "conversation_not_found": (404, "No existe una conversación válida."),
        "conversation_customer_mismatch": (
            400,
            "La conversación no pertenece al cliente de la oportunidad.",
        ),
    }
    status, detail = mapping.get(str(error), (400, "La acción no es válida."))
    return HTTPException(status_code=status, detail=detail)


@router.post("/opportunities/{opportunity_id}/actions/prepare", status_code=201)
def prepare_opportunity_action(
    business_slug: str,
    opportunity_id: int,
    payload: OpportunityActionPrepare,
    request: Request,
    actor: User = Depends(require_business_access),
    db: Session = Depends(get_db),
):
    if payload.action_type not in {"contact_customer", "open_conversation"}:
        raise HTTPException(status_code=422, detail="Unsupported opportunity action type")
    business = business_or_404(db, business_slug)
    opportunity = opportunity_or_404(
        db, business_id=business.id, opportunity_id=opportunity_id, lock=True
    )
    try:
        row, created = OpportunityActionService(db).prepare(
            business=business,
            opportunity=opportunity,
            actor_user_id=actor.id,
            action_type=payload.action_type,
            requested_conversation_id=payload.conversation_id,
        )
    except ValueError as error:
        raise _action_error(error) from error
    db.commit()
    db.refresh(row)
    record_audit(
        db,
        action="opportunity_viewed",
        request=request,
        actor=actor,
        business_id=business.id,
        resource_type="customer_opportunity",
        resource_id=opportunity.id,
        metadata={"type": opportunity.type},
    )
    record_audit(
        db,
        action="action_prepared" if created else "action_prepare_reused",
        request=request,
        actor=actor,
        business_id=business.id,
        resource_type="opportunity_action",
        resource_id=row.id,
        metadata={
            "opportunity_id": opportunity.id,
            "action_type": row.action_type,
            "channel": row.channel,
        },
    )
    return {
        "ok": True,
        "created": created,
        "action": serialize_action(db, row),
    }


@router.get("/actions/{action_id}")
def get_opportunity_action(
    business_slug: str,
    action_id: int,
    db: Session = Depends(get_db),
):
    business = business_or_404(db, business_slug)
    row = action_or_404(db, business_id=business.id, action_id=action_id)
    return {"action": serialize_action(db, row)}


@router.patch("/actions/{action_id}")
def edit_opportunity_action(
    business_slug: str,
    action_id: int,
    payload: OpportunityActionUpdate,
    request: Request,
    actor: User = Depends(require_business_access),
    db: Session = Depends(get_db),
):
    business = business_or_404(db, business_slug)
    row = action_or_404(db, business_id=business.id, action_id=action_id, lock=True)
    sync_action_from_message(row)
    if row.status != "draft":
        raise HTTPException(status_code=409, detail="Only draft actions can be edited")
    if row.opportunity.status != "pending":
        invalidate_actions_for_resolved_opportunity(db, opportunity=row.opportunity)
        db.commit()
        raise HTTPException(status_code=409, detail="La oportunidad ya no está pendiente.")
    row.final_text = payload.final_text.strip()
    row.last_edited_by_user_id = actor.id
    row.failure_reason = None
    db.commit()
    db.refresh(row)
    record_audit(
        db,
        action="action_edited",
        request=request,
        actor=actor,
        business_id=business.id,
        resource_type="opportunity_action",
        resource_id=row.id,
        metadata={"opportunity_id": row.opportunity_id, "channel": row.channel},
    )
    return {"ok": True, "action": serialize_action(db, row)}


@router.post("/actions/{action_id}/send")
def send_opportunity_action(
    business_slug: str,
    action_id: int,
    request: Request,
    actor: User = Depends(require_business_access),
    db: Session = Depends(get_db),
):
    business = business_or_404(db, business_slug)
    row = action_or_404(db, business_id=business.id, action_id=action_id, lock=True)
    sync_action_from_message(row)
    if row.message_id is not None and row.status in {
        "approved",
        "sending",
        "sent",
        "completed",
    }:
        return {"ok": True, "idempotent": True, "action": serialize_action(db, row)}
    if row.status != "draft":
        raise HTTPException(status_code=409, detail="Opportunity action cannot be sent")
    opportunity = opportunity_or_404(
        db,
        business_id=business.id,
        opportunity_id=row.opportunity_id,
        lock=True,
    )
    if opportunity.status != "pending":
        invalidate_actions_for_resolved_opportunity(db, opportunity=opportunity)
        db.commit()
        raise HTTPException(status_code=409, detail="La oportunidad ya no está pendiente.")
    if row.conversation is None or row.channel != row.conversation.channel:
        row.failure_reason = "no_customer_channel"
        db.commit()
        raise HTTPException(
            status_code=409,
            detail={
                "reason": "no_customer_channel",
                "message": "No hay un canal conectado disponible; puedes copiar el texto.",
            },
        )
    capabilities = conversation_delivery_capabilities(db, conversation=row.conversation)
    if not capabilities.integrated_delivery_available:
        reason = capabilities.unavailable_reason or "delivery_not_available"
        row.failure_reason = reason
        db.commit()
        record_audit(
            db,
            action="action_failed",
            request=request,
            actor=actor,
            business_id=business.id,
            resource_type="opportunity_action",
            resource_id=row.id,
            metadata={"reason": reason, "channel": row.channel},
        )
        return JSONResponse(
            status_code=409,
            content={
                "ok": False,
                "detail": {
                    "reason": reason,
                    "message": (
                        "El canal no permite el envío integrado ahora. Puedes copiar el texto "
                        "y gestionarlo manualmente."
                    ),
                },
                "action": serialize_action(db, row),
            },
        )

    now = utc_now()
    row.status = "approved"
    row.approved_by_user_id = actor.id
    row.sent_by_user_id = actor.id
    row.approved_at = now
    row.failure_reason = None
    try:
        delivery = send_outbound_message(
            db,
            conversation=row.conversation,
            body=(row.final_text or row.suggested_text or "").strip(),
            sender_type="business",
        )
        row.message = delivery.message
        if delivery.message.delivery_status in {"sent", "delivered", "read"}:
            row.status = "sent"
            row.sent_at = now
        elif delivery.message.delivery_status in {"failed", "blocked", "cancelled"}:
            row.status = "failed"
            row.failed_at = now
            row.failure_reason = (
                delivery.unavailable_reason or delivery.client_error_message or "provider_failed"
            )[:500]
        else:
            row.status = "approved"
        if delivery.ok:
            automation_settings, _ = ensure_automation_configuration(db, business)
            apply_human_reply_pause(
                row.conversation,
                automation_settings,
                updated_by=actor.id,
            )
        db.commit()
    except ConversationDeliveryUnavailable as error:
        db.rollback()
        row = action_or_404(db, business_id=business.id, action_id=action_id)
        row.failure_reason = error.reason
        db.commit()
        record_audit(
            db,
            action="action_failed",
            request=request,
            actor=actor,
            business_id=business.id,
            resource_type="opportunity_action",
            resource_id=row.id,
            metadata={"reason": error.reason, "channel": row.channel},
        )
        return JSONResponse(
            status_code=error.status_code,
            content={
                "ok": False,
                "detail": {"reason": error.reason, "message": error.safe_message},
                "action": serialize_action(db, row),
            },
        )
    db.refresh(row)
    audit_action = "action_sent" if row.status == "sent" else (
        "action_failed" if row.status == "failed" else "action_approved"
    )
    record_audit(
        db,
        action=audit_action,
        request=request,
        actor=actor,
        business_id=business.id,
        resource_type="opportunity_action",
        resource_id=row.id,
        metadata={
            "opportunity_id": row.opportunity_id,
            "channel": row.channel,
            "delivery_status": row.message.delivery_status if row.message else None,
        },
    )
    response = {"ok": delivery.ok, "idempotent": False, "action": serialize_action(db, row)}
    if not delivery.ok:
        return JSONResponse(status_code=502, content=response)
    return response


@router.post("/actions/{action_id}/assisted-delivery")
def prepare_opportunity_assisted_delivery(
    business_slug: str,
    action_id: int,
    request: Request,
    actor: User = Depends(require_business_access),
    db: Session = Depends(get_db),
):
    business = business_or_404(db, business_slug)
    row = action_or_404(db, business_id=business.id, action_id=action_id)
    sync_action_from_message(row)
    if row.status not in {"draft", "failed"}:
        raise HTTPException(
            status_code=409,
            detail="La acción ya no admite entrega asistida.",
        )
    if row.opportunity.status != "pending":
        raise HTTPException(status_code=409, detail="La oportunidad ya no está pendiente.")
    try:
        whatsapp_url = build_action_assisted_whatsapp_url(row)
    except ValueError as error:
        raise HTTPException(
            status_code=409,
            detail="Este cliente no tiene un teléfono válido.",
        ) from error
    record_audit(
        db,
        action="opportunity_action_assisted_delivery_opened",
        request=request,
        actor=actor,
        business_id=business.id,
        resource_type="opportunity_action",
        resource_id=row.id,
        metadata={"opportunity_id": row.opportunity_id, "channel": "whatsapp"},
    )
    return {
        "ok": True,
        "delivery_mode": "assisted",
        "sent": False,
        "whatsapp_url": whatsapp_url,
        "action": serialize_action(db, row),
    }


@router.post("/actions/{action_id}/cancel")
def cancel_opportunity_action(
    business_slug: str,
    action_id: int,
    request: Request,
    actor: User = Depends(require_business_access),
    db: Session = Depends(get_db),
):
    business = business_or_404(db, business_slug)
    row = action_or_404(db, business_id=business.id, action_id=action_id, lock=True)
    if row.status != "draft":
        raise HTTPException(status_code=409, detail="Only draft actions can be cancelled")
    row.status = "cancelled"
    row.cancelled_at = utc_now()
    db.commit()
    record_audit(
        db,
        action="action_cancelled",
        request=request,
        actor=actor,
        business_id=business.id,
        resource_type="opportunity_action",
        resource_id=row.id,
    )
    return {"ok": True, "action": serialize_action(db, row)}


@router.post("/opportunities/{opportunity_id}/mark-handled")
def mark_opportunity_handled(
    business_slug: str,
    opportunity_id: int,
    request: Request,
    actor: User = Depends(require_business_access),
    db: Session = Depends(get_db),
):
    business = business_or_404(db, business_slug)
    opportunity = opportunity_or_404(
        db, business_id=business.id, opportunity_id=opportunity_id, lock=True
    )
    try:
        row, created = OpportunityActionService(db).prepare(
            business=business,
            opportunity=opportunity,
            actor_user_id=actor.id,
            action_type="mark_handled",
        )
    except ValueError as error:
        raise _action_error(error) from error
    opportunity.status = "actioned"
    opportunity.actioned_at = opportunity.actioned_at or utc_now()
    invalidate_actions_for_resolved_opportunity(db, opportunity=opportunity)
    db.commit()
    record_audit(
        db,
        action="opportunity_handled",
        request=request,
        actor=actor,
        business_id=business.id,
        resource_type="customer_opportunity",
        resource_id=opportunity.id,
        metadata={"opportunity_action_id": row.id},
    )
    return {
        "ok": True,
        "created": created,
        "action": serialize_action(db, row),
    }


@router.post("/opportunities/{opportunity_id}/open-conversation")
def open_opportunity_conversation(
    business_slug: str,
    opportunity_id: int,
    request: Request,
    actor: User = Depends(require_business_access),
    db: Session = Depends(get_db),
):
    business = business_or_404(db, business_slug)
    opportunity = opportunity_or_404(
        db, business_id=business.id, opportunity_id=opportunity_id
    )
    try:
        row, created = OpportunityActionService(db).prepare(
            business=business,
            opportunity=opportunity,
            actor_user_id=actor.id,
            action_type="open_conversation",
        )
    except ValueError as error:
        raise _action_error(error) from error
    db.commit()
    record_audit(
        db,
        action="opportunity_conversation_opened",
        request=request,
        actor=actor,
        business_id=business.id,
        resource_type="opportunity_action",
        resource_id=row.id,
        metadata={"conversation_id": row.conversation_id},
    )
    return {
        "ok": True,
        "created": created,
        "conversation_id": row.conversation_id,
        "action": serialize_action(db, row),
    }


@router.post("/actions/{action_id}/attribute", dependencies=[Depends(require_business_admin)])
def manually_attribute_booking(
    business_slug: str,
    action_id: int,
    payload: ManualBookingAttributionCreate,
    request: Request,
    actor: User = Depends(require_business_admin),
    db: Session = Depends(get_db),
):
    business = business_or_404(db, business_slug)
    row = action_or_404(db, business_id=business.id, action_id=action_id, lock=True)
    sync_action_from_message(row)
    if row.status not in {"sent", "completed"}:
        raise HTTPException(status_code=409, detail="Only a sent action can be attributed")
    booking = (
        db.query(Booking)
        .filter(Booking.id == payload.booking_id, Booking.business_id == business.id)
        .first()
    )
    if booking is None:
        raise HTTPException(status_code=404, detail="Booking not found")
    try:
        attribution, created = create_booking_attribution(
            db,
            action=row,
            booking=booking,
            method="manual",
            actor_user_id=actor.id,
        )
    except ValueError as error:
        raise HTTPException(status_code=409, detail=str(error)) from error
    db.commit()
    db.refresh(attribution)
    record_audit(
        db,
        action="booking_attribution_manual",
        request=request,
        actor=actor,
        business_id=business.id,
        resource_type="booking_attribution",
        resource_id=attribution.id,
        metadata={"booking_id": booking.id, "opportunity_action_id": row.id},
    )
    return {
        "ok": True,
        "created": created,
        "attribution": serialize_attribution(attribution),
    }


@router.get("/growth-metrics")
def get_growth_metrics(
    business_slug: str,
    period: str = Query(default="30d", pattern="^(7d|30d|custom)$"),
    date_from: datetime | None = Query(default=None, alias="from"),
    date_to: datetime | None = Query(default=None, alias="to"),
    db: Session = Depends(get_db),
):
    business = business_or_404(db, business_slug)
    try:
        return growth_metrics(
            db,
            business=business,
            period=period,
            date_from=date_from,
            date_to=date_to,
        )
    except ValueError as error:
        raise HTTPException(status_code=422, detail="Invalid growth metrics period") from error
