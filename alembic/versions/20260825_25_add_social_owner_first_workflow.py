"""add owner-first social workflow and versioned approvals

Revision ID: 20260825_25
Revises: 20260824_24
Create Date: 2026-08-25
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260825_25"
down_revision: str | Sequence[str] | None = "20260824_24"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_OLD_GROWTH_TYPES = (
    "type IN ('low_future_occupancy','high_due_customer_pool',"
    "'low_return_rate','service_demand_drop','seasonal_window')"
)
_NEW_GROWTH_TYPES = (
    "type IN ('low_future_occupancy','high_due_customer_pool',"
    "'low_return_rate','service_demand_drop','seasonal_window','new_service')"
)


def _replace_growth_type_constraint(expression: str) -> None:
    with op.batch_alter_table("business_growth_signals") as batch:
        batch.drop_constraint("ck_business_growth_signals_type", type_="check")
        batch.create_check_constraint("ck_business_growth_signals_type", expression)


def upgrade() -> None:
    _replace_growth_type_constraint(_NEW_GROWTH_TYPES)

    op.create_table(
        "social_idea_reviews",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("business_id", sa.Integer(), nullable=False),
        sa.Column("proposal_id", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(30), nullable=False, server_default="pending"),
        sa.Column("owner_intent", sa.String(30), nullable=False),
        sa.Column("owner_accepted_by_user_id", sa.Integer(), nullable=True),
        sa.Column("owner_accepted_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("owner_context_json", sa.Text(), nullable=False),
        sa.Column("presentation_json", sa.Text(), nullable=False),
        sa.Column("template_version", sa.String(50), nullable=False),
        sa.Column("admin_reviewed_by_user_id", sa.Integer(), nullable=True),
        sa.Column("admin_reviewed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("admin_note", sa.Text(), nullable=True),
        sa.Column("adjustments_json", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "status IN ('pending','approved','changes_requested','rejected')",
            name="ck_social_idea_reviews_status",
        ),
        sa.CheckConstraint(
            "owner_intent IN ('visibility','promotion')",
            name="ck_social_idea_reviews_owner_intent",
        ),
        sa.ForeignKeyConstraint(["business_id"], ["businesses.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["proposal_id"], ["social_content_proposals.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["owner_accepted_by_user_id"], ["users.id"], ondelete="SET NULL"
        ),
        sa.ForeignKeyConstraint(
            ["admin_reviewed_by_user_id"], ["users.id"], ondelete="SET NULL"
        ),
        sa.UniqueConstraint("proposal_id", name="uq_social_idea_review_proposal"),
    )
    op.create_index("ix_social_idea_reviews_business_id", "social_idea_reviews", ["business_id"])
    op.create_index("ix_social_idea_reviews_proposal_id", "social_idea_reviews", ["proposal_id"])
    op.create_index("ix_social_idea_reviews_status", "social_idea_reviews", ["status"])
    op.create_index(
        "ix_social_idea_reviews_business_status",
        "social_idea_reviews",
        ["business_id", "status"],
    )

    op.create_table(
        "social_promotions",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("business_id", sa.Integer(), nullable=False),
        sa.Column("idea_review_id", sa.Integer(), nullable=False),
        sa.Column("service_id", sa.Integer(), nullable=True),
        sa.Column("status", sa.String(30), nullable=False, server_default="requested"),
        sa.Column("requested_by_user_id", sa.Integer(), nullable=True),
        sa.Column("requested_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "status IN ('requested','proposed','owner_approved','owner_rejected','cancelled','expired')",
            name="ck_social_promotions_status",
        ),
        sa.ForeignKeyConstraint(["business_id"], ["businesses.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["idea_review_id"], ["social_idea_reviews.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(["service_id"], ["services.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(
            ["requested_by_user_id"], ["users.id"], ondelete="SET NULL"
        ),
        sa.UniqueConstraint("idea_review_id", name="uq_social_promotion_idea_review"),
    )
    op.create_index("ix_social_promotions_business_id", "social_promotions", ["business_id"])
    op.create_index("ix_social_promotions_idea_review_id", "social_promotions", ["idea_review_id"])
    op.create_index("ix_social_promotions_service_id", "social_promotions", ["service_id"])
    op.create_index("ix_social_promotions_status", "social_promotions", ["status"])
    op.create_index(
        "ix_social_promotions_business_status", "social_promotions", ["business_id", "status"]
    )

    op.create_table(
        "social_promotion_revisions",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("promotion_id", sa.Integer(), nullable=False),
        sa.Column("revision_number", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(30), nullable=False, server_default="proposed"),
        sa.Column("discount_type", sa.String(20), nullable=False),
        sa.Column("discount_value", sa.Numeric(12, 2), nullable=False),
        sa.Column("regular_price", sa.Numeric(12, 2), nullable=False),
        sa.Column("promotional_price", sa.Numeric(12, 2), nullable=False),
        sa.Column("currency", sa.String(3), nullable=False),
        sa.Column("valid_from", sa.DateTime(timezone=True), nullable=False),
        sa.Column("valid_until", sa.DateTime(timezone=True), nullable=False),
        sa.Column("days_json", sa.Text(), nullable=False),
        sa.Column("scope", sa.String(240), nullable=False),
        sa.Column("proposed_by_user_id", sa.Integer(), nullable=True),
        sa.Column("proposed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("owner_decided_by_user_id", sa.Integer(), nullable=True),
        sa.Column("owner_decided_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("owner_note", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "status IN ('proposed','owner_approved','owner_rejected','superseded')",
            name="ck_social_promotion_revisions_status",
        ),
        sa.CheckConstraint(
            "discount_type IN ('percent','fixed')",
            name="ck_social_promotion_revisions_discount_type",
        ),
        sa.CheckConstraint("discount_value > 0", name="ck_social_promotion_discount_positive"),
        sa.CheckConstraint(
            "regular_price >= 0 AND promotional_price >= 0 AND promotional_price < regular_price",
            name="ck_social_promotion_revision_prices",
        ),
        sa.CheckConstraint(
            "valid_until > valid_from", name="ck_social_promotion_revision_window"
        ),
        sa.ForeignKeyConstraint(
            ["promotion_id"], ["social_promotions.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["proposed_by_user_id"], ["users.id"], ondelete="SET NULL"
        ),
        sa.ForeignKeyConstraint(
            ["owner_decided_by_user_id"], ["users.id"], ondelete="SET NULL"
        ),
        sa.UniqueConstraint(
            "promotion_id", "revision_number", name="uq_social_promotion_revision_number"
        ),
    )
    op.create_index(
        "ix_social_promotion_revisions_promotion_id",
        "social_promotion_revisions",
        ["promotion_id"],
    )
    op.create_index(
        "ix_social_promotion_revisions_status", "social_promotion_revisions", ["status"]
    )

    op.create_table(
        "instagram_content_editorial_reviews",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("business_id", sa.Integer(), nullable=False),
        sa.Column("content_id", sa.Integer(), nullable=False),
        sa.Column("version_id", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(30), nullable=False, server_default="pending"),
        sa.Column("submitted_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("reviewed_by_user_id", sa.Integer(), nullable=True),
        sa.Column("reviewed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("note", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "status IN ('pending','approved','changes_requested','rejected')",
            name="ck_instagram_editorial_reviews_status",
        ),
        sa.ForeignKeyConstraint(["business_id"], ["businesses.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["content_id"], ["instagram_contents.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["version_id"], ["instagram_content_versions.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["reviewed_by_user_id"], ["users.id"], ondelete="SET NULL"
        ),
        sa.UniqueConstraint("version_id", name="uq_instagram_editorial_review_version"),
    )
    op.create_index(
        "ix_instagram_editorial_reviews_business_id",
        "instagram_content_editorial_reviews",
        ["business_id"],
    )
    op.create_index(
        "ix_instagram_editorial_reviews_content_id",
        "instagram_content_editorial_reviews",
        ["content_id"],
    )
    op.create_index(
        "ix_instagram_editorial_reviews_version_id",
        "instagram_content_editorial_reviews",
        ["version_id"],
    )
    op.create_index(
        "ix_instagram_editorial_reviews_status",
        "instagram_content_editorial_reviews",
        ["status"],
    )
    op.create_index(
        "ix_instagram_editorial_reviews_business_status",
        "instagram_content_editorial_reviews",
        ["business_id", "status"],
    )


def downgrade() -> None:
    op.drop_table("instagram_content_editorial_reviews")
    op.drop_table("social_promotion_revisions")
    op.drop_table("social_promotions")
    op.drop_table("social_idea_reviews")
    _replace_growth_type_constraint(_OLD_GROWTH_TYPES)
