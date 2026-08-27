"""add operational social publication policy

Revision ID: 20260825_26
Revises: 20260825_25
Create Date: 2026-08-25
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260825_26"
down_revision: str | Sequence[str] | None = "20260825_25"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("social_content_proposals") as batch:
        batch.add_column(
            sa.Column("operator_postponed_until", sa.DateTime(timezone=True), nullable=True)
        )
        batch.create_index(
            "ix_social_content_proposals_operator_postponed_until",
            ["operator_postponed_until"],
        )

    with op.batch_alter_table("instagram_content_versions") as batch:
        batch.add_column(sa.Column("promotion_revision_id", sa.Integer(), nullable=True))
        batch.create_foreign_key(
            "fk_instagram_content_versions_promotion_revision",
            "social_promotion_revisions",
            ["promotion_revision_id"],
            ["id"],
            ondelete="RESTRICT",
        )
        batch.create_index(
            "ix_instagram_content_versions_promotion_revision_id",
            ["promotion_revision_id"],
        )

    op.create_table(
        "instagram_content_publication_holds",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("business_id", sa.Integer(), nullable=False),
        sa.Column("content_id", sa.Integer(), nullable=False),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.Column("held_by_user_id", sa.Integer(), nullable=True),
        sa.Column("held_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("released_by_user_id", sa.Integer(), nullable=True),
        sa.Column("released_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("release_note", sa.Text(), nullable=True),
        sa.ForeignKeyConstraint(["business_id"], ["businesses.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["content_id"], ["instagram_contents.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["held_by_user_id"], ["users.id"], ondelete="SET NULL"
        ),
        sa.ForeignKeyConstraint(
            ["released_by_user_id"], ["users.id"], ondelete="SET NULL"
        ),
    )
    op.create_index(
        "ix_instagram_content_publication_holds_business_id",
        "instagram_content_publication_holds",
        ["business_id"],
    )
    op.create_index(
        "ix_instagram_content_publication_holds_content_id",
        "instagram_content_publication_holds",
        ["content_id"],
    )
    op.create_index(
        "ix_instagram_content_publication_holds_held_by_user_id",
        "instagram_content_publication_holds",
        ["held_by_user_id"],
    )
    op.create_index(
        "ix_instagram_content_publication_holds_released_by_user_id",
        "instagram_content_publication_holds",
        ["released_by_user_id"],
    )
    op.create_index(
        "ix_instagram_content_publication_holds_released_at",
        "instagram_content_publication_holds",
        ["released_at"],
    )
    op.create_index(
        "ix_instagram_content_holds_content_released",
        "instagram_content_publication_holds",
        ["content_id", "released_at"],
    )
    op.create_index(
        "ix_instagram_content_holds_business_held",
        "instagram_content_publication_holds",
        ["business_id", "held_at"],
    )


def downgrade() -> None:
    op.drop_table("instagram_content_publication_holds")
    with op.batch_alter_table("instagram_content_versions") as batch:
        batch.drop_index("ix_instagram_content_versions_promotion_revision_id")
        batch.drop_constraint(
            "fk_instagram_content_versions_promotion_revision", type_="foreignkey"
        )
        batch.drop_column("promotion_revision_id")
    with op.batch_alter_table("social_content_proposals") as batch:
        batch.drop_index("ix_social_content_proposals_operator_postponed_until")
        batch.drop_column("operator_postponed_until")
