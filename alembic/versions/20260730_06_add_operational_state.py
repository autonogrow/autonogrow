"""add operational state and backup metadata

Revision ID: 20260730_06
Revises: 20260730_05
Create Date: 2026-07-30
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy import inspect

revision: str = "20260730_06"
down_revision: str | Sequence[str] | None = "20260730_05"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    tables = set(inspect(op.get_bind()).get_table_names())
    for table_name, index_name in (
        ("webhook_inbox_events", "ix_webhook_inbox_events_request_id"),
        ("channel_outbox_messages", "ix_channel_outbox_messages_request_id"),
    ):
        columns = {item["name"] for item in inspect(op.get_bind()).get_columns(table_name)}
        if "request_id" not in columns:
            with op.batch_alter_table(table_name) as batch_op:
                batch_op.add_column(sa.Column("request_id", sa.String(64)))
                batch_op.create_index(index_name, ["request_id"])
    if "operational_states" not in tables:
        op.create_table(
            "operational_states",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("key", sa.String(80), nullable=False),
            sa.Column("enabled", sa.Boolean(), nullable=False),
            sa.Column("safe_reason", sa.String(500)),
            sa.Column("updated_by_user_id", sa.Integer()),
            sa.Column("enabled_at", sa.DateTime()),
            sa.Column("disabled_at", sa.DateTime()),
            sa.Column("created_at", sa.DateTime(), nullable=False),
            sa.Column("updated_at", sa.DateTime(), nullable=False),
            sa.ForeignKeyConstraint(["updated_by_user_id"], ["users.id"], ondelete="SET NULL"),
            sa.UniqueConstraint("key", name="uq_operational_states_key"),
        )
        op.create_index("ix_operational_states_key", "operational_states", ["key"], unique=True)
        op.create_index(
            "ix_operational_states_updated_by_user_id",
            "operational_states",
            ["updated_by_user_id"],
        )
    if "backup_records" not in tables:
        op.create_table(
            "backup_records",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("backup_set_id", sa.String(80), nullable=False),
            sa.Column("backup_type", sa.String(30), nullable=False),
            sa.Column("environment", sa.String(30), nullable=False),
            sa.Column("release_id", sa.String(120), nullable=False),
            sa.Column("artifact_name", sa.String(255), nullable=False),
            sa.Column("manifest_name", sa.String(255)),
            sa.Column("checksum_sha256", sa.String(64)),
            sa.Column("size_bytes", sa.BigInteger(), nullable=False),
            sa.Column("status", sa.String(30), nullable=False),
            sa.Column("protected", sa.Boolean(), nullable=False),
            sa.Column("verification_status", sa.String(30)),
            sa.Column("verified_at", sa.DateTime()),
            sa.Column("restore_test_status", sa.String(30)),
            sa.Column("restore_tested_at", sa.DateTime()),
            sa.Column("safe_details_json", sa.Text(), nullable=False),
            sa.Column("created_at", sa.DateTime(), nullable=False),
            sa.Column("updated_at", sa.DateTime(), nullable=False),
            sa.CheckConstraint(
                "backup_type IN ('postgresql','uploads')", name="ck_backup_records_type"
            ),
            sa.CheckConstraint(
                "status IN ('creating','valid','invalid','warning','failed')",
                name="ck_backup_records_status",
            ),
            sa.CheckConstraint("size_bytes >= 0", name="ck_backup_records_size"),
        )
        for column in (
            "backup_set_id",
            "backup_type",
            "status",
            "verification_status",
            "verified_at",
            "restore_test_status",
            "restore_tested_at",
            "created_at",
        ):
            op.create_index(f"ix_backup_records_{column}", "backup_records", [column])


def downgrade() -> None:
    tables = set(inspect(op.get_bind()).get_table_names())
    if "backup_records" in tables:
        op.drop_table("backup_records")
    if "operational_states" in tables:
        op.drop_table("operational_states")
    for table_name, index_name in (
        ("channel_outbox_messages", "ix_channel_outbox_messages_request_id"),
        ("webhook_inbox_events", "ix_webhook_inbox_events_request_id"),
    ):
        columns = {item["name"] for item in inspect(op.get_bind()).get_columns(table_name)}
        if "request_id" in columns:
            with op.batch_alter_table(table_name) as batch_op:
                indexes = {item["name"] for item in inspect(op.get_bind()).get_indexes(table_name)}
                if index_name in indexes:
                    batch_op.drop_index(index_name)
                batch_op.drop_column("request_id")
