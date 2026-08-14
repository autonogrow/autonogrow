from __future__ import annotations

from datetime import datetime, timedelta, timezone
from decimal import Decimal
from typing import Any

from sqlalchemy.orm import Session

from app.models import (
    AuditLog,
    BookingAttribution,
    Business,
    CustomerOpportunity,
    OpportunityAction,
)
from app.models.customer_opportunity import OPPORTUNITY_TYPES


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def period_bounds(
    *,
    period: str,
    date_from: datetime | None = None,
    date_to: datetime | None = None,
    now: datetime | None = None,
) -> tuple[datetime, datetime]:
    current = now or utc_now()
    if period == "7d":
        return current - timedelta(days=7), current
    if period == "30d":
        return current - timedelta(days=30), current
    if period != "custom" or date_from is None or date_to is None:
        raise ValueError("invalid_metrics_period")
    start = date_from if date_from.tzinfo else date_from.replace(tzinfo=timezone.utc)
    end = date_to if date_to.tzinfo else date_to.replace(tzinfo=timezone.utc)
    if start >= end or end - start > timedelta(days=366):
        raise ValueError("invalid_metrics_range")
    return start.astimezone(timezone.utc), end.astimezone(timezone.utc)


def _empty_type_metrics() -> dict[str, int]:
    return {
        "detected": 0,
        "pending": 0,
        "handled": 0,
        "dismissed": 0,
        "actions_prepared": 0,
        "messages_sent": 0,
        "bookings_attributed": 0,
        "attributed_bookings_completed": 0,
    }


def growth_metrics(
    db: Session,
    *,
    business: Business,
    period: str,
    date_from: datetime | None = None,
    date_to: datetime | None = None,
    now: datetime | None = None,
) -> dict[str, Any]:
    start, end = period_bounds(
        period=period, date_from=date_from, date_to=date_to, now=now
    )
    opportunities = (
        db.query(CustomerOpportunity)
        .filter(
            CustomerOpportunity.business_id == business.id,
            CustomerOpportunity.detected_at >= start,
            CustomerOpportunity.detected_at <= end,
        )
        .all()
    )
    actions = (
        db.query(OpportunityAction)
        .filter(
            OpportunityAction.business_id == business.id,
            OpportunityAction.created_at >= start,
            OpportunityAction.created_at <= end,
        )
        .all()
    )
    attributions = (
        db.query(BookingAttribution)
        .filter(
            BookingAttribution.business_id == business.id,
            BookingAttribution.attributed_at >= start,
            BookingAttribution.attributed_at <= end,
        )
        .all()
    )
    type_metrics = {opportunity_type: _empty_type_metrics() for opportunity_type in OPPORTUNITY_TYPES}
    for opportunity in opportunities:
        row = type_metrics[opportunity.type]
        row["detected"] += 1
        if opportunity.status == "pending":
            row["pending"] += 1
        if opportunity.status in {"actioned", "resolved"}:
            row["handled"] += 1
        if opportunity.status == "dismissed":
            row["dismissed"] += 1
    for action in actions:
        row = type_metrics[action.opportunity.type]
        if action.action_type == "contact_customer":
            row["actions_prepared"] += 1
        if action.sent_at is not None and start <= action.sent_at <= end:
            row["messages_sent"] += 1
    completed_attributions: list[BookingAttribution] = []
    for attribution in attributions:
        row = type_metrics[attribution.opportunity.type]
        row["bookings_attributed"] += 1
        if attribution.completed_at is not None and attribution.booking.status == "completed":
            row["attributed_bookings_completed"] += 1
            completed_attributions.append(attribution)

    viewed_ids = {
        int(log.resource_id)
        for log in db.query(AuditLog)
        .filter(
            AuditLog.business_id == business.id,
            AuditLog.action == "opportunity_viewed",
            AuditLog.created_at >= start.replace(tzinfo=None),
            AuditLog.created_at <= end.replace(tzinfo=None),
        )
        .all()
        if log.resource_id and log.resource_id.isdigit()
    }
    known_values = [
        row.price_amount_snapshot
        for row in completed_attributions
        if row.price_amount_snapshot is not None
        and (row.currency_snapshot or business.currency) == business.currency
    ]
    revenue: Decimal | None = None
    if completed_attributions and len(known_values) == len(completed_attributions):
        revenue = sum(known_values, Decimal("0"))

    detected = len(opportunities)
    actioned_opportunity_ids = {
        action.opportunity_id
        for action in actions
        if action.action_type in {"contact_customer", "mark_handled"}
    }
    sent_actions = [action for action in actions if action.sent_at is not None]
    return {
        "business_slug": business.slug,
        "period": period,
        "from": start.isoformat(),
        "to": end.isoformat(),
        "summary": {
            "opportunities_detected": detected,
            "opportunities_pending": sum(
                1 for opportunity in opportunities if opportunity.status == "pending"
            ),
            "opportunities_handled": sum(
                1
                for opportunity in opportunities
                if opportunity.status in {"actioned", "resolved"}
            ),
            "opportunities_dismissed": sum(
                1 for opportunity in opportunities if opportunity.status == "dismissed"
            ),
            "actions_prepared": sum(
                1 for action in actions if action.action_type == "contact_customer"
            ),
            "messages_sent": len(sent_actions),
            "bookings_attributed": len(attributions),
            "attributed_bookings_completed": len(completed_attributions),
            "attributed_revenue": str(revenue) if revenue is not None else None,
            "revenue_currency": business.currency if revenue is not None else None,
        },
        "funnel": {
            "detected": detected,
            "viewed": len(viewed_ids),
            "actioned": len(actioned_opportunity_ids),
            "sent": len(sent_actions),
            "booked": len(attributions),
            "completed": len(completed_attributions),
        },
        "by_type": type_metrics,
    }
