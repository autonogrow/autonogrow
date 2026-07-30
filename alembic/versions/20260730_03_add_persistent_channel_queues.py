"""add persistent channel queues

Revision ID: 20260730_03
Revises: 20260730_02
Create Date: 2026-07-30
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260730_03"
down_revision: str | Sequence[str] | None = "20260730_02"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "webhook_inbox_events",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("provider", sa.String(40), nullable=False),
        sa.Column("channel", sa.String(40), nullable=False),
        sa.Column("event_type", sa.String(80)),
        sa.Column("provider_event_id", sa.String(255)),
        sa.Column("idempotency_key", sa.String(255), nullable=False),
        sa.Column("payload_hash", sa.String(64), nullable=False),
        sa.Column("payload_json", sa.Text(), nullable=False),
        sa.Column("payload_size_bytes", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(30), nullable=False),
        sa.Column("attempt_count", sa.Integer(), nullable=False),
        sa.Column("max_attempts", sa.Integer(), nullable=False),
        sa.Column("received_at", sa.DateTime(), nullable=False),
        sa.Column("available_at", sa.DateTime(), nullable=False),
        sa.Column("processing_started_at", sa.DateTime()),
        sa.Column("processed_at", sa.DateTime()),
        sa.Column("failed_at", sa.DateTime()),
        sa.Column("next_retry_at", sa.DateTime()),
        sa.Column("locked_by", sa.String(200)),
        sa.Column("lock_expires_at", sa.DateTime()),
        sa.Column("business_id", sa.Integer()),
        sa.Column("integration_id", sa.Integer()),
        sa.Column("last_error_code", sa.String(120)),
        sa.Column("safe_error_message", sa.String(500)),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.CheckConstraint("attempt_count >= 0", name="ck_webhook_inbox_attempt_count"),
        sa.CheckConstraint("max_attempts > 0", name="ck_webhook_inbox_max_attempts"),
        sa.CheckConstraint("payload_size_bytes >= 0", name="ck_webhook_inbox_payload_size"),
        sa.CheckConstraint(
            "status IN ('pending','processing','processed','retry','ignored','failed','dead_letter','cancelled')",
            name="ck_webhook_inbox_status",
        ),
        sa.ForeignKeyConstraint(["business_id"], ["businesses.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(
            ["integration_id"], ["business_channel_integrations.id"], ondelete="SET NULL"
        ),
        sa.UniqueConstraint("idempotency_key", name="uq_webhook_inbox_idempotency_key"),
    )
    op.create_index(
        "ix_webhook_inbox_status_available", "webhook_inbox_events", ["status", "available_at"]
    )
    op.create_index(
        "ix_webhook_inbox_status_retry", "webhook_inbox_events", ["status", "next_retry_at"]
    )
    op.create_index(
        "ix_webhook_inbox_provider_event", "webhook_inbox_events", ["provider", "provider_event_id"]
    )
    for column in ("business_id", "integration_id", "lock_expires_at", "received_at"):
        op.create_index(f"ix_webhook_inbox_events_{column}", "webhook_inbox_events", [column])

    op.create_table(
        "channel_outbox_messages",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("business_id", sa.Integer(), nullable=False),
        sa.Column("integration_id", sa.Integer(), nullable=False),
        sa.Column("conversation_id", sa.Integer(), nullable=False),
        sa.Column("conversation_message_id", sa.Integer()),
        sa.Column("channel", sa.String(40), nullable=False),
        sa.Column("provider", sa.String(40), nullable=False),
        sa.Column("recipient_external_id", sa.String(255), nullable=False),
        sa.Column("payload_json", sa.Text(), nullable=False),
        sa.Column("idempotency_key", sa.String(255), nullable=False),
        sa.Column("status", sa.String(30), nullable=False),
        sa.Column("attempt_count", sa.Integer(), nullable=False),
        sa.Column("max_attempts", sa.Integer(), nullable=False),
        sa.Column("available_at", sa.DateTime(), nullable=False),
        sa.Column("processing_started_at", sa.DateTime()),
        sa.Column("sent_at", sa.DateTime()),
        sa.Column("failed_at", sa.DateTime()),
        sa.Column("next_retry_at", sa.DateTime()),
        sa.Column("locked_by", sa.String(200)),
        sa.Column("lock_expires_at", sa.DateTime()),
        sa.Column("provider_message_id", sa.String(255)),
        sa.Column("last_http_status", sa.Integer()),
        sa.Column("last_error_code", sa.String(120)),
        sa.Column("last_error_subcode", sa.String(120)),
        sa.Column("last_error_type", sa.String(120)),
        sa.Column("safe_error_message", sa.String(500)),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.CheckConstraint("attempt_count >= 0", name="ck_channel_outbox_attempt_count"),
        sa.CheckConstraint("max_attempts > 0", name="ck_channel_outbox_max_attempts"),
        sa.CheckConstraint(
            "status IN ('pending','processing','sent','retry','blocked','failed','dead_letter','cancelled')",
            name="ck_channel_outbox_status",
        ),
        sa.ForeignKeyConstraint(["business_id"], ["businesses.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["integration_id"], ["business_channel_integrations.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(["conversation_id"], ["conversations.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["conversation_message_id"], ["conversation_messages.id"], ondelete="SET NULL"
        ),
        sa.UniqueConstraint(
            "conversation_message_id", name="uq_channel_outbox_conversation_message_id"
        ),
        sa.UniqueConstraint("idempotency_key", name="uq_channel_outbox_idempotency_key"),
    )
    op.create_index(
        "ix_channel_outbox_status_available", "channel_outbox_messages", ["status", "available_at"]
    )
    op.create_index(
        "ix_channel_outbox_status_retry", "channel_outbox_messages", ["status", "next_retry_at"]
    )
    for column in (
        "business_id",
        "integration_id",
        "conversation_id",
        "provider_message_id",
        "lock_expires_at",
        "created_at",
    ):
        op.create_index(f"ix_channel_outbox_messages_{column}", "channel_outbox_messages", [column])

    op.create_table(
        "worker_heartbeats",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("worker_id", sa.String(200), nullable=False),
        sa.Column("worker_type", sa.String(80), nullable=False),
        sa.Column("status", sa.String(30), nullable=False),
        sa.Column("started_at", sa.DateTime(), nullable=False),
        sa.Column("last_seen_at", sa.DateTime(), nullable=False),
        sa.Column("current_job_type", sa.String(40)),
        sa.Column("current_job_id", sa.Integer()),
        sa.Column("version", sa.String(80)),
        sa.Column("hostname", sa.String(255)),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.CheckConstraint(
            "status IN ('starting','idle','processing','stopping','stopped','error')",
            name="ck_worker_heartbeat_status",
        ),
        sa.UniqueConstraint("worker_id", name="uq_worker_heartbeats_worker_id"),
    )


def downgrade() -> None:
    op.drop_table("worker_heartbeats")
    op.drop_table("channel_outbox_messages")
    op.drop_table("webhook_inbox_events")
