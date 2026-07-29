from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base


class SystemIncident(Base):
    __tablename__ = "system_incidents"

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    incident_key: Mapped[str] = mapped_column(String(64), unique=True, index=True, nullable=False)
    severity: Mapped[str] = mapped_column(String(20), index=True, nullable=False)
    category: Mapped[str] = mapped_column(String(80), index=True, nullable=False)
    status: Mapped[str] = mapped_column(String(20), default="open", index=True, nullable=False)
    business_id: Mapped[int | None] = mapped_column(
        ForeignKey("businesses.id", ondelete="SET NULL"), index=True
    )
    integration_id: Mapped[int | None] = mapped_column(
        ForeignKey("business_channel_integrations.id", ondelete="SET NULL"), index=True
    )
    channel: Mapped[str | None] = mapped_column(String(40), index=True)
    provider: Mapped[str | None] = mapped_column(String(60), index=True)
    provider_error_code: Mapped[str | None] = mapped_column(String(80), index=True)
    operation: Mapped[str] = mapped_column(String(100), index=True, nullable=False)
    conversation_id: Mapped[int | None] = mapped_column(Integer, index=True)
    message_id: Mapped[int | None] = mapped_column(Integer, index=True)
    occurrence_count: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    first_occurred_at: Mapped[datetime] = mapped_column(DateTime, index=True, nullable=False)
    last_occurred_at: Mapped[datetime] = mapped_column(DateTime, index=True, nullable=False)
    notified_at: Mapped[datetime | None] = mapped_column(DateTime, index=True)
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime, index=True)
    safe_details_json: Mapped[str] = mapped_column(Text, default="{}", nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False
    )

    business = relationship("Business", back_populates="system_incidents")
