from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Float,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base
from app.models.utc_datetime import UTCDateTime

SOCIAL_PROPOSAL_STATUSES = ("active", "dismissed", "accepted", "resolved", "expired")
SOCIAL_PROPOSAL_OBJECTIVES = (
    "increase_bookings",
    "reactivate_customers",
    "promote_service",
    "seasonal_activation",
    "social_proof",
    "educate",
    "engagement",
    "fill_capacity",
)
SOCIAL_PROPOSAL_TYPES = (
    "availability_push",
    "service_push",
    "return_activation",
    "seasonal_content",
    "review_social_proof",
    "evergreen_content",
)
SOCIAL_PROPOSAL_PRIORITIES = ("low", "normal", "high")
SOCIAL_CONTENT_FORMATS = ("story", "reel", "carousel", "static_post")
SOCIAL_CONTENT_CTAS = (
    "book_now",
    "check_availability",
    "contact_us",
    "learn_more",
    "discover_service",
    "none",
)
SOCIAL_CONTENT_ANGLES = (
    "availability",
    "before_after",
    "process",
    "faq",
    "benefit",
    "testimonial",
    "seasonal",
    "limited_window",
    "educational",
    "behind_the_scenes",
)
SOCIAL_ASSET_REQUIREMENTS = (
    "none",
    "existing_media",
    "new_photo",
    "new_video",
    "review",
    "before_after",
)
BUSINESS_REVIEW_STATUSES = ("pending", "usable", "rejected", "removed")


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


class BusinessReview(Base):
    """A received review, distinct from the outbound ReviewRequest workflow."""

    __tablename__ = "business_reviews"
    __table_args__ = (
        CheckConstraint("rating >= 1 AND rating <= 5", name="ck_business_reviews_rating"),
        CheckConstraint(
            "status IN ('pending','usable','rejected','removed')",
            name="ck_business_reviews_status",
        ),
        UniqueConstraint(
            "business_id", "source", "external_id", name="uq_business_reviews_source"
        ),
        Index(
            "ix_business_reviews_business_usable_date",
            "business_id",
            "status",
            "reviewed_at",
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    business_id: Mapped[int] = mapped_column(
        ForeignKey("businesses.id", ondelete="CASCADE"), nullable=False, index=True
    )
    service_id: Mapped[int | None] = mapped_column(
        ForeignKey("services.id", ondelete="SET NULL"), index=True
    )
    source: Mapped[str] = mapped_column(String(50), nullable=False)
    external_id: Mapped[str] = mapped_column(String(200), nullable=False)
    rating: Mapped[float] = mapped_column(Float, nullable=False)
    review_text: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(String(20), default="pending", nullable=False)
    social_use_approved: Mapped[bool] = mapped_column(
        Boolean, default=False, server_default=text("false"), nullable=False
    )
    reviewed_at: Mapped[datetime] = mapped_column(UTCDateTime(), nullable=False, index=True)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utc_now, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        UTCDateTime(), default=utc_now, onupdate=utc_now, nullable=False
    )

    business = relationship("Business", back_populates="received_reviews")
    service = relationship("BusinessService", back_populates="received_reviews")
    proposals = relationship("SocialContentProposal", back_populates="source_review")


class SocialContentProposalSignal(Base):
    __tablename__ = "social_content_proposal_signals"
    __table_args__ = (
        UniqueConstraint(
            "proposal_id", "signal_id", name="uq_social_content_proposal_signal"
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    proposal_id: Mapped[int] = mapped_column(
        ForeignKey("social_content_proposals.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    signal_id: Mapped[int] = mapped_column(
        ForeignKey("business_growth_signals.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    proposal = relationship("SocialContentProposal", back_populates="signal_links")
    signal = relationship("BusinessGrowthSignal")


class SocialContentProposal(Base):
    __tablename__ = "social_content_proposals"
    __table_args__ = (
        CheckConstraint(
            "status IN ('active','dismissed','accepted','resolved','expired')",
            name="ck_social_content_proposals_status",
        ),
        CheckConstraint(
            "objective IN ('increase_bookings','reactivate_customers','promote_service',"
            "'seasonal_activation','social_proof','educate','engagement','fill_capacity')",
            name="ck_social_content_proposals_objective",
        ),
        CheckConstraint(
            "proposal_type IN ('availability_push','service_push','return_activation',"
            "'seasonal_content','review_social_proof','evergreen_content')",
            name="ck_social_content_proposals_type",
        ),
        CheckConstraint(
            "priority IN ('low','normal','high')",
            name="ck_social_content_proposals_priority",
        ),
        CheckConstraint("priority_score >= 0", name="ck_social_content_proposals_score"),
        CheckConstraint(
            "recommended_cta IN ('book_now','check_availability','contact_us','learn_more',"
            "'discover_service','none')",
            name="ck_social_content_proposals_cta",
        ),
        CheckConstraint(
            "angle_code IN ('availability','before_after','process','faq','benefit',"
            "'testimonial','seasonal','limited_window','educational','behind_the_scenes')",
            name="ck_social_content_proposals_angle",
        ),
        CheckConstraint(
            "asset_requirement IN ('none','existing_media','new_photo','new_video',"
            "'review','before_after')",
            name="ck_social_content_proposals_asset_requirement",
        ),
        CheckConstraint(
            "target_window_end > target_window_start",
            name="ck_social_content_proposals_window",
        ),
        UniqueConstraint(
            "business_id", "dedupe_key", name="uq_social_content_proposals_dedupe"
        ),
        Index(
            "ix_social_content_proposals_business_status_priority",
            "business_id",
            "status",
            "priority",
        ),
        Index(
            "ix_social_content_proposals_business_type_service",
            "business_id",
            "proposal_type",
            "service_id",
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    business_id: Mapped[int] = mapped_column(
        ForeignKey("businesses.id", ondelete="CASCADE"), nullable=False, index=True
    )
    status: Mapped[str] = mapped_column(String(20), default="active", nullable=False, index=True)
    objective: Mapped[str] = mapped_column(String(40), nullable=False, index=True)
    proposal_type: Mapped[str] = mapped_column(String(40), nullable=False, index=True)
    priority: Mapped[str] = mapped_column(String(20), nullable=False, index=True)
    priority_score: Mapped[int] = mapped_column(Integer, nullable=False)
    service_id: Mapped[int | None] = mapped_column(
        ForeignKey("services.id", ondelete="SET NULL"), index=True
    )
    source_event_id: Mapped[int | None] = mapped_column(
        ForeignKey("business_calendar_events.id", ondelete="SET NULL"), index=True
    )
    source_review_id: Mapped[int | None] = mapped_column(
        ForeignKey("business_reviews.id", ondelete="SET NULL"), index=True
    )
    reason_code: Mapped[str] = mapped_column(String(100), nullable=False)
    reason_text: Mapped[str] = mapped_column(String(500), nullable=False)
    evidence_json: Mapped[str] = mapped_column(Text, nullable=False)
    recommended_formats_json: Mapped[str] = mapped_column(Text, nullable=False)
    recommended_cta: Mapped[str] = mapped_column(String(30), nullable=False)
    angle_code: Mapped[str] = mapped_column(String(30), nullable=False)
    available_asset_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    asset_requirement: Mapped[str] = mapped_column(String(30), nullable=False)
    target_window_start: Mapped[datetime] = mapped_column(UTCDateTime(), nullable=False)
    target_window_end: Mapped[datetime] = mapped_column(UTCDateTime(), nullable=False)
    detected_at: Mapped[datetime] = mapped_column(UTCDateTime(), nullable=False)
    expires_at: Mapped[datetime] = mapped_column(UTCDateTime(), nullable=False, index=True)
    dismissed_at: Mapped[datetime | None] = mapped_column(UTCDateTime())
    accepted_at: Mapped[datetime | None] = mapped_column(UTCDateTime())
    accepted_by_user_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), index=True
    )
    accepted_context_json: Mapped[str | None] = mapped_column(Text)
    resolved_at: Mapped[datetime | None] = mapped_column(UTCDateTime())
    dedupe_key: Mapped[str] = mapped_column(String(255), nullable=False)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utc_now, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        UTCDateTime(), default=utc_now, onupdate=utc_now, nullable=False
    )

    business = relationship("Business", back_populates="social_content_proposals")
    service = relationship("BusinessService", back_populates="social_content_proposals")
    source_event = relationship("BusinessCalendarEvent")
    source_review = relationship("BusinessReview", back_populates="proposals")
    accepted_by = relationship("User")
    signal_links = relationship(
        "SocialContentProposalSignal",
        back_populates="proposal",
        cascade="all, delete-orphan",
    )
    generated_content = relationship(
        "InstagramContent", back_populates="source_proposal", uselist=False
    )
    idea_review = relationship(
        "SocialIdeaReview", back_populates="proposal", uselist=False, cascade="all, delete-orphan"
    )

    @property
    def source_signals(self):
        return [link.signal for link in self.signal_links]


class SocialIdeaReview(Base):
    __tablename__ = "social_idea_reviews"
    __table_args__ = (
        CheckConstraint(
            "status IN ('pending','approved','changes_requested','rejected')",
            name="ck_social_idea_reviews_status",
        ),
        CheckConstraint(
            "owner_intent IN ('visibility','promotion')",
            name="ck_social_idea_reviews_owner_intent",
        ),
        UniqueConstraint("proposal_id", name="uq_social_idea_review_proposal"),
        Index("ix_social_idea_reviews_business_status", "business_id", "status"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    business_id: Mapped[int] = mapped_column(
        ForeignKey("businesses.id", ondelete="CASCADE"), nullable=False, index=True
    )
    proposal_id: Mapped[int] = mapped_column(
        ForeignKey("social_content_proposals.id", ondelete="CASCADE"),
        nullable=False,
        unique=True,
        index=True,
    )
    status: Mapped[str] = mapped_column(String(30), default="pending", nullable=False, index=True)
    owner_intent: Mapped[str] = mapped_column(String(30), nullable=False)
    owner_accepted_by_user_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), index=True
    )
    owner_accepted_at: Mapped[datetime] = mapped_column(UTCDateTime(), nullable=False)
    owner_context_json: Mapped[str] = mapped_column(Text, nullable=False)
    presentation_json: Mapped[str] = mapped_column(Text, nullable=False)
    template_version: Mapped[str] = mapped_column(String(50), nullable=False)
    admin_reviewed_by_user_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), index=True
    )
    admin_reviewed_at: Mapped[datetime | None] = mapped_column(UTCDateTime())
    admin_note: Mapped[str | None] = mapped_column(Text)
    adjustments_json: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utc_now, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        UTCDateTime(), default=utc_now, onupdate=utc_now, nullable=False
    )

    proposal = relationship("SocialContentProposal", back_populates="idea_review")
    owner_accepted_by = relationship("User", foreign_keys=[owner_accepted_by_user_id])
    admin_reviewed_by = relationship("User", foreign_keys=[admin_reviewed_by_user_id])
    promotion = relationship(
        "SocialPromotion", back_populates="idea_review", uselist=False, cascade="all, delete-orphan"
    )


class SocialPromotion(Base):
    __tablename__ = "social_promotions"
    __table_args__ = (
        CheckConstraint(
            "status IN ('requested','proposed','owner_approved','owner_rejected','cancelled','expired')",
            name="ck_social_promotions_status",
        ),
        UniqueConstraint("idea_review_id", name="uq_social_promotion_idea_review"),
        Index("ix_social_promotions_business_status", "business_id", "status"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    business_id: Mapped[int] = mapped_column(
        ForeignKey("businesses.id", ondelete="CASCADE"), nullable=False, index=True
    )
    idea_review_id: Mapped[int] = mapped_column(
        ForeignKey("social_idea_reviews.id", ondelete="CASCADE"),
        nullable=False,
        unique=True,
        index=True,
    )
    service_id: Mapped[int | None] = mapped_column(
        ForeignKey("services.id", ondelete="SET NULL"), index=True
    )
    status: Mapped[str] = mapped_column(String(30), default="requested", nullable=False, index=True)
    requested_by_user_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), index=True
    )
    requested_at: Mapped[datetime] = mapped_column(UTCDateTime(), nullable=False)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utc_now, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        UTCDateTime(), default=utc_now, onupdate=utc_now, nullable=False
    )

    idea_review = relationship("SocialIdeaReview", back_populates="promotion")
    service = relationship("BusinessService")
    revisions = relationship(
        "SocialPromotionRevision",
        back_populates="promotion",
        cascade="all, delete-orphan",
        order_by="SocialPromotionRevision.revision_number",
    )


class SocialPromotionRevision(Base):
    __tablename__ = "social_promotion_revisions"
    __table_args__ = (
        CheckConstraint(
            "status IN ('proposed','owner_approved','owner_rejected','superseded')",
            name="ck_social_promotion_revisions_status",
        ),
        CheckConstraint(
            "discount_type IN ('percent','fixed')",
            name="ck_social_promotion_revisions_discount_type",
        ),
        CheckConstraint("discount_value > 0", name="ck_social_promotion_discount_positive"),
        CheckConstraint(
            "regular_price >= 0 AND promotional_price >= 0 AND promotional_price < regular_price",
            name="ck_social_promotion_revision_prices",
        ),
        CheckConstraint("valid_until > valid_from", name="ck_social_promotion_revision_window"),
        UniqueConstraint(
            "promotion_id", "revision_number", name="uq_social_promotion_revision_number"
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    promotion_id: Mapped[int] = mapped_column(
        ForeignKey("social_promotions.id", ondelete="CASCADE"), nullable=False, index=True
    )
    revision_number: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[str] = mapped_column(String(30), default="proposed", nullable=False, index=True)
    discount_type: Mapped[str] = mapped_column(String(20), nullable=False)
    discount_value: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False)
    regular_price: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False)
    promotional_price: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False)
    currency: Mapped[str] = mapped_column(String(3), nullable=False)
    valid_from: Mapped[datetime] = mapped_column(UTCDateTime(), nullable=False)
    valid_until: Mapped[datetime] = mapped_column(UTCDateTime(), nullable=False)
    days_json: Mapped[str] = mapped_column(Text, nullable=False)
    scope: Mapped[str] = mapped_column(String(240), nullable=False)
    proposed_by_user_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), index=True
    )
    proposed_at: Mapped[datetime] = mapped_column(UTCDateTime(), nullable=False)
    owner_decided_by_user_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), index=True
    )
    owner_decided_at: Mapped[datetime | None] = mapped_column(UTCDateTime())
    owner_note: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utc_now, nullable=False)

    promotion = relationship("SocialPromotion", back_populates="revisions")
    proposed_by = relationship("User", foreign_keys=[proposed_by_user_id])
    owner_decided_by = relationship("User", foreign_keys=[owner_decided_by_user_id])
