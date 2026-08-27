from datetime import datetime, timezone

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
        CheckConstraint(
            "source_kind IN ('business_upload','instagram')",
            name="ck_instagram_raw_assets_source_kind",
        ),
        UniqueConstraint(
            "source_remote_media_id",
            name="uq_instagram_raw_asset_remote_media",
        ),
        Index("ix_instagram_raw_assets_business_created", "business_id", "created_at"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    business_id: Mapped[int] = mapped_column(
        ForeignKey("businesses.id", ondelete="CASCADE"), nullable=False, index=True
    )
    service_id: Mapped[int | None] = mapped_column(
        ForeignKey("services.id", ondelete="SET NULL"), index=True
    )
    active: Mapped[bool] = mapped_column(
        Boolean, default=True, server_default=text("true"), nullable=False
    )
    uploaded_by_user_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), index=True
    )
    source_kind: Mapped[str] = mapped_column(
        String(30), nullable=False, default="business_upload", server_default="business_upload"
    )
    source_remote_media_id: Mapped[int | None] = mapped_column(
        ForeignKey("instagram_remote_media.id", ondelete="RESTRICT"), index=True
    )
    original_filename: Mapped[str] = mapped_column(String(255), nullable=False)
    storage_key: Mapped[str] = mapped_column(String(500), unique=True, nullable=False)
    media_type: Mapped[str] = mapped_column(String(100), nullable=False)
    size_bytes: Mapped[int] = mapped_column(Integer, nullable=False)
    sha256: Mapped[str | None] = mapped_column(String(64))
    label: Mapped[str | None] = mapped_column(String(240))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False)

    business = relationship("Business", back_populates="instagram_raw_assets")
    service = relationship("BusinessService", back_populates="instagram_raw_assets")
    uploaded_by = relationship("User", foreign_keys=[uploaded_by_user_id])
    content_links = relationship(
        "InstagramContentRawAsset",
        back_populates="raw_asset",
        passive_deletes=True,
        lazy="selectin",
    )
    final_derivatives = relationship(
        "InstagramFinalAsset",
        back_populates="source_raw_asset",
        passive_deletes=True,
    )
    source_remote_media = relationship(
        "InstagramRemoteMedia",
        back_populates="materialized_raw_asset",
    )


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
        UniqueConstraint(
            "source_proposal_id", name="uq_instagram_contents_source_proposal_id"
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    business_id: Mapped[int] = mapped_column(
        ForeignKey("businesses.id", ondelete="CASCADE"), nullable=False, index=True
    )
    source_proposal_id: Mapped[int | None] = mapped_column(
        ForeignKey("social_content_proposals.id", ondelete="SET NULL"),
        index=True,
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
    archived_at: Mapped[datetime | None] = mapped_column(UTCDateTime(), index=True)

    business = relationship("Business", back_populates="instagram_contents")
    source_proposal = relationship("SocialContentProposal", back_populates="generated_content")
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
    editorial_reviews = relationship(
        "InstagramContentEditorialReview",
        back_populates="content",
        cascade="all, delete-orphan",
    )
    publication_holds = relationship(
        "InstagramContentPublicationHold",
        back_populates="content",
        cascade="all, delete-orphan",
        order_by="InstagramContentPublicationHold.held_at",
    )
    publish_jobs = relationship(
        "InstagramPublishJob", back_populates="content", cascade="all, delete-orphan"
    )
    source_asset_links = relationship(
        "InstagramContentRawAsset",
        back_populates="content",
        cascade="all, delete-orphan",
        lazy="selectin",
    )


class InstagramContentRawAsset(Base):
    __tablename__ = "instagram_content_raw_assets"
    __table_args__ = (
        UniqueConstraint("content_id", "raw_asset_id", name="uq_instagram_content_raw_asset"),
        Index(
            "ix_instagram_content_raw_assets_business_content",
            "business_id",
            "content_id",
        ),
        Index(
            "ix_instagram_content_raw_assets_business_raw",
            "business_id",
            "raw_asset_id",
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    business_id: Mapped[int] = mapped_column(
        ForeignKey("businesses.id", ondelete="CASCADE"), nullable=False, index=True
    )
    content_id: Mapped[int] = mapped_column(
        ForeignKey("instagram_contents.id", ondelete="CASCADE"), nullable=False, index=True
    )
    raw_asset_id: Mapped[int] = mapped_column(
        ForeignKey("instagram_raw_assets.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    associated_by_user_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), index=True
    )
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False)

    content = relationship("InstagramContent", back_populates="source_asset_links", lazy="joined")
    raw_asset = relationship("InstagramRawAsset", back_populates="content_links", lazy="joined")


class InstagramFinalAsset(Base):
    __tablename__ = "instagram_final_assets"
    __table_args__ = (
        Index("ix_instagram_final_assets_content_created", "content_id", "created_at"),
        UniqueConstraint(
            "content_id",
            "source_raw_asset_id",
            "derivation_fingerprint",
            name="uq_instagram_final_asset_derivation",
        ),
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
    source_raw_asset_id: Mapped[int | None] = mapped_column(
        ForeignKey("instagram_raw_assets.id", ondelete="RESTRICT"), index=True
    )
    original_filename: Mapped[str] = mapped_column(String(255), nullable=False)
    storage_key: Mapped[str] = mapped_column(String(500), unique=True, nullable=False)
    media_type: Mapped[str] = mapped_column(String(100), nullable=False)
    size_bytes: Mapped[int] = mapped_column(Integer, nullable=False)
    sha256: Mapped[str | None] = mapped_column(String(64))
    derivation_fingerprint: Mapped[str | None] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False)

    content = relationship("InstagramContent", back_populates="final_assets")
    source_raw_asset = relationship("InstagramRawAsset", back_populates="final_derivatives")
    version_links = relationship(
        "InstagramContentVersionAsset", back_populates="asset", cascade="all, delete-orphan"
    )


class InstagramContentVersion(Base):
    __tablename__ = "instagram_content_versions"
    __table_args__ = (
        UniqueConstraint("content_id", "version_number", name="uq_instagram_content_version"),
        CheckConstraint("version_number > 0", name="ck_instagram_content_version_positive"),
        CheckConstraint(
            "format IN ('single_image','carousel','reel','story')",
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
    editorial_package_json: Mapped[str | None] = mapped_column(Text)
    generation_source: Mapped[str | None] = mapped_column(String(30))
    generator_version: Mapped[str | None] = mapped_column(String(50))
    promotion_revision_id: Mapped[int | None] = mapped_column(
        ForeignKey("social_promotion_revisions.id", ondelete="RESTRICT"), index=True
    )
    story_transform_json: Mapped[str | None] = mapped_column(Text)
    story_renderer_version: Mapped[str | None] = mapped_column(String(50))
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
    editorial_review = relationship(
        "InstagramContentEditorialReview", back_populates="version", uselist=False
    )
    promotion_revision = relationship(
        "SocialPromotionRevision", back_populates="content_versions"
    )
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


class InstagramContentEditorialReview(Base):
    __tablename__ = "instagram_content_editorial_reviews"
    __table_args__ = (
        UniqueConstraint("version_id", name="uq_instagram_editorial_review_version"),
        CheckConstraint(
            "status IN ('pending','approved','changes_requested','rejected')",
            name="ck_instagram_editorial_reviews_status",
        ),
        Index(
            "ix_instagram_editorial_reviews_business_status", "business_id", "status"
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    business_id: Mapped[int] = mapped_column(
        ForeignKey("businesses.id", ondelete="CASCADE"), nullable=False, index=True
    )
    content_id: Mapped[int] = mapped_column(
        ForeignKey("instagram_contents.id", ondelete="CASCADE"), nullable=False, index=True
    )
    version_id: Mapped[int] = mapped_column(
        ForeignKey("instagram_content_versions.id", ondelete="CASCADE"),
        nullable=False,
        unique=True,
        index=True,
    )
    status: Mapped[str] = mapped_column(String(30), default="pending", nullable=False, index=True)
    submitted_at: Mapped[datetime] = mapped_column(UTCDateTime(), nullable=False)
    reviewed_by_user_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), index=True
    )
    reviewed_at: Mapped[datetime | None] = mapped_column(UTCDateTime())
    note: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(
        UTCDateTime(), default=lambda: datetime.now(timezone.utc), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        UTCDateTime(),
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
        nullable=False,
    )

    content = relationship("InstagramContent", back_populates="editorial_reviews")
    version = relationship("InstagramContentVersion", back_populates="editorial_review")
    reviewed_by = relationship("User")


class InstagramContentPublicationHold(Base):
    __tablename__ = "instagram_content_publication_holds"
    __table_args__ = (
        Index(
            "ix_instagram_content_holds_content_released",
            "content_id",
            "released_at",
        ),
        Index(
            "ix_instagram_content_holds_business_held",
            "business_id",
            "held_at",
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    business_id: Mapped[int] = mapped_column(
        ForeignKey("businesses.id", ondelete="CASCADE"), nullable=False, index=True
    )
    content_id: Mapped[int] = mapped_column(
        ForeignKey("instagram_contents.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    reason: Mapped[str] = mapped_column(Text, nullable=False)
    held_by_user_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), index=True
    )
    held_at: Mapped[datetime] = mapped_column(UTCDateTime(), nullable=False)
    released_by_user_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), index=True
    )
    released_at: Mapped[datetime | None] = mapped_column(UTCDateTime(), index=True)
    release_note: Mapped[str | None] = mapped_column(Text)

    content = relationship("InstagramContent", back_populates="publication_holds")
    held_by = relationship("User", foreign_keys=[held_by_user_id])
    released_by = relationship("User", foreign_keys=[released_by_user_id])


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
