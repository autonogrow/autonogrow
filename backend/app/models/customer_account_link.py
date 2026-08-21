from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Index, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base


class CustomerAccountLink(Base):
    """Conservative link between a global account and one business customer."""

    __tablename__ = "customer_account_links"
    __table_args__ = (
        UniqueConstraint("customer_id", name="uq_customer_account_links_customer"),
        UniqueConstraint("user_id", "business_id", name="uq_customer_account_links_user_business"),
        Index("ix_customer_account_links_business_user", "business_id", "user_id"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    customer_id: Mapped[int] = mapped_column(
        ForeignKey("customers.id", ondelete="CASCADE"), nullable=False, index=True
    )
    business_id: Mapped[int] = mapped_column(
        ForeignKey("businesses.id", ondelete="CASCADE"), nullable=False, index=True
    )
    link_method: Mapped[str] = mapped_column(String(40), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False)

    user = relationship("User", back_populates="customer_links")
    customer = relationship("Customer", back_populates="account_link")
    business = relationship("Business")
