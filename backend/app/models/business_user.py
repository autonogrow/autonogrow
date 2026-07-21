from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base


class BusinessUser(Base):
    __tablename__ = "business_users"
    __table_args__ = (UniqueConstraint("business_id", "user_id", name="uq_business_user"),)

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    business_id: Mapped[int] = mapped_column(ForeignKey("businesses.id", ondelete="CASCADE"), index=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    role: Mapped[str] = mapped_column(String(40), default="business_staff", nullable=False)
    active: Mapped[bool] = mapped_column(default=True, nullable=False)
    public_name: Mapped[str | None] = mapped_column(String(200))
    bookable: Mapped[bool] = mapped_column(default=False, nullable=False)
    show_schedule: Mapped[bool] = mapped_column(default=True, nullable=False)
    bio: Mapped[str | None] = mapped_column(Text)
    avatar_url: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)

    business = relationship("Business", back_populates="user_memberships")
    user = relationship("User", back_populates="business_memberships")
    availability = relationship(
        "BusinessUserAvailability", back_populates="business_user", cascade="all, delete-orphan"
    )
    availability_exceptions = relationship(
        "BusinessUserAvailabilityException", back_populates="business_user", cascade="all, delete-orphan"
    )
    assigned_bookings = relationship("Booking", back_populates="staff_business_user")
    # TODO: add a business_user_services association when per-professional specialization is needed.
