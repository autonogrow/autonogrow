"""hash, expire and revoke guest booking management tokens

Revision ID: 20260901_31
Revises: 20260901_30
Create Date: 2026-09-01
"""

import hashlib
from collections.abc import Sequence
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

import sqlalchemy as sa
from alembic import op

revision: str = "20260901_31"
down_revision: str | Sequence[str] | None = "20260901_30"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

TERMINAL_STATUSES = frozenset({"rejected", "cancelled", "completed", "no_show"})


def _as_utc_naive(value: datetime, timezone_name: str) -> datetime:
    if value.tzinfo is not None:
        return value.astimezone(timezone.utc).replace(tzinfo=None)
    try:
        local_timezone = ZoneInfo(timezone_name)
    except ZoneInfoNotFoundError:
        local_timezone = timezone.utc
    return value.replace(tzinfo=local_timezone).astimezone(timezone.utc).replace(tzinfo=None)


def _expiry(
    created_at: datetime,
    appointment_end: datetime | None,
    timezone_name: str,
) -> datetime:
    return min(
        (_as_utc_naive(appointment_end, timezone_name) if appointment_end else created_at)
        + timedelta(days=7),
        created_at + timedelta(days=90),
    )


def upgrade() -> None:
    connection = op.get_bind()
    inspector = sa.inspect(connection)
    existing_columns = {column["name"] for column in inspector.get_columns("bookings")}
    existing_indexes = {index["name"] for index in inspector.get_indexes("bookings")}
    if "public_manage_token_hash" not in existing_columns:
        op.add_column(
            "bookings",
            sa.Column("public_manage_token_hash", sa.String(length=64), nullable=True),
        )
    if "public_manage_token_expires_at" not in existing_columns:
        op.add_column(
            "bookings",
            sa.Column("public_manage_token_expires_at", sa.DateTime(), nullable=True),
        )
    if "public_manage_token_revoked_at" not in existing_columns:
        op.add_column(
            "bookings",
            sa.Column("public_manage_token_revoked_at", sa.DateTime(), nullable=True),
        )

    bookings = sa.table(
        "bookings",
        sa.column("id", sa.Integer()),
        sa.column("business_id", sa.Integer()),
        sa.column("public_manage_token", sa.String()),
        sa.column("public_manage_token_hash", sa.String()),
        sa.column("public_manage_token_expires_at", sa.DateTime()),
        sa.column("public_manage_token_revoked_at", sa.DateTime()),
        sa.column("customer_user_id", sa.Integer()),
        sa.column("status", sa.String()),
        sa.column("created_at", sa.DateTime()),
        sa.column("end_datetime", sa.DateTime()),
    )
    businesses = sa.table(
        "businesses",
        sa.column("id", sa.Integer()),
        sa.column("timezone", sa.String()),
    )
    if "public_manage_token" in existing_columns:
        migrated_at = datetime.utcnow()
        rows = connection.execute(
            sa.select(
                bookings.c.id,
                bookings.c.public_manage_token,
                bookings.c.customer_user_id,
                bookings.c.status,
                bookings.c.created_at,
                bookings.c.end_datetime,
                businesses.c.timezone,
            )
            .select_from(bookings.join(businesses, businesses.c.id == bookings.c.business_id))
            .where(bookings.c.public_manage_token.is_not(None))
        )
        for row in rows:
            token = row.public_manage_token
            if not token:
                continue
            created_at = row.created_at or migrated_at
            revoked_at = (
                migrated_at
                if row.customer_user_id is not None or row.status in TERMINAL_STATUSES
                else None
            )
            connection.execute(
                bookings.update()
                .where(bookings.c.id == row.id)
                .values(
                    public_manage_token_hash=hashlib.sha256(token.encode("utf-8")).hexdigest(),
                    public_manage_token_expires_at=_expiry(
                        created_at,
                        row.end_datetime,
                        row.timezone or "UTC",
                    ),
                    public_manage_token_revoked_at=revoked_at,
                )
            )

    with op.batch_alter_table("bookings") as batch_op:
        if "public_manage_token" in existing_columns:
            if "ix_bookings_public_manage_token" in existing_indexes:
                batch_op.drop_index("ix_bookings_public_manage_token")
            batch_op.drop_column("public_manage_token")
        if "ix_bookings_public_manage_token_hash" not in existing_indexes:
            batch_op.create_index(
                "ix_bookings_public_manage_token_hash",
                ["public_manage_token_hash"],
                unique=True,
            )
        if "ix_bookings_public_manage_token_expires_at" not in existing_indexes:
            batch_op.create_index(
                "ix_bookings_public_manage_token_expires_at",
                ["public_manage_token_expires_at"],
                unique=False,
            )


def downgrade() -> None:
    with op.batch_alter_table("bookings") as batch_op:
        batch_op.add_column(sa.Column("public_manage_token", sa.String(length=255), nullable=True))
        batch_op.drop_index("ix_bookings_public_manage_token_expires_at")
        batch_op.drop_index("ix_bookings_public_manage_token_hash")
        batch_op.drop_column("public_manage_token_revoked_at")
        batch_op.drop_column("public_manage_token_expires_at")
        batch_op.drop_column("public_manage_token_hash")
        batch_op.create_index(
            "ix_bookings_public_manage_token", ["public_manage_token"], unique=True
        )
