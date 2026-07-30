from datetime import datetime

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Index, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base

INTEGRATION_STATUSES = (
    "pending",
    "connected",
    "degraded",
    "expired",
    "disconnected",
    "revoked",
    "error",
)


class BusinessChannelIntegration(Base):
    __tablename__ = "business_channel_integrations"
    __table_args__ = (
        UniqueConstraint(
            "provider",
            "external_account_id",
            name="uq_channel_integration_provider_account",
        ),
        UniqueConstraint(
            "business_id",
            "provider",
            name="uq_channel_integration_business_provider",
        ),
        CheckConstraint(
            "integration_status IN ('pending','connected','degraded','expired',"
            "'disconnected','revoked','error')",
            name="ck_channel_integration_status",
        ),
        CheckConstraint(
            "(encrypted_access_token IS NULL AND encryption_key_version IS NULL) OR "
            "(encrypted_access_token IS NOT NULL AND encryption_key_version IS NOT NULL)",
            name="ck_channel_integration_encrypted_token_version",
        ),
        Index(
            "ix_channel_integrations_business_provider",
            "business_id",
            "provider",
        ),
        Index(
            "ix_channel_integrations_provider_account_status",
            "provider",
            "external_account_id",
            "integration_status",
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    business_id: Mapped[int] = mapped_column(
        ForeignKey("businesses.id", ondelete="CASCADE"), nullable=False, index=True
    )
    channel: Mapped[str] = mapped_column(String(40), nullable=False, index=True)
    provider: Mapped[str] = mapped_column(String(60), nullable=False, index=True)
    external_account_id: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    external_account_name: Mapped[str | None] = mapped_column(String(255))
    encrypted_access_token: Mapped[str | None] = mapped_column(Text)
    encryption_key_version: Mapped[str | None] = mapped_column(String(60), index=True)
    token_type: Mapped[str | None] = mapped_column(String(40))
    token_expires_at: Mapped[datetime | None] = mapped_column(DateTime, index=True)
    token_last_refreshed_at: Mapped[datetime | None] = mapped_column(DateTime)
    granted_scopes_json: Mapped[str | None] = mapped_column(Text)
    integration_status: Mapped[str] = mapped_column(
        String(30), default="pending", nullable=False, index=True
    )
    provider_status: Mapped[str | None] = mapped_column(String(80))
    connected_at: Mapped[datetime | None] = mapped_column(DateTime)
    disconnected_at: Mapped[datetime | None] = mapped_column(DateTime)
    last_verified_at: Mapped[datetime | None] = mapped_column(DateTime)
    last_success_at: Mapped[datetime | None] = mapped_column(DateTime)
    last_error_at: Mapped[datetime | None] = mapped_column(DateTime)
    last_error_code: Mapped[str | None] = mapped_column(String(80))
    last_error_subcode: Mapped[str | None] = mapped_column(String(80))
    last_error_type: Mapped[str | None] = mapped_column(String(120))
    safe_error_message: Mapped[str | None] = mapped_column(String(500))
    metadata_json: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow, nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False
    )

    business = relationship("Business", back_populates="channel_integrations")
