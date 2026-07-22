from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base


class BusinessService(Base):
    __tablename__ = "services"

    __table_args__ = (
        UniqueConstraint("business_id", "name", name="uq_service_business_name"),
    )

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    business_id: Mapped[int] = mapped_column(ForeignKey("businesses.id", ondelete="CASCADE"), index=True)

    name: Mapped[str] = mapped_column(String(200), nullable=False)
    description: Mapped[str | None] = mapped_column(Text)
    price_text: Mapped[str | None] = mapped_column(String(80))
    duration_text: Mapped[str | None] = mapped_column(String(80))
    duration_minutes: Mapped[int | None] = mapped_column(Integer)

    active: Mapped[bool] = mapped_column(default=True, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False)

    business = relationship("Business", back_populates="services")
    bookings = relationship("Booking", back_populates="service")
    staff_members = relationship(
        "BusinessUser",
        secondary="business_user_services",
        back_populates="services",
    )
