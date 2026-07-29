from datetime import datetime, timezone
from decimal import Decimal

from sqlalchemy import DateTime, ForeignKey, Index, Integer, Numeric, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


class AutomationCreditTransaction(Base):
    __tablename__ = "automation_credit_transactions"
    __table_args__ = (
        UniqueConstraint(
            "business_id",
            "idempotency_key",
            name="uq_automation_credit_business_idempotency",
        ),
        UniqueConstraint(
            "related_message_id",
            name="uq_automation_credit_related_message",
        ),
        Index(
            "ix_automation_credit_business_created",
            "business_id",
            "created_at",
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    business_id: Mapped[int] = mapped_column(
        ForeignKey("businesses.id", ondelete="CASCADE"), index=True, nullable=False
    )
    transaction_type: Mapped[str] = mapped_column(String(50), index=True, nullable=False)
    amount: Mapped[int] = mapped_column(Integer, nullable=False)
    included_delta: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    additional_delta: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    included_balance_after: Mapped[int] = mapped_column(Integer, nullable=False)
    additional_balance_after: Mapped[int] = mapped_column(Integer, nullable=False)
    total_balance_after: Mapped[int] = mapped_column(Integer, nullable=False)
    payment_amount: Mapped[Decimal | None] = mapped_column(Numeric(12, 2))
    payment_method: Mapped[str | None] = mapped_column(String(60))
    reason: Mapped[str] = mapped_column(String(500), nullable=False)
    external_reference: Mapped[str | None] = mapped_column(String(120))
    related_message_id: Mapped[int | None] = mapped_column(
        ForeignKey("conversation_messages.id", ondelete="SET NULL"), index=True
    )
    period_started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    owner_user_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), index=True
    )
    idempotency_key: Mapped[str | None] = mapped_column(String(120))
    safe_metadata_json: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utc_now, index=True, nullable=False
    )
