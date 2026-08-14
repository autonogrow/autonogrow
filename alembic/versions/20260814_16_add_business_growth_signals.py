"""add business growth signals and calendar events

Revision ID: 20260814_16
Revises: 20260814_15
Create Date: 2026-08-14
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260814_16"
down_revision: str | Sequence[str] | None = "20260814_15"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    tables = set(inspector.get_table_names())
    if {"business_calendar_events", "business_growth_signals"}.issubset(tables):
        return

    op.create_table(
        "business_calendar_events",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("business_id", sa.Integer(), nullable=False),
        sa.Column("title", sa.String(length=200), nullable=False),
        sa.Column("starts_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("ends_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("category", sa.String(length=80)),
        sa.Column("service_id", sa.Integer()),
        sa.Column("enabled", sa.Boolean(), server_default=sa.text("true"), nullable=False),
        sa.Column(
            "yearly_recurrence", sa.Boolean(), server_default=sa.text("false"), nullable=False
        ),
        sa.Column("created_by_user_id", sa.Integer()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "ends_at > starts_at", name="ck_business_calendar_events_period"
        ),
        sa.CheckConstraint(
            "length(trim(title)) > 0", name="ck_business_calendar_events_title"
        ),
        sa.ForeignKeyConstraint(["business_id"], ["businesses.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["service_id"], ["services.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(
            ["created_by_user_id"], ["users.id"], ondelete="SET NULL"
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_business_calendar_events_business_enabled_start",
        "business_calendar_events",
        ["business_id", "enabled", "starts_at"],
    )
    for column in ("business_id", "starts_at", "service_id", "created_by_user_id"):
        op.create_index(
            f"ix_business_calendar_events_{column}", "business_calendar_events", [column]
        )

    op.create_table(
        "business_growth_signals",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("business_id", sa.Integer(), nullable=False),
        sa.Column("type", sa.String(length=50), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("severity", sa.String(length=20), nullable=False),
        sa.Column("scope_type", sa.String(length=20), nullable=False),
        sa.Column("service_id", sa.Integer()),
        sa.Column("calendar_event_id", sa.Integer()),
        sa.Column("detected_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("period_start", sa.DateTime(timezone=True), nullable=False),
        sa.Column("period_end", sa.DateTime(timezone=True), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True)),
        sa.Column("resolved_at", sa.DateTime(timezone=True)),
        sa.Column("dismissed_at", sa.DateTime(timezone=True)),
        sa.Column("last_evaluated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("reason_code", sa.String(length=100), nullable=False),
        sa.Column("explanation_json", sa.Text(), nullable=False),
        sa.Column("observed_json", sa.Text(), nullable=False),
        sa.Column("baseline_json", sa.Text()),
        sa.Column("recommendation_code", sa.String(length=80), nullable=False),
        sa.Column("dedupe_key", sa.String(length=255), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "type IN ('low_future_occupancy','high_due_customer_pool',"
            "'low_return_rate','service_demand_drop','seasonal_window')",
            name="ck_business_growth_signals_type",
        ),
        sa.CheckConstraint(
            "status IN ('active','dismissed','resolved','expired')",
            name="ck_business_growth_signals_status",
        ),
        sa.CheckConstraint(
            "severity IN ('info','low','medium','high')",
            name="ck_business_growth_signals_severity",
        ),
        sa.CheckConstraint(
            "scope_type IN ('business','service')",
            name="ck_business_growth_signals_scope",
        ),
        sa.CheckConstraint(
            "period_end > period_start", name="ck_business_growth_signals_period"
        ),
        sa.ForeignKeyConstraint(["business_id"], ["businesses.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["service_id"], ["services.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(
            ["calendar_event_id"], ["business_calendar_events.id"], ondelete="SET NULL"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "business_id", "dedupe_key", name="uq_business_growth_signal_dedupe"
        ),
    )
    op.create_index(
        "ix_business_growth_signals_business_status_severity",
        "business_growth_signals",
        ["business_id", "status", "severity"],
    )
    op.create_index(
        "ix_business_growth_signals_business_type_period",
        "business_growth_signals",
        ["business_id", "type", "period_start", "period_end"],
    )
    for column in (
        "business_id",
        "type",
        "status",
        "severity",
        "service_id",
        "calendar_event_id",
        "period_start",
        "period_end",
        "expires_at",
    ):
        op.create_index(
            f"ix_business_growth_signals_{column}", "business_growth_signals", [column]
        )


def downgrade() -> None:
    op.drop_table("business_growth_signals")
    op.drop_table("business_calendar_events")
