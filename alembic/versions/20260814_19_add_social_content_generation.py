"""add versioned social content generation

Revision ID: 20260814_19
Revises: 20260814_18
Create Date: 2026-08-14
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260814_19"
down_revision: str | Sequence[str] | None = "20260814_18"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    raw_columns = {item["name"] for item in inspector.get_columns("instagram_raw_assets")}
    if {"service_id", "active"} - raw_columns:
        with op.batch_alter_table("instagram_raw_assets") as batch:
            if "service_id" not in raw_columns:
                batch.add_column(sa.Column("service_id", sa.Integer(), nullable=True))
                batch.create_foreign_key(
                    "fk_instagram_raw_assets_service_id_services",
                    "services",
                    ["service_id"],
                    ["id"],
                    ondelete="SET NULL",
                )
                batch.create_index("ix_instagram_raw_assets_service_id", ["service_id"])
            if "active" not in raw_columns:
                batch.add_column(
                    sa.Column(
                        "active",
                        sa.Boolean(),
                        server_default=sa.text("true"),
                        nullable=False,
                    )
                )

    gallery_columns = {item["name"] for item in inspector.get_columns("business_gallery_images")}
    if "service_id" not in gallery_columns:
        with op.batch_alter_table("business_gallery_images") as batch:
            batch.add_column(sa.Column("service_id", sa.Integer(), nullable=True))
            batch.create_foreign_key(
                "fk_business_gallery_images_service_id_services",
                "services",
                ["service_id"],
                ["id"],
                ondelete="SET NULL",
            )
            batch.create_index("ix_business_gallery_images_service_id", ["service_id"])

    content_columns = {item["name"] for item in inspector.get_columns("instagram_contents")}
    if "source_proposal_id" not in content_columns:
        with op.batch_alter_table("instagram_contents") as batch:
            batch.add_column(sa.Column("source_proposal_id", sa.Integer(), nullable=True))
            batch.create_foreign_key(
                "fk_instagram_contents_source_proposal",
                "social_content_proposals",
                ["source_proposal_id"],
                ["id"],
                ondelete="SET NULL",
            )
            batch.create_index("ix_instagram_contents_source_proposal_id", ["source_proposal_id"])
            batch.create_unique_constraint(
                "uq_instagram_contents_source_proposal_id", ["source_proposal_id"]
            )

    version_columns = {item["name"] for item in inspector.get_columns("instagram_content_versions")}
    missing_version_columns = {
        "editorial_package_json",
        "generation_source",
        "generator_version",
    } - version_columns
    if missing_version_columns:
        with op.batch_alter_table("instagram_content_versions") as batch:
            batch.drop_constraint("ck_instagram_content_version_format", type_="check")
            batch.create_check_constraint(
                "ck_instagram_content_version_format",
                "format IN ('single_image','carousel','reel','story')",
            )
            if "editorial_package_json" in missing_version_columns:
                batch.add_column(sa.Column("editorial_package_json", sa.Text(), nullable=True))
            if "generation_source" in missing_version_columns:
                batch.add_column(
                    sa.Column("generation_source", sa.String(length=30), nullable=True)
                )
            if "generator_version" in missing_version_columns:
                batch.add_column(
                    sa.Column("generator_version", sa.String(length=50), nullable=True)
                )


def downgrade() -> None:
    with op.batch_alter_table("instagram_content_versions") as batch:
        batch.drop_column("generator_version")
        batch.drop_column("generation_source")
        batch.drop_column("editorial_package_json")
        batch.drop_constraint("ck_instagram_content_version_format", type_="check")
        batch.create_check_constraint(
            "ck_instagram_content_version_format",
            "format IN ('single_image','carousel')",
        )

    with op.batch_alter_table("instagram_contents") as batch:
        batch.drop_constraint("uq_instagram_contents_source_proposal_id", type_="unique")
        batch.drop_index("ix_instagram_contents_source_proposal_id")
        batch.drop_constraint(
            "fk_instagram_contents_source_proposal",
            type_="foreignkey",
        )
        batch.drop_column("source_proposal_id")

    with op.batch_alter_table("business_gallery_images") as batch:
        batch.drop_index("ix_business_gallery_images_service_id")
        batch.drop_constraint("fk_business_gallery_images_service_id_services", type_="foreignkey")
        batch.drop_column("service_id")

    with op.batch_alter_table("instagram_raw_assets") as batch:
        batch.drop_index("ix_instagram_raw_assets_service_id")
        batch.drop_constraint("fk_instagram_raw_assets_service_id_services", type_="foreignkey")
        batch.drop_column("active")
        batch.drop_column("service_id")
