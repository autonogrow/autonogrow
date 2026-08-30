from __future__ import annotations

import json
from pathlib import Path

import pytest
from alembic import command
from scripts.migrate_sqlite_to_postgresql import (
    COPY_ORDER,
    DESTINATION_ONLY_TABLES,
    OPTIONAL_SOURCE_TABLES,
    REQUIRED_SOURCE_TABLES,
    analyze_source_data,
    analyze_source_schema,
    copy_rows,
    require_complete_source,
    require_destination_column_policies,
    require_empty_destination,
    safe_source_database_report,
    structural_checksum,
    structural_checksum_column_names,
    validate_copy_order,
)
from scripts.migrate_sqlite_to_postgresql import (
    main as migration_main,
)
from sqlalchemy import MetaData, Table, create_engine, inspect, text
from sqlalchemy.engine import Engine

from app.core.database import Base
from app.core.migration_state import alembic_config, head_revisions
from app.models.registry import register_models


def upgraded_sqlite(tmp_path: Path, revision: str = "head") -> Engine:
    path = tmp_path / f"source-{revision}.db"
    url = f"sqlite:///{path.as_posix()}"
    config = alembic_config()
    config.attributes["database_url"] = url
    command.upgrade(config, revision)
    return create_engine(url)


def staging_baseline_source(tmp_path: Path) -> Engine:
    source = upgraded_sqlite(tmp_path, "20260730_01")
    with source.begin() as connection:
        connection.execute(text("DROP TABLE alembic_version"))
        connection.execute(
            text("CREATE TABLE app_migrations (name VARCHAR(255) PRIMARY KEY, applied_at DATETIME)")
        )
        connection.execute(
            text("INSERT INTO app_migrations (name) VALUES ('legacy-schema-marker')")
        )
    return source


def reflected_test_table(
    tmp_path: Path,
    database_name: str,
    table_name: str,
    statements: list[str],
) -> tuple[Engine, Table]:
    path = tmp_path / f"{database_name}.db"
    engine = create_engine(f"sqlite:///{path.as_posix()}")
    with engine.begin() as connection:
        for statement in statements:
            connection.exec_driver_sql(statement)
    return engine, Table(table_name, MetaData(), autoload_with=engine)


def test_copy_order_matches_current_metadata_and_foreign_keys() -> None:
    register_models()
    validate_copy_order()
    assert set(COPY_ORDER) == set(Base.metadata.tables)
    assert "operational_states" in COPY_ORDER
    assert "backup_records" in COPY_ORDER
    assert COPY_ORDER.index("users") < COPY_ORDER.index("operational_states")


def test_checksum_is_identical_with_different_physical_column_order(
    tmp_path: Path,
) -> None:
    source, source_table = reflected_test_table(
        tmp_path,
        "checksum-order-source",
        "conversation_automation_settings",
        [
            "CREATE TABLE conversation_automation_settings ("
            "id INTEGER PRIMARY KEY, business_id INTEGER NOT NULL, "
            "period_yyyymm TEXT NOT NULL, period_status TEXT NOT NULL, "
            "included_credits_per_period INTEGER NOT NULL, "
            "included_credits_used INTEGER NOT NULL, "
            "additional_credits_balance INTEGER NOT NULL)",
            "INSERT INTO conversation_automation_settings VALUES "
            "(4, 1, '2026-07', 'open', 10, 2, 3)",
        ],
    )
    destination, destination_table = reflected_test_table(
        tmp_path,
        "checksum-order-destination",
        "conversation_automation_settings",
        [
            "CREATE TABLE conversation_automation_settings ("
            "id INTEGER PRIMARY KEY, business_id INTEGER NOT NULL, "
            "included_credits_per_period INTEGER NOT NULL, "
            "included_credits_used INTEGER NOT NULL, "
            "additional_credits_balance INTEGER NOT NULL, "
            "period_yyyymm TEXT NOT NULL, period_status TEXT NOT NULL)",
            "INSERT INTO conversation_automation_settings VALUES "
            "(4, 1, 10, 2, 3, '2026-07', 'open')",
        ],
    )
    expected_columns = (
        "additional_credits_balance",
        "business_id",
        "id",
        "included_credits_per_period",
        "included_credits_used",
        "period_status",
        "period_yyyymm",
    )
    assert structural_checksum_column_names(source_table) == expected_columns
    assert structural_checksum_column_names(destination_table) == expected_columns
    with source.connect() as source_connection, destination.connect() as destination_connection:
        assert structural_checksum(source_connection, source_table) == structural_checksum(
            destination_connection, destination_table
        )
    source.dispose()
    destination.dispose()


@pytest.mark.parametrize(
    ("table_name", "source_columns", "destination_columns", "row", "fk_column"),
    [
        (
            "bookings",
            "id INTEGER PRIMARY KEY, business_id INTEGER, customer_id INTEGER, "
            "customer_user_id INTEGER, service_id INTEGER, staff_business_user_id INTEGER",
            "id INTEGER PRIMARY KEY, business_id INTEGER REFERENCES businesses(id), "
            "customer_id INTEGER REFERENCES customers(id), "
            "customer_user_id INTEGER REFERENCES users(id), "
            "service_id INTEGER REFERENCES services(id), "
            "staff_business_user_id INTEGER REFERENCES business_users(id)",
            "(80, 42, 40, 10, 30, 20)",
            "staff_business_user_id",
        ),
        (
            "system_incidents",
            "id INTEGER PRIMARY KEY, business_id INTEGER, integration_id INTEGER",
            "id INTEGER PRIMARY KEY, business_id INTEGER REFERENCES businesses(id), "
            "integration_id INTEGER REFERENCES business_channel_integrations(id)",
            "(120, 42, 77)",
            "integration_id",
        ),
    ],
)
def test_checksum_uses_canonical_fk_when_sqlite_does_not_reflect_constraint(
    tmp_path: Path,
    table_name: str,
    source_columns: str,
    destination_columns: str,
    row: str,
    fk_column: str,
) -> None:
    parent_tables = [
        "CREATE TABLE businesses (id INTEGER PRIMARY KEY)",
        "CREATE TABLE customers (id INTEGER PRIMARY KEY)",
        "CREATE TABLE users (id INTEGER PRIMARY KEY)",
        "CREATE TABLE services (id INTEGER PRIMARY KEY)",
        "CREATE TABLE business_users (id INTEGER PRIMARY KEY)",
        "CREATE TABLE business_channel_integrations (id INTEGER PRIMARY KEY)",
    ]
    source, source_table = reflected_test_table(
        tmp_path,
        f"{table_name}-source",
        table_name,
        [
            f"CREATE TABLE {table_name} ({source_columns})",
            f"INSERT INTO {table_name} VALUES {row}",
        ],
    )
    destination, destination_table = reflected_test_table(
        tmp_path,
        f"{table_name}-destination",
        table_name,
        parent_tables
        + [
            f"CREATE TABLE {table_name} ({destination_columns})",
            f"INSERT INTO {table_name} VALUES {row}",
        ],
    )
    assert not source_table.c[fk_column].foreign_keys
    assert destination_table.c[fk_column].foreign_keys
    assert fk_column in structural_checksum_column_names(source_table)
    with source.connect() as source_connection, destination.connect() as destination_connection:
        assert structural_checksum(source_connection, source_table) == structural_checksum(
            destination_connection, destination_table
        )
    source.dispose()
    destination.dispose()


def test_checksum_changes_for_real_structural_value_difference(tmp_path: Path) -> None:
    first, first_table = reflected_test_table(
        tmp_path,
        "checksum-value-first",
        "system_incidents",
        [
            "CREATE TABLE system_incidents ("
            "id INTEGER PRIMARY KEY, business_id INTEGER, integration_id INTEGER)",
            "INSERT INTO system_incidents VALUES (120, 42, 77)",
        ],
    )
    second, second_table = reflected_test_table(
        tmp_path,
        "checksum-value-second",
        "system_incidents",
        [
            "CREATE TABLE system_incidents ("
            "id INTEGER PRIMARY KEY, business_id INTEGER, integration_id INTEGER)",
            "INSERT INTO system_incidents VALUES (120, 42, 78)",
        ],
    )
    with first.connect() as first_connection, second.connect() as second_connection:
        assert structural_checksum(first_connection, first_table) != structural_checksum(
            second_connection, second_table
        )
    first.dispose()
    second.dispose()


def test_allowed_missing_column_is_excluded_symmetrically(tmp_path: Path) -> None:
    source, source_table = reflected_test_table(
        tmp_path,
        "checksum-missing-source",
        "businesses",
        [
            "CREATE TABLE businesses (id INTEGER PRIMARY KEY, slug TEXT, status TEXT)",
            "INSERT INTO businesses VALUES (42, 'legacy-business', 'active')",
        ],
    )
    destination, destination_table = reflected_test_table(
        tmp_path,
        "checksum-missing-destination",
        "businesses",
        [
            "CREATE TABLE businesses ("
            "id INTEGER PRIMARY KEY, slug TEXT, status TEXT, activated_by_user_id INTEGER)",
            "INSERT INTO businesses VALUES (42, 'legacy-business', 'active', NULL)",
        ],
    )
    excluded = frozenset({"activated_by_user_id"})
    with source.connect() as source_connection, destination.connect() as destination_connection:
        assert structural_checksum(
            source_connection, source_table, excluded
        ) == structural_checksum(destination_connection, destination_table, excluded)
    source.dispose()
    destination.dispose()


def test_source_table_classifications_are_explicit_and_complete() -> None:
    assert OPTIONAL_SOURCE_TABLES == (
        "webhook_inbox_events",
        "channel_outbox_messages",
        "worker_heartbeats",
        "business_onboarding_sessions",
        "business_onboarding_templates",
        "business_staff_profiles",
        "business_staff_profile_services",
        "business_channel_controls",
        "instagram_content_settings",
        "instagram_remote_media",
        "instagram_media_sync_states",
        "instagram_raw_assets",
        "instagram_contents",
        "instagram_content_raw_assets",
        "instagram_final_assets",
        "instagram_content_versions",
        "instagram_content_version_assets",
        "instagram_content_editorial_reviews",
        "instagram_content_publication_holds",
        "instagram_content_validations",
        "instagram_content_comments",
        "instagram_publish_jobs",
        "instagram_oauth_attempts",
        "whatsapp_embedded_signup_attempts",
        "meta_integration_jobs",
        "scheduled_customer_followups",
        "customer_opportunities",
        "opportunity_actions",
        "booking_attributions",
        "business_calendar_events",
        "business_growth_signals",
        "customer_memory_items",
        "customer_account_links",
        "business_reviews",
        "social_content_proposals",
        "social_content_proposal_signals",
        "social_idea_reviews",
        "social_promotions",
        "social_promotion_revisions",
        "operational_states",
        "backup_records",
        "business_module_access",
        "pilot_baselines",
    )
    assert DESTINATION_ONLY_TABLES == ("alembic_version",)
    assert set(REQUIRED_SOURCE_TABLES).isdisjoint(OPTIONAL_SOURCE_TABLES)
    assert set(REQUIRED_SOURCE_TABLES) | set(OPTIONAL_SOURCE_TABLES) == set(COPY_ORDER)


def test_exact_30_table_staging_baseline_is_valid(tmp_path: Path) -> None:
    source = staging_baseline_source(tmp_path)
    actual_tables = set(inspect(source).get_table_names())
    assert len(actual_tables) == 30
    assert actual_tables == set(REQUIRED_SOURCE_TABLES) | {"app_migrations"}
    source_tables = require_complete_source(source)
    assert source_tables == REQUIRED_SOURCE_TABLES
    analysis = analyze_source_schema(source)
    assert analysis["absent_optional_tables"] == sorted(OPTIONAL_SOURCE_TABLES)
    assert not analysis["missing_required_tables"]
    assert not analysis["incompatible_columns"]
    assert set(analysis["allowed_missing_columns"]) == {
        "availability_settings",
        "business_channel_integrations",
        "businesses",
        "services",
            "bookings",
            "business_gallery_images",
            "conversations",
            "users",
        "customers",
    }
    report = safe_source_database_report(source, source_tables)
    for table_name in OPTIONAL_SOURCE_TABLES:
        assert report[table_name] == {"present": False, "rows": 0}
    source.dispose()


def test_modern_source_with_new_tables_is_structurally_valid(tmp_path: Path) -> None:
    source = upgraded_sqlite(tmp_path)
    assert require_complete_source(source) == COPY_ORDER
    source.dispose()


def test_modern_source_copies_new_table_rows(tmp_path: Path) -> None:
    source = upgraded_sqlite(tmp_path)
    destination_path = tmp_path / "modern-destination.db"
    destination_url = f"sqlite:///{destination_path.as_posix()}"
    config = alembic_config()
    config.attributes["database_url"] = destination_url
    command.upgrade(config, "head")
    destination = create_engine(destination_url)
    with source.begin() as connection:
        connection.execute(
            text(
                "INSERT INTO operational_states "
                "(id, key, enabled, created_at, updated_at) VALUES "
                "(7, 'modern-state', 1, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)"
            )
        )
        connection.execute(
            text(
                "INSERT INTO backup_records "
                "(id, backup_set_id, backup_type, environment, release_id, artifact_name, "
                "checksum_sha256, size_bytes, status, protected, safe_details_json, "
                "created_at, updated_at) VALUES "
                "(8, 'set-8', 'postgresql', 'test', 'release-8', 'backup-8.dump', "
                ":checksum, 8, 'valid', 0, '{}', CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)"
            ),
            {"checksum": "8" * 64},
        )

    copy_rows(source, destination)
    with destination.connect() as connection:
        assert connection.execute(text("SELECT count(*) FROM operational_states")).scalar_one() == 1
        assert connection.execute(text("SELECT count(*) FROM backup_records")).scalar_one() == 1
        assert (
            connection.execute(
                text("SELECT checksum_sha256 FROM backup_records WHERE id = 8")
            ).scalar_one()
            == "8" * 64
        )
    source.dispose()
    destination.dispose()


def test_baseline_columns_use_only_explicit_safe_defaults_and_nulls(
    tmp_path: Path,
) -> None:
    source = staging_baseline_source(tmp_path)
    destination_path = tmp_path / "baseline-destination.db"
    destination_url = f"sqlite:///{destination_path.as_posix()}"
    config = alembic_config()
    config.attributes["database_url"] = destination_url
    command.upgrade(config, "head")
    destination = create_engine(destination_url)
    with source.begin() as connection:
        connection.execute(
            text(
                "INSERT INTO businesses (id, slug, name, status, created_at, updated_at) "
                "VALUES (42, 'legacy-business', 'Legacy Business', 'inactive', "
                "CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)"
            )
        )
        connection.execute(
            text(
                "INSERT INTO services (id, business_id, name, active, created_at) "
                "VALUES (43, 42, 'Legacy Service', 1, CURRENT_TIMESTAMP)"
            )
        )
        connection.execute(
            text(
                "INSERT INTO availability_settings "
                "(id, business_id, timezone, slot_interval_minutes, "
                "buffer_between_bookings_minutes, min_notice_minutes, max_days_ahead, "
                "weekly_schedule_json, created_at, updated_at) VALUES "
                "(44, 42, 'Europe/Madrid', 15, 0, 120, 30, '{}', "
                "CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)"
            )
        )

    analysis = analyze_source_schema(source)
    data_analysis = analyze_source_data(source)
    assert data_analysis["planned_value_transforms"] == [
        {
            "table": "businesses",
            "column": "status",
            "from": "inactive",
            "to": "suspended",
            "rows": 1,
            "reason": "explicit 20260730_05 Alembic transition",
        }
    ]
    require_destination_column_policies(destination, analysis)
    copy_rows(source, destination)
    with destination.connect() as connection:
        business = connection.execute(
            text(
                "SELECT status, country_code, language_code, timezone, currency, "
                "seo_noindex, activated_at FROM businesses WHERE id = 42"
            )
        ).one()
        assert business == (
            "suspended",
            "ES",
            "es",
            "Europe/Madrid",
            "EUR",
            1,
            None,
        )
        service = connection.execute(
            text(
                "SELECT currency, visible, bookable, requires_approval, "
                "buffer_before_minutes, buffer_after_minutes, position, price_amount "
                "FROM services WHERE id = 43"
            )
        ).one()
        assert service == ("EUR", 1, 1, 0, 0, 0, 0, None)
        availability = connection.execute(
            text(
                "SELECT auto_confirm_bookings, cancellation_allowed, "
                "cancellation_notice_minutes, reschedule_allowed, "
                "max_simultaneous_bookings FROM availability_settings WHERE id = 44"
            )
        ).one()
        assert availability == (1, 1, 120, 1, 1)
    source.dispose()
    destination.dispose()


def test_unknown_legacy_business_status_remains_blocking(tmp_path: Path) -> None:
    source = staging_baseline_source(tmp_path)
    with source.begin() as connection:
        connection.execute(
            text(
                "INSERT INTO businesses (id, slug, name, status, created_at, updated_at) "
                "VALUES (1, 'unknown-status', 'Unknown', 'legacy-unknown', "
                "CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)"
            )
        )
    with pytest.raises(RuntimeError, match="unsupported business statuses.*legacy-unknown"):
        require_complete_source(source)
    source.dispose()


def test_missing_essential_legacy_table_is_still_rejected(tmp_path: Path) -> None:
    source = staging_baseline_source(tmp_path)
    with source.begin() as connection:
        connection.execute(text("DROP TABLE audit_logs"))
    with pytest.raises(RuntimeError, match="missing tables.*audit_logs"):
        require_complete_source(source)
    source.dispose()


def test_incompatible_source_columns_remain_blocking(tmp_path: Path) -> None:
    source = staging_baseline_source(tmp_path)
    with source.begin() as connection:
        connection.execute(text("ALTER TABLE users ADD COLUMN unknown_legacy_value TEXT"))
    analysis = analyze_source_schema(source)
    assert analysis["incompatible_columns"] == {
        "users": {"missing": [], "extra": ["unknown_legacy_value"]}
    }
    with pytest.raises(RuntimeError, match="incompatible columns.*unknown_legacy_value"):
        require_complete_source(source)
    source.dispose()


def test_dry_run_writes_report_before_raising_on_incompatible_source(
    tmp_path: Path, monkeypatch
) -> None:
    source = staging_baseline_source(tmp_path)
    with source.begin() as connection:
        connection.execute(text("ALTER TABLE users ADD COLUMN unknown_legacy_value TEXT"))
    report_path = tmp_path / "blocked-report.json"
    monkeypatch.setattr(
        "sys.argv",
        [
            "migrate_sqlite_to_postgresql.py",
            "--source",
            str(source.url.database),
            "--destination-url",
            "postgresql+psycopg://unused:unused@127.0.0.1:1/unused",
            "--report",
            str(report_path),
        ],
    )
    with pytest.raises(RuntimeError, match="incompatible columns"):
        migration_main()
    report = json.loads(report_path.read_text(encoding="utf-8"))
    assert report["ready_to_apply"] is False
    assert report["copyable_tables"]
    assert report["absent_optional_source_tables"] == sorted(OPTIONAL_SOURCE_TABLES)
    assert report["incompatible_source_columns"]["users"]["extra"] == ["unknown_legacy_value"]
    assert report["blockers"]
    source.dispose()


def test_partial_destination_schema_is_rejected(tmp_path: Path) -> None:
    destination = upgraded_sqlite(tmp_path)
    with destination.begin() as connection:
        connection.execute(text("DROP TABLE backup_records"))
    with pytest.raises(RuntimeError, match="schema is incomplete.*backup_records"):
        require_empty_destination(destination)
    destination.dispose()


def test_alembic_has_expected_single_head() -> None:
    assert head_revisions() == ("20260830_28",)
