"""add owner channel controls and guided simulated onboarding

Revision ID: 20260802_07
Revises: 20260730_06
Create Date: 2026-08-02
"""

from collections.abc import Sequence
from datetime import datetime, timezone

import sqlalchemy as sa
from alembic import op
from sqlalchemy import inspect

revision: str = "20260802_07"
down_revision: str | Sequence[str] | None = "20260730_06"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _backfill_existing_integrations() -> None:
    connection = op.get_bind()
    tables = set(inspect(connection).get_table_names())
    if "business_channel_integrations" not in tables:
        return

    integrations = sa.table(
        "business_channel_integrations",
        sa.column("id", sa.Integer()),
        sa.column("business_id", sa.Integer()),
        sa.column("channel", sa.String()),
        sa.column("integration_status", sa.String()),
        sa.column("connected_at", sa.DateTime(timezone=True)),
        sa.column("created_at", sa.DateTime()),
        sa.column("updated_at", sa.DateTime()),
    )
    controls = sa.table(
        "business_channel_controls",
        sa.column("business_id", sa.Integer()),
        sa.column("channel", sa.String()),
        sa.column("status", sa.String()),
        sa.column("connector_policy", sa.String()),
        sa.column("connection_mode", sa.String()),
        sa.column("integrated_delivery_enabled", sa.Boolean()),
        sa.column("automation_enabled", sa.Boolean()),
        sa.column("approved_at", sa.DateTime(timezone=True)),
        sa.column("created_at", sa.DateTime()),
        sa.column("updated_at", sa.DateTime()),
    )
    settings_by_business: dict[int, dict] = {}
    if "conversation_automation_settings" in tables:
        automation_settings = sa.table(
            "conversation_automation_settings",
            sa.column("business_id", sa.Integer()),
            sa.column("automation_enabled", sa.Boolean()),
            sa.column("automation_feature_enabled", sa.Boolean()),
            sa.column("instagram_channel_enabled", sa.Boolean()),
            sa.column("whatsapp_channel_enabled", sa.Boolean()),
        )
        settings_by_business = {
            row["business_id"]: dict(row)
            for row in connection.execute(sa.select(automation_settings)).mappings()
        }

    seen: set[tuple[int, str]] = set()
    now = datetime.now(timezone.utc)
    rows = connection.execute(sa.select(integrations).order_by(integrations.c.id)).mappings()
    for row in rows:
        channel = row["channel"]
        key = (row["business_id"], channel)
        if channel not in {"instagram", "whatsapp"} or key in seen:
            continue
        seen.add(key)
        integration_status = row["integration_status"]
        approved = integration_status in {"connected", "degraded"}
        status = (
            "approved"
            if approved
            else ("pending_approval" if integration_status == "pending" else "available")
        )
        settings = settings_by_business.get(row["business_id"], {})
        channel_in_plan = bool(settings.get(f"{channel}_channel_enabled", True))
        delivery_enabled = approved and channel_in_plan
        automation_enabled = bool(
            delivery_enabled
            and settings.get("automation_feature_enabled", False)
            and settings.get("automation_enabled", False)
        )
        connection.execute(
            sa.insert(controls).values(
                business_id=row["business_id"],
                channel=channel,
                status=status,
                connector_policy="owner_only",
                connection_mode="legacy",
                integrated_delivery_enabled=delivery_enabled,
                automation_enabled=automation_enabled,
                approved_at=row["connected_at"] if approved else None,
                created_at=row["created_at"] or now,
                updated_at=row["updated_at"] or now,
            )
        )


def upgrade() -> None:
    tables = set(inspect(op.get_bind()).get_table_names())
    if "business_channel_controls" in tables:
        return
    op.create_table(
        "business_channel_controls",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("business_id", sa.Integer(), nullable=False),
        sa.Column("channel", sa.String(40), nullable=False),
        sa.Column("status", sa.String(30), nullable=False),
        sa.Column("connector_policy", sa.String(30), nullable=False),
        sa.Column("connection_mode", sa.String(30), nullable=False),
        sa.Column("integrated_delivery_enabled", sa.Boolean(), nullable=False),
        sa.Column("automation_enabled", sa.Boolean(), nullable=False),
        sa.Column("requested_by_user_id", sa.Integer()),
        sa.Column("requested_at", sa.DateTime(timezone=True)),
        sa.Column("approved_by_user_id", sa.Integer()),
        sa.Column("approved_at", sa.DateTime(timezone=True)),
        sa.Column("suspended_at", sa.DateTime(timezone=True)),
        sa.Column("revoked_at", sa.DateTime(timezone=True)),
        sa.Column("last_reason", sa.String(500)),
        sa.Column("created_by_user_id", sa.Integer()),
        sa.Column("updated_by_user_id", sa.Integer()),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.CheckConstraint(
            "channel IN ('instagram','whatsapp')",
            name="ck_business_channel_control_channel",
        ),
        sa.CheckConstraint(
            "status IN ('available','pending_approval','approved','suspended','revoked')",
            name="ck_business_channel_control_status",
        ),
        sa.CheckConstraint(
            "connector_policy IN ('business_admin','owner_only')",
            name="ck_business_channel_control_connector_policy",
        ),
        sa.CheckConstraint(
            "connection_mode IN ('simulated','legacy')",
            name="ck_business_channel_control_connection_mode",
        ),
        sa.CheckConstraint(
            "status = 'approved' OR "
            "(integrated_delivery_enabled = false AND automation_enabled = false)",
            name="ck_business_channel_control_approved_capabilities",
        ),
        sa.ForeignKeyConstraint(["business_id"], ["businesses.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["requested_by_user_id"], ["users.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["approved_by_user_id"], ["users.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["created_by_user_id"], ["users.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["updated_by_user_id"], ["users.id"], ondelete="SET NULL"),
        sa.UniqueConstraint("business_id", "channel", name="uq_business_channel_control"),
    )
    for column in (
        "business_id",
        "channel",
        "status",
        "requested_by_user_id",
        "approved_by_user_id",
        "created_by_user_id",
        "updated_by_user_id",
    ):
        op.create_index(
            f"ix_business_channel_controls_{column}",
            "business_channel_controls",
            [column],
        )
    op.create_index(
        "ix_business_channel_controls_business_status",
        "business_channel_controls",
        ["business_id", "status"],
    )
    _backfill_existing_integrations()


def downgrade() -> None:
    if "business_channel_controls" in set(inspect(op.get_bind()).get_table_names()):
        op.drop_table("business_channel_controls")
