"""add temporary Instagram OAuth attempts

Revision ID: 20260803_08
Revises: 20260802_07
Create Date: 2026-08-03
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy import inspect

revision: str = "20260803_08"
down_revision: str | Sequence[str] | None = "20260802_07"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _replace_connection_mode_check(*, downgrade: bool = False) -> None:
    allowed = "'simulated','legacy'" if downgrade else "'simulated','legacy','oauth'"
    with op.batch_alter_table("business_channel_controls") as batch:
        batch.drop_constraint(
            "ck_business_channel_control_connection_mode",
            type_="check",
        )
        batch.create_check_constraint(
            "ck_business_channel_control_connection_mode",
            f"connection_mode IN ({allowed})",
        )


def upgrade() -> None:
    tables = set(inspect(op.get_bind()).get_table_names())
    if "instagram_oauth_attempts" not in tables:
        op.create_table(
            "instagram_oauth_attempts",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("business_id", sa.Integer(), nullable=False),
            sa.Column("user_id", sa.Integer(), nullable=False),
            sa.Column("channel_control_id", sa.Integer(), nullable=False),
            sa.Column("purpose", sa.String(30), nullable=False),
            sa.Column("status", sa.String(30), nullable=False),
            sa.Column("state_hash", sa.String(64), nullable=False),
            sa.Column("session_fingerprint_hash", sa.String(64), nullable=False),
            sa.Column("return_path", sa.String(500), nullable=False),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("consumed_at", sa.DateTime(timezone=True)),
            sa.Column("invalidated_at", sa.DateTime(timezone=True)),
            sa.Column("candidate_external_account_id", sa.String(255)),
            sa.Column("candidate_external_account_name", sa.String(255)),
            sa.Column("candidate_account_type", sa.String(40)),
            sa.Column("candidate_encrypted_access_token", sa.Text()),
            sa.Column("candidate_encryption_key_version", sa.String(60)),
            sa.Column("candidate_token_expires_at", sa.DateTime(timezone=True)),
            sa.Column("candidate_granted_scopes", sa.Text()),
            sa.Column("webhook_subscription_status", sa.String(60)),
            sa.Column("safe_error_code", sa.String(80)),
            sa.Column("safe_error_message", sa.String(500)),
            sa.Column("metadata_json", sa.Text()),
            sa.CheckConstraint(
                "purpose IN ('initial_connection','reconnect','replacement')",
                name="ck_instagram_oauth_attempt_purpose",
            ),
            sa.CheckConstraint(
                "status IN ('pending','processing','candidate_ready','consumed','expired',"
                "'cancelled','failed','rejected','approved')",
                name="ck_instagram_oauth_attempt_status",
            ),
            sa.CheckConstraint(
                "(candidate_encrypted_access_token IS NULL AND "
                "candidate_encryption_key_version IS NULL) OR "
                "(candidate_encrypted_access_token IS NOT NULL AND "
                "candidate_encryption_key_version IS NOT NULL)",
                name="ck_instagram_oauth_attempt_encrypted_token_version",
            ),
            sa.ForeignKeyConstraint(["business_id"], ["businesses.id"], ondelete="CASCADE"),
            sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
            sa.ForeignKeyConstraint(
                ["channel_control_id"], ["business_channel_controls.id"], ondelete="CASCADE"
            ),
            sa.UniqueConstraint("state_hash", name="uq_instagram_oauth_attempt_state_hash"),
            sa.UniqueConstraint(
                "candidate_external_account_id",
                name="uq_instagram_oauth_attempt_candidate_account",
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
            "candidate_external_account_id",
        ):
            op.create_index(
                f"ix_instagram_oauth_attempts_{column}",
                "instagram_oauth_attempts",
                [column],
            )
        op.create_index(
            "ix_instagram_oauth_attempts_business_status",
            "instagram_oauth_attempts",
            ["business_id", "status"],
        )
        op.create_index(
            "ix_instagram_oauth_attempts_user_status",
            "instagram_oauth_attempts",
            ["user_id", "status"],
        )
    _replace_connection_mode_check()


def downgrade() -> None:
    tables = set(inspect(op.get_bind()).get_table_names())
    if "instagram_oauth_attempts" in tables:
        op.drop_table("instagram_oauth_attempts")
    op.execute(
        sa.text(
            "UPDATE business_channel_controls SET connection_mode = 'simulated' "
            "WHERE connection_mode = 'oauth'"
        )
    )
    _replace_connection_mode_check(downgrade=True)
