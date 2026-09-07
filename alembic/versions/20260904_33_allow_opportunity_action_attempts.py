"""allow recoverable opportunity action attempts

Revision ID: 20260904_33
Revises: 20260903_32
Create Date: 2026-09-04
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260904_33"
down_revision: str | Sequence[str] | None = "20260903_32"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

OLD_CONSTRAINT = "uq_opportunity_action_conservative_dedupe"
ACTIVE_CONTACT_INDEX = "uq_opportunity_action_active_contact"
NON_CONTACT_INDEX = "uq_opportunity_action_singleton_non_contact"


def _where(dialect: str, predicate: str) -> dict[str, sa.TextClause]:
    clause = sa.text(predicate)
    return {"postgresql_where": clause} if dialect == "postgresql" else {"sqlite_where": clause}


def upgrade() -> None:
    connection = op.get_bind()
    inspector = sa.inspect(connection)
    unique_constraints = {
        item.get("name") for item in inspector.get_unique_constraints("opportunity_actions")
    }
    indexes = {item.get("name") for item in inspector.get_indexes("opportunity_actions")}
    if OLD_CONSTRAINT in unique_constraints:
        with op.batch_alter_table("opportunity_actions") as batch:
            batch.drop_constraint(OLD_CONSTRAINT, type_="unique")
    dialect = connection.dialect.name
    if ACTIVE_CONTACT_INDEX not in indexes:
        op.create_index(
            ACTIVE_CONTACT_INDEX,
            "opportunity_actions",
            ["business_id", "opportunity_id", "action_type"],
            unique=True,
            **_where(
                dialect,
                "action_type = 'contact_customer' "
                "AND status IN ('draft','approved','sending')",
            ),
        )
    if NON_CONTACT_INDEX not in indexes:
        op.create_index(
            NON_CONTACT_INDEX,
            "opportunity_actions",
            ["business_id", "opportunity_id", "action_type"],
            unique=True,
            **_where(dialect, "action_type <> 'contact_customer'"),
        )


def downgrade() -> None:
    connection = op.get_bind()
    duplicate = connection.execute(
        sa.text(
            "SELECT business_id, opportunity_id, action_type "
            "FROM opportunity_actions GROUP BY business_id, opportunity_id, action_type "
            "HAVING COUNT(*) > 1 LIMIT 1"
        )
    ).first()
    if duplicate is not None:
        raise RuntimeError(
            "Cannot restore the legacy uniqueness constraint without deleting action history"
        )
    indexes = {item.get("name") for item in sa.inspect(connection).get_indexes("opportunity_actions")}
    if ACTIVE_CONTACT_INDEX in indexes:
        op.drop_index(ACTIVE_CONTACT_INDEX, table_name="opportunity_actions")
    if NON_CONTACT_INDEX in indexes:
        op.drop_index(NON_CONTACT_INDEX, table_name="opportunity_actions")
    with op.batch_alter_table("opportunity_actions") as batch:
        batch.create_unique_constraint(
            OLD_CONSTRAINT,
            ["business_id", "opportunity_id", "action_type"],
        )
