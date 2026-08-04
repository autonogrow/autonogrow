from datetime import datetime

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Index, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base

INSTAGRAM_OAUTH_PURPOSES = ("initial_connection", "reconnect", "replacement")
INSTAGRAM_OAUTH_STATUSES = (
    "pending",
    "processing",
    "candidate_ready",
    "consumed",
    "expired",
    "cancelled",
    "failed",
    "rejected",
    "approved",
)


class InstagramOAuthAttempt(Base):
    """Short-lived OAuth state and encrypted candidate credentials.

    The opaque state, authorization code and raw provider responses are never
    persisted. A row may outlive its state only while an Owner reviews the
    encrypted candidate.
    """

    __tablename__ = "instagram_oauth_attempts"
    __table_args__ = (
        CheckConstraint(
            "purpose IN ('initial_connection','reconnect','replacement')",
            name="ck_instagram_oauth_attempt_purpose",
        ),
        CheckConstraint(
            "status IN ('pending','processing','candidate_ready','consumed','expired',"
            "'cancelled','failed','rejected','approved')",
            name="ck_instagram_oauth_attempt_status",
        ),
        CheckConstraint(
            "(candidate_encrypted_access_token IS NULL AND "
            "candidate_encryption_key_version IS NULL) OR "
            "(candidate_encrypted_access_token IS NOT NULL AND "
            "candidate_encryption_key_version IS NOT NULL)",
            name="ck_instagram_oauth_attempt_encrypted_token_version",
        ),
        Index(
            "ix_instagram_oauth_attempts_business_status",
            "business_id",
            "status",
        ),
        UniqueConstraint(
            "candidate_external_account_id",
            name="uq_instagram_oauth_attempt_candidate_account",
        ),
        Index(
            "ix_instagram_oauth_attempts_user_status",
            "user_id",
            "status",
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    business_id: Mapped[int] = mapped_column(
        ForeignKey("businesses.id", ondelete="CASCADE"), nullable=False, index=True
    )
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    channel_control_id: Mapped[int] = mapped_column(
        ForeignKey("business_channel_controls.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    purpose: Mapped[str] = mapped_column(String(30), nullable=False, index=True)
    status: Mapped[str] = mapped_column(String(30), nullable=False, index=True)
    state_hash: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)
    session_fingerprint_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    return_path: Mapped[str] = mapped_column(String(500), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    expires_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, index=True
    )
    consumed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    invalidated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    candidate_external_account_id: Mapped[str | None] = mapped_column(String(255), index=True)
    candidate_external_account_name: Mapped[str | None] = mapped_column(String(255))
    candidate_account_type: Mapped[str | None] = mapped_column(String(40))
    candidate_encrypted_access_token: Mapped[str | None] = mapped_column(Text)
    candidate_encryption_key_version: Mapped[str | None] = mapped_column(String(60))
    candidate_token_expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    candidate_granted_scopes: Mapped[str | None] = mapped_column(Text)
    webhook_subscription_status: Mapped[str | None] = mapped_column(String(60))
    safe_error_code: Mapped[str | None] = mapped_column(String(80))
    safe_error_message: Mapped[str | None] = mapped_column(String(500))
    metadata_json: Mapped[str | None] = mapped_column(Text)

    business = relationship("Business", back_populates="instagram_oauth_attempts")
