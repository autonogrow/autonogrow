"""add customer account identity and conservative business links

Revision ID: 20260821_22
Revises: 20260816_21
Create Date: 2026-08-21
"""

from collections import defaultdict
from collections.abc import Sequence
from datetime import datetime

import phonenumbers
import sqlalchemy as sa
from alembic import op
from phonenumbers import PhoneNumberFormat

revision: str = "20260821_22"
down_revision: str | Sequence[str] | None = "20260816_21"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _normalized_phone(value: str | None, region: str = "ES") -> str | None:
    clean = (value or "").strip()
    if not clean:
        return None
    if clean.startswith("00"):
        clean = f"+{clean[2:]}"
    try:
        parsed = phonenumbers.parse(clean, region)
    except phonenumbers.NumberParseException:
        return None
    if not phonenumbers.is_valid_number(parsed):
        return None
    return phonenumbers.format_number(parsed, PhoneNumberFormat.E164)


def _backfill_phone_columns(bind: sa.Connection) -> None:
    for table_name in ("users", "customers"):
        table = sa.table(
            table_name,
            sa.column("id", sa.Integer()),
            sa.column("phone", sa.String()),
            sa.column("phone_normalized", sa.String()),
        )
        for row in bind.execute(sa.select(table.c.id, table.c.phone)):
            normalized = _normalized_phone(row.phone)
            if normalized:
                bind.execute(
                    sa.update(table)
                    .where(table.c.id == row.id)
                    .values(phone_normalized=normalized)
                )


def _backfill_explicit_booking_links(bind: sa.Connection) -> None:
    bookings = sa.table(
        "bookings",
        sa.column("customer_user_id", sa.Integer()),
        sa.column("customer_id", sa.Integer()),
        sa.column("business_id", sa.Integer()),
    )
    links = sa.table(
        "customer_account_links",
        sa.column("user_id", sa.Integer()),
        sa.column("customer_id", sa.Integer()),
        sa.column("business_id", sa.Integer()),
        sa.column("link_method", sa.String()),
        sa.column("created_at", sa.DateTime()),
    )
    candidates: dict[tuple[int, int], set[int]] = defaultdict(set)
    rows = bind.execute(
        sa.select(
            bookings.c.customer_user_id,
            bookings.c.customer_id,
            bookings.c.business_id,
        ).where(bookings.c.customer_user_id.is_not(None))
    )
    for row in rows:
        candidates[(row.customer_user_id, row.business_id)].add(row.customer_id)
    claimed_customers: set[int] = set()
    pending = []
    for (user_id, business_id), customer_ids in candidates.items():
        if len(customer_ids) != 1:
            continue
        customer_id = next(iter(customer_ids))
        if customer_id in claimed_customers:
            continue
        claimed_customers.add(customer_id)
        pending.append(
            {
                "user_id": user_id,
                "customer_id": customer_id,
                "business_id": business_id,
                "link_method": "legacy_authenticated_booking",
                "created_at": datetime.utcnow(),
            }
        )
    if pending:
        bind.execute(sa.insert(links), pending)


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    user_columns = {item["name"] for item in inspector.get_columns("users")}
    missing_user_columns = {
        "phone_normalized",
        "phone_verified",
        "instagram_username",
        "instagram_provider_user_id",
        "instagram_verified",
    } - user_columns
    if missing_user_columns:
        with op.batch_alter_table("users") as batch:
            if "phone_normalized" in missing_user_columns:
                batch.add_column(sa.Column("phone_normalized", sa.String(20), nullable=True))
            if "phone_verified" in missing_user_columns:
                batch.add_column(
                    sa.Column(
                        "phone_verified", sa.Boolean(), server_default=sa.false(), nullable=False
                    )
                )
            if "instagram_username" in missing_user_columns:
                batch.add_column(sa.Column("instagram_username", sa.String(30), nullable=True))
            if "instagram_provider_user_id" in missing_user_columns:
                batch.add_column(
                    sa.Column("instagram_provider_user_id", sa.String(255), nullable=True)
                )
            if "instagram_verified" in missing_user_columns:
                batch.add_column(
                    sa.Column(
                        "instagram_verified",
                        sa.Boolean(),
                        server_default=sa.false(),
                        nullable=False,
                    )
                )
    inspector = sa.inspect(bind)
    user_indexes = {item["name"] for item in inspector.get_indexes("users")}
    user_unique_columns = {
        tuple(item["column_names"]) for item in inspector.get_unique_constraints("users")
    }
    with op.batch_alter_table("users") as batch:
        if "ix_users_phone_normalized" not in user_indexes:
            batch.create_index("ix_users_phone_normalized", ["phone_normalized"])
        if "ix_users_instagram_username" not in user_indexes:
            batch.create_index("ix_users_instagram_username", ["instagram_username"])
        if ("instagram_provider_user_id",) not in user_unique_columns:
            batch.create_unique_constraint(
                "uq_users_instagram_provider_user_id", ["instagram_provider_user_id"]
            )

    customer_columns = {item["name"] for item in sa.inspect(bind).get_columns("customers")}
    if "phone_normalized" not in customer_columns:
        with op.batch_alter_table("customers") as batch:
            batch.add_column(sa.Column("phone_normalized", sa.String(20), nullable=True))
    customer_indexes = {item["name"] for item in sa.inspect(bind).get_indexes("customers")}
    if "ix_customers_phone_normalized" not in customer_indexes:
        with op.batch_alter_table("customers") as batch:
            batch.create_index("ix_customers_phone_normalized", ["phone_normalized"])

    if "customer_account_links" not in sa.inspect(bind).get_table_names():
        op.create_table(
            "customer_account_links",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("user_id", sa.Integer(), nullable=False),
            sa.Column("customer_id", sa.Integer(), nullable=False),
            sa.Column("business_id", sa.Integer(), nullable=False),
            sa.Column("link_method", sa.String(40), nullable=False),
            sa.Column("created_at", sa.DateTime(), nullable=False),
            sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
            sa.ForeignKeyConstraint(["customer_id"], ["customers.id"], ondelete="CASCADE"),
            sa.ForeignKeyConstraint(["business_id"], ["businesses.id"], ondelete="CASCADE"),
            sa.UniqueConstraint("customer_id", name="uq_customer_account_links_customer"),
            sa.UniqueConstraint(
                "user_id", "business_id", name="uq_customer_account_links_user_business"
            ),
        )
        op.create_index(
            "ix_customer_account_links_user_id", "customer_account_links", ["user_id"]
        )
        op.create_index(
            "ix_customer_account_links_customer_id", "customer_account_links", ["customer_id"]
        )
        op.create_index(
            "ix_customer_account_links_business_id", "customer_account_links", ["business_id"]
        )
        op.create_index(
            "ix_customer_account_links_business_user",
            "customer_account_links",
            ["business_id", "user_id"],
        )
    _backfill_phone_columns(bind)
    _backfill_explicit_booking_links(bind)


def downgrade() -> None:
    op.drop_table("customer_account_links")
    with op.batch_alter_table("customers") as batch:
        batch.drop_index("ix_customers_phone_normalized")
        batch.drop_column("phone_normalized")
    with op.batch_alter_table("users") as batch:
        batch.drop_constraint("uq_users_instagram_provider_user_id", type_="unique")
        batch.drop_index("ix_users_instagram_username")
        batch.drop_index("ix_users_phone_normalized")
        batch.drop_column("instagram_verified")
        batch.drop_column("instagram_provider_user_id")
        batch.drop_column("instagram_username")
        batch.drop_column("phone_verified")
        batch.drop_column("phone_normalized")
