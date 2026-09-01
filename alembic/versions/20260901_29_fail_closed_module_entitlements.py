"""materialize module access before enforcing fail-closed capabilities

Revision ID: 20260901_29
Revises: 20260830_28
Create Date: 2026-09-01
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260901_29"
down_revision: str | Sequence[str] | None = "20260830_28"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

MODULE_KEYS = ("essential", "growth", "social")


def upgrade() -> None:
    bind = op.get_bind()
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
    legacy_business_ids = tuple(
        bind.execute(
            sa.select(businesses.c.id).where(
                ~sa.exists(
                    sa.select(1)
                    .select_from(access)
                    .where(access.c.business_id == businesses.c.id)
                )
            )
        ).scalars()
    )

    for module_key in MODULE_KEYS:
        row_exists = sa.exists(
            sa.select(1)
            .select_from(access)
            .where(
                access.c.business_id == businesses.c.id,
                access.c.module_key == module_key,
            )
        )
        # Zero-row businesses previously received every module from the central
        # legacy fallback. Partial configurations already denied each missing key.
        historically_available = businesses.c.id.in_(legacy_business_ids)
        bind.execute(
            sa.insert(access).from_select(
                (
                    "business_id",
                    "module_key",
                    "entitled",
                    "active",
                    "module_cost_period",
                    "created_at",
                    "updated_at",
                ),
                sa.select(
                    businesses.c.id,
                    sa.literal(module_key),
                    historically_available,
                    historically_available,
                    sa.literal("monthly"),
                    sa.func.current_timestamp(),
                    sa.func.current_timestamp(),
                ).where(~row_exists),
            )
        )


def downgrade() -> None:
    # Data-only safety migration: removing explicit configuration would recreate
    # the ambiguous state that this revision eliminates.
    pass
