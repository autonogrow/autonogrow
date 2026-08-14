from datetime import datetime
from decimal import Decimal

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base


class BusinessService(Base):
    __tablename__ = "services"

    __table_args__ = (
        UniqueConstraint("business_id", "name", name="uq_service_business_name"),
        CheckConstraint(
            "(duration_minutes IS NULL OR duration_minutes > 0) AND "
            "(price_amount IS NULL OR price_amount >= 0) AND "
            "buffer_before_minutes >= 0 AND buffer_after_minutes >= 0 AND position >= 0 AND "
            "(follow_up_interval_days IS NULL OR follow_up_interval_days > 0) AND "
            "follow_up_window_days >= 0 AND "
            "(follow_up_enabled = false OR follow_up_interval_days IS NOT NULL)",
            name="ck_services_onboarding_values",
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    business_id: Mapped[int] = mapped_column(
        ForeignKey("businesses.id", ondelete="CASCADE"), index=True
    )

    name: Mapped[str] = mapped_column(String(200), nullable=False)
    description: Mapped[str | None] = mapped_column(Text)
    price_text: Mapped[str | None] = mapped_column(String(80))
    duration_text: Mapped[str | None] = mapped_column(String(80))
    duration_minutes: Mapped[int | None] = mapped_column(Integer)
    price_amount: Mapped[Decimal | None] = mapped_column(Numeric(12, 2))
    currency: Mapped[str] = mapped_column(
        String(3), default="EUR", server_default="EUR", nullable=False
    )
    category: Mapped[str | None] = mapped_column(String(120))
    visible: Mapped[bool] = mapped_column(default=True, server_default=text("true"), nullable=False)
    bookable: Mapped[bool] = mapped_column(
        default=True, server_default=text("true"), nullable=False
    )
    requires_approval: Mapped[bool] = mapped_column(
        default=False, server_default=text("false"), nullable=False
    )
    buffer_before_minutes: Mapped[int] = mapped_column(
        Integer, default=0, server_default="0", nullable=False
    )
    buffer_after_minutes: Mapped[int] = mapped_column(
        Integer, default=0, server_default="0", nullable=False
    )
    position: Mapped[int] = mapped_column(Integer, default=0, server_default="0", nullable=False)
    source_key: Mapped[str | None] = mapped_column(String(200), index=True)
    archived_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    follow_up_enabled: Mapped[bool] = mapped_column(
        default=False, server_default=text("false"), nullable=False
    )
    follow_up_interval_days: Mapped[int | None] = mapped_column(Integer)
    follow_up_window_days: Mapped[int] = mapped_column(
        Integer, default=0, server_default="0", nullable=False
    )

    active: Mapped[bool] = mapped_column(default=True, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False)

    business = relationship("Business", back_populates="services")
    bookings = relationship("Booking", back_populates="service")
    opportunities = relationship("CustomerOpportunity", back_populates="source_service")
    scheduled_followups = relationship("ScheduledCustomerFollowUp", back_populates="service")
    growth_signals = relationship("BusinessGrowthSignal", back_populates="service")
    calendar_events = relationship("BusinessCalendarEvent", back_populates="service")
    staff_members = relationship(
        "BusinessUser",
        secondary="business_user_services",
        back_populates="services",
    )
