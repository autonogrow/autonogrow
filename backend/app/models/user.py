from datetime import datetime

from sqlalchemy import Boolean, DateTime, String, false
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    email: Mapped[str] = mapped_column(String(320), unique=True, index=True, nullable=False)
    name: Mapped[str | None] = mapped_column(String(200))
    picture_url: Mapped[str | None] = mapped_column(String(1000))
    google_sub: Mapped[str | None] = mapped_column(String(255), unique=True, index=True)
    email_verified: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    is_owner: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    phone: Mapped[str | None] = mapped_column(String(40))
    phone_normalized: Mapped[str | None] = mapped_column(String(20), index=True)
    phone_verified: Mapped[bool] = mapped_column(
        Boolean, default=False, server_default=false(), nullable=False
    )
    preferred_name: Mapped[str | None] = mapped_column(String(200))
    instagram_username: Mapped[str | None] = mapped_column(String(30), index=True)
    instagram_provider_user_id: Mapped[str | None] = mapped_column(String(255), unique=True)
    instagram_verified: Mapped[bool] = mapped_column(
        Boolean, default=False, server_default=false(), nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False
    )
    last_login_at: Mapped[datetime | None] = mapped_column(DateTime)

    business_memberships = relationship(
        "BusinessUser", back_populates="user", cascade="all, delete-orphan"
    )
    auth_sessions = relationship(
        "AuthSession", back_populates="user", cascade="all, delete-orphan"
    )
    bookings = relationship("Booking", back_populates="customer_user")
    customer_links = relationship(
        "CustomerAccountLink", back_populates="user", cascade="all, delete-orphan"
    )
