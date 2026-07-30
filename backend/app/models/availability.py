from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base


class WeeklyAvailability(Base):
    __tablename__ = "weekly_availability"

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    business_id: Mapped[int] = mapped_column(
        ForeignKey("businesses.id", ondelete="CASCADE"), index=True
    )

    weekday: Mapped[int] = mapped_column(Integer, nullable=False)
    slots_json: Mapped[str] = mapped_column(Text, nullable=False)
    active: Mapped[bool] = mapped_column(default=True, nullable=False)

    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False)


class BlockedDate(Base):
    __tablename__ = "blocked_dates"

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    business_id: Mapped[int] = mapped_column(
        ForeignKey("businesses.id", ondelete="CASCADE"), index=True
    )

    date: Mapped[str] = mapped_column(String(20), nullable=False)
    reason: Mapped[str | None] = mapped_column(Text)

    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False)


class AvailabilitySettings(Base):
    __tablename__ = "availability_settings"

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    business_id: Mapped[int] = mapped_column(
        ForeignKey("businesses.id", ondelete="CASCADE"), unique=True, index=True
    )

    timezone: Mapped[str] = mapped_column(String(80), default="Europe/Madrid", nullable=False)
    slot_interval_minutes: Mapped[int] = mapped_column(Integer, default=15, nullable=False)
    buffer_between_bookings_minutes: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    min_notice_minutes: Mapped[int] = mapped_column(Integer, default=120, nullable=False)
    max_days_ahead: Mapped[int] = mapped_column(Integer, default=30, nullable=False)
    weekly_schedule_json: Mapped[str] = mapped_column(Text, nullable=False)

    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False
    )


class AvailabilityException(Base):
    __tablename__ = "availability_exceptions"

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    business_id: Mapped[int] = mapped_column(
        ForeignKey("businesses.id", ondelete="CASCADE"), index=True
    )

    date: Mapped[str] = mapped_column(String(20), index=True, nullable=False)
    type: Mapped[str] = mapped_column(String(40), nullable=False)
    windows_json: Mapped[str | None] = mapped_column(Text)
    reason: Mapped[str | None] = mapped_column(Text)

    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False)


class BusinessUserAvailability(Base):
    __tablename__ = "business_user_availability"
    __table_args__ = (
        UniqueConstraint("business_user_id", "weekday", name="uq_business_user_availability_day"),
    )

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    business_user_id: Mapped[int] = mapped_column(
        ForeignKey("business_users.id", ondelete="CASCADE"), index=True
    )
    weekday: Mapped[int] = mapped_column(Integer, nullable=False)
    windows_json: Mapped[str] = mapped_column(Text, nullable=False, default="[]")
    active: Mapped[bool] = mapped_column(default=True, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False
    )

    business_user = relationship("BusinessUser", back_populates="availability")


class BusinessUserAvailabilityException(Base):
    __tablename__ = "business_user_availability_exceptions"
    __table_args__ = (
        UniqueConstraint(
            "business_user_id", "date", name="uq_business_user_availability_exception_date"
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    business_user_id: Mapped[int] = mapped_column(
        ForeignKey("business_users.id", ondelete="CASCADE"), index=True
    )
    date: Mapped[str] = mapped_column(String(20), index=True, nullable=False)
    type: Mapped[str] = mapped_column(String(40), nullable=False)
    windows_json: Mapped[str | None] = mapped_column(Text)
    reason: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False
    )

    business_user = relationship("BusinessUser", back_populates="availability_exceptions")
