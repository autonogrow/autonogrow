from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import CheckConstraint, Float, ForeignKey, Index, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base
from app.models.utc_datetime import UTCDateTime

MEMORY_CATEGORIES = (
    "preference",
    "service_interest",
    "availability_preference",
    "operational_note",
    "relationship",
    "other",
)
MEMORY_SOURCE_TYPES = (
    "manual",
    "booking",
    "service_history",
    "conversation",
    "system",
)
MEMORY_VALUE_TYPES = ("text", "integer", "boolean", "date")
MEMORY_STATUSES = ("active", "superseded", "expired", "deleted")


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


class CustomerMemoryItem(Base):
    __tablename__ = "customer_memory_items"
    __table_args__ = (
        CheckConstraint(
            "category IN ('preference','service_interest','availability_preference',"
            "'operational_note','relationship','other')",
            name="ck_customer_memory_items_category",
        ),
        CheckConstraint(
            "source_type IN ('manual','booking','service_history','conversation','system')",
            name="ck_customer_memory_items_source_type",
        ),
        CheckConstraint(
            "value_type IN ('text','integer','boolean','date')",
            name="ck_customer_memory_items_value_type",
        ),
        CheckConstraint(
            "status IN ('active','superseded','expired','deleted')",
            name="ck_customer_memory_items_status",
        ),
        CheckConstraint(
            "confidence IS NULL OR (confidence >= 0 AND confidence <= 1)",
            name="ck_customer_memory_items_confidence",
        ),
        CheckConstraint("length(trim(key)) > 0", name="ck_customer_memory_items_key"),
        CheckConstraint("length(trim(value)) > 0", name="ck_customer_memory_items_value"),
        Index(
            "ix_customer_memory_business_customer_status",
            "business_id",
            "customer_id",
            "status",
        ),
        Index(
            "ix_customer_memory_business_category_key",
            "business_id",
            "category",
            "key",
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    business_id: Mapped[int] = mapped_column(
        ForeignKey("businesses.id", ondelete="CASCADE"), nullable=False, index=True
    )
    customer_id: Mapped[int] = mapped_column(
        ForeignKey("customers.id", ondelete="CASCADE"), nullable=False, index=True
    )
    category: Mapped[str] = mapped_column(String(40), nullable=False, index=True)
    key: Mapped[str] = mapped_column(String(100), nullable=False, index=True)
    value: Mapped[str] = mapped_column(Text, nullable=False)
    value_type: Mapped[str] = mapped_column(String(20), default="text", nullable=False)
    source_type: Mapped[str] = mapped_column(String(30), nullable=False, index=True)
    source_id: Mapped[str | None] = mapped_column(String(120))
    confidence: Mapped[float | None] = mapped_column(Float)
    status: Mapped[str] = mapped_column(
        String(20), default="active", nullable=False, index=True
    )
    is_sensitive: Mapped[bool] = mapped_column(default=False, nullable=False)
    created_by_user_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), index=True
    )
    created_at: Mapped[datetime] = mapped_column(
        UTCDateTime(), default=utc_now, nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        UTCDateTime(), default=utc_now, onupdate=utc_now, nullable=False
    )
    expires_at: Mapped[datetime | None] = mapped_column(UTCDateTime(), index=True)
    superseded_at: Mapped[datetime | None] = mapped_column(UTCDateTime())
    deleted_at: Mapped[datetime | None] = mapped_column(UTCDateTime())
    superseded_by_id: Mapped[int | None] = mapped_column(
        ForeignKey("customer_memory_items.id", ondelete="SET NULL"), index=True
    )

    business = relationship("Business", back_populates="customer_memory_items")
    customer = relationship("Customer", back_populates="memory_items")
    created_by_user = relationship("User", foreign_keys=[created_by_user_id])
    superseded_by = relationship(
        "CustomerMemoryItem", remote_side=[id], foreign_keys=[superseded_by_id]
    )
