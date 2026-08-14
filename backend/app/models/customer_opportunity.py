from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import CheckConstraint, ForeignKey, Index, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base
from app.models.utc_datetime import UTCDateTime

OPPORTUNITY_TYPES = (
    "cancelled_not_rebooked",
    "no_show_not_rebooked",
    "lead_not_converted",
    "service_due",
    "scheduled_followup",
)
OPPORTUNITY_STATUSES = ("pending", "actioned", "dismissed", "resolved", "expired")
OPPORTUNITY_PRIORITIES = ("low", "normal", "high")


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


class CustomerOpportunity(Base):
    __tablename__ = "customer_opportunities"
    __table_args__ = (
        CheckConstraint(
            "type IN ('cancelled_not_rebooked','no_show_not_rebooked',"
            "'lead_not_converted','service_due','scheduled_followup')",
            name="ck_customer_opportunities_type",
        ),
        CheckConstraint(
            "status IN ('pending','actioned','dismissed','resolved','expired')",
            name="ck_customer_opportunities_status",
        ),
        CheckConstraint(
            "priority IN ('low','normal','high')",
            name="ck_customer_opportunities_priority",
        ),
        CheckConstraint(
            "follow_up_interval_days_snapshot IS NULL OR follow_up_interval_days_snapshot > 0",
            name="ck_customer_opportunities_interval_positive",
        ),
        CheckConstraint(
            "follow_up_window_days_snapshot IS NULL OR follow_up_window_days_snapshot >= 0",
            name="ck_customer_opportunities_window_nonnegative",
        ),
        UniqueConstraint("business_id", "dedupe_key", name="uq_opportunity_business_dedupe"),
        UniqueConstraint(
            "scheduled_followup_id", name="uq_customer_opportunity_scheduled_followup"
        ),
        Index(
            "ix_customer_opportunities_business_status_due",
            "business_id",
            "status",
            "due_at",
        ),
        Index(
            "ix_customer_opportunities_business_customer",
            "business_id",
            "customer_id",
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    business_id: Mapped[int] = mapped_column(
        ForeignKey("businesses.id", ondelete="CASCADE"), nullable=False, index=True
    )
    customer_id: Mapped[int] = mapped_column(
        ForeignKey("customers.id", ondelete="CASCADE"), nullable=False, index=True
    )
    type: Mapped[str] = mapped_column(String(50), nullable=False, index=True)
    status: Mapped[str] = mapped_column(
        String(30), default="pending", nullable=False, index=True
    )
    priority: Mapped[str] = mapped_column(String(20), default="normal", nullable=False)
    detected_at: Mapped[datetime] = mapped_column(UTCDateTime(), nullable=False)
    due_at: Mapped[datetime] = mapped_column(UTCDateTime(), nullable=False, index=True)
    expires_at: Mapped[datetime | None] = mapped_column(UTCDateTime(), index=True)
    actioned_at: Mapped[datetime | None] = mapped_column(UTCDateTime())
    resolved_at: Mapped[datetime | None] = mapped_column(UTCDateTime())
    dismissed_at: Mapped[datetime | None] = mapped_column(UTCDateTime())
    source_booking_id: Mapped[int | None] = mapped_column(
        ForeignKey("bookings.id", ondelete="SET NULL"), index=True
    )
    source_service_id: Mapped[int | None] = mapped_column(
        ForeignKey("services.id", ondelete="SET NULL"), index=True
    )
    source_conversation_id: Mapped[int | None] = mapped_column(
        ForeignKey("conversations.id", ondelete="SET NULL"), index=True
    )
    scheduled_followup_id: Mapped[int | None] = mapped_column(
        ForeignKey("scheduled_customer_followups.id", ondelete="SET NULL"), index=True
    )
    reason_code: Mapped[str] = mapped_column(String(100), nullable=False)
    reason_text: Mapped[str] = mapped_column(Text, nullable=False)
    dedupe_key: Mapped[str] = mapped_column(String(255), nullable=False)
    source_occurred_at: Mapped[datetime | None] = mapped_column(UTCDateTime())
    follow_up_interval_days_snapshot: Mapped[int | None] = mapped_column(Integer)
    follow_up_window_days_snapshot: Mapped[int | None] = mapped_column(Integer)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utc_now, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        UTCDateTime(), default=utc_now, onupdate=utc_now, nullable=False
    )

    business = relationship("Business", back_populates="customer_opportunities")
    customer = relationship("Customer", back_populates="opportunities")
    source_booking = relationship("Booking", back_populates="opportunities")
    source_service = relationship("BusinessService", back_populates="opportunities")
    source_conversation = relationship("Conversation", back_populates="opportunities")
    scheduled_followup = relationship("ScheduledCustomerFollowUp", back_populates="opportunity")


class ScheduledCustomerFollowUp(Base):
    __tablename__ = "scheduled_customer_followups"
    __table_args__ = (
        CheckConstraint(
            "status IN ('scheduled','cancelled','converted')",
            name="ck_scheduled_customer_followups_status",
        ),
        UniqueConstraint("business_id", "dedupe_key", name="uq_followup_business_dedupe"),
        Index(
            "ix_scheduled_followups_business_status_due",
            "business_id",
            "status",
            "due_at",
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    business_id: Mapped[int] = mapped_column(
        ForeignKey("businesses.id", ondelete="CASCADE"), nullable=False, index=True
    )
    customer_id: Mapped[int] = mapped_column(
        ForeignKey("customers.id", ondelete="CASCADE"), nullable=False, index=True
    )
    booking_id: Mapped[int | None] = mapped_column(
        ForeignKey("bookings.id", ondelete="SET NULL"), index=True
    )
    service_id: Mapped[int | None] = mapped_column(
        ForeignKey("services.id", ondelete="SET NULL"), index=True
    )
    created_by_user_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), index=True
    )
    due_at: Mapped[datetime] = mapped_column(UTCDateTime(), nullable=False, index=True)
    status: Mapped[str] = mapped_column(
        String(30), default="scheduled", nullable=False, index=True
    )
    note: Mapped[str | None] = mapped_column(String(500))
    dedupe_key: Mapped[str] = mapped_column(String(255), nullable=False)
    cancelled_at: Mapped[datetime | None] = mapped_column(UTCDateTime())
    converted_at: Mapped[datetime | None] = mapped_column(UTCDateTime())
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utc_now, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        UTCDateTime(), default=utc_now, onupdate=utc_now, nullable=False
    )

    business = relationship("Business", back_populates="scheduled_customer_followups")
    customer = relationship("Customer", back_populates="scheduled_followups")
    booking = relationship("Booking", back_populates="scheduled_followups")
    service = relationship("BusinessService", back_populates="scheduled_followups")
    opportunity = relationship(
        "CustomerOpportunity", back_populates="scheduled_followup", uselist=False
    )
