"""deduplicate future review request cycles by customer

Revision ID: 20260903_32
Revises: 20260901_31
Create Date: 2026-09-03
"""

from collections import defaultdict
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260903_32"
down_revision: str | Sequence[str] | None = "20260901_31"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

CUSTOMER_INDEX = "ix_review_requests_customer_id"
CUSTOMER_FK = "fk_review_requests_customer_id_customers"
CUSTOMER_CYCLE_INDEX = "uq_review_requests_customer_cycle_anchor"


def upgrade() -> None:
    connection = op.get_bind()
    inspector = sa.inspect(connection)
    columns = {item["name"] for item in inspector.get_columns("review_requests")}
    indexes = {item["name"] for item in inspector.get_indexes("review_requests")}
    foreign_keys = {
        item.get("name")
        for item in inspector.get_foreign_keys("review_requests")
        if item.get("name")
    }

    with op.batch_alter_table("review_requests") as batch:
        if "customer_id" not in columns:
            batch.add_column(sa.Column("customer_id", sa.Integer(), nullable=True))
        if "is_customer_cycle_anchor" not in columns:
            batch.add_column(
                sa.Column(
                    "is_customer_cycle_anchor",
                    sa.Boolean(),
                    server_default=sa.true(),
                    nullable=False,
                )
            )
        if CUSTOMER_FK not in foreign_keys:
            batch.create_foreign_key(
                CUSTOMER_FK,
                "customers",
                ["customer_id"],
                ["id"],
                ondelete="SET NULL",
            )
        if CUSTOMER_INDEX not in indexes:
            batch.create_index(CUSTOMER_INDEX, ["customer_id"], unique=False)

    review_requests = sa.table(
        "review_requests",
        sa.column("id", sa.Integer()),
        sa.column("business_id", sa.Integer()),
        sa.column("booking_id", sa.Integer()),
        sa.column("customer_id", sa.Integer()),
        sa.column("is_customer_cycle_anchor", sa.Boolean()),
        sa.column("created_at", sa.DateTime()),
    )
    bookings = sa.table(
        "bookings",
        sa.column("id", sa.Integer()),
        sa.column("business_id", sa.Integer()),
        sa.column("customer_id", sa.Integer()),
    )
    customers = sa.table(
        "customers",
        sa.column("id", sa.Integer()),
        sa.column("business_id", sa.Integer()),
    )

    rows = connection.execute(
        sa.select(
            review_requests.c.id,
            review_requests.c.business_id,
            review_requests.c.created_at,
            bookings.c.customer_id,
            customers.c.business_id.label("customer_business_id"),
        )
        .select_from(
            review_requests.outerjoin(
                bookings, bookings.c.id == review_requests.c.booking_id
            ).outerjoin(customers, customers.c.id == bookings.c.customer_id)
        )
        .order_by(review_requests.c.created_at, review_requests.c.id)
    ).all()

    customer_rows: dict[tuple[int, int], list[int]] = defaultdict(list)
    for row in rows:
        stable_customer_id = (
            row.customer_id
            if row.customer_id is not None and row.customer_business_id == row.business_id
            else None
        )
        connection.execute(
            review_requests.update()
            .where(review_requests.c.id == row.id)
            .values(
                customer_id=stable_customer_id,
                is_customer_cycle_anchor=False,
            )
        )
        if stable_customer_id is not None:
            customer_rows[(row.business_id, stable_customer_id)].append(row.id)

    # The earliest request remains the immutable origin cycle. Later legacy cycles
    # stay queryable as history but do not participate in future uniqueness.
    for request_ids in customer_rows.values():
        connection.execute(
            review_requests.update()
            .where(review_requests.c.id == request_ids[0])
            .values(is_customer_cycle_anchor=True)
        )

    inspector = sa.inspect(connection)
    indexes = {item["name"] for item in inspector.get_indexes("review_requests")}
    if CUSTOMER_CYCLE_INDEX not in indexes:
        dialect = connection.dialect.name
        where = (
            sa.text("is_customer_cycle_anchor AND customer_id IS NOT NULL")
            if dialect == "postgresql"
            else sa.text("is_customer_cycle_anchor = 1 AND customer_id IS NOT NULL")
        )
        kwargs = {"postgresql_where": where} if dialect == "postgresql" else {"sqlite_where": where}
        op.create_index(
            CUSTOMER_CYCLE_INDEX,
            "review_requests",
            ["business_id", "customer_id"],
            unique=True,
            **kwargs,
        )


def downgrade() -> None:
    connection = op.get_bind()
    inspector = sa.inspect(connection)
    columns = {item["name"] for item in inspector.get_columns("review_requests")}
    indexes = {item["name"] for item in inspector.get_indexes("review_requests")}
    foreign_keys = {
        item.get("name")
        for item in inspector.get_foreign_keys("review_requests")
        if item.get("name")
    }
    with op.batch_alter_table("review_requests") as batch:
        if CUSTOMER_CYCLE_INDEX in indexes:
            batch.drop_index(CUSTOMER_CYCLE_INDEX)
        if CUSTOMER_INDEX in indexes:
            batch.drop_index(CUSTOMER_INDEX)
        if CUSTOMER_FK in foreign_keys:
            batch.drop_constraint(CUSTOMER_FK, type_="foreignkey")
        if "is_customer_cycle_anchor" in columns:
            batch.drop_column("is_customer_cycle_anchor")
        if "customer_id" in columns:
            batch.drop_column("customer_id")
