"""add Instagram Meta publishing states

Revision ID: 20260806_13
Revises: 20260806_12
Create Date: 2026-08-06
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260806_13"
down_revision: str | Sequence[str] | None = "20260806_12"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_OLD = (
    "status IN ('queued','claimed','simulating_publish','published','retry_wait',"
    "'failed','action_required','cancelled')"
)
_NEW = (
    "status IN ('queued','claimed','creating_container','publishing','simulating_publish',"
    "'published','retry_wait','failed','action_required','cancelled')"
)


def _replace(expression: str) -> None:
    with op.batch_alter_table("instagram_publish_jobs") as batch_op:
        batch_op.drop_constraint("ck_instagram_publish_jobs_status", type_="check")
        batch_op.create_check_constraint("ck_instagram_publish_jobs_status", expression)


def upgrade() -> None:
    asset_columns = {
        column["name"] for column in sa.inspect(op.get_bind()).get_columns("instagram_final_assets")
    }
    if "sha256" not in asset_columns:
        with op.batch_alter_table("instagram_final_assets") as batch_op:
            batch_op.add_column(sa.Column("sha256", sa.String(length=64), nullable=True))
    _replace(_NEW)


def downgrade() -> None:
    op.execute(
        "UPDATE instagram_publish_jobs SET status = 'action_required', "
        "provider_status = 'migration_downgrade_requires_review' "
        "WHERE status IN ('creating_container','publishing')"
    )
    _replace(_OLD)
    asset_columns = {
        column["name"] for column in sa.inspect(op.get_bind()).get_columns("instagram_final_assets")
    }
    if "sha256" in asset_columns:
        with op.batch_alter_table("instagram_final_assets") as batch_op:
            batch_op.drop_column("sha256")
