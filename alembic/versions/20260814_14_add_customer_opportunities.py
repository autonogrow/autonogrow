"""add customer opportunities growth engine

Revision ID: 20260814_14
Revises: 20260806_13
Create Date: 2026-08-14
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260814_14"
down_revision: str | Sequence[str] | None = "20260806_13"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # Legacy local databases may be stamped at the baseline after create_all() built
    # the current model schema. Preserve that supported migration path.
    inspector = sa.inspect(op.get_bind())
    tables = set(inspector.get_table_names())
    service_columns = (
        {column["name"] for column in inspector.get_columns("services")}
        if "services" in tables
        else set()
    )
    booking_columns = (
        {column["name"] for column in inspector.get_columns("bookings")}
        if "bookings" in tables
        else set()
    )
    if {
        "customer_opportunities",
        "scheduled_customer_followups",
    }.issubset(tables) and {
        "follow_up_enabled",
        "follow_up_interval_days",
        "follow_up_window_days",
    }.issubset(service_columns) and {
        "follow_up_enabled_snapshot",
        "follow_up_interval_days_snapshot",
        "follow_up_window_days_snapshot",
    }.issubset(booking_columns):
        return

    with op.batch_alter_table("services") as batch_op:
        batch_op.drop_constraint("ck_services_onboarding_values", type_="check")
        batch_op.add_column(
            sa.Column(
                "follow_up_enabled",
                sa.Boolean(),
                server_default=sa.text("false"),
                nullable=False,
            )
        )
        batch_op.add_column(sa.Column("follow_up_interval_days", sa.Integer(), nullable=True))
        batch_op.add_column(
            sa.Column(
                "follow_up_window_days", sa.Integer(), server_default="0", nullable=False
            )
        )
        batch_op.create_check_constraint(
            "ck_services_onboarding_values",
            "(duration_minutes IS NULL OR duration_minutes > 0) AND "
            "(price_amount IS NULL OR price_amount >= 0) AND "
            "buffer_before_minutes >= 0 AND buffer_after_minutes >= 0 AND position >= 0 AND "
            "(follow_up_interval_days IS NULL OR follow_up_interval_days > 0) AND "
            "follow_up_window_days >= 0 AND "
            "(follow_up_enabled = false OR follow_up_interval_days IS NOT NULL)",
        )

    with op.batch_alter_table("bookings") as batch_op:
        batch_op.add_column(
            sa.Column(
                "follow_up_enabled_snapshot",
                sa.Boolean(),
                server_default=sa.text("false"),
                nullable=False,
            )
        )
        batch_op.add_column(
            sa.Column("follow_up_interval_days_snapshot", sa.Integer(), nullable=True)
        )
        batch_op.add_column(
            sa.Column("follow_up_window_days_snapshot", sa.Integer(), nullable=True)
        )
        batch_op.create_check_constraint(
            "ck_bookings_follow_up_snapshot",
            "(follow_up_interval_days_snapshot IS NULL OR "
            "follow_up_interval_days_snapshot > 0) AND "
            "(follow_up_window_days_snapshot IS NULL OR "
            "follow_up_window_days_snapshot >= 0)",
        )

    op.create_table(
        "scheduled_customer_followups",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("business_id", sa.Integer(), nullable=False),
        sa.Column("customer_id", sa.Integer(), nullable=False),
        sa.Column("booking_id", sa.Integer(), nullable=True),
        sa.Column("service_id", sa.Integer(), nullable=True),
        sa.Column("created_by_user_id", sa.Integer(), nullable=True),
        sa.Column("due_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("status", sa.String(length=30), nullable=False),
        sa.Column("note", sa.String(length=500), nullable=True),
        sa.Column("dedupe_key", sa.String(length=255), nullable=False),
        sa.Column("cancelled_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("converted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "status IN ('scheduled','cancelled','converted')",
            name="ck_scheduled_customer_followups_status",
        ),
        sa.ForeignKeyConstraint(["booking_id"], ["bookings.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["business_id"], ["businesses.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["created_by_user_id"], ["users.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["customer_id"], ["customers.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["service_id"], ["services.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("business_id", "dedupe_key", name="uq_followup_business_dedupe"),
    )
    op.create_index(
        "ix_scheduled_followups_business_status_due",
        "scheduled_customer_followups",
        ["business_id", "status", "due_at"],
    )
    for column in ("business_id", "customer_id", "booking_id", "service_id", "created_by_user_id", "due_at", "status"):
        op.create_index(
            f"ix_scheduled_customer_followups_{column}",
            "scheduled_customer_followups",
            [column],
        )

    op.create_table(
        "customer_opportunities",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("business_id", sa.Integer(), nullable=False),
        sa.Column("customer_id", sa.Integer(), nullable=False),
        sa.Column("type", sa.String(length=50), nullable=False),
        sa.Column("status", sa.String(length=30), nullable=False),
        sa.Column("priority", sa.String(length=20), nullable=False),
        sa.Column("detected_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("due_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("actioned_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("resolved_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("dismissed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("source_booking_id", sa.Integer(), nullable=True),
        sa.Column("source_service_id", sa.Integer(), nullable=True),
        sa.Column("source_conversation_id", sa.Integer(), nullable=True),
        sa.Column("scheduled_followup_id", sa.Integer(), nullable=True),
        sa.Column("reason_code", sa.String(length=100), nullable=False),
        sa.Column("reason_text", sa.Text(), nullable=False),
        sa.Column("dedupe_key", sa.String(length=255), nullable=False),
        sa.Column("source_occurred_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("follow_up_interval_days_snapshot", sa.Integer(), nullable=True),
        sa.Column("follow_up_window_days_snapshot", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "type IN ('cancelled_not_rebooked','no_show_not_rebooked',"
            "'lead_not_converted','service_due','scheduled_followup')",
            name="ck_customer_opportunities_type",
        ),
        sa.CheckConstraint(
            "status IN ('pending','actioned','dismissed','resolved','expired')",
            name="ck_customer_opportunities_status",
        ),
        sa.CheckConstraint(
            "priority IN ('low','normal','high')",
            name="ck_customer_opportunities_priority",
        ),
        sa.CheckConstraint(
            "follow_up_interval_days_snapshot IS NULL OR "
            "follow_up_interval_days_snapshot > 0",
            name="ck_customer_opportunities_interval_positive",
        ),
        sa.CheckConstraint(
            "follow_up_window_days_snapshot IS NULL OR "
            "follow_up_window_days_snapshot >= 0",
            name="ck_customer_opportunities_window_nonnegative",
        ),
        sa.ForeignKeyConstraint(["business_id"], ["businesses.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["customer_id"], ["customers.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["scheduled_followup_id"], ["scheduled_customer_followups.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["source_booking_id"], ["bookings.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["source_conversation_id"], ["conversations.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["source_service_id"], ["services.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("business_id", "dedupe_key", name="uq_opportunity_business_dedupe"),
        sa.UniqueConstraint(
            "scheduled_followup_id", name="uq_customer_opportunity_scheduled_followup"
        ),
    )
    op.create_index(
        "ix_customer_opportunities_business_status_due",
        "customer_opportunities",
        ["business_id", "status", "due_at"],
    )
    op.create_index(
        "ix_customer_opportunities_business_customer",
        "customer_opportunities",
        ["business_id", "customer_id"],
    )
    for column in (
        "business_id",
        "customer_id",
        "type",
        "status",
        "due_at",
        "expires_at",
        "source_booking_id",
        "source_service_id",
        "source_conversation_id",
        "scheduled_followup_id",
    ):
        op.create_index(
            f"ix_customer_opportunities_{column}", "customer_opportunities", [column]
        )


def downgrade() -> None:
    op.drop_table("customer_opportunities")
    op.drop_table("scheduled_customer_followups")
    with op.batch_alter_table("bookings") as batch_op:
        batch_op.drop_constraint("ck_bookings_follow_up_snapshot", type_="check")
        batch_op.drop_column("follow_up_window_days_snapshot")
        batch_op.drop_column("follow_up_interval_days_snapshot")
        batch_op.drop_column("follow_up_enabled_snapshot")
    with op.batch_alter_table("services") as batch_op:
        batch_op.drop_constraint("ck_services_onboarding_values", type_="check")
        batch_op.drop_column("follow_up_window_days")
        batch_op.drop_column("follow_up_interval_days")
        batch_op.drop_column("follow_up_enabled")
        batch_op.create_check_constraint(
            "ck_services_onboarding_values",
            "(duration_minutes IS NULL OR duration_minutes > 0) AND "
            "(price_amount IS NULL OR price_amount >= 0) AND "
            "buffer_before_minutes >= 0 AND buffer_after_minutes >= 0 AND position >= 0",
        )
