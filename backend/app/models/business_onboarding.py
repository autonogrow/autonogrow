from datetime import datetime, timezone

from sqlalchemy import (
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


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


class BusinessOnboardingTemplate(Base):
    __tablename__ = "business_onboarding_templates"
    __table_args__ = (
        UniqueConstraint("key", "version", name="uq_onboarding_template_key_version"),
        CheckConstraint("version > 0", name="ck_onboarding_template_version_positive"),
        Index("ix_onboarding_templates_active_category", "is_active", "category"),
    )

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    key: Mapped[str] = mapped_column(String(80), nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(160), nullable=False)
    category: Mapped[str] = mapped_column(String(120), nullable=False, index=True)
    description: Mapped[str] = mapped_column(String(500), nullable=False)
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    is_active: Mapped[bool] = mapped_column(default=True, nullable=False, index=True)
    is_system: Mapped[bool] = mapped_column(default=True, nullable=False)
    configuration_json: Mapped[str] = mapped_column(Text, nullable=False)
    created_by_user_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), index=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, onupdate=utc_now, nullable=False
    )
    sessions = relationship("BusinessOnboardingSession", back_populates="template")


class BusinessStaffProfileService(Base):
    """Explicit assignment kept separate from authenticated user memberships."""

    __tablename__ = "business_staff_profile_services"
    __table_args__ = (
        UniqueConstraint("staff_profile_id", "service_id", name="uq_staff_profile_service"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    staff_profile_id: Mapped[int] = mapped_column(
        ForeignKey("business_staff_profiles.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    service_id: Mapped[int] = mapped_column(
        ForeignKey("services.id", ondelete="CASCADE"), nullable=False, index=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, nullable=False
    )


class BusinessOnboardingSession(Base):
    __tablename__ = "business_onboarding_sessions"
    __table_args__ = (
        CheckConstraint(
            "status IN ('in_progress','blocked','completed','cancelled')",
            name="ck_onboarding_session_status",
        ),
        CheckConstraint(
            "current_step IN ("
            "'template','business_identity','contact_and_location','services','staff',"
            "'schedules','booking_rules','branding','landing_content','automations',"
            "'integrations','credits_and_plan','readiness_review','preview','activation')",
            name="ck_onboarding_session_current_step",
        ),
        Index("ix_onboarding_sessions_status_activity", "status", "last_activity_at"),
        Index(
            "uq_onboarding_sessions_active_business",
            "business_id",
            unique=True,
            sqlite_where=text("status IN ('in_progress','blocked')"),
            postgresql_where=text("status IN ('in_progress','blocked')"),
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    business_id: Mapped[int] = mapped_column(
        ForeignKey("businesses.id", ondelete="CASCADE"), nullable=False, index=True
    )
    template_id: Mapped[int | None] = mapped_column(
        ForeignKey("business_onboarding_templates.id", ondelete="SET NULL"), index=True
    )
    status: Mapped[str] = mapped_column(String(30), default="in_progress", nullable=False)
    current_step: Mapped[str] = mapped_column(String(60), default="template", nullable=False)
    steps_version: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    completed_steps_json: Mapped[str] = mapped_column(Text, default="[]", nullable=False)
    skipped_steps_json: Mapped[str] = mapped_column(Text, default="[]", nullable=False)
    step_activity_json: Mapped[str] = mapped_column(Text, default="{}", nullable=False)
    validation_summary_json: Mapped[str | None] = mapped_column(Text)
    started_by_user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    last_updated_by_user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    started_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, nullable=False
    )
    last_activity_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, nullable=False, index=True
    )
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    cancelled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, onupdate=utc_now, nullable=False
    )
    business = relationship("Business", back_populates="onboarding_sessions")
    template = relationship("BusinessOnboardingTemplate", back_populates="sessions")


class BusinessStaffProfile(Base):
    """Bookable staff identity without implicitly granting application access."""

    __tablename__ = "business_staff_profiles"
    __table_args__ = (
        UniqueConstraint("business_id", "email", name="uq_business_staff_profile_email"),
        Index("ix_business_staff_profiles_business_active", "business_id", "active"),
        CheckConstraint("capacity >= 1", name="ck_business_staff_profile_capacity"),
    )

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    business_id: Mapped[int] = mapped_column(
        ForeignKey("businesses.id", ondelete="CASCADE"), nullable=False, index=True
    )
    linked_business_user_id: Mapped[int | None] = mapped_column(
        ForeignKey("business_users.id", ondelete="SET NULL"), unique=True, index=True
    )
    public_name: Mapped[str] = mapped_column(String(200), nullable=False)
    email: Mapped[str | None] = mapped_column(String(320))
    phone: Mapped[str | None] = mapped_column(String(40))
    role_label: Mapped[str] = mapped_column(String(120), default="professional", nullable=False)
    color: Mapped[str | None] = mapped_column(String(20))
    capacity: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    active: Mapped[bool] = mapped_column(default=True, nullable=False)
    schedule_json: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, onupdate=utc_now, nullable=False
    )
    service_links = relationship("BusinessStaffProfileService", cascade="all, delete-orphan")
