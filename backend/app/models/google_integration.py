from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base


class GoogleIntegration(Base):
    __tablename__ = "google_integrations"

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    business_id: Mapped[int] = mapped_column(
        ForeignKey("businesses.id", ondelete="CASCADE"), index=True
    )

    cluster_name: Mapped[str | None] = mapped_column(String(120))
    gcp_project_id: Mapped[str | None] = mapped_column(String(200))

    service_account_email: Mapped[str | None] = mapped_column(String(300))
    credentials_ref: Mapped[str | None] = mapped_column(Text)
    calendar_id: Mapped[str | None] = mapped_column(String(300))

    status: Mapped[str] = mapped_column(String(60), default="not_configured", nullable=False)
    last_successful_sync_at: Mapped[datetime | None] = mapped_column(DateTime)
    last_error: Mapped[str | None] = mapped_column(Text)

    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False
    )

    business = relationship("Business", back_populates="google_integrations")
