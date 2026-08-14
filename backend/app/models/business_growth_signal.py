from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    ForeignKey,
    Index,
    String,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base
from app.models.utc_datetime import UTCDateTime

GROWTH_SIGNAL_TYPES = (
    "low_future_occupancy",
    "high_due_customer_pool",
    "low_return_rate",
    "service_demand_drop",
    "seasonal_window",
)
GROWTH_SIGNAL_STATUSES = ("active", "dismissed", "resolved", "expired")
GROWTH_SIGNAL_SEVERITIES = ("info", "low", "medium", "high")
GROWTH_SIGNAL_SCOPES = ("business", "service")


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


class BusinessGrowthSignal(Base):
    __tablename__ = "business_growth_signals"
    __table_args__ = (
        CheckConstraint(
            "type IN ('low_future_occupancy','high_due_customer_pool',"
            "'low_return_rate','service_demand_drop','seasonal_window')",
            name="ck_business_growth_signals_type",
        ),
        CheckConstraint(
            "status IN ('active','dismissed','resolved','expired')",
            name="ck_business_growth_signals_status",
        ),
        CheckConstraint(
            "severity IN ('info','low','medium','high')",
            name="ck_business_growth_signals_severity",
        ),
        CheckConstraint(
            "scope_type IN ('business','service')",
            name="ck_business_growth_signals_scope",
        ),
        CheckConstraint(
            "period_end > period_start",
            name="ck_business_growth_signals_period",
        ),
        UniqueConstraint(
            "business_id", "dedupe_key", name="uq_business_growth_signal_dedupe"
        ),
        Index(
            "ix_business_growth_signals_business_status_severity",
            "business_id",
            "status",
            "severity",
        ),
        Index(
            "ix_business_growth_signals_business_type_period",
            "business_id",
            "type",
            "period_start",
            "period_end",
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    business_id: Mapped[int] = mapped_column(
        ForeignKey("businesses.id", ondelete="CASCADE"), nullable=False, index=True
    )
    type: Mapped[str] = mapped_column(String(50), nullable=False, index=True)
    status: Mapped[str] = mapped_column(
        String(20), default="active", nullable=False, index=True
    )
    severity: Mapped[str] = mapped_column(String(20), nullable=False, index=True)
    scope_type: Mapped[str] = mapped_column(String(20), nullable=False)
    service_id: Mapped[int | None] = mapped_column(
        ForeignKey("services.id", ondelete="SET NULL"), index=True
    )
    calendar_event_id: Mapped[int | None] = mapped_column(
        ForeignKey("business_calendar_events.id", ondelete="SET NULL"), index=True
    )
    detected_at: Mapped[datetime] = mapped_column(UTCDateTime(), nullable=False)
    period_start: Mapped[datetime] = mapped_column(UTCDateTime(), nullable=False, index=True)
    period_end: Mapped[datetime] = mapped_column(UTCDateTime(), nullable=False, index=True)
    expires_at: Mapped[datetime | None] = mapped_column(UTCDateTime(), index=True)
    resolved_at: Mapped[datetime | None] = mapped_column(UTCDateTime())
    dismissed_at: Mapped[datetime | None] = mapped_column(UTCDateTime())
    last_evaluated_at: Mapped[datetime] = mapped_column(UTCDateTime(), nullable=False)
    reason_code: Mapped[str] = mapped_column(String(100), nullable=False)
    explanation_json: Mapped[str] = mapped_column(Text, nullable=False)
    observed_json: Mapped[str] = mapped_column(Text, nullable=False)
    baseline_json: Mapped[str | None] = mapped_column(Text)
    recommendation_code: Mapped[str] = mapped_column(String(80), nullable=False)
    dedupe_key: Mapped[str] = mapped_column(String(255), nullable=False)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utc_now, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        UTCDateTime(), default=utc_now, onupdate=utc_now, nullable=False
    )

    business = relationship("Business", back_populates="growth_signals")
    service = relationship("BusinessService", back_populates="growth_signals")
    calendar_event = relationship("BusinessCalendarEvent", back_populates="signals")


class BusinessCalendarEvent(Base):
    __tablename__ = "business_calendar_events"
    __table_args__ = (
        CheckConstraint("ends_at > starts_at", name="ck_business_calendar_events_period"),
        CheckConstraint("length(trim(title)) > 0", name="ck_business_calendar_events_title"),
        Index(
            "ix_business_calendar_events_business_enabled_start",
            "business_id",
            "enabled",
            "starts_at",
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    business_id: Mapped[int] = mapped_column(
        ForeignKey("businesses.id", ondelete="CASCADE"), nullable=False, index=True
    )
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    starts_at: Mapped[datetime] = mapped_column(UTCDateTime(), nullable=False, index=True)
    ends_at: Mapped[datetime] = mapped_column(UTCDateTime(), nullable=False)
    category: Mapped[str | None] = mapped_column(String(80))
    service_id: Mapped[int | None] = mapped_column(
        ForeignKey("services.id", ondelete="SET NULL"), index=True
    )
    enabled: Mapped[bool] = mapped_column(
        Boolean, default=True, server_default=text("true"), nullable=False
    )
    yearly_recurrence: Mapped[bool] = mapped_column(
        Boolean, default=False, server_default=text("false"), nullable=False
    )
    created_by_user_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), index=True
    )
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utc_now, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        UTCDateTime(), default=utc_now, onupdate=utc_now, nullable=False
    )

    business = relationship("Business", back_populates="calendar_events")
    service = relationship("BusinessService", back_populates="calendar_events")
    signals = relationship("BusinessGrowthSignal", back_populates="calendar_event")
