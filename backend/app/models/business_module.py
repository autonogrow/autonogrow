from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    ForeignKey,
    Index,
    Numeric,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base
from app.models.utc_datetime import UTCDateTime

PRODUCT_MODULES = ("essential", "growth", "social")


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


class BusinessModuleAccess(Base):
    """Commercial entitlement and operational activation for one product module.

    Integration health and worker state deliberately live in their existing models/config.
    """

    __tablename__ = "business_module_access"
    __table_args__ = (
        UniqueConstraint("business_id", "module_key", name="uq_business_module_access"),
        CheckConstraint(
            "module_key IN ('essential','growth','social')",
            name="ck_business_module_access_key",
        ),
        CheckConstraint(
            "module_cost_amount IS NULL OR module_cost_amount >= 0",
            name="ck_business_module_access_cost_nonnegative",
        ),
        CheckConstraint(
            "module_cost_period IN ('monthly')",
            name="ck_business_module_access_cost_period",
        ),
        Index("ix_business_module_access_business_active", "business_id", "active"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    business_id: Mapped[int] = mapped_column(
        ForeignKey("businesses.id", ondelete="CASCADE"), nullable=False, index=True
    )
    module_key: Mapped[str] = mapped_column(String(30), nullable=False, index=True)
    entitled: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    module_cost_amount: Mapped[Decimal | None] = mapped_column(Numeric(12, 2))
    module_cost_currency: Mapped[str | None] = mapped_column(String(3))
    module_cost_period: Mapped[str] = mapped_column(
        String(20), default="monthly", nullable=False
    )
    updated_by_user_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), index=True
    )
    created_at: Mapped[datetime] = mapped_column(
        UTCDateTime(), default=utc_now, nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        UTCDateTime(), default=utc_now, onupdate=utc_now, nullable=False
    )

    business = relationship("Business", back_populates="module_access")


class PilotBaseline(Base):
    """Optional pre-pilot reference values; never presented as causal attribution."""

    __tablename__ = "pilot_baselines"
    __table_args__ = (
        UniqueConstraint("business_id", name="uq_pilot_baselines_business"),
        CheckConstraint(
            "monthly_bookings IS NULL OR monthly_bookings >= 0",
            name="ck_pilot_baselines_bookings_nonnegative",
        ),
        CheckConstraint(
            "average_ticket IS NULL OR average_ticket >= 0",
            name="ck_pilot_baselines_ticket_nonnegative",
        ),
        CheckConstraint(
            "occupancy_percentage IS NULL OR "
            "(occupancy_percentage >= 0 AND occupancy_percentage <= 100)",
            name="ck_pilot_baselines_occupancy_range",
        ),
        CheckConstraint(
            "recurring_customer_percentage IS NULL OR "
            "(recurring_customer_percentage >= 0 AND recurring_customer_percentage <= 100)",
            name="ck_pilot_baselines_recurrence_range",
        ),
        CheckConstraint(
            "cancellation_percentage IS NULL OR "
            "(cancellation_percentage >= 0 AND cancellation_percentage <= 100)",
            name="ck_pilot_baselines_cancellation_range",
        ),
        CheckConstraint(
            "no_show_percentage IS NULL OR "
            "(no_show_percentage >= 0 AND no_show_percentage <= 100)",
            name="ck_pilot_baselines_no_show_range",
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    business_id: Mapped[int] = mapped_column(
        ForeignKey("businesses.id", ondelete="CASCADE"), nullable=False, unique=True
    )
    monthly_bookings: Mapped[int | None]
    average_ticket: Mapped[Decimal | None] = mapped_column(Numeric(12, 2))
    occupancy_percentage: Mapped[Decimal | None] = mapped_column(Numeric(5, 2))
    recurring_customer_percentage: Mapped[Decimal | None] = mapped_column(Numeric(5, 2))
    cancellation_percentage: Mapped[Decimal | None] = mapped_column(Numeric(5, 2))
    no_show_percentage: Mapped[Decimal | None] = mapped_column(Numeric(5, 2))
    currency: Mapped[str] = mapped_column(String(3), default="EUR", nullable=False)
    notes: Mapped[str | None] = mapped_column(Text)
    captured_at: Mapped[datetime] = mapped_column(
        UTCDateTime(), default=utc_now, nullable=False
    )
    updated_by_user_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), index=True
    )
    updated_at: Mapped[datetime] = mapped_column(
        UTCDateTime(), default=utc_now, onupdate=utc_now, nullable=False
    )

    business = relationship("Business", back_populates="pilot_baseline")
