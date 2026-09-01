from datetime import datetime
from decimal import Decimal

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    Text,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base


class Booking(Base):
    __tablename__ = "bookings"
    __table_args__ = (
        CheckConstraint(
            "duration_minutes IS NULL OR duration_minutes > 0",
            name="ck_bookings_duration_positive",
        ),
        CheckConstraint(
            "start_datetime IS NULL OR end_datetime IS NULL OR end_datetime > start_datetime",
            name="ck_bookings_datetime_order",
        ),
        CheckConstraint(
            "(follow_up_interval_days_snapshot IS NULL OR "
            "follow_up_interval_days_snapshot > 0) AND "
            "(follow_up_window_days_snapshot IS NULL OR "
            "follow_up_window_days_snapshot >= 0)",
            name="ck_bookings_follow_up_snapshot",
        ),
        CheckConstraint(
            "price_amount_snapshot IS NULL OR price_amount_snapshot >= 0",
            name="ck_bookings_price_snapshot_nonnegative",
        ),
        Index(
            "ix_bookings_business_staff_start_status",
            "business_id",
            "staff_business_user_id",
            "start_datetime",
            "status",
        ),
        Index(
            "ix_bookings_business_start_end_status",
            "business_id",
            "start_datetime",
            "end_datetime",
            "status",
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True, index=True)

    business_id: Mapped[int] = mapped_column(
        ForeignKey("businesses.id", ondelete="CASCADE"), index=True
    )
    customer_id: Mapped[int] = mapped_column(
        ForeignKey("customers.id", ondelete="CASCADE"), index=True
    )
    customer_user_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), index=True
    )
    customer_email: Mapped[str | None] = mapped_column(String(320), index=True)
    public_manage_token_hash: Mapped[str | None] = mapped_column(
        String(64), unique=True, index=True
    )
    public_manage_token_expires_at: Mapped[datetime | None] = mapped_column(DateTime, index=True)
    public_manage_token_revoked_at: Mapped[datetime | None] = mapped_column(DateTime)
    created_by_user: Mapped[bool] = mapped_column(default=False, nullable=False)
    service_id: Mapped[int | None] = mapped_column(
        ForeignKey("services.id", ondelete="SET NULL"), nullable=True
    )
    staff_business_user_id: Mapped[int | None] = mapped_column(
        ForeignKey("business_users.id", ondelete="SET NULL"), index=True
    )

    service_name: Mapped[str] = mapped_column(String(200), nullable=False)
    duration_minutes: Mapped[int | None] = mapped_column(Integer)
    price_amount_snapshot: Mapped[Decimal | None] = mapped_column(Numeric(12, 2))
    currency_snapshot: Mapped[str | None] = mapped_column(String(3))
    follow_up_enabled_snapshot: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    follow_up_interval_days_snapshot: Mapped[int | None] = mapped_column(Integer)
    follow_up_window_days_snapshot: Mapped[int | None] = mapped_column(Integer)
    start_datetime: Mapped[datetime | None] = mapped_column(DateTime)
    end_datetime: Mapped[datetime | None] = mapped_column(DateTime)

    preferred_date: Mapped[str | None] = mapped_column(String(20))
    preferred_day_label: Mapped[str | None] = mapped_column(String(100))
    preferred_time: Mapped[str] = mapped_column(String(20), nullable=False)

    notes: Mapped[str | None] = mapped_column(Text)
    internal_notes: Mapped[str | None] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(40), default="requested", nullable=False)
    source: Mapped[str] = mapped_column(String(40), default="landing", nullable=False)

    google_calendar_event_id: Mapped[str | None] = mapped_column(String(300))
    google_sync_status: Mapped[str] = mapped_column(String(40), default="pending", nullable=False)

    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False
    )

    business = relationship("Business", back_populates="bookings")
    customer = relationship("Customer", back_populates="bookings")
    customer_user = relationship("User", back_populates="bookings")
    service = relationship("BusinessService", back_populates="bookings")
    staff_business_user = relationship("BusinessUser", back_populates="assigned_bookings")
    sync_jobs = relationship("SyncJob", back_populates="booking", cascade="all, delete-orphan")
    review_request = relationship(
        "ReviewRequest", back_populates="booking", cascade="all, delete-orphan", uselist=False
    )
    message_outbox = relationship(
        "MessageOutbox", back_populates="booking", cascade="all, delete-orphan"
    )
    opportunities = relationship("CustomerOpportunity", back_populates="source_booking")
    scheduled_followups = relationship("ScheduledCustomerFollowUp", back_populates="booking")
    opportunity_actions = relationship(
        "OpportunityAction", foreign_keys="OpportunityAction.booking_id", back_populates="booking"
    )
    attribution = relationship("BookingAttribution", back_populates="booking", uselist=False)
