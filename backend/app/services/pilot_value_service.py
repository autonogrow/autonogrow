from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal
from typing import Any

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.models import (
    Booking,
    Business,
    BusinessModuleAccess,
    InstagramContent,
    PilotBaseline,
    SocialContentProposal,
)
from app.services.capability_service import module_capabilities
from app.services.growth_metrics_service import growth_metrics, period_bounds


def _money(value: Decimal | None, currency: str) -> dict[str, str] | None:
    return {"amount": str(value), "currency": currency} if value is not None else None


def _roi(
    *,
    active: bool,
    cost: Decimal | None,
    cost_currency: str | None,
    direct_revenue: Decimal | None,
    revenue_currency: str,
    period: str,
) -> dict[str, Any]:
    if not active:
        return {"status": "not_active", "available": False}
    if cost is None:
        return {"status": "unavailable_no_cost", "available": False}
    if cost == 0:
        return {"status": "unavailable_zero_cost", "available": False}
    if period != "30d":
        return {
            "status": "unavailable_period_mismatch",
            "available": False,
            "reason": "El coste configurado es mensual y no se prorratea de forma implícita.",
        }
    if cost_currency != revenue_currency:
        return {"status": "unavailable_currency_mismatch", "available": False}
    if direct_revenue is None:
        return {"status": "unavailable_attribution_incomplete", "available": False}
    net = direct_revenue - cost
    return_per_euro = direct_revenue / cost
    percentage = (net / cost) * Decimal("100")
    return {
        "status": "available",
        "available": True,
        "estimated_net_return": _money(net.quantize(Decimal("0.01")), revenue_currency),
        "return_per_euro": str(return_per_euro.quantize(Decimal("0.01"))),
        "roi_percentage": str(percentage.quantize(Decimal("0.01"))),
        "formula": "(directly_attributable_revenue - module_cost) / module_cost",
    }


def _baseline_payload(row: PilotBaseline | None) -> dict[str, Any] | None:
    if row is None:
        return None
    return {
        "monthly_bookings": row.monthly_bookings,
        "average_ticket": str(row.average_ticket) if row.average_ticket is not None else None,
        "occupancy_percentage": (
            str(row.occupancy_percentage) if row.occupancy_percentage is not None else None
        ),
        "recurring_customer_percentage": (
            str(row.recurring_customer_percentage)
            if row.recurring_customer_percentage is not None
            else None
        ),
        "cancellation_percentage": (
            str(row.cancellation_percentage)
            if row.cancellation_percentage is not None
            else None
        ),
        "no_show_percentage": (
            str(row.no_show_percentage) if row.no_show_percentage is not None else None
        ),
        "currency": row.currency,
        "notes": row.notes,
        "captured_at": row.captured_at.isoformat(),
    }


def pilot_value_summary(
    db: Session,
    *,
    business: Business,
    period: str = "30d",
    date_from: datetime | None = None,
    date_to: datetime | None = None,
    now: datetime | None = None,
) -> dict[str, Any]:
    start, end = period_bounds(
        period=period, date_from=date_from, date_to=date_to, now=now
    )
    start_naive = start.astimezone(timezone.utc).replace(tzinfo=None)
    end_naive = end.astimezone(timezone.utc).replace(tzinfo=None)
    capabilities = module_capabilities(db, business.id)

    bookings = (
        db.query(Booking)
        .filter(
            Booking.business_id == business.id,
            Booking.created_at >= start_naive,
            Booking.created_at <= end_naive,
        )
        .all()
    )
    completed = [booking for booking in bookings if booking.status == "completed"]
    managed_values = [
        booking.price_amount_snapshot
        for booking in completed
        if booking.price_amount_snapshot is not None
        and (booking.currency_snapshot or business.currency) == business.currency
    ]
    managed_value = sum(managed_values, Decimal("0"))
    online_sources = {"landing", "customer_portal", "customer_repeat", "public"}
    returning_customers = (
        db.query(Booking.customer_id)
        .filter(
            Booking.business_id == business.id,
            Booking.created_at >= start_naive,
            Booking.created_at <= end_naive,
            Booking.status == "completed",
        )
        .group_by(Booking.customer_id)
        .having(func.count(Booking.id) > 1)
        .count()
    )
    essential_metrics = {
        "bookings_managed": len(bookings),
        "bookings_online": sum(1 for booking in bookings if booking.source in online_sources),
        "bookings_completed": len(completed),
        "bookings_cancelled": sum(1 for booking in bookings if booking.status == "cancelled"),
        "no_shows": sum(1 for booking in bookings if booking.status == "no_show"),
        "customers_served": len({booking.customer_id for booking in completed}),
        "returning_customers": returning_customers,
        "managed_booking_value": _money(managed_value, business.currency),
        "managed_value_coverage": {
            "bookings_with_known_value": len(managed_values),
            "completed_bookings": len(completed),
        },
    }

    growth = growth_metrics(
        db,
        business=business,
        period=period,
        date_from=date_from,
        date_to=date_to,
        now=now,
    )
    growth_summary = growth["summary"]
    growth_direct = (
        Decimal(growth_summary["attributed_revenue"])
        if growth_summary["attributed_revenue"] is not None
        else Decimal("0")
        if growth_summary["attributed_bookings_completed"] == 0
        else None
    )

    proposals = (
        db.query(SocialContentProposal)
        .filter(
            SocialContentProposal.business_id == business.id,
            SocialContentProposal.detected_at >= start,
            SocialContentProposal.detected_at <= end,
        )
        .all()
    )
    contents = (
        db.query(InstagramContent)
        .filter(
            InstagramContent.business_id == business.id,
            InstagramContent.created_at >= start_naive,
            InstagramContent.created_at <= end_naive,
            InstagramContent.archived_at.is_(None),
        )
        .all()
    )
    social_metrics = {
        "proposals_created": len(proposals),
        "proposals_accepted": sum(1 for proposal in proposals if proposal.status == "accepted"),
        "content_pieces_created": len(contents),
        "publications_recorded": sum(1 for content in contents if content.status == "published"),
        "directly_attributable_bookings": None,
        "attribution_note": (
            "No existe tracking Social suficiente; actividad editorial no se convierte en ventas."
        ),
    }

    module_metrics: dict[str, dict[str, Any]] = {
        "essential": {
            "classification": "operational_value",
            "metrics": essential_metrics,
            "directly_attributable_revenue": None,
            "attribution_note": (
                "El volumen gestionado no equivale a ingreso incremental atribuible."
            ),
        },
        "growth": {
            "classification": "directly_attributable",
            "metrics": growth_summary,
            "directly_attributable_revenue": _money(growth_direct, business.currency),
            "attribution_note": (
                "Solo incluye reservas enlazadas a acciones Growth y completadas."
            ),
        },
        "social": {
            "classification": "operational_value",
            "metrics": social_metrics,
            "directly_attributable_revenue": None,
            "attribution_note": social_metrics["attribution_note"],
        },
    }
    access_rows = {
        row.module_key: row
        for row in db.query(BusinessModuleAccess)
        .filter(BusinessModuleAccess.business_id == business.id)
        .all()
    }
    for module_key, values in module_metrics.items():
        capability = capabilities[module_key]
        values["state"] = "active" if capability["available"] else "disabled"
        if not capability["available"]:
            values["metrics"] = None
            values["directly_attributable_revenue"] = None
        row = access_rows.get(module_key)
        direct_money = values["directly_attributable_revenue"]
        direct_value = Decimal(direct_money["amount"]) if direct_money else None
        values["roi"] = _roi(
            active=bool(capability["available"]),
            cost=row.module_cost_amount if row else None,
            cost_currency=row.module_cost_currency if row else None,
            direct_revenue=direct_value,
            revenue_currency=business.currency,
            period=period,
        )
        values["module_cost"] = capability["module_cost"]

    baseline = db.query(PilotBaseline).filter(PilotBaseline.business_id == business.id).first()
    baseline_data = _baseline_payload(baseline)
    comparison: dict[str, Any] | None = None
    if period == "30d" and baseline and baseline.monthly_bookings is not None:
        comparison = {
            "label": "Variación durante el piloto",
            "causal_claim": False,
            "monthly_bookings": {
                "baseline": baseline.monthly_bookings,
                "pilot_period": len(bookings),
                "difference": len(bookings) - baseline.monthly_bookings,
            },
        }
    return {
        "business_id": business.id,
        "business_slug": business.slug,
        "period": period,
        "from": start.isoformat(),
        "to": end.isoformat(),
        "modules": module_metrics,
        "baseline": baseline_data,
        "baseline_comparison": comparison,
        "semantics": {
            "directly_attributable": "Cadena verificable entre acción y reserva.",
            "influenced": "Relación plausible sin afirmar causalidad.",
            "operational_value": "Uso, volumen gestionado o trabajo realizado.",
        },
    }
