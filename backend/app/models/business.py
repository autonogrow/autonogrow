from datetime import datetime

from sqlalchemy import DateTime, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base


class Business(Base):
    __tablename__ = "businesses"

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    slug: Mapped[str] = mapped_column(String(120), unique=True, index=True, nullable=False)

    name: Mapped[str] = mapped_column(String(200), nullable=False)
    category: Mapped[str | None] = mapped_column(String(160))
    headline: Mapped[str | None] = mapped_column(Text)
    description: Mapped[str | None] = mapped_column(Text)

    phone: Mapped[str | None] = mapped_column(String(40))
    city: Mapped[str | None] = mapped_column(String(120))
    address: Mapped[str | None] = mapped_column(Text)
    schedule: Mapped[str | None] = mapped_column(Text)

    maps_url: Mapped[str | None] = mapped_column(Text)
    instagram_url: Mapped[str | None] = mapped_column(Text)
    reviews_url: Mapped[str | None] = mapped_column(Text)

    primary_color: Mapped[str | None] = mapped_column(String(20))
    secondary_color: Mapped[str | None] = mapped_column(String(20))
    accent_color: Mapped[str | None] = mapped_column(String(20))
    background_color: Mapped[str | None] = mapped_column(String(20))
    theme_key: Mapped[str | None] = mapped_column(String(40))
    template_key: Mapped[str | None] = mapped_column(String(40))
    logo_url: Mapped[str | None] = mapped_column(Text)
    logo_alt: Mapped[str | None] = mapped_column(String(240))
    status: Mapped[str] = mapped_column(String(40), default="active", nullable=False)

    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)

    services = relationship("BusinessService", back_populates="business", cascade="all, delete-orphan")
    customers = relationship("Customer", back_populates="business", cascade="all, delete-orphan")
    bookings = relationship("Booking", back_populates="business", cascade="all, delete-orphan")
    review_requests = relationship("ReviewRequest", back_populates="business", cascade="all, delete-orphan")
    message_outbox = relationship("MessageOutbox", back_populates="business", cascade="all, delete-orphan")
    system_incidents = relationship("SystemIncident", back_populates="business")
    google_integrations = relationship("GoogleIntegration", back_populates="business", cascade="all, delete-orphan")
    gallery_images = relationship("BusinessGalleryImage", back_populates="business", cascade="all, delete-orphan")
    user_memberships = relationship("BusinessUser", back_populates="business", cascade="all, delete-orphan")
    conversations = relationship("Conversation", back_populates="business", cascade="all, delete-orphan")
    conversation_templates = relationship("ConversationTemplate", back_populates="business", cascade="all, delete-orphan")
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
