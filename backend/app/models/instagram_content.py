from datetime import datetime

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base
from app.models.utc_datetime import UTCDateTime


class InstagramContentSettings(Base):
    __tablename__ = "instagram_content_settings"

    business_id: Mapped[int] = mapped_column(
        ForeignKey("businesses.id", ondelete="CASCADE"), primary_key=True
    )
    enabled: Mapped[bool] = mapped_column(
        Boolean, default=False, server_default=text("false"), nullable=False
    )
    owner_can_validate_instagram_content: Mapped[bool] = mapped_column(
        Boolean, default=False, server_default=text("false"), nullable=False
    )
    enabled_by_user_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), index=True
    )
    validation_delegated_by_user_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), index=True
    )
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False
    )

    business = relationship("Business", back_populates="instagram_content_settings")


class InstagramRawAsset(Base):
    __tablename__ = "instagram_raw_assets"
    __table_args__ = (
        Index("ix_instagram_raw_assets_business_created", "business_id", "created_at"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    business_id: Mapped[int] = mapped_column(
        ForeignKey("businesses.id", ondelete="CASCADE"), nullable=False, index=True
    )
    uploaded_by_user_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), index=True
    )
    original_filename: Mapped[str] = mapped_column(String(255), nullable=False)
    storage_key: Mapped[str] = mapped_column(String(500), unique=True, nullable=False)
    media_type: Mapped[str] = mapped_column(String(100), nullable=False)
    size_bytes: Mapped[int] = mapped_column(Integer, nullable=False)
    label: Mapped[str | None] = mapped_column(String(240))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False)

    business = relationship("Business", back_populates="instagram_raw_assets")


class InstagramContent(Base):
    __tablename__ = "instagram_contents"
    __table_args__ = (
        CheckConstraint(
            "status IN ('draft','ready_for_review','changes_requested','validated',"
            "'scheduled','published','cancelled')",
            name="ck_instagram_contents_status",
        ),
        Index("ix_instagram_contents_business_status", "business_id", "status"),
        Index("ix_instagram_contents_business_planned", "business_id", "planned_publish_at"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    business_id: Mapped[int] = mapped_column(
        ForeignKey("businesses.id", ondelete="CASCADE"), nullable=False, index=True
    )
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    status: Mapped[str] = mapped_column(String(30), default="draft", nullable=False, index=True)
    planned_publish_at: Mapped[datetime | None] = mapped_column(UTCDateTime(), index=True)
    created_by_user_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), index=True
    )
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False
    )

    business = relationship("Business", back_populates="instagram_contents")
    versions = relationship(
        "InstagramContentVersion",
        back_populates="content",
        cascade="all, delete-orphan",
        order_by="InstagramContentVersion.version_number",
    )
    final_assets = relationship(
        "InstagramFinalAsset", back_populates="content", cascade="all, delete-orphan"
    )
    comments = relationship(
        "InstagramContentComment", back_populates="content", cascade="all, delete-orphan"
    )
    validations = relationship(
        "InstagramContentValidation", back_populates="content", cascade="all, delete-orphan"
    )
    publish_jobs = relationship(
        "InstagramPublishJob", back_populates="content", cascade="all, delete-orphan"
    )


class InstagramFinalAsset(Base):
    __tablename__ = "instagram_final_assets"
    __table_args__ = (
        Index("ix_instagram_final_assets_content_created", "content_id", "created_at"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    business_id: Mapped[int] = mapped_column(
        ForeignKey("businesses.id", ondelete="CASCADE"), nullable=False, index=True
    )
    content_id: Mapped[int] = mapped_column(
        ForeignKey("instagram_contents.id", ondelete="CASCADE"), nullable=False, index=True
    )
    uploaded_by_user_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), index=True
    )
    original_filename: Mapped[str] = mapped_column(String(255), nullable=False)
    storage_key: Mapped[str] = mapped_column(String(500), unique=True, nullable=False)
    media_type: Mapped[str] = mapped_column(String(100), nullable=False)
    size_bytes: Mapped[int] = mapped_column(Integer, nullable=False)
    sha256: Mapped[str | None] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False)

    content = relationship("InstagramContent", back_populates="final_assets")
    version_links = relationship(
        "InstagramContentVersionAsset", back_populates="asset", cascade="all, delete-orphan"
    )


class InstagramContentVersion(Base):
    __tablename__ = "instagram_content_versions"
    __table_args__ = (
        UniqueConstraint("content_id", "version_number", name="uq_instagram_content_version"),
        CheckConstraint("version_number > 0", name="ck_instagram_content_version_positive"),
        CheckConstraint(
            "format IN ('single_image','carousel')",
            name="ck_instagram_content_version_format",
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    business_id: Mapped[int] = mapped_column(
        ForeignKey("businesses.id", ondelete="CASCADE"), nullable=False, index=True
    )
    content_id: Mapped[int] = mapped_column(
        ForeignKey("instagram_contents.id", ondelete="CASCADE"), nullable=False, index=True
    )
    version_number: Mapped[int] = mapped_column(Integer, nullable=False)
    caption: Mapped[str] = mapped_column(Text, default="", nullable=False)
    format: Mapped[str] = mapped_column(String(30), default="single_image", nullable=False)
    created_by_user_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), index=True
    )
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False)

    content = relationship("InstagramContent", back_populates="versions")
    asset_links = relationship(
        "InstagramContentVersionAsset",
        back_populates="version",
        cascade="all, delete-orphan",
        order_by="InstagramContentVersionAsset.position",
    )
    validation = relationship("InstagramContentValidation", back_populates="version", uselist=False)
    comments = relationship("InstagramContentComment", back_populates="version")
    publish_job = relationship("InstagramPublishJob", back_populates="version", uselist=False)


class InstagramContentVersionAsset(Base):
    __tablename__ = "instagram_content_version_assets"
    __table_args__ = (
        UniqueConstraint("version_id", "position", name="uq_instagram_version_asset_position"),
        UniqueConstraint("version_id", "asset_id", name="uq_instagram_version_asset"),
        CheckConstraint("position >= 0", name="ck_instagram_version_asset_position"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    version_id: Mapped[int] = mapped_column(
        ForeignKey("instagram_content_versions.id", ondelete="CASCADE"), nullable=False, index=True
    )
    asset_id: Mapped[int] = mapped_column(
        ForeignKey("instagram_final_assets.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    position: Mapped[int] = mapped_column(Integer, nullable=False)
    is_cover: Mapped[bool] = mapped_column(
        Boolean, default=False, server_default=text("false"), nullable=False
    )

    version = relationship("InstagramContentVersion", back_populates="asset_links")
    asset = relationship("InstagramFinalAsset", back_populates="version_links")


class InstagramContentValidation(Base):
    __tablename__ = "instagram_content_validations"
    __table_args__ = (
        UniqueConstraint("version_id", name="uq_instagram_content_validation_version"),
        CheckConstraint(
            "validator_role IN ('business_admin','owner_delegate')",
            name="ck_instagram_content_validation_role",
        ),
        Index("ix_instagram_validations_content_active", "content_id", "invalidated_at"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    business_id: Mapped[int] = mapped_column(
        ForeignKey("businesses.id", ondelete="CASCADE"), nullable=False, index=True
    )
    content_id: Mapped[int] = mapped_column(
        ForeignKey("instagram_contents.id", ondelete="CASCADE"), nullable=False, index=True
    )
    version_id: Mapped[int] = mapped_column(
        ForeignKey("instagram_content_versions.id", ondelete="CASCADE"), nullable=False, index=True
    )
    validated_by_user_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), index=True
    )
    validator_role: Mapped[str] = mapped_column(String(30), nullable=False)
    validated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    invalidated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    invalidation_reason: Mapped[str | None] = mapped_column(String(240))

    content = relationship("InstagramContent", back_populates="validations")
    version = relationship("InstagramContentVersion", back_populates="validation")


class InstagramContentComment(Base):
    __tablename__ = "instagram_content_comments"
    __table_args__ = (
        CheckConstraint(
            "kind IN ('comment','proposal','change_request')",
            name="ck_instagram_content_comment_kind",
        ),
        Index("ix_instagram_comments_content_created", "content_id", "created_at"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    business_id: Mapped[int] = mapped_column(
        ForeignKey("businesses.id", ondelete="CASCADE"), nullable=False, index=True
    )
    content_id: Mapped[int] = mapped_column(
        ForeignKey("instagram_contents.id", ondelete="CASCADE"), nullable=False, index=True
    )
    version_id: Mapped[int] = mapped_column(
        ForeignKey("instagram_content_versions.id", ondelete="CASCADE"), nullable=False, index=True
    )
    author_user_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), index=True
    )
    kind: Mapped[str] = mapped_column(String(30), nullable=False)
    body: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False)

    content = relationship("InstagramContent", back_populates="comments")
    version = relationship("InstagramContentVersion", back_populates="comments")
