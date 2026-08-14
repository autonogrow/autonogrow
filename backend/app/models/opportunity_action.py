from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal

from sqlalchemy import (
    CheckConstraint,
    ForeignKey,
    Index,
    Numeric,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base
from app.models.utc_datetime import UTCDateTime

OPPORTUNITY_ACTION_TYPES = (
    "contact_customer",
    "mark_handled",
    "open_conversation",
)
OPPORTUNITY_ACTION_STATUSES = (
    "draft",
    "approved",
    "sending",
    "sent",
    "failed",
    "cancelled",
    "completed",
)
ATTRIBUTION_METHODS = ("direct_link", "post_action_window", "manual")


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


class OpportunityAction(Base):
    __tablename__ = "opportunity_actions"
    __table_args__ = (
        CheckConstraint(
            "action_type IN ('contact_customer','mark_handled','open_conversation')",
            name="ck_opportunity_actions_type",
        ),
        CheckConstraint(
            "status IN ('draft','approved','sending','sent','failed','cancelled','completed')",
            name="ck_opportunity_actions_status",
        ),
        CheckConstraint(
            "channel IS NULL OR channel IN ('whatsapp','instagram')",
            name="ck_opportunity_actions_channel",
        ),
        UniqueConstraint(
            "business_id",
            "opportunity_id",
            "action_type",
            name="uq_opportunity_action_conservative_dedupe",
        ),
        UniqueConstraint("message_id", name="uq_opportunity_action_message"),
        Index(
            "ix_opportunity_actions_business_status_created",
            "business_id",
            "status",
            "created_at",
        ),
        Index(
            "ix_opportunity_actions_opportunity_created",
            "opportunity_id",
            "created_at",
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    business_id: Mapped[int] = mapped_column(
        ForeignKey("businesses.id", ondelete="CASCADE"), nullable=False, index=True
    )
    opportunity_id: Mapped[int] = mapped_column(
        ForeignKey("customer_opportunities.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    customer_id: Mapped[int] = mapped_column(
        ForeignKey("customers.id", ondelete="CASCADE"), nullable=False, index=True
    )
    action_type: Mapped[str] = mapped_column(String(40), nullable=False, index=True)
    status: Mapped[str] = mapped_column(
        String(30), default="draft", nullable=False, index=True
    )
    channel: Mapped[str | None] = mapped_column(String(30), index=True)
    conversation_id: Mapped[int | None] = mapped_column(
        ForeignKey("conversations.id", ondelete="SET NULL"), index=True
    )
    message_id: Mapped[int | None] = mapped_column(
        ForeignKey("conversation_messages.id", ondelete="SET NULL"), index=True
    )
    booking_id: Mapped[int | None] = mapped_column(
        ForeignKey("bookings.id", ondelete="SET NULL"), index=True
    )
    suggested_text: Mapped[str | None] = mapped_column(Text)
    final_text: Mapped[str | None] = mapped_column(Text)
    created_by_user_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), index=True
    )
    last_edited_by_user_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), index=True
    )
    approved_by_user_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), index=True
    )
    sent_by_user_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), index=True
    )
    approved_at: Mapped[datetime | None] = mapped_column(UTCDateTime())
    sent_at: Mapped[datetime | None] = mapped_column(UTCDateTime())
    failed_at: Mapped[datetime | None] = mapped_column(UTCDateTime())
    cancelled_at: Mapped[datetime | None] = mapped_column(UTCDateTime())
    completed_at: Mapped[datetime | None] = mapped_column(UTCDateTime())
    expires_at: Mapped[datetime | None] = mapped_column(UTCDateTime(), index=True)
    failure_reason: Mapped[str | None] = mapped_column(String(500))
    created_at: Mapped[datetime] = mapped_column(
        UTCDateTime(), default=utc_now, nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        UTCDateTime(), default=utc_now, onupdate=utc_now, nullable=False
    )

    business = relationship("Business", back_populates="opportunity_actions")
    opportunity = relationship("CustomerOpportunity", back_populates="actions")
    customer = relationship("Customer", back_populates="opportunity_actions")
    conversation = relationship("Conversation", back_populates="opportunity_actions")
    message = relationship("ConversationMessage", back_populates="opportunity_action")
    booking = relationship(
        "Booking", foreign_keys=[booking_id], back_populates="opportunity_actions"
    )
    attribution = relationship(
        "BookingAttribution",
        back_populates="action",
        cascade="all, delete-orphan",
        uselist=False,
    )


class BookingAttribution(Base):
    __tablename__ = "booking_attributions"
    __table_args__ = (
        CheckConstraint(
            "method IN ('direct_link','post_action_window','manual')",
            name="ck_booking_attributions_method",
        ),
        CheckConstraint(
            "price_amount_snapshot IS NULL OR price_amount_snapshot >= 0",
            name="ck_booking_attributions_price_nonnegative",
        ),
        UniqueConstraint("action_id", name="uq_booking_attribution_action"),
        UniqueConstraint("booking_id", name="uq_booking_attribution_booking"),
        Index(
            "ix_booking_attributions_business_created",
            "business_id",
            "attributed_at",
        ),
        Index(
            "ix_booking_attributions_opportunity",
            "opportunity_id",
            "attributed_at",
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    business_id: Mapped[int] = mapped_column(
        ForeignKey("businesses.id", ondelete="CASCADE"), nullable=False, index=True
    )
    opportunity_id: Mapped[int] = mapped_column(
        ForeignKey("customer_opportunities.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    action_id: Mapped[int] = mapped_column(
        ForeignKey("opportunity_actions.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    booking_id: Mapped[int] = mapped_column(
        ForeignKey("bookings.id", ondelete="CASCADE"), nullable=False, index=True
    )
    method: Mapped[str] = mapped_column(String(40), nullable=False, index=True)
    price_amount_snapshot: Mapped[Decimal | None] = mapped_column(Numeric(12, 2))
    currency_snapshot: Mapped[str | None] = mapped_column(String(3))
    attributed_at: Mapped[datetime] = mapped_column(
        UTCDateTime(), default=utc_now, nullable=False, index=True
    )
    completed_at: Mapped[datetime | None] = mapped_column(UTCDateTime(), index=True)
    created_by_user_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), index=True
    )
    created_at: Mapped[datetime] = mapped_column(
        UTCDateTime(), default=utc_now, nullable=False
    )

    business = relationship("Business", back_populates="booking_attributions")
    opportunity = relationship("CustomerOpportunity", back_populates="attributions")
    action = relationship("OpportunityAction", back_populates="attribution")
    booking = relationship("Booking", back_populates="attribution")
