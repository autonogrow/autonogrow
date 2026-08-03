from datetime import datetime

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Index, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base

CONTROLLED_CHANNELS = ("instagram", "whatsapp")
CHANNEL_CONTROL_STATUSES = (
    "available",
    "pending_approval",
    "approved",
    "suspended",
    "revoked",
)
CHANNEL_CONNECTOR_POLICIES = ("business_admin", "owner_only")


class BusinessChannelControl(Base):
    __tablename__ = "business_channel_controls"
    __table_args__ = (
        UniqueConstraint("business_id", "channel", name="uq_business_channel_control"),
        CheckConstraint(
            "channel IN ('instagram','whatsapp')",
            name="ck_business_channel_control_channel",
        ),
        CheckConstraint(
            "status IN ('available','pending_approval','approved','suspended','revoked')",
            name="ck_business_channel_control_status",
        ),
        CheckConstraint(
            "connector_policy IN ('business_admin','owner_only')",
            name="ck_business_channel_control_connector_policy",
        ),
        CheckConstraint(
            "connection_mode IN ('simulated','legacy')",
            name="ck_business_channel_control_connection_mode",
        ),
        CheckConstraint(
            "status = 'approved' OR "
            "(integrated_delivery_enabled = false AND automation_enabled = false)",
            name="ck_business_channel_control_approved_capabilities",
        ),
        Index("ix_business_channel_controls_business_status", "business_id", "status"),
    )

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    business_id: Mapped[int] = mapped_column(
        ForeignKey("businesses.id", ondelete="CASCADE"), nullable=False, index=True
    )
    channel: Mapped[str] = mapped_column(String(40), nullable=False, index=True)
    status: Mapped[str] = mapped_column(String(30), default="available", nullable=False, index=True)
    connector_policy: Mapped[str] = mapped_column(
        String(30), default="business_admin", nullable=False
    )
    connection_mode: Mapped[str] = mapped_column(String(30), default="simulated", nullable=False)
    integrated_delivery_enabled: Mapped[bool] = mapped_column(default=False, nullable=False)
    automation_enabled: Mapped[bool] = mapped_column(default=False, nullable=False)
    requested_by_user_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), index=True
    )
    requested_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    approved_by_user_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), index=True
    )
    approved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    suspended_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_reason: Mapped[str | None] = mapped_column(String(500))
    created_by_user_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), index=True
    )
    updated_by_user_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), index=True
    )
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False
    )

    business = relationship("Business", back_populates="channel_controls")
