"""add Instagram remote media sync and Story transforms

Revision ID: 20260824_24
Revises: 20260822_23
Create Date: 2026-08-24
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260824_24"
down_revision: str | Sequence[str] | None = "20260822_23"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_OLD_JOB_TYPES = "job_type IN ('health_check','retry_subscription','attempt_cleanup')"
_NEW_JOB_TYPES = (
    "job_type IN ('health_check','retry_subscription','attempt_cleanup',"
    "'instagram_media_sync')"
)
_OLD_JOB_TARGET = (
    "((job_type IN ('health_check','retry_subscription') AND integration_id IS NOT NULL) "
    "OR (job_type = 'attempt_cleanup' AND integration_id IS NULL))"
)
_NEW_JOB_TARGET = (
    "((job_type IN ('health_check','retry_subscription','instagram_media_sync') "
    "AND integration_id IS NOT NULL) OR "
    "(job_type = 'attempt_cleanup' AND integration_id IS NULL))"
)


def _replace_job_constraints(job_types: str, target: str) -> None:
    with op.batch_alter_table("meta_integration_jobs") as batch:
        batch.drop_constraint("ck_meta_integration_job_type", type_="check")
        batch.drop_constraint("ck_meta_integration_job_integration_required", type_="check")
        batch.create_check_constraint("ck_meta_integration_job_type", job_types)
        batch.create_check_constraint("ck_meta_integration_job_integration_required", target)


def upgrade() -> None:
    bind = op.get_bind()
    existing_tables = set(sa.inspect(bind).get_table_names())
    if "instagram_remote_media" not in existing_tables:
        op.create_table(
        "instagram_remote_media",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("business_id", sa.Integer(), nullable=False),
        sa.Column("integration_id", sa.Integer(), nullable=False),
        sa.Column("provider_media_id", sa.String(255), nullable=False),
        sa.Column("parent_id", sa.Integer(), nullable=True),
        sa.Column("position", sa.Integer(), nullable=True),
        sa.Column("origin", sa.String(20), nullable=False, server_default="instagram"),
        sa.Column("media_type", sa.String(30), nullable=False),
        sa.Column("media_product_type", sa.String(30), nullable=True),
        sa.Column("caption", sa.Text(), nullable=True),
        sa.Column("provider_timestamp", sa.DateTime(timezone=True), nullable=True),
        sa.Column("permalink", sa.String(500), nullable=True),
        sa.Column("provider_preview_url", sa.Text(), nullable=True),
        sa.Column("remote_status", sa.String(20), nullable=False, server_default="available"),
        sa.Column("first_seen_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_seen_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_checked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("unavailable_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_error_code", sa.String(120), nullable=True),
        sa.Column("last_seen_sync_id", sa.String(64), nullable=True),
        sa.Column("internal_content_id", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "origin IN ('autonogrow','instagram')", name="ck_instagram_remote_media_origin"
        ),
        sa.CheckConstraint(
            "remote_status IN ('available','unavailable')",
            name="ck_instagram_remote_media_status",
        ),
        sa.CheckConstraint(
            "position IS NULL OR position >= 0", name="ck_instagram_remote_position"
        ),
        sa.ForeignKeyConstraint(["business_id"], ["businesses.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["integration_id"], ["business_channel_integrations.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["parent_id"], ["instagram_remote_media.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["internal_content_id"], ["instagram_contents.id"], ondelete="SET NULL"
        ),
        sa.UniqueConstraint(
            "integration_id",
            "provider_media_id",
            name="uq_instagram_remote_integration_media",
        ),
        )
        op.create_index(
            "ix_instagram_remote_media_business_id", "instagram_remote_media", ["business_id"]
        )
        op.create_index(
            "ix_instagram_remote_media_integration_id",
            "instagram_remote_media",
            ["integration_id"],
        )
        op.create_index(
            "ix_instagram_remote_media_provider_media_id",
            "instagram_remote_media",
            ["provider_media_id"],
        )
        op.create_index(
            "ix_instagram_remote_media_parent_id", "instagram_remote_media", ["parent_id"]
        )
        op.create_index(
            "ix_instagram_remote_media_provider_timestamp",
            "instagram_remote_media",
            ["provider_timestamp"],
        )
        op.create_index(
            "ix_instagram_remote_media_remote_status",
            "instagram_remote_media",
            ["remote_status"],
        )
        op.create_index(
            "ix_instagram_remote_media_last_seen_sync_id",
            "instagram_remote_media",
            ["last_seen_sync_id"],
        )
        op.create_index(
            "ix_instagram_remote_media_internal_content_id",
            "instagram_remote_media",
            ["internal_content_id"],
        )
        op.create_index(
            "ix_instagram_remote_business_status_time",
            "instagram_remote_media",
            ["business_id", "remote_status", "provider_timestamp"],
        )
        op.create_index(
            "ix_instagram_remote_integration_parent",
            "instagram_remote_media",
            ["integration_id", "parent_id"],
        )

    if "instagram_media_sync_states" not in existing_tables:
        op.create_table(
        "instagram_media_sync_states",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("business_id", sa.Integer(), nullable=False),
        sa.Column("integration_id", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(20), nullable=False, server_default="idle"),
        sa.Column("run_id", sa.String(64), nullable=True),
        sa.Column("after_cursor", sa.String(1000), nullable=True),
        sa.Column("last_attempt_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_success_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_error_code", sa.String(120), nullable=True),
        sa.Column("safe_error_message", sa.String(500), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "status IN ('idle','queued','running','succeeded','failed')",
            name="ck_instagram_media_sync_status",
        ),
        sa.ForeignKeyConstraint(["business_id"], ["businesses.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["integration_id"], ["business_channel_integrations.id"], ondelete="CASCADE"
        ),
        sa.UniqueConstraint("integration_id", name="uq_instagram_media_sync_integration"),
        )
        op.create_index(
            "ix_instagram_media_sync_states_business_id",
            "instagram_media_sync_states",
            ["business_id"],
        )
        op.create_index(
            "ix_instagram_media_sync_states_status", "instagram_media_sync_states", ["status"]
        )
        op.create_index(
            "ix_instagram_media_sync_states_last_success_at",
            "instagram_media_sync_states",
            ["last_success_at"],
        )
        op.create_index(
            "ix_instagram_media_sync_business_status",
            "instagram_media_sync_states",
            ["business_id", "status"],
        )

    raw_columns = {
        item["name"] for item in sa.inspect(bind).get_columns("instagram_raw_assets")
    }
    if "source_kind" not in raw_columns:
        with op.batch_alter_table("instagram_raw_assets") as batch:
            batch.add_column(
                sa.Column(
                    "source_kind", sa.String(30), nullable=False, server_default="business_upload"
                )
            )
            batch.add_column(sa.Column("source_remote_media_id", sa.Integer(), nullable=True))
            batch.add_column(sa.Column("sha256", sa.String(64), nullable=True))
            batch.create_check_constraint(
                "ck_instagram_raw_assets_source_kind",
                "source_kind IN ('business_upload','instagram')",
            )
            batch.create_foreign_key(
                "fk_instagram_raw_assets_source_remote_media_id",
                "instagram_remote_media",
                ["source_remote_media_id"],
                ["id"],
                ondelete="RESTRICT",
            )
            batch.create_index(
                "ix_instagram_raw_assets_source_remote_media_id", ["source_remote_media_id"]
            )
            batch.create_unique_constraint(
                "uq_instagram_raw_asset_remote_media", ["source_remote_media_id"]
            )

    final_columns = {
        item["name"] for item in sa.inspect(bind).get_columns("instagram_final_assets")
    }
    if "derivation_fingerprint" not in final_columns:
        with op.batch_alter_table("instagram_final_assets") as batch:
            batch.drop_constraint("uq_instagram_final_asset_content_raw_source", type_="unique")
            batch.add_column(sa.Column("derivation_fingerprint", sa.String(64), nullable=True))
        op.execute(
            "UPDATE instagram_final_assets SET derivation_fingerprint = 'copy' "
            "WHERE source_raw_asset_id IS NOT NULL"
        )
        with op.batch_alter_table("instagram_final_assets") as batch:
            batch.create_unique_constraint(
                "uq_instagram_final_asset_derivation",
                ["content_id", "source_raw_asset_id", "derivation_fingerprint"],
            )

    version_columns = {
        item["name"] for item in sa.inspect(bind).get_columns("instagram_content_versions")
    }
    if "story_transform_json" not in version_columns:
        with op.batch_alter_table("instagram_content_versions") as batch:
            batch.add_column(sa.Column("story_transform_json", sa.Text(), nullable=True))
            batch.add_column(sa.Column("story_renderer_version", sa.String(50), nullable=True))

    _replace_job_constraints(_NEW_JOB_TYPES, _NEW_JOB_TARGET)


def downgrade() -> None:
    _replace_job_constraints(_OLD_JOB_TYPES, _OLD_JOB_TARGET)
    with op.batch_alter_table("instagram_content_versions") as batch:
        batch.drop_column("story_renderer_version")
        batch.drop_column("story_transform_json")
    with op.batch_alter_table("instagram_final_assets") as batch:
        batch.drop_constraint("uq_instagram_final_asset_derivation", type_="unique")
        batch.drop_column("derivation_fingerprint")
        batch.create_unique_constraint(
            "uq_instagram_final_asset_content_raw_source",
            ["content_id", "source_raw_asset_id"],
        )
    with op.batch_alter_table("instagram_raw_assets") as batch:
        batch.drop_constraint("uq_instagram_raw_asset_remote_media", type_="unique")
        batch.drop_index("ix_instagram_raw_assets_source_remote_media_id")
        batch.drop_constraint(
            "fk_instagram_raw_assets_source_remote_media_id", type_="foreignkey"
        )
        batch.drop_constraint("ck_instagram_raw_assets_source_kind", type_="check")
        batch.drop_column("sha256")
        batch.drop_column("source_remote_media_id")
        batch.drop_column("source_kind")
    op.drop_table("instagram_media_sync_states")
    op.drop_table("instagram_remote_media")
