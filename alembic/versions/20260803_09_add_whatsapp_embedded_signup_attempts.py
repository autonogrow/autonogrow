"""add temporary WhatsApp Embedded Signup attempts

Revision ID: 20260803_09
Revises: 20260803_08
Create Date: 2026-08-03
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy import inspect

revision: str = "20260803_09"
down_revision: str | Sequence[str] | None = "20260803_08"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _replace_connection_mode_check(*, downgrade: bool = False) -> None:
    allowed = (
        "'simulated','legacy','oauth'"
        if downgrade
        else "'simulated','legacy','oauth','embedded_signup'"
    )
    with op.batch_alter_table("business_channel_controls") as batch:
        batch.drop_constraint("ck_business_channel_control_connection_mode", type_="check")
        batch.create_check_constraint(
            "ck_business_channel_control_connection_mode",
            f"connection_mode IN ({allowed})",
        )


def upgrade() -> None:
    inspector = inspect(op.get_bind())
    integration_columns = {
        column["name"] for column in inspector.get_columns("business_channel_integrations")
    }
    if "provider_account_id" not in integration_columns:
        with op.batch_alter_table("business_channel_integrations") as batch:
            batch.add_column(sa.Column("provider_account_id", sa.String(255), nullable=True))
            batch.create_index(
                "ix_business_channel_integrations_provider_account_id",
                ["provider_account_id"],
                unique=False,
            )

    tables = set(inspect(op.get_bind()).get_table_names())
    if "whatsapp_embedded_signup_attempts" not in tables:
        op.create_table(
            "whatsapp_embedded_signup_attempts",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("business_id", sa.Integer(), nullable=False),
            sa.Column("user_id", sa.Integer(), nullable=False),
            sa.Column("channel_control_id", sa.Integer(), nullable=False),
            sa.Column("purpose", sa.String(30), nullable=False),
            sa.Column("status", sa.String(30), nullable=False),
            sa.Column("state_hash", sa.String(64), nullable=False),
            sa.Column("session_fingerprint_hash", sa.String(64), nullable=False),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("consumed_at", sa.DateTime(timezone=True)),
            sa.Column("invalidated_at", sa.DateTime(timezone=True)),
            sa.Column("candidate_meta_business_id", sa.String(255)),
            sa.Column("candidate_waba_id", sa.String(255)),
            sa.Column("candidate_phone_number_id", sa.String(255)),
            sa.Column("candidate_display_phone_number_redacted", sa.String(80)),
            sa.Column("candidate_verified_name", sa.String(255)),
            sa.Column("candidate_phone_status", sa.String(80)),
            sa.Column("candidate_encrypted_access_token", sa.Text()),
            sa.Column("candidate_encryption_key_version", sa.String(60)),
            sa.Column("candidate_token_expires_at", sa.DateTime(timezone=True)),
            sa.Column("candidate_granted_scopes", sa.Text()),
            sa.Column("app_subscription_status", sa.String(60)),
            sa.Column("phone_registration_status", sa.String(60)),
            sa.Column("safe_error_code", sa.String(80)),
            sa.Column("safe_error_message", sa.String(500)),
            sa.Column("metadata_json", sa.Text()),
            sa.CheckConstraint(
                "purpose IN ('initial_connection','reconnect','replacement')",
                name="ck_whatsapp_signup_attempt_purpose",
            ),
            sa.CheckConstraint(
                "status IN ('pending','processing','candidate_ready','expired','cancelled',"
                "'failed','rejected','approved')",
                name="ck_whatsapp_signup_attempt_status",
            ),
            sa.CheckConstraint(
                "(candidate_encrypted_access_token IS NULL AND "
                "candidate_encryption_key_version IS NULL) OR "
                "(candidate_encrypted_access_token IS NOT NULL AND "
                "candidate_encryption_key_version IS NOT NULL)",
                name="ck_whatsapp_signup_attempt_encrypted_token_version",
            ),
            sa.ForeignKeyConstraint(["business_id"], ["businesses.id"], ondelete="CASCADE"),
            sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
            sa.ForeignKeyConstraint(
                ["channel_control_id"], ["business_channel_controls.id"], ondelete="CASCADE"
            ),
            sa.UniqueConstraint("state_hash", name="uq_whatsapp_signup_attempt_state_hash"),
            sa.UniqueConstraint(
                "candidate_waba_id", name="uq_whatsapp_signup_attempt_candidate_waba"
            ),
            sa.UniqueConstraint(
                "candidate_phone_number_id",
                name="uq_whatsapp_signup_attempt_candidate_phone",
            ),
        )
        for column in (
            "id",
            "business_id",
            "user_id",
            "channel_control_id",
            "purpose",
            "status",
            "expires_at",
            "candidate_meta_business_id",
            "candidate_waba_id",
            "candidate_phone_number_id",
        ):
            op.create_index(
                f"ix_whatsapp_embedded_signup_attempts_{column}",
                "whatsapp_embedded_signup_attempts",
                [column],
            )
        op.create_index(
            "ix_whatsapp_signup_attempts_business_status",
            "whatsapp_embedded_signup_attempts",
            ["business_id", "status"],
        )
        op.create_index(
            "ix_whatsapp_signup_attempts_user_status",
            "whatsapp_embedded_signup_attempts",
            ["user_id", "status"],
        )
    _replace_connection_mode_check()


def downgrade() -> None:
    tables = set(inspect(op.get_bind()).get_table_names())
    if "whatsapp_embedded_signup_attempts" in tables:
        op.drop_table("whatsapp_embedded_signup_attempts")
    op.execute(
        sa.text(
            "UPDATE business_channel_controls SET connection_mode = 'simulated' "
            "WHERE connection_mode = 'embedded_signup'"
        )
    )
    _replace_connection_mode_check(downgrade=True)
    integration_columns = {
        column["name"]
        for column in inspect(op.get_bind()).get_columns("business_channel_integrations")
    }
    if "provider_account_id" in integration_columns:
        with op.batch_alter_table("business_channel_integrations") as batch:
            batch.drop_index("ix_business_channel_integrations_provider_account_id")
            batch.drop_column("provider_account_id")
