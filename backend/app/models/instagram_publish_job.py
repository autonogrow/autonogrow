from datetime import datetime, timezone

from sqlalchemy import CheckConstraint, ForeignKey, Index, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base
from app.models.utc_datetime import UTCDateTime

INSTAGRAM_PUBLISH_JOB_STATUSES = (
    "queued",
    "claimed",
    "creating_container",
    "publishing",
    "simulating_publish",
    "published",
    "retry_wait",
    "failed",
    "action_required",
    "cancelled",
)


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


class InstagramPublishJob(Base):
    __tablename__ = "instagram_publish_jobs"
    __table_args__ = (
        CheckConstraint("attempt_count >= 0", name="ck_instagram_publish_jobs_attempts"),
        CheckConstraint("max_attempts > 0", name="ck_instagram_publish_jobs_max_attempts"),
        CheckConstraint(
            "status IN ('queued','claimed','creating_container','publishing',"
            "'simulating_publish','published','retry_wait',"
            "'failed','action_required','cancelled')",
            name="ck_instagram_publish_jobs_status",
        ),
        UniqueConstraint("content_version_id", name="uq_instagram_publish_job_version"),
        Index("ix_instagram_publish_jobs_status_scheduled", "status", "scheduled_for"),
        Index("ix_instagram_publish_jobs_status_next_attempt", "status", "next_attempt_at"),
        Index("ix_instagram_publish_jobs_claim_expiry", "status", "claim_expires_at"),
        Index("ix_instagram_publish_jobs_business_created", "business_id", "created_at"),
        Index("ix_instagram_publish_jobs_content_created", "content_item_id", "created_at"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    business_id: Mapped[int] = mapped_column(
        ForeignKey("businesses.id", ondelete="CASCADE"), nullable=False, index=True
    )
    content_item_id: Mapped[int] = mapped_column(
        ForeignKey("instagram_contents.id", ondelete="CASCADE"), nullable=False, index=True
    )
    content_version_id: Mapped[int] = mapped_column(
        ForeignKey("instagram_content_versions.id", ondelete="CASCADE"), nullable=False, index=True
    )
    integration_id: Mapped[int | None] = mapped_column(
        ForeignKey("business_channel_integrations.id", ondelete="SET NULL"), index=True
    )
    status: Mapped[str] = mapped_column(String(30), default="queued", nullable=False, index=True)
    scheduled_for: Mapped[datetime] = mapped_column(UTCDateTime(), nullable=False, index=True)
    attempt_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    max_attempts: Mapped[int] = mapped_column(Integer, nullable=False)
    next_attempt_at: Mapped[datetime | None] = mapped_column(UTCDateTime(), index=True)
    claimed_at: Mapped[datetime | None] = mapped_column(UTCDateTime())
    claim_expires_at: Mapped[datetime | None] = mapped_column(UTCDateTime(), index=True)
    claimed_by: Mapped[str | None] = mapped_column(String(200))
    idempotency_key: Mapped[str] = mapped_column(String(255), unique=True, nullable=False)
    provider_container_id: Mapped[str | None] = mapped_column(String(255))
    provider_media_id: Mapped[str | None] = mapped_column(String(255), index=True)
    provider_permalink: Mapped[str | None] = mapped_column(String(500))
    provider_status: Mapped[str | None] = mapped_column(String(80))
    provider_error_code: Mapped[str | None] = mapped_column(String(120))
    safe_error_message: Mapped[str | None] = mapped_column(String(500))
    provider_metadata_json: Mapped[str | None] = mapped_column(Text)
    created_by_user_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), index=True
    )
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=_utc_now, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        UTCDateTime(), default=_utc_now, onupdate=_utc_now, nullable=False
    )
    published_at: Mapped[datetime | None] = mapped_column(UTCDateTime())
    cancelled_at: Mapped[datetime | None] = mapped_column(UTCDateTime())

    content = relationship("InstagramContent", back_populates="publish_jobs")
    version = relationship("InstagramContentVersion", back_populates="publish_job")
    integration = relationship("BusinessChannelIntegration")
