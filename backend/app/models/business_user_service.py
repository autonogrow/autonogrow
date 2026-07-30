from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


class BusinessUserService(Base):
    __tablename__ = "business_user_services"
    __table_args__ = (
        UniqueConstraint("business_user_id", "service_id", name="uq_business_user_service"),
    )

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    business_user_id: Mapped[int] = mapped_column(
        ForeignKey("business_users.id", ondelete="CASCADE"), index=True
    )
    service_id: Mapped[int] = mapped_column(
        ForeignKey("services.id", ondelete="CASCADE"), index=True
    )
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False)
