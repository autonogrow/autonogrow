from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base


class ReviewRequest(Base):
    __tablename__ = "review_requests"
    __table_args__ = (UniqueConstraint("booking_id", name="uq_review_requests_booking_id"),)

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    business_id: Mapped[int] = mapped_column(
        ForeignKey("businesses.id", ondelete="CASCADE"), index=True
    )
    booking_id: Mapped[int] = mapped_column(
        ForeignKey("bookings.id", ondelete="CASCADE"), index=True
    )

    customer_name: Mapped[str] = mapped_column(String(200), nullable=False)
    customer_phone: Mapped[str | None] = mapped_column(String(40))
    reviews_url: Mapped[str] = mapped_column(Text, nullable=False)
    message: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(String(40), default="pending", nullable=False)

    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False)
    copied_at: Mapped[datetime | None] = mapped_column(DateTime)
    sent_at: Mapped[datetime | None] = mapped_column(DateTime)

    business = relationship("Business", back_populates="review_requests")
    booking = relationship("Booking", back_populates="review_request")
    message_outbox = relationship("MessageOutbox", back_populates="review_request")
