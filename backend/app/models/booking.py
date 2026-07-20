from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base


class Booking(Base):
    __tablename__ = "bookings"

    id: Mapped[int] = mapped_column(primary_key=True, index=True)

    business_id: Mapped[int] = mapped_column(ForeignKey("businesses.id", ondelete="CASCADE"), index=True)
    customer_id: Mapped[int] = mapped_column(ForeignKey("customers.id", ondelete="CASCADE"), index=True)
    customer_user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), index=True)
    customer_email: Mapped[str | None] = mapped_column(String(320), index=True)
    public_manage_token: Mapped[str | None] = mapped_column(String(255), unique=True, index=True)
    created_by_user: Mapped[bool] = mapped_column(default=False, nullable=False)
    service_id: Mapped[int | None] = mapped_column(ForeignKey("services.id", ondelete="SET NULL"), nullable=True)

    service_name: Mapped[str] = mapped_column(String(200), nullable=False)
    duration_minutes: Mapped[int | None] = mapped_column(Integer)
    start_datetime: Mapped[datetime | None] = mapped_column(DateTime)
    end_datetime: Mapped[datetime | None] = mapped_column(DateTime)

    preferred_date: Mapped[str | None] = mapped_column(String(20))
    preferred_day_label: Mapped[str | None] = mapped_column(String(100))
    preferred_time: Mapped[str] = mapped_column(String(20), nullable=False)

    notes: Mapped[str | None] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(40), default="requested", nullable=False)
    source: Mapped[str] = mapped_column(String(40), default="landing", nullable=False)

    google_calendar_event_id: Mapped[str | None] = mapped_column(String(300))
    google_sync_status: Mapped[str] = mapped_column(String(40), default="pending", nullable=False)

    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)

    business = relationship("Business", back_populates="bookings")
    customer = relationship("Customer", back_populates="bookings")
    customer_user = relationship("User", back_populates="bookings")
    service = relationship("BusinessService", back_populates="bookings")
    sync_jobs = relationship("SyncJob", back_populates="booking", cascade="all, delete-orphan")
    review_request = relationship(
        "ReviewRequest", back_populates="booking", cascade="all, delete-orphan", uselist=False
    )
    message_outbox = relationship(
        "MessageOutbox", back_populates="booking", cascade="all, delete-orphan"
    )
