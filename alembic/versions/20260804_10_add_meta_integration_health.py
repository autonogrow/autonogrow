"""add persistent Meta integration health and maintenance jobs

Revision ID: 20260804_10
Revises: 20260803_09
Create Date: 2026-08-04
"""

from collections.abc import Sequence
from datetime import datetime, timedelta

import sqlalchemy as sa
from alembic import op
from sqlalchemy import inspect

revision: str = "20260804_10"
down_revision: str | Sequence[str] | None = "20260803_09"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    columns = {
        column["name"]
        for column in inspect(op.get_bind()).get_columns("business_channel_integrations")
    }
    if "health_status" not in columns:
        with op.batch_alter_table("business_channel_integrations") as batch:
            batch.add_column(
                sa.Column(
                    "health_status",
                    sa.String(30),
                    nullable=False,
                    server_default="unknown",
                )
            )
            batch.add_column(sa.Column("last_health_check_at", sa.DateTime(), nullable=True))
            batch.add_column(sa.Column("next_health_check_at", sa.DateTime(), nullable=True))
            batch.add_column(
                sa.Column(
                    "consecutive_health_failures",
                    sa.Integer(),
                    nullable=False,
                    server_default="0",
                )
            )
            batch.add_column(sa.Column("health_error_code", sa.String(80), nullable=True))
            batch.add_column(sa.Column("health_safe_error_message", sa.String(500), nullable=True))
            batch.add_column(sa.Column("health_metadata_json", sa.Text(), nullable=True))
            batch.create_check_constraint(
                "ck_channel_integration_health_status",
                "health_status IN ('unknown','healthy','warning','degraded','action_required',"
                "'revoked','suspended','error')",
            )
            batch.create_check_constraint(
                "ck_channel_integration_health_failures",
                "consecutive_health_failures >= 0",
            )
            batch.create_index(
                "ix_business_channel_integrations_health_status",
                ["health_status"],
                unique=False,
            )
            batch.create_index(
                "ix_business_channel_integrations_next_health_check_at",
                ["next_health_check_at"],
                unique=False,
            )

        # Spread the initial checks over one interval. No operational or commercial
        # state is changed by this deterministic backfill.
        bind = op.get_bind()
        rows = bind.execute(
            sa.text(
                "SELECT id FROM business_channel_integrations "
                "WHERE integration_status IN ('connected','degraded') ORDER BY id"
            )
        ).fetchall()
        base = datetime.utcnow()
        for (integration_id,) in rows:
            jitter_seconds = (int(integration_id) * 2654435761) % 86400
            bind.execute(
                sa.text(
                    "UPDATE business_channel_integrations "
                    "SET next_health_check_at = :next_check WHERE id = :integration_id"
                ),
                {
                    "next_check": base + timedelta(seconds=jitter_seconds),
                    "integration_id": integration_id,
                },
            )

    tables = set(inspect(op.get_bind()).get_table_names())
    if "meta_integration_jobs" not in tables:
        op.create_table(
            "meta_integration_jobs",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("business_id", sa.Integer(), nullable=False),
            sa.Column("integration_id", sa.Integer(), nullable=True),
            sa.Column("job_type", sa.String(30), nullable=False),
            sa.Column("status", sa.String(30), nullable=False, server_default="queued"),
            sa.Column("idempotency_key", sa.String(255), nullable=False),
            sa.Column("actor_user_id", sa.Integer(), nullable=True),
            sa.Column("origin", sa.String(20), nullable=False),
            sa.Column("attempt_count", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("max_attempts", sa.Integer(), nullable=False, server_default="5"),
            sa.Column("available_at", sa.DateTime(), nullable=False),
            sa.Column("next_retry_at", sa.DateTime(), nullable=True),
            sa.Column("locked_by", sa.String(200), nullable=True),
            sa.Column("lock_expires_at", sa.DateTime(), nullable=True),
            sa.Column("processing_started_at", sa.DateTime(), nullable=True),
            sa.Column("completed_at", sa.DateTime(), nullable=True),
            sa.Column("failed_at", sa.DateTime(), nullable=True),
            sa.Column("duration_ms", sa.Integer(), nullable=True),
            sa.Column("last_error_code", sa.String(120), nullable=True),
            sa.Column("safe_error_message", sa.String(500), nullable=True),
            sa.Column("created_at", sa.DateTime(), nullable=False),
            sa.Column("updated_at", sa.DateTime(), nullable=False),
            sa.CheckConstraint(
                "job_type IN ('health_check','retry_subscription','attempt_cleanup')",
                name="ck_meta_integration_job_type",
            ),
            sa.CheckConstraint(
                "status IN ('queued','processing','retry','completed','failed','dead_letter')",
                name="ck_meta_integration_job_status",
            ),
            sa.CheckConstraint(
                "origin IN ('scheduler','owner','admin','system')",
                name="ck_meta_integration_job_origin",
            ),
            sa.CheckConstraint("attempt_count >= 0", name="ck_meta_integration_job_attempt_count"),
            sa.CheckConstraint("max_attempts > 0", name="ck_meta_integration_job_max_attempts"),
            sa.CheckConstraint(
                "((job_type IN ('health_check','retry_subscription') AND "
                "integration_id IS NOT NULL) OR "
                "(job_type = 'attempt_cleanup' AND integration_id IS NULL))",
                name="ck_meta_integration_job_integration_required",
            ),
            sa.ForeignKeyConstraint(["business_id"], ["businesses.id"], ondelete="CASCADE"),
            sa.ForeignKeyConstraint(
                ["integration_id"],
                ["business_channel_integrations.id"],
                ondelete="CASCADE",
            ),
            sa.ForeignKeyConstraint(["actor_user_id"], ["users.id"], ondelete="SET NULL"),
            sa.UniqueConstraint("idempotency_key", name="uq_meta_integration_job_idempotency"),
        )
        op.create_index(
            "ix_meta_integration_jobs_business_id", "meta_integration_jobs", ["business_id"]
        )
        op.create_index(
            "ix_meta_integration_jobs_integration_id",
            "meta_integration_jobs",
            ["integration_id"],
        )
        op.create_index(
            "ix_meta_integration_jobs_actor_user_id",
            "meta_integration_jobs",
            ["actor_user_id"],
        )
        op.create_index("ix_meta_integration_jobs_job_type", "meta_integration_jobs", ["job_type"])
        op.create_index("ix_meta_integration_jobs_status", "meta_integration_jobs", ["status"])
        op.create_index(
            "ix_meta_integration_jobs_status_available",
            "meta_integration_jobs",
            ["status", "available_at"],
        )
        op.create_index(
            "ix_meta_integration_jobs_status_lock",
            "meta_integration_jobs",
            ["status", "lock_expires_at"],
        )
        op.create_index(
            "ix_meta_integration_jobs_business_status",
            "meta_integration_jobs",
            ["business_id", "status"],
        )
        op.create_index(
            "ix_meta_integration_jobs_integration_type_status",
            "meta_integration_jobs",
            ["integration_id", "job_type", "status"],
        )


def downgrade() -> None:
    tables = set(inspect(op.get_bind()).get_table_names())
    if "meta_integration_jobs" in tables:
        op.drop_table("meta_integration_jobs")

    columns = {
        column["name"]
        for column in inspect(op.get_bind()).get_columns("business_channel_integrations")
    }
    if "health_status" in columns:
        with op.batch_alter_table("business_channel_integrations") as batch:
            batch.drop_index("ix_business_channel_integrations_next_health_check_at")
            batch.drop_index("ix_business_channel_integrations_health_status")
            batch.drop_constraint("ck_channel_integration_health_failures", type_="check")
            batch.drop_constraint("ck_channel_integration_health_status", type_="check")
            batch.drop_column("health_metadata_json")
            batch.drop_column("health_safe_error_message")
            batch.drop_column("health_error_code")
            batch.drop_column("consecutive_health_failures")
            batch.drop_column("next_health_check_at")
            batch.drop_column("last_health_check_at")
            batch.drop_column("health_status")
