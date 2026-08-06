"""add Instagram simulated publishing scheduler jobs

Revision ID: 20260806_12
Revises: 20260806_11
Create Date: 2026-08-06
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy import inspect

revision: str = "20260806_12"
down_revision: str | Sequence[str] | None = "20260806_11"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _replace_content_status_constraint(*, published: bool) -> None:
    statuses = (
        "'draft','ready_for_review','changes_requested','validated','scheduled',"
        + ("'published'," if published else "")
        + "'cancelled'"
    )
    with op.batch_alter_table("instagram_contents") as batch_op:
        batch_op.drop_constraint("ck_instagram_contents_status", type_="check")
        batch_op.create_check_constraint("ck_instagram_contents_status", f"status IN ({statuses})")


def upgrade() -> None:
    inspector = inspect(op.get_bind())
    if "instagram_publish_jobs" in inspector.get_table_names():
        required_columns = {
            "id",
            "business_id",
            "content_item_id",
            "content_version_id",
            "integration_id",
            "status",
            "scheduled_for",
            "idempotency_key",
            "claim_expires_at",
            "provider_media_id",
            "created_at",
            "updated_at",
        }
        actual_columns = {
            column["name"] for column in inspector.get_columns("instagram_publish_jobs")
        }
        if not required_columns <= actual_columns:
            raise RuntimeError("Partial instagram_publish_jobs schema detected")
        return
    _replace_content_status_constraint(published=True)
    op.create_table(
        "instagram_publish_jobs",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("business_id", sa.Integer(), nullable=False),
        sa.Column("content_item_id", sa.Integer(), nullable=False),
        sa.Column("content_version_id", sa.Integer(), nullable=False),
        sa.Column("integration_id", sa.Integer(), nullable=True),
        sa.Column("status", sa.String(30), nullable=False),
        sa.Column("scheduled_for", sa.DateTime(timezone=True), nullable=False),
        sa.Column("attempt_count", sa.Integer(), nullable=False),
        sa.Column("max_attempts", sa.Integer(), nullable=False),
        sa.Column("next_attempt_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("claimed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("claim_expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("claimed_by", sa.String(200), nullable=True),
        sa.Column("idempotency_key", sa.String(255), nullable=False),
        sa.Column("provider_container_id", sa.String(255), nullable=True),
        sa.Column("provider_media_id", sa.String(255), nullable=True),
        sa.Column("provider_permalink", sa.String(500), nullable=True),
        sa.Column("provider_status", sa.String(80), nullable=True),
        sa.Column("provider_error_code", sa.String(120), nullable=True),
        sa.Column("safe_error_message", sa.String(500), nullable=True),
        sa.Column("provider_metadata_json", sa.Text(), nullable=True),
        sa.Column("created_by_user_id", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("published_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("cancelled_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint("attempt_count >= 0", name="ck_instagram_publish_jobs_attempts"),
        sa.CheckConstraint("max_attempts > 0", name="ck_instagram_publish_jobs_max_attempts"),
        sa.CheckConstraint(
            "status IN ('queued','claimed','simulating_publish','published','retry_wait',"
            "'failed','action_required','cancelled')",
            name="ck_instagram_publish_jobs_status",
        ),
        sa.ForeignKeyConstraint(["business_id"], ["businesses.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["content_item_id"], ["instagram_contents.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["content_version_id"], ["instagram_content_versions.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["integration_id"], ["business_channel_integrations.id"], ondelete="SET NULL"
        ),
        sa.ForeignKeyConstraint(["created_by_user_id"], ["users.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("content_version_id", name="uq_instagram_publish_job_version"),
        sa.UniqueConstraint("idempotency_key"),
    )
    indexes = (
        ("ix_instagram_publish_jobs_business_id", ["business_id"]),
        ("ix_instagram_publish_jobs_content_item_id", ["content_item_id"]),
        ("ix_instagram_publish_jobs_content_version_id", ["content_version_id"]),
        ("ix_instagram_publish_jobs_integration_id", ["integration_id"]),
        ("ix_instagram_publish_jobs_status", ["status"]),
        ("ix_instagram_publish_jobs_scheduled_for", ["scheduled_for"]),
        ("ix_instagram_publish_jobs_next_attempt_at", ["next_attempt_at"]),
        ("ix_instagram_publish_jobs_claim_expires_at", ["claim_expires_at"]),
        ("ix_instagram_publish_jobs_provider_media_id", ["provider_media_id"]),
        ("ix_instagram_publish_jobs_created_by_user_id", ["created_by_user_id"]),
        ("ix_instagram_publish_jobs_status_scheduled", ["status", "scheduled_for"]),
        ("ix_instagram_publish_jobs_status_next_attempt", ["status", "next_attempt_at"]),
        ("ix_instagram_publish_jobs_claim_expiry", ["status", "claim_expires_at"]),
        ("ix_instagram_publish_jobs_business_created", ["business_id", "created_at"]),
        ("ix_instagram_publish_jobs_content_created", ["content_item_id", "created_at"]),
    )
    for name, columns in indexes:
        op.create_index(name, "instagram_publish_jobs", columns)


def downgrade() -> None:
    op.drop_table("instagram_publish_jobs")
    op.execute("UPDATE instagram_contents SET status = 'scheduled' WHERE status = 'published'")
    _replace_content_status_constraint(published=False)
