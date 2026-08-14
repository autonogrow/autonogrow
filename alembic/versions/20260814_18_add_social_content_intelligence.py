"""add social content intelligence proposals

Revision ID: 20260814_18
Revises: 20260814_17
Create Date: 2026-08-14
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260814_18"
down_revision: str | Sequence[str] | None = "20260814_17"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    tables = set(sa.inspect(op.get_bind()).get_table_names())
    if "business_reviews" not in tables:
        op.create_table(
            "business_reviews",
            sa.Column("id", sa.Integer(), nullable=False),
            sa.Column("business_id", sa.Integer(), nullable=False),
            sa.Column("service_id", sa.Integer()),
            sa.Column("source", sa.String(length=50), nullable=False),
            sa.Column("external_id", sa.String(length=200), nullable=False),
            sa.Column("rating", sa.Float(), nullable=False),
            sa.Column("review_text", sa.Text(), nullable=False),
            sa.Column("status", sa.String(length=20), nullable=False),
            sa.Column(
                "social_use_approved",
                sa.Boolean(),
                server_default=sa.text("false"),
                nullable=False,
            ),
            sa.Column("reviewed_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
            sa.CheckConstraint("rating >= 1 AND rating <= 5", name="ck_business_reviews_rating"),
            sa.CheckConstraint(
                "status IN ('pending','usable','rejected','removed')",
                name="ck_business_reviews_status",
            ),
            sa.ForeignKeyConstraint(["business_id"], ["businesses.id"], ondelete="CASCADE"),
            sa.ForeignKeyConstraint(["service_id"], ["services.id"], ondelete="SET NULL"),
            sa.PrimaryKeyConstraint("id"),
            sa.UniqueConstraint(
                "business_id", "source", "external_id", name="uq_business_reviews_source"
            ),
        )
        for column in ("business_id", "service_id", "reviewed_at"):
            op.create_index(f"ix_business_reviews_{column}", "business_reviews", [column])
        op.create_index(
            "ix_business_reviews_business_usable_date",
            "business_reviews",
            ["business_id", "status", "reviewed_at"],
        )

    if "social_content_proposals" not in tables:
        op.create_table(
            "social_content_proposals",
            sa.Column("id", sa.Integer(), nullable=False),
            sa.Column("business_id", sa.Integer(), nullable=False),
            sa.Column("status", sa.String(length=20), nullable=False),
            sa.Column("objective", sa.String(length=40), nullable=False),
            sa.Column("proposal_type", sa.String(length=40), nullable=False),
            sa.Column("priority", sa.String(length=20), nullable=False),
            sa.Column("priority_score", sa.Integer(), nullable=False),
            sa.Column("service_id", sa.Integer()),
            sa.Column("source_event_id", sa.Integer()),
            sa.Column("source_review_id", sa.Integer()),
            sa.Column("reason_code", sa.String(length=100), nullable=False),
            sa.Column("reason_text", sa.String(length=500), nullable=False),
            sa.Column("evidence_json", sa.Text(), nullable=False),
            sa.Column("recommended_formats_json", sa.Text(), nullable=False),
            sa.Column("recommended_cta", sa.String(length=30), nullable=False),
            sa.Column("angle_code", sa.String(length=30), nullable=False),
            sa.Column("available_asset_count", sa.Integer(), nullable=False),
            sa.Column("asset_requirement", sa.String(length=30), nullable=False),
            sa.Column("target_window_start", sa.DateTime(timezone=True), nullable=False),
            sa.Column("target_window_end", sa.DateTime(timezone=True), nullable=False),
            sa.Column("detected_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("dismissed_at", sa.DateTime(timezone=True)),
            sa.Column("accepted_at", sa.DateTime(timezone=True)),
            sa.Column("accepted_by_user_id", sa.Integer()),
            sa.Column("accepted_context_json", sa.Text()),
            sa.Column("resolved_at", sa.DateTime(timezone=True)),
            sa.Column("dedupe_key", sa.String(length=255), nullable=False),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
            sa.CheckConstraint(
                "status IN ('active','dismissed','accepted','resolved','expired')",
                name="ck_social_content_proposals_status",
            ),
            sa.CheckConstraint(
                "objective IN ('increase_bookings','reactivate_customers','promote_service',"
                "'seasonal_activation','social_proof','educate','engagement','fill_capacity')",
                name="ck_social_content_proposals_objective",
            ),
            sa.CheckConstraint(
                "proposal_type IN ('availability_push','service_push','return_activation',"
                "'seasonal_content','review_social_proof','evergreen_content')",
                name="ck_social_content_proposals_type",
            ),
            sa.CheckConstraint(
                "priority IN ('low','normal','high')",
                name="ck_social_content_proposals_priority",
            ),
            sa.CheckConstraint("priority_score >= 0", name="ck_social_content_proposals_score"),
            sa.CheckConstraint(
                "recommended_cta IN ('book_now','check_availability','contact_us','learn_more',"
                "'discover_service','none')",
                name="ck_social_content_proposals_cta",
            ),
            sa.CheckConstraint(
                "angle_code IN ('availability','before_after','process','faq','benefit',"
                "'testimonial','seasonal','limited_window','educational','behind_the_scenes')",
                name="ck_social_content_proposals_angle",
            ),
            sa.CheckConstraint(
                "asset_requirement IN ('none','existing_media','new_photo','new_video',"
                "'review','before_after')",
                name="ck_social_content_proposals_asset_requirement",
            ),
            sa.CheckConstraint(
                "target_window_end > target_window_start",
                name="ck_social_content_proposals_window",
            ),
            sa.ForeignKeyConstraint(["business_id"], ["businesses.id"], ondelete="CASCADE"),
            sa.ForeignKeyConstraint(["service_id"], ["services.id"], ondelete="SET NULL"),
            sa.ForeignKeyConstraint(
                ["source_event_id"], ["business_calendar_events.id"], ondelete="SET NULL"
            ),
            sa.ForeignKeyConstraint(
                ["source_review_id"], ["business_reviews.id"], ondelete="SET NULL"
            ),
            sa.ForeignKeyConstraint(
                ["accepted_by_user_id"], ["users.id"], ondelete="SET NULL"
            ),
            sa.PrimaryKeyConstraint("id"),
            sa.UniqueConstraint(
                "business_id", "dedupe_key", name="uq_social_content_proposals_dedupe"
            ),
        )
        for column in (
            "business_id",
            "status",
            "objective",
            "proposal_type",
            "priority",
            "service_id",
            "source_event_id",
            "source_review_id",
            "accepted_by_user_id",
            "expires_at",
        ):
            op.create_index(
                f"ix_social_content_proposals_{column}", "social_content_proposals", [column]
            )
        op.create_index(
            "ix_social_content_proposals_business_status_priority",
            "social_content_proposals",
            ["business_id", "status", "priority"],
        )
        op.create_index(
            "ix_social_content_proposals_business_type_service",
            "social_content_proposals",
            ["business_id", "proposal_type", "service_id"],
        )

    tables = set(sa.inspect(op.get_bind()).get_table_names())
    if "social_content_proposal_signals" not in tables:
        op.create_table(
            "social_content_proposal_signals",
            sa.Column("id", sa.Integer(), nullable=False),
            sa.Column("proposal_id", sa.Integer(), nullable=False),
            sa.Column("signal_id", sa.Integer(), nullable=False),
            sa.ForeignKeyConstraint(
                ["proposal_id"], ["social_content_proposals.id"], ondelete="CASCADE"
            ),
            sa.ForeignKeyConstraint(
                ["signal_id"], ["business_growth_signals.id"], ondelete="CASCADE"
            ),
            sa.PrimaryKeyConstraint("id"),
            sa.UniqueConstraint(
                "proposal_id", "signal_id", name="uq_social_content_proposal_signal"
            ),
        )
        op.create_index(
            "ix_social_content_proposal_signals_proposal_id",
            "social_content_proposal_signals",
            ["proposal_id"],
        )
        op.create_index(
            "ix_social_content_proposal_signals_signal_id",
            "social_content_proposal_signals",
            ["signal_id"],
        )


def downgrade() -> None:
    tables = set(sa.inspect(op.get_bind()).get_table_names())
    if "social_content_proposal_signals" in tables:
        op.drop_table("social_content_proposal_signals")
    if "social_content_proposals" in tables:
        op.drop_table("social_content_proposals")
    if "business_reviews" in tables:
        op.drop_table("business_reviews")
