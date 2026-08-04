from datetime import datetime

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Index, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base

META_INTEGRATION_JOB_TYPES = ("health_check", "retry_subscription", "attempt_cleanup")
META_INTEGRATION_JOB_STATUSES = (
    "queued",
    "processing",
    "retry",
    "completed",
    "failed",
    "dead_letter",
)
META_INTEGRATION_JOB_ORIGINS = ("scheduler", "owner", "admin", "system")


class MetaIntegrationJob(Base):
    __tablename__ = "meta_integration_jobs"
    __table_args__ = (
        CheckConstraint(
            "job_type IN ('health_check','retry_subscription','attempt_cleanup')",
            name="ck_meta_integration_job_type",
        ),
        CheckConstraint(
            "status IN ('queued','processing','retry','completed','failed','dead_letter')",
            name="ck_meta_integration_job_status",
        ),
        CheckConstraint(
            "origin IN ('scheduler','owner','admin','system')",
            name="ck_meta_integration_job_origin",
        ),
        CheckConstraint("attempt_count >= 0", name="ck_meta_integration_job_attempt_count"),
        CheckConstraint("max_attempts > 0", name="ck_meta_integration_job_max_attempts"),
        CheckConstraint(
            "((job_type IN ('health_check','retry_subscription') AND integration_id IS NOT NULL) "
            "OR (job_type = 'attempt_cleanup' AND integration_id IS NULL))",
            name="ck_meta_integration_job_integration_required",
        ),
        Index("ix_meta_integration_jobs_status_available", "status", "available_at"),
        Index("ix_meta_integration_jobs_status_lock", "status", "lock_expires_at"),
        Index("ix_meta_integration_jobs_business_status", "business_id", "status"),
        Index(
            "ix_meta_integration_jobs_integration_type_status",
            "integration_id",
            "job_type",
            "status",
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    business_id: Mapped[int] = mapped_column(
        ForeignKey("businesses.id", ondelete="CASCADE"), nullable=False, index=True
    )
    integration_id: Mapped[int | None] = mapped_column(
        ForeignKey("business_channel_integrations.id", ondelete="CASCADE"), index=True
    )
    job_type: Mapped[str] = mapped_column(String(30), nullable=False, index=True)
    status: Mapped[str] = mapped_column(
        String(30), nullable=False, default="queued", server_default="queued", index=True
    )
    idempotency_key: Mapped[str] = mapped_column(String(255), nullable=False, unique=True)
    actor_user_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), index=True
    )
    origin: Mapped[str] = mapped_column(String(20), nullable=False)
    attempt_count: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default="0"
    )
    max_attempts: Mapped[int] = mapped_column(
        Integer, nullable=False, default=5, server_default="5"
    )
    available_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, default=datetime.utcnow
    )
    next_retry_at: Mapped[datetime | None] = mapped_column(DateTime)
    locked_by: Mapped[str | None] = mapped_column(String(200))
    lock_expires_at: Mapped[datetime | None] = mapped_column(DateTime)
    processing_started_at: Mapped[datetime | None] = mapped_column(DateTime)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime)
    failed_at: Mapped[datetime | None] = mapped_column(DateTime)
    duration_ms: Mapped[int | None] = mapped_column(Integer)
    last_error_code: Mapped[str | None] = mapped_column(String(120))
    safe_error_message: Mapped[str | None] = mapped_column(String(500))
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow
    )
