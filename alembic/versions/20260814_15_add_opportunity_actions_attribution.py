"""add opportunity actions and booking attribution

Revision ID: 20260814_15
Revises: 20260814_14
Create Date: 2026-08-14
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260814_15"
down_revision: str | Sequence[str] | None = "20260814_14"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    tables = set(inspector.get_table_names())
    booking_columns = (
        {column["name"] for column in inspector.get_columns("bookings")}
        if "bookings" in tables
        else set()
    )
    if {"opportunity_actions", "booking_attributions"}.issubset(tables) and {
        "price_amount_snapshot",
        "currency_snapshot",
    }.issubset(booking_columns):
        return

    with op.batch_alter_table("bookings") as batch_op:
        batch_op.add_column(sa.Column("price_amount_snapshot", sa.Numeric(12, 2)))
        batch_op.add_column(sa.Column("currency_snapshot", sa.String(length=3)))
        batch_op.create_check_constraint(
            "ck_bookings_price_snapshot_nonnegative",
            "price_amount_snapshot IS NULL OR price_amount_snapshot >= 0",
        )

    op.create_table(
        "opportunity_actions",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("business_id", sa.Integer(), nullable=False),
        sa.Column("opportunity_id", sa.Integer(), nullable=False),
        sa.Column("customer_id", sa.Integer(), nullable=False),
        sa.Column("action_type", sa.String(length=40), nullable=False),
        sa.Column("status", sa.String(length=30), nullable=False),
        sa.Column("channel", sa.String(length=30)),
        sa.Column("conversation_id", sa.Integer()),
        sa.Column("message_id", sa.Integer()),
        sa.Column("booking_id", sa.Integer()),
        sa.Column("suggested_text", sa.Text()),
        sa.Column("final_text", sa.Text()),
        sa.Column("created_by_user_id", sa.Integer()),
        sa.Column("last_edited_by_user_id", sa.Integer()),
        sa.Column("approved_by_user_id", sa.Integer()),
        sa.Column("sent_by_user_id", sa.Integer()),
        sa.Column("approved_at", sa.DateTime(timezone=True)),
        sa.Column("sent_at", sa.DateTime(timezone=True)),
        sa.Column("failed_at", sa.DateTime(timezone=True)),
        sa.Column("cancelled_at", sa.DateTime(timezone=True)),
        sa.Column("completed_at", sa.DateTime(timezone=True)),
        sa.Column("expires_at", sa.DateTime(timezone=True)),
        sa.Column("failure_reason", sa.String(length=500)),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "action_type IN ('contact_customer','mark_handled','open_conversation')",
            name="ck_opportunity_actions_type",
        ),
        sa.CheckConstraint(
            "status IN ('draft','approved','sending','sent','failed','cancelled','completed')",
            name="ck_opportunity_actions_status",
        ),
        sa.CheckConstraint(
            "channel IS NULL OR channel IN ('whatsapp','instagram')",
            name="ck_opportunity_actions_channel",
        ),
        sa.ForeignKeyConstraint(["business_id"], ["businesses.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["opportunity_id"], ["customer_opportunities.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(["customer_id"], ["customers.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["conversation_id"], ["conversations.id"], ondelete="SET NULL"
        ),
        sa.ForeignKeyConstraint(
            ["message_id"], ["conversation_messages.id"], ondelete="SET NULL"
        ),
        sa.ForeignKeyConstraint(["booking_id"], ["bookings.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(
            ["created_by_user_id"], ["users.id"], ondelete="SET NULL"
        ),
        sa.ForeignKeyConstraint(
            ["last_edited_by_user_id"], ["users.id"], ondelete="SET NULL"
        ),
        sa.ForeignKeyConstraint(
            ["approved_by_user_id"], ["users.id"], ondelete="SET NULL"
        ),
        sa.ForeignKeyConstraint(["sent_by_user_id"], ["users.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "business_id",
            "opportunity_id",
            "action_type",
            name="uq_opportunity_action_conservative_dedupe",
        ),
        sa.UniqueConstraint("message_id", name="uq_opportunity_action_message"),
    )
    op.create_index(
        "ix_opportunity_actions_business_status_created",
        "opportunity_actions",
        ["business_id", "status", "created_at"],
    )
    op.create_index(
        "ix_opportunity_actions_opportunity_created",
        "opportunity_actions",
        ["opportunity_id", "created_at"],
    )
    for column in (
        "business_id",
        "opportunity_id",
        "customer_id",
        "action_type",
        "status",
        "channel",
        "conversation_id",
        "message_id",
        "booking_id",
        "created_by_user_id",
        "last_edited_by_user_id",
        "approved_by_user_id",
        "sent_by_user_id",
        "expires_at",
    ):
        op.create_index(f"ix_opportunity_actions_{column}", "opportunity_actions", [column])

    op.create_table(
        "booking_attributions",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("business_id", sa.Integer(), nullable=False),
        sa.Column("opportunity_id", sa.Integer(), nullable=False),
        sa.Column("action_id", sa.Integer(), nullable=False),
        sa.Column("booking_id", sa.Integer(), nullable=False),
        sa.Column("method", sa.String(length=40), nullable=False),
        sa.Column("price_amount_snapshot", sa.Numeric(12, 2)),
        sa.Column("currency_snapshot", sa.String(length=3)),
        sa.Column("attributed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True)),
        sa.Column("created_by_user_id", sa.Integer()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "method IN ('direct_link','post_action_window','manual')",
            name="ck_booking_attributions_method",
        ),
        sa.CheckConstraint(
            "price_amount_snapshot IS NULL OR price_amount_snapshot >= 0",
            name="ck_booking_attributions_price_nonnegative",
        ),
        sa.ForeignKeyConstraint(["business_id"], ["businesses.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["opportunity_id"], ["customer_opportunities.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["action_id"], ["opportunity_actions.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(["booking_id"], ["bookings.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["created_by_user_id"], ["users.id"], ondelete="SET NULL"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("action_id", name="uq_booking_attribution_action"),
        sa.UniqueConstraint("booking_id", name="uq_booking_attribution_booking"),
    )
    op.create_index(
        "ix_booking_attributions_business_created",
        "booking_attributions",
        ["business_id", "attributed_at"],
    )
    op.create_index(
        "ix_booking_attributions_opportunity",
        "booking_attributions",
        ["opportunity_id", "attributed_at"],
    )
    for column in (
        "business_id",
        "opportunity_id",
        "action_id",
        "booking_id",
        "method",
        "attributed_at",
        "completed_at",
        "created_by_user_id",
    ):
        op.create_index(
            f"ix_booking_attributions_{column}", "booking_attributions", [column]
        )


def downgrade() -> None:
    op.drop_table("booking_attributions")
    op.drop_table("opportunity_actions")
    with op.batch_alter_table("bookings") as batch_op:
        batch_op.drop_constraint("ck_bookings_price_snapshot_nonnegative", type_="check")
        batch_op.drop_column("currency_snapshot")
        batch_op.drop_column("price_amount_snapshot")
