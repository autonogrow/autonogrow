"""add Instagram content editorial workflow

Revision ID: 20260806_11
Revises: 20260804_10
Create Date: 2026-08-06
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy import inspect

revision: str = "20260806_11"
down_revision: str | Sequence[str] | None = "20260804_10"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    required_tables = {
        "instagram_content_settings",
        "instagram_raw_assets",
        "instagram_contents",
        "instagram_final_assets",
        "instagram_content_versions",
        "instagram_content_version_assets",
        "instagram_content_validations",
        "instagram_content_comments",
    }
    existing_tables = set(inspect(op.get_bind()).get_table_names())
    if required_tables <= existing_tables:
        return
    partial_tables = required_tables & existing_tables
    if partial_tables:
        names = ", ".join(sorted(partial_tables))
        raise RuntimeError(f"Partial Instagram editorial schema detected: {names}")

    op.create_table(
        "instagram_content_settings",
        sa.Column("business_id", sa.Integer(), nullable=False),
        sa.Column("enabled", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.Column(
            "owner_can_validate_instagram_content",
            sa.Boolean(),
            server_default=sa.text("false"),
            nullable=False,
        ),
        sa.Column("enabled_by_user_id", sa.Integer(), nullable=True),
        sa.Column("validation_delegated_by_user_id", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["business_id"], ["businesses.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["enabled_by_user_id"], ["users.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(
            ["validation_delegated_by_user_id"], ["users.id"], ondelete="SET NULL"
        ),
        sa.PrimaryKeyConstraint("business_id"),
    )
    op.create_index(
        "ix_instagram_content_settings_enabled_by_user_id",
        "instagram_content_settings",
        ["enabled_by_user_id"],
    )
    op.create_index(
        "ix_instagram_content_settings_validation_delegated_by_user_id",
        "instagram_content_settings",
        ["validation_delegated_by_user_id"],
    )

    op.create_table(
        "instagram_raw_assets",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("business_id", sa.Integer(), nullable=False),
        sa.Column("uploaded_by_user_id", sa.Integer(), nullable=True),
        sa.Column("original_filename", sa.String(255), nullable=False),
        sa.Column("storage_key", sa.String(500), nullable=False),
        sa.Column("media_type", sa.String(100), nullable=False),
        sa.Column("size_bytes", sa.Integer(), nullable=False),
        sa.Column("label", sa.String(240), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["business_id"], ["businesses.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["uploaded_by_user_id"], ["users.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("storage_key"),
    )
    op.create_index("ix_instagram_raw_assets_business_id", "instagram_raw_assets", ["business_id"])
    op.create_index(
        "ix_instagram_raw_assets_uploaded_by_user_id",
        "instagram_raw_assets",
        ["uploaded_by_user_id"],
    )
    op.create_index(
        "ix_instagram_raw_assets_business_created",
        "instagram_raw_assets",
        ["business_id", "created_at"],
    )

    op.create_table(
        "instagram_contents",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("business_id", sa.Integer(), nullable=False),
        sa.Column("title", sa.String(200), nullable=False),
        sa.Column("status", sa.String(30), nullable=False),
        sa.Column("planned_publish_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_by_user_id", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.CheckConstraint(
            "status IN ('draft','ready_for_review','changes_requested','validated',"
            "'scheduled','cancelled')",
            name="ck_instagram_contents_status",
        ),
        sa.ForeignKeyConstraint(["business_id"], ["businesses.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["created_by_user_id"], ["users.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_instagram_contents_business_id", "instagram_contents", ["business_id"])
    op.create_index("ix_instagram_contents_status", "instagram_contents", ["status"])
    op.create_index(
        "ix_instagram_contents_planned_publish_at", "instagram_contents", ["planned_publish_at"]
    )
    op.create_index(
        "ix_instagram_contents_created_by_user_id", "instagram_contents", ["created_by_user_id"]
    )
    op.create_index(
        "ix_instagram_contents_business_status", "instagram_contents", ["business_id", "status"]
    )
    op.create_index(
        "ix_instagram_contents_business_planned",
        "instagram_contents",
        ["business_id", "planned_publish_at"],
    )

    op.create_table(
        "instagram_final_assets",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("business_id", sa.Integer(), nullable=False),
        sa.Column("content_id", sa.Integer(), nullable=False),
        sa.Column("uploaded_by_user_id", sa.Integer(), nullable=True),
        sa.Column("original_filename", sa.String(255), nullable=False),
        sa.Column("storage_key", sa.String(500), nullable=False),
        sa.Column("media_type", sa.String(100), nullable=False),
        sa.Column("size_bytes", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["business_id"], ["businesses.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["content_id"], ["instagram_contents.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["uploaded_by_user_id"], ["users.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("storage_key"),
    )
    op.create_index(
        "ix_instagram_final_assets_business_id", "instagram_final_assets", ["business_id"]
    )
    op.create_index(
        "ix_instagram_final_assets_content_id", "instagram_final_assets", ["content_id"]
    )
    op.create_index(
        "ix_instagram_final_assets_uploaded_by_user_id",
        "instagram_final_assets",
        ["uploaded_by_user_id"],
    )
    op.create_index(
        "ix_instagram_final_assets_content_created",
        "instagram_final_assets",
        ["content_id", "created_at"],
    )

    op.create_table(
        "instagram_content_versions",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("business_id", sa.Integer(), nullable=False),
        sa.Column("content_id", sa.Integer(), nullable=False),
        sa.Column("version_number", sa.Integer(), nullable=False),
        sa.Column("caption", sa.Text(), nullable=False),
        sa.Column("format", sa.String(30), nullable=False),
        sa.Column("created_by_user_id", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.CheckConstraint("version_number > 0", name="ck_instagram_content_version_positive"),
        sa.CheckConstraint(
            "format IN ('single_image','carousel')", name="ck_instagram_content_version_format"
        ),
        sa.ForeignKeyConstraint(["business_id"], ["businesses.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["content_id"], ["instagram_contents.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["created_by_user_id"], ["users.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("content_id", "version_number", name="uq_instagram_content_version"),
    )
    op.create_index(
        "ix_instagram_content_versions_business_id", "instagram_content_versions", ["business_id"]
    )
    op.create_index(
        "ix_instagram_content_versions_content_id", "instagram_content_versions", ["content_id"]
    )
    op.create_index(
        "ix_instagram_content_versions_created_by_user_id",
        "instagram_content_versions",
        ["created_by_user_id"],
    )

    op.create_table(
        "instagram_content_version_assets",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("version_id", sa.Integer(), nullable=False),
        sa.Column("asset_id", sa.Integer(), nullable=False),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.Column("is_cover", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.CheckConstraint("position >= 0", name="ck_instagram_version_asset_position"),
        sa.ForeignKeyConstraint(
            ["version_id"], ["instagram_content_versions.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(["asset_id"], ["instagram_final_assets.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("version_id", "asset_id", name="uq_instagram_version_asset"),
        sa.UniqueConstraint("version_id", "position", name="uq_instagram_version_asset_position"),
    )
    op.create_index(
        "ix_instagram_content_version_assets_version_id",
        "instagram_content_version_assets",
        ["version_id"],
    )
    op.create_index(
        "ix_instagram_content_version_assets_asset_id",
        "instagram_content_version_assets",
        ["asset_id"],
    )

    op.create_table(
        "instagram_content_validations",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("business_id", sa.Integer(), nullable=False),
        sa.Column("content_id", sa.Integer(), nullable=False),
        sa.Column("version_id", sa.Integer(), nullable=False),
        sa.Column("validated_by_user_id", sa.Integer(), nullable=True),
        sa.Column("validator_role", sa.String(30), nullable=False),
        sa.Column("validated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("invalidated_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("invalidation_reason", sa.String(240), nullable=True),
        sa.CheckConstraint(
            "validator_role IN ('business_admin','owner_delegate')",
            name="ck_instagram_content_validation_role",
        ),
        sa.ForeignKeyConstraint(["business_id"], ["businesses.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["content_id"], ["instagram_contents.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["version_id"], ["instagram_content_versions.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(["validated_by_user_id"], ["users.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("version_id", name="uq_instagram_content_validation_version"),
    )
    op.create_index(
        "ix_instagram_content_validations_business_id",
        "instagram_content_validations",
        ["business_id"],
    )
    op.create_index(
        "ix_instagram_content_validations_content_id",
        "instagram_content_validations",
        ["content_id"],
    )
    op.create_index(
        "ix_instagram_content_validations_version_id",
        "instagram_content_validations",
        ["version_id"],
    )
    op.create_index(
        "ix_instagram_content_validations_validated_by_user_id",
        "instagram_content_validations",
        ["validated_by_user_id"],
    )
    op.create_index(
        "ix_instagram_validations_content_active",
        "instagram_content_validations",
        ["content_id", "invalidated_at"],
    )

    op.create_table(
        "instagram_content_comments",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("business_id", sa.Integer(), nullable=False),
        sa.Column("content_id", sa.Integer(), nullable=False),
        sa.Column("version_id", sa.Integer(), nullable=False),
        sa.Column("author_user_id", sa.Integer(), nullable=True),
        sa.Column("kind", sa.String(30), nullable=False),
        sa.Column("body", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.CheckConstraint(
            "kind IN ('comment','proposal','change_request')",
            name="ck_instagram_content_comment_kind",
        ),
        sa.ForeignKeyConstraint(["business_id"], ["businesses.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["content_id"], ["instagram_contents.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["version_id"], ["instagram_content_versions.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(["author_user_id"], ["users.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_instagram_content_comments_business_id", "instagram_content_comments", ["business_id"]
    )
    op.create_index(
        "ix_instagram_content_comments_content_id", "instagram_content_comments", ["content_id"]
    )
    op.create_index(
        "ix_instagram_content_comments_version_id", "instagram_content_comments", ["version_id"]
    )
    op.create_index(
        "ix_instagram_content_comments_author_user_id",
        "instagram_content_comments",
        ["author_user_id"],
    )
    op.create_index(
        "ix_instagram_comments_content_created",
        "instagram_content_comments",
        ["content_id", "created_at"],
    )


def downgrade() -> None:
    op.drop_table("instagram_content_comments")
    op.drop_table("instagram_content_validations")
    op.drop_table("instagram_content_version_assets")
    op.drop_table("instagram_content_versions")
    op.drop_table("instagram_final_assets")
    op.drop_table("instagram_contents")
    op.drop_table("instagram_raw_assets")
    op.drop_table("instagram_content_settings")
