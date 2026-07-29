from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base


class Conversation(Base):
    __tablename__ = "conversations"
    __table_args__ = (
        UniqueConstraint(
            "business_id",
            "channel",
            "external_user_id",
            name="uq_conversation_external_user",
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    business_id: Mapped[int] = mapped_column(
        ForeignKey("businesses.id", ondelete="CASCADE"), index=True
    )
    channel: Mapped[str] = mapped_column(String(30), index=True, nullable=False)
    external_conversation_id: Mapped[str | None] = mapped_column(String(255))
    external_user_id: Mapped[str | None] = mapped_column(String(255), index=True)
    customer_name: Mapped[str | None] = mapped_column(String(200))
    customer_phone: Mapped[str | None] = mapped_column(String(40))
    customer_username: Mapped[str | None] = mapped_column(String(200))
    status: Mapped[str] = mapped_column(
        String(30), default="pending", index=True, nullable=False
    )
    last_message_text: Mapped[str | None] = mapped_column(Text)
    last_message_at: Mapped[datetime | None] = mapped_column(DateTime, index=True)
    last_inbound_at: Mapped[datetime | None] = mapped_column(DateTime)
    last_outbound_at: Mapped[datetime | None] = mapped_column(DateTime)
    assigned_business_user_id: Mapped[int | None] = mapped_column(
        ForeignKey("business_users.id", ondelete="SET NULL"), index=True
    )
    detected_intent: Mapped[str | None] = mapped_column(String(60), index=True)
    intent_confidence: Mapped[int | None] = mapped_column(Integer)
    matched_patterns_json: Mapped[str | None] = mapped_column(Text)
    automation_mode: Mapped[str] = mapped_column(
        String(20), default="automatic", nullable=False
    )
    automation_paused_until: Mapped[datetime | None] = mapped_column(DateTime, index=True)
    automation_pause_reason: Mapped[str | None] = mapped_column(String(60))
    automation_pause_updated_by: Mapped[int | None] = mapped_column(Integer)
    automation_pause_updated_at: Mapped[datetime | None] = mapped_column(DateTime)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow, nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False
    )

    business = relationship("Business", back_populates="conversations")
    assigned_business_user = relationship("BusinessUser")
    messages = relationship(
        "ConversationMessage",
        back_populates="conversation",
        cascade="all, delete-orphan",
        order_by="ConversationMessage.created_at, ConversationMessage.id",
    )
    suggestions = relationship(
        "ConversationSuggestion",
        back_populates="conversation",
        cascade="all, delete-orphan",
        order_by="ConversationSuggestion.created_at, ConversationSuggestion.id",
    )


class ConversationMessage(Base):
    __tablename__ = "conversation_messages"

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    conversation_id: Mapped[int] = mapped_column(
        ForeignKey("conversations.id", ondelete="CASCADE"), index=True
    )
    direction: Mapped[str] = mapped_column(String(20), nullable=False)
    sender_type: Mapped[str] = mapped_column(String(30), nullable=False)
    body: Mapped[str] = mapped_column(Text, nullable=False)
    provider_message_id: Mapped[str | None] = mapped_column(String(255), index=True)
    delivery_status: Mapped[str | None] = mapped_column(String(30))
    raw_payload_json: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow, index=True, nullable=False
    )

    conversation = relationship("Conversation", back_populates="messages")


class ConversationTemplate(Base):
    __tablename__ = "conversation_templates"
    __table_args__ = (
        UniqueConstraint("business_id", "name", name="uq_conversation_template_name"),
    )

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    business_id: Mapped[int] = mapped_column(
        ForeignKey("businesses.id", ondelete="CASCADE"), index=True
    )
    name: Mapped[str] = mapped_column(String(160), nullable=False)
    body: Mapped[str] = mapped_column(Text, nullable=False)
    active: Mapped[bool] = mapped_column(default=True, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow, nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False
    )

    business = relationship("Business", back_populates="conversation_templates")


class ConversationAutomationSettings(Base):
    __tablename__ = "conversation_automation_settings"

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    business_id: Mapped[int] = mapped_column(
        ForeignKey("businesses.id", ondelete="CASCADE"), unique=True, index=True
    )
    automation_enabled: Mapped[bool] = mapped_column(default=False, nullable=False)
    monthly_auto_limit: Mapped[int] = mapped_column(Integer, default=1000, nullable=False)
    auto_used_current_period: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    # Deprecated compatibility field. Moving 30-day periods below are the source
    # of truth and this value must never trigger an automatic usage reset.
    period_yyyymm: Mapped[str] = mapped_column(String(7), nullable=False)
    period_started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    period_ends_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    payment_confirmed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    period_status: Mapped[str] = mapped_column(
        String(30), default="pending_renewal", nullable=False
    )
    on_limit_reached: Mapped[str] = mapped_column(
        String(30), default="semi_automatic", nullable=False
    )
    auto_threshold: Mapped[int] = mapped_column(Integer, default=80, nullable=False)
    human_reply_pause_minutes: Mapped[int] = mapped_column(
        Integer, default=60, nullable=False
    )
    plan_key: Mapped[str | None] = mapped_column(String(60))
    automation_feature_enabled: Mapped[bool] = mapped_column(default=True, nullable=False)
    instagram_channel_enabled: Mapped[bool] = mapped_column(default=True, nullable=False)
    whatsapp_channel_enabled: Mapped[bool] = mapped_column(default=True, nullable=False)
    allowed_limit_behaviors_json: Mapped[str] = mapped_column(
        Text, default='["semi_automatic", "disabled"]', nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow, nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False
    )

    business = relationship("Business", back_populates="conversation_automation_settings")


class ConversationAutomationRule(Base):
    __tablename__ = "conversation_automation_rules"
    __table_args__ = (
        UniqueConstraint("business_id", "intent", name="uq_conversation_automation_rule"),
    )

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    business_id: Mapped[int] = mapped_column(
        ForeignKey("businesses.id", ondelete="CASCADE"), index=True
    )
    intent: Mapped[str] = mapped_column(String(60), nullable=False)
    mode: Mapped[str] = mapped_column(
        String(30), default="disabled", nullable=False
    )
    template_id: Mapped[int | None] = mapped_column(
        ForeignKey("conversation_templates.id", ondelete="SET NULL"), index=True
    )
    active: Mapped[bool] = mapped_column(default=True, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow, nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False
    )

    business = relationship("Business", back_populates="conversation_automation_rules")
    template = relationship("ConversationTemplate")


class ConversationSuggestion(Base):
    __tablename__ = "conversation_suggestions"

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    conversation_id: Mapped[int] = mapped_column(
        ForeignKey("conversations.id", ondelete="CASCADE"), index=True
    )
    message_id: Mapped[int | None] = mapped_column(
        ForeignKey("conversation_messages.id", ondelete="SET NULL"), index=True
    )
    intent: Mapped[str] = mapped_column(String(60), nullable=False)
    confidence: Mapped[int] = mapped_column(Integer, nullable=False)
    body: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(
        String(30), default="pending", index=True, nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow, nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False
    )

    conversation = relationship("Conversation", back_populates="suggestions")
    message = relationship("ConversationMessage")
