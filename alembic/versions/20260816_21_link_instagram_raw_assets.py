"""link Instagram raw assets to editorial content

Revision ID: 20260816_21
Revises: 20260815_20
Create Date: 2026-08-16
"""

import json
from collections.abc import Sequence
from datetime import datetime, timezone

import sqlalchemy as sa
from alembic import op
from sqlalchemy.engine import Connection

revision: str = "20260816_21"
down_revision: str | Sequence[str] | None = "20260815_20"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _backfill_editorial_sources(bind: Connection) -> None:
    versions = sa.table(
        "instagram_content_versions",
        sa.column("business_id", sa.Integer()),
        sa.column("content_id", sa.Integer()),
        sa.column("editorial_package_json", sa.Text()),
    )
    raw_assets = sa.table(
        "instagram_raw_assets",
        sa.column("id", sa.Integer()),
        sa.column("business_id", sa.Integer()),
    )
    links = sa.table(
        "instagram_content_raw_assets",
        sa.column("business_id", sa.Integer()),
        sa.column("content_id", sa.Integer()),
        sa.column("raw_asset_id", sa.Integer()),
        sa.column("associated_by_user_id", sa.Integer()),
        sa.column("created_at", sa.DateTime()),
    )
    valid_assets = {
        (row.business_id, row.id)
        for row in bind.execute(sa.select(raw_assets.c.business_id, raw_assets.c.id))
    }
    existing = {
        (row.content_id, row.raw_asset_id)
        for row in bind.execute(sa.select(links.c.content_id, links.c.raw_asset_id))
    }
    pending: list[dict[str, object]] = []
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    rows = bind.execute(
        sa.select(
            versions.c.business_id,
            versions.c.content_id,
            versions.c.editorial_package_json,
        ).where(versions.c.editorial_package_json.is_not(None))
    )
    for row in rows:
        try:
            package = json.loads(row.editorial_package_json)
        except (TypeError, ValueError):
            continue
        if not isinstance(package, dict):
            continue
        asset_plan = package.get("asset_plan")
        if not isinstance(asset_plan, dict):
            continue
        recommended = asset_plan.get("recommended", [])
        if not isinstance(recommended, list):
            continue
        for item in recommended:
            if not isinstance(item, dict) or item.get("source") != "instagram_raw_asset":
                continue
            raw_asset_id = item.get("id")
            key = (row.content_id, raw_asset_id)
            if (
                not isinstance(raw_asset_id, int)
                or (row.business_id, raw_asset_id) not in valid_assets
                or key in existing
            ):
                continue
            existing.add(key)
            pending.append(
                {
                    "business_id": row.business_id,
                    "content_id": row.content_id,
                    "raw_asset_id": raw_asset_id,
                    "associated_by_user_id": None,
                    "created_at": now,
                }
            )
    if pending:
        bind.execute(sa.insert(links), pending)


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if "instagram_content_raw_assets" not in inspector.get_table_names():
        op.create_table(
            "instagram_content_raw_assets",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("business_id", sa.Integer(), nullable=False),
            sa.Column("content_id", sa.Integer(), nullable=False),
            sa.Column("raw_asset_id", sa.Integer(), nullable=False),
            sa.Column("associated_by_user_id", sa.Integer(), nullable=True),
            sa.Column("created_at", sa.DateTime(), nullable=False),
            sa.ForeignKeyConstraint(["business_id"], ["businesses.id"], ondelete="CASCADE"),
            sa.ForeignKeyConstraint(["content_id"], ["instagram_contents.id"], ondelete="CASCADE"),
            sa.ForeignKeyConstraint(
                ["raw_asset_id"], ["instagram_raw_assets.id"], ondelete="RESTRICT"
            ),
            sa.ForeignKeyConstraint(["associated_by_user_id"], ["users.id"], ondelete="SET NULL"),
            sa.UniqueConstraint(
                "content_id", "raw_asset_id", name="uq_instagram_content_raw_asset"
            ),
        )
        op.create_index(
            "ix_instagram_content_raw_assets_business_id",
            "instagram_content_raw_assets",
            ["business_id"],
        )
        op.create_index(
            "ix_instagram_content_raw_assets_content_id",
            "instagram_content_raw_assets",
            ["content_id"],
        )
        op.create_index(
            "ix_instagram_content_raw_assets_raw_asset_id",
            "instagram_content_raw_assets",
            ["raw_asset_id"],
        )
        op.create_index(
            "ix_instagram_content_raw_assets_associated_by_user_id",
            "instagram_content_raw_assets",
            ["associated_by_user_id"],
        )
        op.create_index(
            "ix_instagram_content_raw_assets_business_content",
            "instagram_content_raw_assets",
            ["business_id", "content_id"],
        )
        op.create_index(
            "ix_instagram_content_raw_assets_business_raw",
            "instagram_content_raw_assets",
            ["business_id", "raw_asset_id"],
        )

    _backfill_editorial_sources(bind)

    final_columns = {
        item["name"] for item in sa.inspect(bind).get_columns("instagram_final_assets")
    }
    if "source_raw_asset_id" not in final_columns:
        with op.batch_alter_table("instagram_final_assets") as batch:
            batch.add_column(sa.Column("source_raw_asset_id", sa.Integer(), nullable=True))
            batch.create_foreign_key(
                "fk_instagram_final_assets_source_raw_asset_id",
                "instagram_raw_assets",
                ["source_raw_asset_id"],
                ["id"],
                ondelete="RESTRICT",
            )
            batch.create_index(
                "ix_instagram_final_assets_source_raw_asset_id", ["source_raw_asset_id"]
            )
            batch.create_unique_constraint(
                "uq_instagram_final_asset_content_raw_source",
                ["content_id", "source_raw_asset_id"],
            )


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    final_columns = {item["name"] for item in inspector.get_columns("instagram_final_assets")}
    if "source_raw_asset_id" in final_columns:
        with op.batch_alter_table("instagram_final_assets") as batch:
            batch.drop_constraint("uq_instagram_final_asset_content_raw_source", type_="unique")
            batch.drop_index("ix_instagram_final_assets_source_raw_asset_id")
            batch.drop_constraint(
                "fk_instagram_final_assets_source_raw_asset_id", type_="foreignkey"
            )
            batch.drop_column("source_raw_asset_id")
    if "instagram_content_raw_assets" in inspector.get_table_names():
        op.drop_table("instagram_content_raw_assets")
