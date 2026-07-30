from datetime import datetime

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Index, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


class WebhookInboxEvent(Base):
    __tablename__ = "webhook_inbox_events"
    __table_args__ = (
        CheckConstraint("attempt_count >= 0", name="ck_webhook_inbox_attempt_count"),
        CheckConstraint("max_attempts > 0", name="ck_webhook_inbox_max_attempts"),
        CheckConstraint("payload_size_bytes >= 0", name="ck_webhook_inbox_payload_size"),
        CheckConstraint(
            "status IN ('pending','processing','processed','retry','ignored','failed','dead_letter','cancelled')",
            name="ck_webhook_inbox_status",
        ),
        Index("ix_webhook_inbox_status_available", "status", "available_at"),
        Index("ix_webhook_inbox_status_retry", "status", "next_retry_at"),
        Index("ix_webhook_inbox_provider_event", "provider", "provider_event_id"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    provider: Mapped[str] = mapped_column(String(40), nullable=False)
    channel: Mapped[str] = mapped_column(String(40), nullable=False)
    event_type: Mapped[str | None] = mapped_column(String(80))
    provider_event_id: Mapped[str | None] = mapped_column(String(255))
    idempotency_key: Mapped[str] = mapped_column(String(255), unique=True, nullable=False)
    payload_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    payload_json: Mapped[str] = mapped_column(Text, nullable=False)
    payload_size_bytes: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[str] = mapped_column(String(30), nullable=False, default="pending")
    attempt_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    max_attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=5)
    received_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=datetime.utcnow)
    available_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, default=datetime.utcnow
    )
    processing_started_at: Mapped[datetime | None] = mapped_column(DateTime)
    processed_at: Mapped[datetime | None] = mapped_column(DateTime)
    failed_at: Mapped[datetime | None] = mapped_column(DateTime)
    next_retry_at: Mapped[datetime | None] = mapped_column(DateTime)
    locked_by: Mapped[str | None] = mapped_column(String(200))
    lock_expires_at: Mapped[datetime | None] = mapped_column(DateTime, index=True)
    business_id: Mapped[int | None] = mapped_column(
        ForeignKey("businesses.id", ondelete="SET NULL"), index=True
    )
    integration_id: Mapped[int | None] = mapped_column(
        ForeignKey("business_channel_integrations.id", ondelete="SET NULL"), index=True
    )
    last_error_code: Mapped[str | None] = mapped_column(String(120))
    safe_error_message: Mapped[str | None] = mapped_column(String(500))
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow
    )


class ChannelOutboxMessage(Base):
    __tablename__ = "channel_outbox_messages"
    __table_args__ = (
        CheckConstraint("attempt_count >= 0", name="ck_channel_outbox_attempt_count"),
        CheckConstraint("max_attempts > 0", name="ck_channel_outbox_max_attempts"),
        CheckConstraint(
            "status IN ('pending','processing','sent','retry','blocked','failed','dead_letter','cancelled')",
            name="ck_channel_outbox_status",
        ),
        Index("ix_channel_outbox_status_available", "status", "available_at"),
        Index("ix_channel_outbox_status_retry", "status", "next_retry_at"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    business_id: Mapped[int] = mapped_column(
        ForeignKey("businesses.id", ondelete="CASCADE"), nullable=False, index=True
    )
    integration_id: Mapped[int] = mapped_column(
        ForeignKey("business_channel_integrations.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    conversation_id: Mapped[int] = mapped_column(
        ForeignKey("conversations.id", ondelete="CASCADE"), nullable=False, index=True
    )
    conversation_message_id: Mapped[int | None] = mapped_column(
        ForeignKey("conversation_messages.id", ondelete="SET NULL"), unique=True
    )
    channel: Mapped[str] = mapped_column(String(40), nullable=False)
    provider: Mapped[str] = mapped_column(String(40), nullable=False)
    recipient_external_id: Mapped[str] = mapped_column(String(255), nullable=False)
    payload_json: Mapped[str] = mapped_column(Text, nullable=False)
    idempotency_key: Mapped[str] = mapped_column(String(255), unique=True, nullable=False)
    status: Mapped[str] = mapped_column(String(30), nullable=False, default="pending")
    attempt_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    max_attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=5)
    available_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, default=datetime.utcnow
    )
    processing_started_at: Mapped[datetime | None] = mapped_column(DateTime)
    sent_at: Mapped[datetime | None] = mapped_column(DateTime)
    failed_at: Mapped[datetime | None] = mapped_column(DateTime)
    next_retry_at: Mapped[datetime | None] = mapped_column(DateTime)
    locked_by: Mapped[str | None] = mapped_column(String(200))
    lock_expires_at: Mapped[datetime | None] = mapped_column(DateTime, index=True)
    provider_message_id: Mapped[str | None] = mapped_column(String(255), index=True)
    last_http_status: Mapped[int | None] = mapped_column(Integer)
    last_error_code: Mapped[str | None] = mapped_column(String(120))
    last_error_subcode: Mapped[str | None] = mapped_column(String(120))
    last_error_type: Mapped[str | None] = mapped_column(String(120))
    safe_error_message: Mapped[str | None] = mapped_column(String(500))
    created_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, default=datetime.utcnow, index=True
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow
    )


class WorkerHeartbeat(Base):
    __tablename__ = "worker_heartbeats"
    __table_args__ = (
        CheckConstraint(
            "status IN ('starting','idle','processing','stopping','stopped','error')",
            name="ck_worker_heartbeat_status",
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    worker_id: Mapped[str] = mapped_column(String(200), unique=True, nullable=False)
    worker_type: Mapped[str] = mapped_column(String(80), nullable=False)
    status: Mapped[str] = mapped_column(String(30), nullable=False, default="starting")
    started_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=datetime.utcnow)
    last_seen_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, default=datetime.utcnow
    )
    current_job_type: Mapped[str | None] = mapped_column(String(40))
    current_job_id: Mapped[int | None] = mapped_column(Integer)
    version: Mapped[str | None] = mapped_column(String(80))
    hostname: Mapped[str | None] = mapped_column(String(255))
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow
    )
