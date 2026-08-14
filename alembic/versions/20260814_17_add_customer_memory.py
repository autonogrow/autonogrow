"""add structured customer memory

Revision ID: 20260814_17
Revises: 20260814_16
Create Date: 2026-08-14
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260814_17"
down_revision: str | Sequence[str] | None = "20260814_16"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    if "customer_memory_items" in set(inspector.get_table_names()):
        return

    op.create_table(
        "customer_memory_items",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("business_id", sa.Integer(), nullable=False),
        sa.Column("customer_id", sa.Integer(), nullable=False),
        sa.Column("category", sa.String(length=40), nullable=False),
        sa.Column("key", sa.String(length=100), nullable=False),
        sa.Column("value", sa.Text(), nullable=False),
        sa.Column("value_type", sa.String(length=20), nullable=False),
        sa.Column("source_type", sa.String(length=30), nullable=False),
        sa.Column("source_id", sa.String(length=120)),
        sa.Column("confidence", sa.Float()),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column(
            "is_sensitive", sa.Boolean(), server_default=sa.text("false"), nullable=False
        ),
        sa.Column("created_by_user_id", sa.Integer()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True)),
        sa.Column("superseded_at", sa.DateTime(timezone=True)),
        sa.Column("deleted_at", sa.DateTime(timezone=True)),
        sa.Column("superseded_by_id", sa.Integer()),
        sa.CheckConstraint(
            "category IN ('preference','service_interest','availability_preference',"
            "'operational_note','relationship','other')",
            name="ck_customer_memory_items_category",
        ),
        sa.CheckConstraint(
            "source_type IN ('manual','booking','service_history','conversation','system')",
            name="ck_customer_memory_items_source_type",
        ),
        sa.CheckConstraint(
            "value_type IN ('text','integer','boolean','date')",
            name="ck_customer_memory_items_value_type",
        ),
        sa.CheckConstraint(
            "status IN ('active','superseded','expired','deleted')",
            name="ck_customer_memory_items_status",
        ),
        sa.CheckConstraint(
            "confidence IS NULL OR (confidence >= 0 AND confidence <= 1)",
            name="ck_customer_memory_items_confidence",
        ),
        sa.CheckConstraint(
            "length(trim(key)) > 0", name="ck_customer_memory_items_key"
        ),
        sa.CheckConstraint(
            "length(trim(value)) > 0", name="ck_customer_memory_items_value"
        ),
        sa.ForeignKeyConstraint(["business_id"], ["businesses.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["customer_id"], ["customers.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["created_by_user_id"], ["users.id"], ondelete="SET NULL"
        ),
        sa.ForeignKeyConstraint(
            ["superseded_by_id"], ["customer_memory_items.id"], ondelete="SET NULL"
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_customer_memory_business_customer_status",
        "customer_memory_items",
        ["business_id", "customer_id", "status"],
    )
    op.create_index(
        "ix_customer_memory_business_category_key",
        "customer_memory_items",
        ["business_id", "category", "key"],
    )
    for column in (
        "business_id",
        "customer_id",
        "category",
        "key",
        "source_type",
        "status",
        "created_by_user_id",
        "expires_at",
        "superseded_by_id",
    ):
        op.create_index(
            f"ix_customer_memory_items_{column}", "customer_memory_items", [column]
        )


def downgrade() -> None:
    op.drop_table("customer_memory_items")
