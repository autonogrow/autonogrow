from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import CheckConstraint, ForeignKey, Index, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base
from app.models.utc_datetime import UTCDateTime


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


class InstagramRemoteMedia(Base):
    __tablename__ = "instagram_remote_media"
    __table_args__ = (
        CheckConstraint(
            "origin IN ('autonogrow','instagram')",
            name="ck_instagram_remote_media_origin",
        ),
        CheckConstraint(
            "remote_status IN ('available','unavailable')",
            name="ck_instagram_remote_media_status",
        ),
        CheckConstraint("position IS NULL OR position >= 0", name="ck_instagram_remote_position"),
        UniqueConstraint(
            "integration_id",
            "provider_media_id",
            name="uq_instagram_remote_integration_media",
        ),
        Index(
            "ix_instagram_remote_business_status_time",
            "business_id",
            "remote_status",
            "provider_timestamp",
        ),
        Index(
            "ix_instagram_remote_integration_parent",
            "integration_id",
            "parent_id",
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    business_id: Mapped[int] = mapped_column(
        ForeignKey("businesses.id", ondelete="CASCADE"), nullable=False, index=True
    )
    integration_id: Mapped[int] = mapped_column(
        ForeignKey("business_channel_integrations.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    provider_media_id: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    parent_id: Mapped[int | None] = mapped_column(
        ForeignKey("instagram_remote_media.id", ondelete="CASCADE"), index=True
    )
    position: Mapped[int | None] = mapped_column(Integer)
    origin: Mapped[str] = mapped_column(
        String(20), nullable=False, default="instagram", server_default="instagram"
    )
    media_type: Mapped[str] = mapped_column(String(30), nullable=False)
    media_product_type: Mapped[str | None] = mapped_column(String(30))
    caption: Mapped[str | None] = mapped_column(Text)
    provider_timestamp: Mapped[datetime | None] = mapped_column(UTCDateTime(), index=True)
    permalink: Mapped[str | None] = mapped_column(String(500))
    provider_preview_url: Mapped[str | None] = mapped_column(Text)
    remote_status: Mapped[str] = mapped_column(
        String(20), nullable=False, default="available", server_default="available", index=True
    )
    first_seen_at: Mapped[datetime] = mapped_column(
        UTCDateTime(), nullable=False, default=_utc_now
    )
    last_seen_at: Mapped[datetime] = mapped_column(
        UTCDateTime(), nullable=False, default=_utc_now
    )
    last_checked_at: Mapped[datetime | None] = mapped_column(UTCDateTime())
    unavailable_at: Mapped[datetime | None] = mapped_column(UTCDateTime())
    last_error_code: Mapped[str | None] = mapped_column(String(120))
    last_seen_sync_id: Mapped[str | None] = mapped_column(String(64), index=True)
    internal_content_id: Mapped[int | None] = mapped_column(
        ForeignKey("instagram_contents.id", ondelete="SET NULL"), index=True
    )
    created_at: Mapped[datetime] = mapped_column(
        UTCDateTime(), nullable=False, default=_utc_now
    )
    updated_at: Mapped[datetime] = mapped_column(
        UTCDateTime(), nullable=False, default=_utc_now, onupdate=_utc_now
    )

    integration = relationship("BusinessChannelIntegration", back_populates="instagram_media")
    parent = relationship(
        "InstagramRemoteMedia",
        remote_side="InstagramRemoteMedia.id",
        back_populates="children",
    )
    children = relationship(
        "InstagramRemoteMedia",
        back_populates="parent",
        cascade="all, delete-orphan",
        order_by="InstagramRemoteMedia.position",
    )
    internal_content = relationship("InstagramContent")
    materialized_raw_asset = relationship(
        "InstagramRawAsset",
        back_populates="source_remote_media",
        uselist=False,
    )


class InstagramMediaSyncState(Base):
    __tablename__ = "instagram_media_sync_states"
    __table_args__ = (
        CheckConstraint(
            "status IN ('idle','queued','running','succeeded','failed')",
            name="ck_instagram_media_sync_status",
        ),
        UniqueConstraint("integration_id", name="uq_instagram_media_sync_integration"),
        Index("ix_instagram_media_sync_business_status", "business_id", "status"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    business_id: Mapped[int] = mapped_column(
        ForeignKey("businesses.id", ondelete="CASCADE"), nullable=False, index=True
    )
    integration_id: Mapped[int] = mapped_column(
        ForeignKey("business_channel_integrations.id", ondelete="CASCADE"), nullable=False
    )
    status: Mapped[str] = mapped_column(
        String(20), nullable=False, default="idle", server_default="idle", index=True
    )
    run_id: Mapped[str | None] = mapped_column(String(64))
    after_cursor: Mapped[str | None] = mapped_column(String(1000))
    last_attempt_at: Mapped[datetime | None] = mapped_column(UTCDateTime())
    last_success_at: Mapped[datetime | None] = mapped_column(UTCDateTime(), index=True)
    last_completed_at: Mapped[datetime | None] = mapped_column(UTCDateTime())
    last_error_code: Mapped[str | None] = mapped_column(String(120))
    safe_error_message: Mapped[str | None] = mapped_column(String(500))
    created_at: Mapped[datetime] = mapped_column(
        UTCDateTime(), nullable=False, default=_utc_now
    )
    updated_at: Mapped[datetime] = mapped_column(
        UTCDateTime(), nullable=False, default=_utc_now, onupdate=_utc_now
    )

    integration = relationship(
        "BusinessChannelIntegration",
        back_populates="instagram_media_sync_state",
    )
