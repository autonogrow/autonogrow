"""add reusable business onboarding

Revision ID: 20260730_05
Revises: 20260730_04
Create Date: 2026-07-30
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy import inspect, text

revision: str = "20260730_05"
down_revision: str | Sequence[str] | None = "20260730_04"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


BUSINESS_COLUMNS = (
    sa.Column("whatsapp_phone", sa.String(40)),
    sa.Column("public_email", sa.String(320)),
    sa.Column("postal_code", sa.String(20)),
    sa.Column("region", sa.String(120)),
    sa.Column("country_code", sa.String(2), nullable=False, server_default="ES"),
    sa.Column("language_code", sa.String(10), nullable=False, server_default="es"),
    sa.Column("timezone", sa.String(80), nullable=False, server_default="Europe/Madrid"),
    sa.Column("currency", sa.String(3), nullable=False, server_default="EUR"),
    sa.Column("legal_name", sa.String(240)),
    sa.Column("tax_identifier", sa.String(80)),
    sa.Column("tiktok_url", sa.Text()),
    sa.Column("external_website_url", sa.Text()),
    sa.Column("landing_cta", sa.String(120)),
    sa.Column("seo_title", sa.String(160)),
    sa.Column("seo_description", sa.String(320)),
    sa.Column("seo_noindex", sa.Boolean(), nullable=False, server_default=sa.true()),
    sa.Column("activated_at", sa.DateTime(timezone=True)),
    sa.Column("activated_by_user_id", sa.Integer()),
    sa.Column("status_updated_at", sa.DateTime(timezone=True)),
    sa.Column("archived_at", sa.DateTime(timezone=True)),
)

SERVICE_COLUMNS = (
    sa.Column("price_amount", sa.Numeric(12, 2)),
    sa.Column("currency", sa.String(3), nullable=False, server_default="EUR"),
    sa.Column("category", sa.String(120)),
    sa.Column("visible", sa.Boolean(), nullable=False, server_default=sa.true()),
    sa.Column("bookable", sa.Boolean(), nullable=False, server_default=sa.true()),
    sa.Column("requires_approval", sa.Boolean(), nullable=False, server_default=sa.false()),
    sa.Column("buffer_before_minutes", sa.Integer(), nullable=False, server_default="0"),
    sa.Column("buffer_after_minutes", sa.Integer(), nullable=False, server_default="0"),
    sa.Column("position", sa.Integer(), nullable=False, server_default="0"),
    sa.Column("source_key", sa.String(200)),
    sa.Column("archived_at", sa.DateTime(timezone=True)),
)

AVAILABILITY_COLUMNS = (
    sa.Column("auto_confirm_bookings", sa.Boolean(), nullable=False, server_default=sa.true()),
    sa.Column("cancellation_allowed", sa.Boolean(), nullable=False, server_default=sa.true()),
    sa.Column("cancellation_notice_minutes", sa.Integer(), nullable=False, server_default="120"),
    sa.Column("reschedule_allowed", sa.Boolean(), nullable=False, server_default=sa.true()),
    sa.Column("max_simultaneous_bookings", sa.Integer(), nullable=False, server_default="1"),
)


def _add_missing_columns(table_name: str, columns: tuple[sa.Column, ...]) -> None:
    existing = {item["name"] for item in inspect(op.get_bind()).get_columns(table_name)}
    with op.batch_alter_table(table_name) as batch_op:
        for column in columns:
            if column.name not in existing:
                batch_op.add_column(column)


def _create_check(table_name: str, name: str, condition: str) -> None:
    existing = {item["name"] for item in inspect(op.get_bind()).get_check_constraints(table_name)}
    if name not in existing:
        with op.batch_alter_table(table_name) as batch_op:
            batch_op.create_check_constraint(name, condition)


def _create_index(table_name: str, name: str, columns: list[str], **kwargs: object) -> None:
    existing = {item["name"] for item in inspect(op.get_bind()).get_indexes(table_name)}
    if name not in existing:
        op.create_index(name, table_name, columns, **kwargs)


def upgrade() -> None:
    _add_missing_columns("businesses", BUSINESS_COLUMNS)
    op.execute(
        text(
            "UPDATE businesses SET status = CASE "
            "WHEN status = 'active' THEN 'active' "
            "WHEN status = 'inactive' THEN 'suspended' "
            "ELSE 'configuration_pending' END "
            "WHERE status NOT IN ('draft','onboarding','configuration_pending','ready',"
            "'active','suspended','archived')"
        )
    )
    _create_check(
        "businesses",
        "ck_businesses_operational_status",
        "status IN ('draft','onboarding','configuration_pending','ready','active',"
        "'suspended','archived')",
    )
    foreign_keys = {
        item.get("name") for item in inspect(op.get_bind()).get_foreign_keys("businesses")
    }
    if "fk_businesses_activated_by_user_id_users" not in foreign_keys:
        with op.batch_alter_table("businesses") as batch_op:
            batch_op.create_foreign_key(
                "fk_businesses_activated_by_user_id_users",
                "users",
                ["activated_by_user_id"],
                ["id"],
                ondelete="SET NULL",
            )
    _create_index("businesses", "ix_businesses_activated_by_user_id", ["activated_by_user_id"])

    _add_missing_columns("services", SERVICE_COLUMNS)
    _create_check(
        "services",
        "ck_services_onboarding_values",
        "(duration_minutes IS NULL OR duration_minutes > 0) AND "
        "(price_amount IS NULL OR price_amount >= 0) AND "
        "buffer_before_minutes >= 0 AND buffer_after_minutes >= 0 AND position >= 0",
    )
    _create_index("services", "ix_services_source_key", ["source_key"])

    _add_missing_columns("availability_settings", AVAILABILITY_COLUMNS)
    _create_check(
        "availability_settings",
        "ck_availability_booking_rules",
        "slot_interval_minutes > 0 AND min_notice_minutes >= 0 AND max_days_ahead > 0 AND "
        "cancellation_notice_minutes >= 0 AND max_simultaneous_bookings >= 1",
    )

    tables = set(inspect(op.get_bind()).get_table_names())
    if "business_onboarding_templates" not in tables:
        op.create_table(
            "business_onboarding_templates",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("key", sa.String(80), nullable=False),
            sa.Column("name", sa.String(160), nullable=False),
            sa.Column("category", sa.String(120), nullable=False),
            sa.Column("description", sa.String(500), nullable=False),
            sa.Column("version", sa.Integer(), nullable=False),
            sa.Column("is_active", sa.Boolean(), nullable=False),
            sa.Column("is_system", sa.Boolean(), nullable=False),
            sa.Column("configuration_json", sa.Text(), nullable=False),
            sa.Column("created_by_user_id", sa.Integer()),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
            sa.CheckConstraint("version > 0", name="ck_onboarding_template_version_positive"),
            sa.ForeignKeyConstraint(["created_by_user_id"], ["users.id"], ondelete="SET NULL"),
            sa.UniqueConstraint("key", "version", name="uq_onboarding_template_key_version"),
        )
        op.create_index(
            "ix_onboarding_templates_active_category",
            "business_onboarding_templates",
            ["is_active", "category"],
        )
        op.create_index(
            "ix_business_onboarding_templates_key",
            "business_onboarding_templates",
            ["key"],
        )
        op.create_index(
            "ix_business_onboarding_templates_category",
            "business_onboarding_templates",
            ["category"],
        )
        op.create_index(
            "ix_business_onboarding_templates_is_active",
            "business_onboarding_templates",
            ["is_active"],
        )
        op.create_index(
            "ix_business_onboarding_templates_created_by_user_id",
            "business_onboarding_templates",
            ["created_by_user_id"],
        )

    tables = set(inspect(op.get_bind()).get_table_names())
    if "business_onboarding_sessions" not in tables:
        op.create_table(
            "business_onboarding_sessions",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("business_id", sa.Integer(), nullable=False),
            sa.Column("template_id", sa.Integer()),
            sa.Column("status", sa.String(30), nullable=False),
            sa.Column("current_step", sa.String(60), nullable=False),
            sa.Column("steps_version", sa.Integer(), nullable=False),
            sa.Column("completed_steps_json", sa.Text(), nullable=False),
            sa.Column("skipped_steps_json", sa.Text(), nullable=False),
            sa.Column("step_activity_json", sa.Text(), nullable=False),
            sa.Column("validation_summary_json", sa.Text()),
            sa.Column("started_by_user_id", sa.Integer(), nullable=False),
            sa.Column("last_updated_by_user_id", sa.Integer(), nullable=False),
            sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("last_activity_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("completed_at", sa.DateTime(timezone=True)),
            sa.Column("cancelled_at", sa.DateTime(timezone=True)),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
            sa.CheckConstraint(
                "status IN ('in_progress','blocked','completed','cancelled')",
                name="ck_onboarding_session_status",
            ),
            sa.CheckConstraint(
                "current_step IN ("
                "'template','business_identity','contact_and_location','services','staff',"
                "'schedules','booking_rules','branding','landing_content','automations',"
                "'integrations','credits_and_plan','readiness_review','preview','activation')",
                name="ck_onboarding_session_current_step",
            ),
            sa.ForeignKeyConstraint(["business_id"], ["businesses.id"], ondelete="CASCADE"),
            sa.ForeignKeyConstraint(
                ["template_id"], ["business_onboarding_templates.id"], ondelete="SET NULL"
            ),
            sa.ForeignKeyConstraint(["started_by_user_id"], ["users.id"], ondelete="RESTRICT"),
            sa.ForeignKeyConstraint(["last_updated_by_user_id"], ["users.id"], ondelete="RESTRICT"),
        )
        for column in (
            "business_id",
            "template_id",
            "started_by_user_id",
            "last_updated_by_user_id",
            "last_activity_at",
        ):
            op.create_index(
                f"ix_business_onboarding_sessions_{column}",
                "business_onboarding_sessions",
                [column],
            )
        op.create_index(
            "ix_onboarding_sessions_status_activity",
            "business_onboarding_sessions",
            ["status", "last_activity_at"],
        )
        dialect = op.get_bind().dialect.name
        where = sa.text("status IN ('in_progress','blocked')")
        kwargs = {"postgresql_where": where} if dialect == "postgresql" else {"sqlite_where": where}
        op.create_index(
            "uq_onboarding_sessions_active_business",
            "business_onboarding_sessions",
            ["business_id"],
            unique=True,
            **kwargs,
        )

    tables = set(inspect(op.get_bind()).get_table_names())
    if "business_staff_profiles" not in tables:
        op.create_table(
            "business_staff_profiles",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("business_id", sa.Integer(), nullable=False),
            sa.Column("linked_business_user_id", sa.Integer()),
            sa.Column("public_name", sa.String(200), nullable=False),
            sa.Column("email", sa.String(320)),
            sa.Column("phone", sa.String(40)),
            sa.Column("role_label", sa.String(120), nullable=False),
            sa.Column("color", sa.String(20)),
            sa.Column("capacity", sa.Integer(), nullable=False),
            sa.Column("active", sa.Boolean(), nullable=False),
            sa.Column("schedule_json", sa.Text()),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
            sa.CheckConstraint("capacity >= 1", name="ck_business_staff_profile_capacity"),
            sa.ForeignKeyConstraint(["business_id"], ["businesses.id"], ondelete="CASCADE"),
            sa.ForeignKeyConstraint(
                ["linked_business_user_id"], ["business_users.id"], ondelete="SET NULL"
            ),
            sa.UniqueConstraint("business_id", "email", name="uq_business_staff_profile_email"),
            sa.UniqueConstraint("linked_business_user_id"),
        )
        op.create_index(
            "ix_business_staff_profiles_business_id",
            "business_staff_profiles",
            ["business_id"],
        )
        op.create_index(
            "ix_business_staff_profiles_linked_business_user_id",
            "business_staff_profiles",
            ["linked_business_user_id"],
        )
        op.create_index(
            "ix_business_staff_profiles_business_active",
            "business_staff_profiles",
            ["business_id", "active"],
        )

    tables = set(inspect(op.get_bind()).get_table_names())
    if "business_staff_profile_services" not in tables:
        op.create_table(
            "business_staff_profile_services",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("staff_profile_id", sa.Integer(), nullable=False),
            sa.Column("service_id", sa.Integer(), nullable=False),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
            sa.ForeignKeyConstraint(
                ["staff_profile_id"], ["business_staff_profiles.id"], ondelete="CASCADE"
            ),
            sa.ForeignKeyConstraint(["service_id"], ["services.id"], ondelete="CASCADE"),
            sa.UniqueConstraint("staff_profile_id", "service_id", name="uq_staff_profile_service"),
        )
        op.create_index(
            "ix_business_staff_profile_services_staff_profile_id",
            "business_staff_profile_services",
            ["staff_profile_id"],
        )
        op.create_index(
            "ix_business_staff_profile_services_service_id",
            "business_staff_profile_services",
            ["service_id"],
        )


def downgrade() -> None:
    op.drop_table("business_staff_profile_services")
    op.drop_table("business_staff_profiles")
    op.drop_table("business_onboarding_sessions")
    op.drop_table("business_onboarding_templates")

    with op.batch_alter_table("availability_settings") as batch_op:
        batch_op.drop_constraint("ck_availability_booking_rules", type_="check")
        for column in reversed(AVAILABILITY_COLUMNS):
            batch_op.drop_column(column.name)

    with op.batch_alter_table("services") as batch_op:
        batch_op.drop_index("ix_services_source_key")
        batch_op.drop_constraint("ck_services_onboarding_values", type_="check")
        for column in reversed(SERVICE_COLUMNS):
            batch_op.drop_column(column.name)

    op.execute(
        text(
            "UPDATE businesses SET status = 'inactive' "
            "WHERE status IN ('draft','onboarding','configuration_pending','ready','suspended','archived')"
        )
    )
    with op.batch_alter_table("businesses") as batch_op:
        batch_op.drop_index("ix_businesses_activated_by_user_id")
        batch_op.drop_constraint("fk_businesses_activated_by_user_id_users", type_="foreignkey")
        batch_op.drop_constraint("ck_businesses_operational_status", type_="check")
        for column in reversed(BUSINESS_COLUMNS):
            batch_op.drop_column(column.name)
