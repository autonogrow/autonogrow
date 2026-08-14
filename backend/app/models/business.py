from datetime import datetime

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, String, Text, text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base


class Business(Base):
    __tablename__ = "businesses"
    __table_args__ = (
        CheckConstraint(
            "status IN ('draft','onboarding','configuration_pending','ready','active',"
            "'suspended','archived')",
            name="ck_businesses_operational_status",
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    slug: Mapped[str] = mapped_column(String(120), unique=True, index=True, nullable=False)

    name: Mapped[str] = mapped_column(String(200), nullable=False)
    category: Mapped[str | None] = mapped_column(String(160))
    headline: Mapped[str | None] = mapped_column(Text)
    description: Mapped[str | None] = mapped_column(Text)

    phone: Mapped[str | None] = mapped_column(String(40))
    whatsapp_phone: Mapped[str | None] = mapped_column(String(40))
    public_email: Mapped[str | None] = mapped_column(String(320))
    city: Mapped[str | None] = mapped_column(String(120))
    address: Mapped[str | None] = mapped_column(Text)
    postal_code: Mapped[str | None] = mapped_column(String(20))
    region: Mapped[str | None] = mapped_column(String(120))
    country_code: Mapped[str] = mapped_column(
        String(2), default="ES", server_default="ES", nullable=False
    )
    language_code: Mapped[str] = mapped_column(
        String(10), default="es", server_default="es", nullable=False
    )
    timezone: Mapped[str] = mapped_column(
        String(80), default="Europe/Madrid", server_default="Europe/Madrid", nullable=False
    )
    currency: Mapped[str] = mapped_column(
        String(3), default="EUR", server_default="EUR", nullable=False
    )
    legal_name: Mapped[str | None] = mapped_column(String(240))
    tax_identifier: Mapped[str | None] = mapped_column(String(80))
    schedule: Mapped[str | None] = mapped_column(Text)

    maps_url: Mapped[str | None] = mapped_column(Text)
    instagram_url: Mapped[str | None] = mapped_column(Text)
    tiktok_url: Mapped[str | None] = mapped_column(Text)
    external_website_url: Mapped[str | None] = mapped_column(Text)
    reviews_url: Mapped[str | None] = mapped_column(Text)
    landing_cta: Mapped[str | None] = mapped_column(String(120))
    seo_title: Mapped[str | None] = mapped_column(String(160))
    seo_description: Mapped[str | None] = mapped_column(String(320))
    seo_noindex: Mapped[bool] = mapped_column(
        default=True, server_default=text("true"), nullable=False
    )

    primary_color: Mapped[str | None] = mapped_column(String(20))
    secondary_color: Mapped[str | None] = mapped_column(String(20))
    accent_color: Mapped[str | None] = mapped_column(String(20))
    background_color: Mapped[str | None] = mapped_column(String(20))
    theme_key: Mapped[str | None] = mapped_column(String(40))
    template_key: Mapped[str | None] = mapped_column(String(40))
    logo_url: Mapped[str | None] = mapped_column(Text)
    logo_alt: Mapped[str | None] = mapped_column(String(240))
    status: Mapped[str] = mapped_column(String(40), default="active", nullable=False)
    activated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    activated_by_user_id: Mapped[int | None] = mapped_column(
        ForeignKey(
            "users.id",
            name="fk_businesses_activated_by_user_id_users",
            ondelete="SET NULL",
        ),
        index=True,
    )
    status_updated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    archived_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False
    )

    services = relationship(
        "BusinessService", back_populates="business", cascade="all, delete-orphan"
    )
    customers = relationship("Customer", back_populates="business", cascade="all, delete-orphan")
    bookings = relationship("Booking", back_populates="business", cascade="all, delete-orphan")
    review_requests = relationship(
        "ReviewRequest", back_populates="business", cascade="all, delete-orphan"
    )
    message_outbox = relationship(
        "MessageOutbox", back_populates="business", cascade="all, delete-orphan"
    )
    system_incidents = relationship("SystemIncident", back_populates="business")
    google_integrations = relationship(
        "GoogleIntegration", back_populates="business", cascade="all, delete-orphan"
    )
    channel_integrations = relationship(
        "BusinessChannelIntegration",
        back_populates="business",
        cascade="all, delete-orphan",
    )
    channel_controls = relationship(
        "BusinessChannelControl",
        back_populates="business",
        cascade="all, delete-orphan",
    )
    instagram_oauth_attempts = relationship(
        "InstagramOAuthAttempt",
        back_populates="business",
        cascade="all, delete-orphan",
    )
    instagram_content_settings = relationship(
        "InstagramContentSettings",
        back_populates="business",
        cascade="all, delete-orphan",
        uselist=False,
    )
    instagram_raw_assets = relationship(
        "InstagramRawAsset", back_populates="business", cascade="all, delete-orphan"
    )
    instagram_contents = relationship(
        "InstagramContent", back_populates="business", cascade="all, delete-orphan"
    )
    whatsapp_embedded_signup_attempts = relationship(
        "WhatsAppEmbeddedSignupAttempt",
        back_populates="business",
        cascade="all, delete-orphan",
    )
    gallery_images = relationship(
        "BusinessGalleryImage", back_populates="business", cascade="all, delete-orphan"
    )
    user_memberships = relationship(
        "BusinessUser", back_populates="business", cascade="all, delete-orphan"
    )
    conversations = relationship(
        "Conversation", back_populates="business", cascade="all, delete-orphan"
    )
    conversation_templates = relationship(
        "ConversationTemplate", back_populates="business", cascade="all, delete-orphan"
    )
    conversation_automation_settings = relationship(
        "ConversationAutomationSettings",
        back_populates="business",
        cascade="all, delete-orphan",
        uselist=False,
    )
    conversation_automation_rules = relationship(
        "ConversationAutomationRule",
        back_populates="business",
        cascade="all, delete-orphan",
    )
    customer_opportunities = relationship(
        "CustomerOpportunity", back_populates="business", cascade="all, delete-orphan"
    )
    opportunity_actions = relationship(
        "OpportunityAction", back_populates="business", cascade="all, delete-orphan"
    )
    booking_attributions = relationship(
        "BookingAttribution", back_populates="business", cascade="all, delete-orphan"
    )
    growth_signals = relationship(
        "BusinessGrowthSignal", back_populates="business", cascade="all, delete-orphan"
    )
    calendar_events = relationship(
        "BusinessCalendarEvent", back_populates="business", cascade="all, delete-orphan"
    )
    scheduled_customer_followups = relationship(
        "ScheduledCustomerFollowUp", back_populates="business", cascade="all, delete-orphan"
    )
    onboarding_sessions = relationship(
        "BusinessOnboardingSession", back_populates="business", cascade="all, delete-orphan"
    )
