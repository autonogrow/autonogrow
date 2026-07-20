from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base


class MessageOutbox(Base):
    __tablename__ = "message_outbox"
    __table_args__ = (
        UniqueConstraint(
            "business_id",
            "booking_id",
            "message_type",
            name="uq_message_outbox_booking_event",
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    business_id: Mapped[int] = mapped_column(
        ForeignKey("businesses.id", ondelete="CASCADE"), index=True
    )
    booking_id: Mapped[int | None] = mapped_column(
        ForeignKey("bookings.id", ondelete="CASCADE"), index=True
    )
    review_request_id: Mapped[int | None] = mapped_column(
        ForeignKey("review_requests.id", ondelete="SET NULL"), index=True
    )

    customer_name: Mapped[str] = mapped_column(String(200), nullable=False)
    customer_phone: Mapped[str | None] = mapped_column(String(40))
    channel: Mapped[str] = mapped_column(String(40), default="whatsapp", nullable=False)
    message_type: Mapped[str] = mapped_column(String(80), nullable=False, index=True)
    message: Mapped[str] = mapped_column(Text, nullable=False)
    whatsapp_url: Mapped[str | None] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(40), default="pending", nullable=False, index=True)

    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False)
    opened_at: Mapped[datetime | None] = mapped_column(DateTime)
    sent_at: Mapped[datetime | None] = mapped_column(DateTime)
    skipped_at: Mapped[datetime | None] = mapped_column(DateTime)

    business = relationship("Business", back_populates="message_outbox")
    booking = relationship("Booking", back_populates="message_outbox")
    review_request = relationship("ReviewRequest", back_populates="message_outbox")
