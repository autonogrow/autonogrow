"""add safe Instagram content archival

Revision ID: 20260815_20
Revises: 20260814_19
Create Date: 2026-08-15
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260815_20"
down_revision: str | Sequence[str] | None = "20260814_19"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    columns = {item["name"] for item in inspector.get_columns("instagram_contents")}
    if "archived_at" not in columns:
        with op.batch_alter_table("instagram_contents") as batch:
            batch.add_column(sa.Column("archived_at", sa.DateTime(timezone=True), nullable=True))
    indexes = {item["name"] for item in sa.inspect(op.get_bind()).get_indexes("instagram_contents")}
    if "ix_instagram_contents_archived_at" not in indexes:
        with op.batch_alter_table("instagram_contents") as batch:
            batch.create_index("ix_instagram_contents_archived_at", ["archived_at"])


def downgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    columns = {item["name"] for item in inspector.get_columns("instagram_contents")}
    if "archived_at" in columns:
        with op.batch_alter_table("instagram_contents") as batch:
            indexes = {item["name"] for item in inspector.get_indexes("instagram_contents")}
            if "ix_instagram_contents_archived_at" in indexes:
                batch.drop_index("ix_instagram_contents_archived_at")
            batch.drop_column("archived_at")
