"""link conversations to customers

Revision ID: 20260830_28
Revises: 20260827_27
Create Date: 2026-08-30
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260830_28"
down_revision: str | Sequence[str] | None = "20260827_27"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    columns = {item["name"] for item in inspector.get_columns("conversations")}
    indexes = {item["name"] for item in inspector.get_indexes("conversations")}
    has_customer_fk = any(
        item.get("constrained_columns") == ["customer_id"]
        and item.get("referred_table") == "customers"
        for item in inspector.get_foreign_keys("conversations")
    )
    needs_column = "customer_id" not in columns
    needs_index = "ix_conversations_customer_id" not in indexes
    if needs_column or not has_customer_fk or needs_index:
        with op.batch_alter_table("conversations") as batch:
            if needs_column:
                batch.add_column(sa.Column("customer_id", sa.Integer(), nullable=True))
            if not has_customer_fk:
                batch.create_foreign_key(
                    "fk_conversations_customer_id_customers",
                    "customers",
                    ["customer_id"],
                    ["id"],
                    ondelete="SET NULL",
                )
            if needs_index:
                batch.create_index("ix_conversations_customer_id", ["customer_id"])


def downgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    columns = {item["name"] for item in inspector.get_columns("conversations")}
    indexes = {item["name"] for item in inspector.get_indexes("conversations")}
    foreign_keys = {
        item["name"]
        for item in inspector.get_foreign_keys("conversations")
        if item.get("name")
    }
    if "customer_id" not in columns:
        return
    with op.batch_alter_table("conversations") as batch:
        if "ix_conversations_customer_id" in indexes:
            batch.drop_index("ix_conversations_customer_id")
        if "fk_conversations_customer_id_customers" in foreign_keys:
            batch.drop_constraint(
                "fk_conversations_customer_id_customers", type_="foreignkey"
            )
        batch.drop_column("customer_id")
