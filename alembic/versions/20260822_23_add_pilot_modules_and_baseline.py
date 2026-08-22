"""add pilot module access, configurable costs and optional baseline

Revision ID: 20260822_23
Revises: 20260821_22
Create Date: 2026-08-22
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260822_23"
down_revision: str | Sequence[str] | None = "20260821_22"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    bind = op.get_bind()
    existing_tables = set(sa.inspect(bind).get_table_names())
    if "business_module_access" not in existing_tables:
        op.create_table(
            "business_module_access",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("business_id", sa.Integer(), nullable=False),
            sa.Column("module_key", sa.String(30), nullable=False),
            sa.Column("entitled", sa.Boolean(), nullable=False, server_default=sa.true()),
            sa.Column("active", sa.Boolean(), nullable=False, server_default=sa.true()),
            sa.Column("module_cost_amount", sa.Numeric(12, 2), nullable=True),
            sa.Column("module_cost_currency", sa.String(3), nullable=True),
            sa.Column(
                "module_cost_period", sa.String(20), nullable=False, server_default="monthly"
            ),
            sa.Column("updated_by_user_id", sa.Integer(), nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
            sa.CheckConstraint(
                "module_key IN ('essential','growth','social')",
                name="ck_business_module_access_key",
            ),
            sa.CheckConstraint(
                "module_cost_amount IS NULL OR module_cost_amount >= 0",
                name="ck_business_module_access_cost_nonnegative",
            ),
            sa.CheckConstraint(
                "module_cost_period IN ('monthly')",
                name="ck_business_module_access_cost_period",
            ),
            sa.ForeignKeyConstraint(["business_id"], ["businesses.id"], ondelete="CASCADE"),
            sa.ForeignKeyConstraint(["updated_by_user_id"], ["users.id"], ondelete="SET NULL"),
            sa.UniqueConstraint("business_id", "module_key", name="uq_business_module_access"),
        )
        op.create_index(
            "ix_business_module_access_business_id", "business_module_access", ["business_id"]
        )
        op.create_index(
            "ix_business_module_access_module_key", "business_module_access", ["module_key"]
        )
        op.create_index(
            "ix_business_module_access_updated_by_user_id",
            "business_module_access",
            ["updated_by_user_id"],
        )
        op.create_index(
            "ix_business_module_access_business_active",
            "business_module_access",
            ["business_id", "active"],
        )

    access = sa.table(
        "business_module_access",
        sa.column("business_id", sa.Integer()),
        sa.column("module_key", sa.String()),
        sa.column("entitled", sa.Boolean()),
        sa.column("active", sa.Boolean()),
        sa.column("module_cost_period", sa.String()),
        sa.column("created_at", sa.DateTime(timezone=True)),
        sa.column("updated_at", sa.DateTime(timezone=True)),
    )
    businesses = sa.table("businesses", sa.column("id", sa.Integer()))
    for module_key in ("essential", "growth", "social"):
        missing_access = ~sa.exists(
            sa.select(1)
            .select_from(access)
            .where(
                access.c.business_id == businesses.c.id,
                access.c.module_key == module_key,
            )
        )
        bind.execute(
            sa.insert(access).from_select(
                [
                    "business_id",
                    "module_key",
                    "entitled",
                    "active",
                    "module_cost_period",
                    "created_at",
                    "updated_at",
                ],
                sa.select(
                    businesses.c.id,
                    sa.literal(module_key),
                    sa.true(),
                    sa.true(),
                    sa.literal("monthly"),
                    sa.func.current_timestamp(),
                    sa.func.current_timestamp(),
                ).where(missing_access),
            )
        )

    if "pilot_baselines" not in existing_tables:
        op.create_table(
            "pilot_baselines",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("business_id", sa.Integer(), nullable=False),
            sa.Column("monthly_bookings", sa.Integer(), nullable=True),
            sa.Column("average_ticket", sa.Numeric(12, 2), nullable=True),
            sa.Column("occupancy_percentage", sa.Numeric(5, 2), nullable=True),
            sa.Column("recurring_customer_percentage", sa.Numeric(5, 2), nullable=True),
            sa.Column("cancellation_percentage", sa.Numeric(5, 2), nullable=True),
            sa.Column("no_show_percentage", sa.Numeric(5, 2), nullable=True),
            sa.Column("currency", sa.String(3), nullable=False, server_default="EUR"),
            sa.Column("notes", sa.Text(), nullable=True),
            sa.Column("captured_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("updated_by_user_id", sa.Integer(), nullable=True),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
            sa.CheckConstraint(
                "monthly_bookings IS NULL OR monthly_bookings >= 0",
                name="ck_pilot_baselines_bookings_nonnegative",
            ),
            sa.CheckConstraint(
                "average_ticket IS NULL OR average_ticket >= 0",
                name="ck_pilot_baselines_ticket_nonnegative",
            ),
            sa.CheckConstraint(
                "occupancy_percentage IS NULL OR "
                "(occupancy_percentage >= 0 AND occupancy_percentage <= 100)",
                name="ck_pilot_baselines_occupancy_range",
            ),
            sa.CheckConstraint(
                "recurring_customer_percentage IS NULL OR "
                "(recurring_customer_percentage >= 0 AND recurring_customer_percentage <= 100)",
                name="ck_pilot_baselines_recurrence_range",
            ),
            sa.CheckConstraint(
                "cancellation_percentage IS NULL OR "
                "(cancellation_percentage >= 0 AND cancellation_percentage <= 100)",
                name="ck_pilot_baselines_cancellation_range",
            ),
            sa.CheckConstraint(
                "no_show_percentage IS NULL OR "
                "(no_show_percentage >= 0 AND no_show_percentage <= 100)",
                name="ck_pilot_baselines_no_show_range",
            ),
            sa.ForeignKeyConstraint(["business_id"], ["businesses.id"], ondelete="CASCADE"),
            sa.ForeignKeyConstraint(["updated_by_user_id"], ["users.id"], ondelete="SET NULL"),
            sa.UniqueConstraint("business_id", name="uq_pilot_baselines_business"),
        )
        op.create_index(
            "ix_pilot_baselines_updated_by_user_id", "pilot_baselines", ["updated_by_user_id"]
        )


def downgrade() -> None:
    op.drop_table("pilot_baselines")
    op.drop_table("business_module_access")
