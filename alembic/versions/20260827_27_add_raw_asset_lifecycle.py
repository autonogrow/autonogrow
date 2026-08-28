"""add Instagram raw asset library lifecycle

Revision ID: 20260827_27
Revises: 20260825_26
Create Date: 2026-08-27
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260827_27"
down_revision: str | Sequence[str] | None = "20260825_26"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("instagram_raw_assets") as batch:
        batch.add_column(sa.Column("removed_at", sa.DateTime(timezone=True), nullable=True))
        batch.add_column(sa.Column("removed_by_user_id", sa.Integer(), nullable=True))
        batch.add_column(sa.Column("storage_deleted_at", sa.DateTime(timezone=True), nullable=True))
        batch.create_foreign_key(
            "fk_instagram_raw_assets_removed_by_user_id",
            "users",
            ["removed_by_user_id"],
            ["id"],
            ondelete="SET NULL",
        )
        batch.create_index(
            "ix_instagram_raw_assets_removed_by_user_id",
            ["removed_by_user_id"],
        )
        batch.create_index("ix_instagram_raw_assets_removed_at", ["removed_at"])
        batch.create_index("ix_instagram_raw_assets_storage_deleted_at", ["storage_deleted_at"])
        batch.create_index(
            "ix_instagram_raw_assets_business_active_created",
            ["business_id", "active", "created_at"],
        )


def downgrade() -> None:
    with op.batch_alter_table("instagram_raw_assets") as batch:
        batch.drop_index("ix_instagram_raw_assets_business_active_created")
        batch.drop_index("ix_instagram_raw_assets_storage_deleted_at")
        batch.drop_index("ix_instagram_raw_assets_removed_at")
        batch.drop_index("ix_instagram_raw_assets_removed_by_user_id")
        batch.drop_constraint(
            "fk_instagram_raw_assets_removed_by_user_id",
            type_="foreignkey",
        )
        batch.drop_column("storage_deleted_at")
        batch.drop_column("removed_by_user_id")
        batch.drop_column("removed_at")
