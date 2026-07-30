"""add PostgreSQL concurrency constraints

Revision ID: 20260730_04
Revises: 20260730_03
Create Date: 2026-07-30
"""

from collections.abc import Sequence

from alembic import op
from sqlalchemy import inspect

revision: str = "20260730_04"
down_revision: str | Sequence[str] | None = "20260730_03"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _create_missing_checks(table_name: str, constraints: tuple[tuple[str, str], ...]) -> None:
    existing = {item["name"] for item in inspect(op.get_bind()).get_check_constraints(table_name)}
    with op.batch_alter_table(table_name) as batch_op:
        for name, condition in constraints:
            if name not in existing:
                batch_op.create_check_constraint(name, condition)


def upgrade() -> None:
    _create_missing_checks(
        "conversation_automation_settings",
        (
            (
                "ck_conversation_automation_included_allowance_nonnegative",
                "included_credits_per_period >= 0",
            ),
            (
                "ck_conversation_automation_included_usage",
                "included_credits_used >= 0 AND "
                "included_credits_used <= included_credits_per_period",
            ),
            (
                "ck_conversation_automation_additional_balance_nonnegative",
                "additional_credits_balance >= 0",
            ),
            (
                "ck_conversation_automation_auto_usage_nonnegative",
                "auto_used_current_period >= 0",
            ),
        ),
    )
    _create_missing_checks(
        "automation_credit_transactions",
        (
            (
                "ck_automation_credit_amount_nonnegative",
                "amount >= 0 OR transaction_type IN ('manual_adjustment','correction')",
            ),
            (
                "ck_automation_credit_included_balance_nonnegative",
                "included_balance_after >= 0",
            ),
            (
                "ck_automation_credit_additional_balance_nonnegative",
                "additional_balance_after >= 0",
            ),
            (
                "ck_automation_credit_total_balance",
                "total_balance_after >= 0 AND "
                "total_balance_after = included_balance_after + additional_balance_after",
            ),
            (
                "ck_automation_credit_payment_nonnegative",
                "payment_amount IS NULL OR payment_amount >= 0",
            ),
        ),
    )
    _create_missing_checks(
        "bookings",
        (
            (
                "ck_bookings_duration_positive",
                "duration_minutes IS NULL OR duration_minutes > 0",
            ),
            (
                "ck_bookings_datetime_order",
                "start_datetime IS NULL OR end_datetime IS NULL OR end_datetime > start_datetime",
            ),
        ),
    )
    existing_indexes = {item["name"] for item in inspect(op.get_bind()).get_indexes("bookings")}
    with op.batch_alter_table("bookings") as batch_op:
        if "ix_bookings_business_staff_start_status" not in existing_indexes:
            batch_op.create_index(
                "ix_bookings_business_staff_start_status",
                ["business_id", "staff_business_user_id", "start_datetime", "status"],
            )
        if "ix_bookings_business_start_end_status" not in existing_indexes:
            batch_op.create_index(
                "ix_bookings_business_start_end_status",
                ["business_id", "start_datetime", "end_datetime", "status"],
            )


def downgrade() -> None:
    with op.batch_alter_table("bookings") as batch_op:
        batch_op.drop_index("ix_bookings_business_start_end_status")
        batch_op.drop_index("ix_bookings_business_staff_start_status")
        batch_op.drop_constraint("ck_bookings_datetime_order", type_="check")
        batch_op.drop_constraint("ck_bookings_duration_positive", type_="check")

    with op.batch_alter_table("automation_credit_transactions") as batch_op:
        batch_op.drop_constraint("ck_automation_credit_payment_nonnegative", type_="check")
        batch_op.drop_constraint("ck_automation_credit_total_balance", type_="check")
        batch_op.drop_constraint(
            "ck_automation_credit_additional_balance_nonnegative", type_="check"
        )
        batch_op.drop_constraint("ck_automation_credit_included_balance_nonnegative", type_="check")
        batch_op.drop_constraint("ck_automation_credit_amount_nonnegative", type_="check")

    with op.batch_alter_table("conversation_automation_settings") as batch_op:
        batch_op.drop_constraint("ck_conversation_automation_auto_usage_nonnegative", type_="check")
        batch_op.drop_constraint(
            "ck_conversation_automation_additional_balance_nonnegative", type_="check"
        )
        batch_op.drop_constraint("ck_conversation_automation_included_usage", type_="check")
        batch_op.drop_constraint(
            "ck_conversation_automation_included_allowance_nonnegative", type_="check"
        )
