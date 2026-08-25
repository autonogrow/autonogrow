"""Validate and copy an AutonoGrow SQLite database into an empty PostgreSQL schema."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any

from sqlalchemy import MetaData, Table, and_, create_engine, func, inspect, or_, select, text
from sqlalchemy.engine import Connection, Engine, make_url

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from alembic import command  # noqa: E402
from alembic.migration import MigrationContext  # noqa: E402

from app.core.config import sanitize_database_url  # noqa: E402
from app.core.database import Base  # noqa: E402
from app.core.migration_state import alembic_config, head_revisions  # noqa: E402
from app.models.registry import register_models  # noqa: E402

COPY_ORDER = (
    "users",
    "operational_states",
    "businesses",
    "business_module_access",
    "pilot_baselines",
    "business_onboarding_templates",
    "business_users",
    "services",
    "business_reviews",
    "business_calendar_events",
    "business_user_services",
    "business_staff_profiles",
    "business_staff_profile_services",
    "business_onboarding_sessions",
    "availability_settings",
    "weekly_availability",
    "blocked_dates",
    "availability_exceptions",
    "business_user_availability",
    "business_user_availability_exceptions",
    "customers",
    "customer_account_links",
    "customer_memory_items",
    "bookings",
    "booking_attachments",
    "scheduled_customer_followups",
    "google_integrations",
    "sync_jobs",
    "review_requests",
    "message_outbox",
    "conversations",
    "conversation_templates",
    "conversation_automation_rules",
    "conversation_messages",
    "conversation_suggestions",
    "conversation_automation_settings",
    "customer_opportunities",
    "opportunity_actions",
    "booking_attributions",
    "business_growth_signals",
    "social_content_proposals",
    "social_content_proposal_signals",
    "social_idea_reviews",
    "social_promotions",
    "social_promotion_revisions",
    "automation_credit_transactions",
    "business_channel_integrations",
    "business_channel_controls",
    "instagram_content_settings",
    "instagram_contents",
    "instagram_remote_media",
    "instagram_media_sync_states",
    "instagram_raw_assets",
    "instagram_content_raw_assets",
    "instagram_final_assets",
    "instagram_content_versions",
    "instagram_content_version_assets",
    "instagram_content_editorial_reviews",
    "instagram_content_validations",
    "instagram_content_comments",
    "instagram_publish_jobs",
    "instagram_oauth_attempts",
    "whatsapp_embedded_signup_attempts",
    "meta_integration_jobs",
    "system_incidents",
    "audit_logs",
    "business_gallery_images",
    "webhook_inbox_events",
    "channel_outbox_messages",
    "worker_heartbeats",
    "backup_records",
)

# Tables introduced after the 20260730_01 staging baseline. If present they are
# copied normally; older sources may omit them without synthesizing rows.
OPTIONAL_SOURCE_TABLES = (
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
REQUIRED_SOURCE_TABLES = tuple(
    table_name for table_name in COPY_ORDER if table_name not in OPTIONAL_SOURCE_TABLES
)

# Alembic owns this destination control table. It is validated, but never copied.
DESTINATION_ONLY_TABLES = ("alembic_version",)

# Closed compatibility matrix for columns added after the staging baseline.
# Values are safe expected values after PostgreSQL applies its explicit default,
# or None when omission is intentionally represented as SQL NULL.
ALLOWED_MISSING_SOURCE_COLUMNS: dict[str, dict[str, dict[str, Any]]] = {
    "users": {
        "phone_normalized": {"action": "omit_as_null", "expected_value": None},
        "phone_verified": {"action": "use_destination_default", "expected_value": False},
        "instagram_username": {"action": "omit_as_null", "expected_value": None},
        "instagram_provider_user_id": {"action": "omit_as_null", "expected_value": None},
        "instagram_verified": {
            "action": "use_destination_default",
            "expected_value": False,
        },
    },
    "customers": {
        "phone_normalized": {"action": "omit_as_null", "expected_value": None},
    },
    "business_gallery_images": {
        "service_id": {"action": "omit_as_null", "expected_value": None},
    },
    "instagram_raw_assets": {
        "service_id": {"action": "omit_as_null", "expected_value": None},
        "active": {"action": "use_destination_default", "expected_value": True},
        "source_kind": {
            "action": "use_destination_default",
            "expected_value": "business_upload",
        },
        "source_remote_media_id": {"action": "omit_as_null", "expected_value": None},
        "sha256": {"action": "omit_as_null", "expected_value": None},
    },
    "instagram_final_assets": {
        "source_raw_asset_id": {"action": "omit_as_null", "expected_value": None},
        "derivation_fingerprint": {"action": "omit_as_null", "expected_value": None},
    },
    "instagram_contents": {
        "source_proposal_id": {"action": "omit_as_null", "expected_value": None},
    },
    "instagram_content_versions": {
        "editorial_package_json": {"action": "omit_as_null", "expected_value": None},
        "generation_source": {"action": "omit_as_null", "expected_value": None},
        "generator_version": {"action": "omit_as_null", "expected_value": None},
        "story_transform_json": {"action": "omit_as_null", "expected_value": None},
        "story_renderer_version": {"action": "omit_as_null", "expected_value": None},
    },
    "business_channel_integrations": {
        "provider_account_id": {"action": "omit_as_null", "expected_value": None},
        "health_status": {"action": "use_destination_default", "expected_value": "unknown"},
        "last_health_check_at": {"action": "omit_as_null", "expected_value": None},
        "next_health_check_at": {"action": "omit_as_null", "expected_value": None},
        "consecutive_health_failures": {
            "action": "use_destination_default",
            "expected_value": 0,
        },
        "health_error_code": {"action": "omit_as_null", "expected_value": None},
        "health_safe_error_message": {"action": "omit_as_null", "expected_value": None},
        "health_metadata_json": {"action": "omit_as_null", "expected_value": None},
    },
    "businesses": {
        "whatsapp_phone": {"action": "omit_as_null", "expected_value": None},
        "public_email": {"action": "omit_as_null", "expected_value": None},
        "postal_code": {"action": "omit_as_null", "expected_value": None},
        "region": {"action": "omit_as_null", "expected_value": None},
        "country_code": {"action": "use_destination_default", "expected_value": "ES"},
        "language_code": {"action": "use_destination_default", "expected_value": "es"},
        "timezone": {
            "action": "use_destination_default",
            "expected_value": "Europe/Madrid",
        },
        "currency": {"action": "use_destination_default", "expected_value": "EUR"},
        "legal_name": {"action": "omit_as_null", "expected_value": None},
        "tax_identifier": {"action": "omit_as_null", "expected_value": None},
        "tiktok_url": {"action": "omit_as_null", "expected_value": None},
        "external_website_url": {"action": "omit_as_null", "expected_value": None},
        "landing_cta": {"action": "omit_as_null", "expected_value": None},
        "seo_title": {"action": "omit_as_null", "expected_value": None},
        "seo_description": {"action": "omit_as_null", "expected_value": None},
        "seo_noindex": {"action": "use_destination_default", "expected_value": True},
        "activated_at": {"action": "omit_as_null", "expected_value": None},
        "activated_by_user_id": {"action": "omit_as_null", "expected_value": None},
        "status_updated_at": {"action": "omit_as_null", "expected_value": None},
        "archived_at": {"action": "omit_as_null", "expected_value": None},
    },
    "services": {
        "price_amount": {"action": "omit_as_null", "expected_value": None},
        "currency": {"action": "use_destination_default", "expected_value": "EUR"},
        "category": {"action": "omit_as_null", "expected_value": None},
        "visible": {"action": "use_destination_default", "expected_value": True},
        "bookable": {"action": "use_destination_default", "expected_value": True},
        "requires_approval": {
            "action": "use_destination_default",
            "expected_value": False,
        },
        "buffer_before_minutes": {
            "action": "use_destination_default",
            "expected_value": 0,
        },
        "buffer_after_minutes": {
            "action": "use_destination_default",
            "expected_value": 0,
        },
        "position": {"action": "use_destination_default", "expected_value": 0},
        "source_key": {"action": "omit_as_null", "expected_value": None},
        "archived_at": {"action": "omit_as_null", "expected_value": None},
        "follow_up_enabled": {
            "action": "use_destination_default",
            "expected_value": False,
        },
        "follow_up_interval_days": {"action": "omit_as_null", "expected_value": None},
        "follow_up_window_days": {
            "action": "use_destination_default",
            "expected_value": 0,
        },
    },
    "bookings": {
        "price_amount_snapshot": {
            "action": "omit_as_null",
            "expected_value": None,
        },
        "currency_snapshot": {
            "action": "omit_as_null",
            "expected_value": None,
        },
        "follow_up_enabled_snapshot": {
            "action": "use_destination_default",
            "expected_value": False,
        },
        "follow_up_interval_days_snapshot": {
            "action": "omit_as_null",
            "expected_value": None,
        },
        "follow_up_window_days_snapshot": {
            "action": "omit_as_null",
            "expected_value": None,
        },
    },
    "availability_settings": {
        "auto_confirm_bookings": {
            "action": "use_destination_default",
            "expected_value": True,
        },
        "cancellation_allowed": {
            "action": "use_destination_default",
            "expected_value": True,
        },
        "cancellation_notice_minutes": {
            "action": "use_destination_default",
            "expected_value": 120,
        },
        "reschedule_allowed": {
            "action": "use_destination_default",
            "expected_value": True,
        },
        "max_simultaneous_bookings": {
            "action": "use_destination_default",
            "expected_value": 1,
        },
    },
    "webhook_inbox_events": {"request_id": {"action": "omit_as_null", "expected_value": None}},
    "channel_outbox_messages": {"request_id": {"action": "omit_as_null", "expected_value": None}},
}

BUSINESS_STATUS_VALUES = frozenset(
    {"draft", "onboarding", "configuration_pending", "ready", "active", "suspended", "archived"}
)
COPY_VALUE_TRANSFORMS = {
    "businesses": {"status": {"inactive": "suspended"}},
}

SENSITIVE_COLUMNS = {
    "encrypted_access_token",
    "candidate_encrypted_access_token",
    "session_fingerprint_hash",
    "state_hash",
    "body",
    "message",
    "payload_json",
    "safe_metadata_json",
    "email",
    "phone",
    "customer_email",
}

CRITICAL_CHECKSUM_COLUMNS = {
    "automation_credit_transactions": frozenset(
        {
            "transaction_type",
            "amount",
            "included_delta",
            "additional_delta",
            "included_balance_after",
            "additional_balance_after",
            "total_balance_after",
            "payment_amount",
            "idempotency_key",
        }
    ),
    "conversation_automation_settings": frozenset(
        {
            "included_credits_per_period",
            "included_credits_used",
            "additional_credits_balance",
            "period_yyyymm",
            "period_status",
        }
    ),
    "business_channel_integrations": frozenset(
        {
            "integration_status",
            "health_status",
            "consecutive_health_failures",
            "encryption_key_version",
            "external_account_id",
        }
    ),
    "instagram_oauth_attempts": frozenset(
        {
            "status",
            "purpose",
            "candidate_encryption_key_version",
            "candidate_external_account_id",
        }
    ),
    "whatsapp_embedded_signup_attempts": frozenset(
        {
            "status",
            "purpose",
            "candidate_encryption_key_version",
            "candidate_waba_id",
            "candidate_phone_number_id",
        }
    ),
    "meta_integration_jobs": frozenset(
        {"job_type", "status", "idempotency_key", "origin", "attempt_count"}
    ),
    "webhook_inbox_events": frozenset({"idempotency_key", "payload_hash", "status"}),
    "channel_outbox_messages": frozenset({"idempotency_key", "status"}),
    "backup_records": frozenset(
        {"backup_set_id", "checksum_sha256", "size_bytes", "status", "protected"}
    ),
    "businesses": frozenset({"slug", "status"}),
}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", required=True, help="SQLite file path or sqlite:/// URL")
    parser.add_argument(
        "--destination-url",
        default=os.getenv("DATABASE_URL", ""),
        help="PostgreSQL URL; defaults to DATABASE_URL",
    )
    parser.add_argument("--report", default="migration_report.json")
    parser.add_argument("--apply", action="store_true", help="Perform the copy")
    parser.add_argument(
        "--upgrade-destination",
        action="store_true",
        help="Explicitly run Alembic upgrade head before validation",
    )
    return parser.parse_args()


def source_url(value: str) -> str:
    stripped = value.strip()
    if stripped.startswith("sqlite:"):
        return stripped
    path = Path(stripped).expanduser().resolve()
    return f"sqlite:///{path.as_posix()}"


def validate_urls(sqlite_url: str, postgresql_url: str) -> None:
    source = make_url(sqlite_url)
    destination = make_url(postgresql_url)
    if source.get_backend_name() != "sqlite" or source.database in {None, "", ":memory:"}:
        raise ValueError("Source must be a persistent SQLite database")
    if destination.get_backend_name() != "postgresql":
        raise ValueError("Destination must be PostgreSQL")
    if str(source) == str(destination):
        raise ValueError("Source and destination cannot be the same database")
    if not Path(source.database).is_file():
        raise ValueError("Source SQLite file does not exist")


def validate_copy_order() -> None:
    register_models()
    expected = set(Base.metadata.tables)
    declared = set(COPY_ORDER)
    if len(COPY_ORDER) != len(declared) or expected != declared:
        missing = sorted(expected - declared)
        extra = sorted(declared - expected)
        raise RuntimeError(f"COPY_ORDER mismatch; missing={missing}, extra={extra}")
    classified = set(REQUIRED_SOURCE_TABLES) | set(OPTIONAL_SOURCE_TABLES)
    if classified != declared or set(REQUIRED_SOURCE_TABLES) & set(OPTIONAL_SOURCE_TABLES):
        raise RuntimeError("Source table classifications do not match COPY_ORDER")
    if set(DESTINATION_ONLY_TABLES) & declared:
        raise RuntimeError("Destination-only tables cannot be present in COPY_ORDER")
    if not set(ALLOWED_MISSING_SOURCE_COLUMNS) <= declared:
        raise RuntimeError("Missing-column policies reference tables outside COPY_ORDER")
    positions = {name: index for index, name in enumerate(COPY_ORDER)}
    for table in Base.metadata.tables.values():
        for foreign_key in table.foreign_keys:
            parent = foreign_key.column.table.name
            if parent != table.name and positions[parent] > positions[table.name]:
                raise RuntimeError(f"COPY_ORDER places {table.name} before dependency {parent}")


def current_revisions(engine: Engine) -> tuple[str, ...]:
    with engine.connect() as connection:
        return tuple(sorted(MigrationContext.configure(connection).get_current_heads()))


def require_destination_at_head(engine: Engine) -> None:
    current = current_revisions(engine)
    expected = head_revisions()
    if len(expected) != 1 or current != expected:
        raise RuntimeError(
            f"Destination is not at the single Alembic head; current={current}, expected={expected}"
        )


def analyze_source_schema(engine_or_connection: Engine | Connection) -> dict[str, Any]:
    """Describe legacy compatibility without raising or changing either database."""

    register_models()
    inspector = inspect(engine_or_connection)
    tables = set(inspector.get_table_names())
    copyable_tables = [table_name for table_name in COPY_ORDER if table_name in tables]
    absent_optional_tables = sorted(set(OPTIONAL_SOURCE_TABLES) - tables)
    missing_required_tables = sorted(set(REQUIRED_SOURCE_TABLES) - tables)
    allowed_missing_columns: dict[str, dict[str, dict[str, Any]]] = {}
    column_mismatches: dict[str, dict[str, list[str]]] = {}
    for table_name in COPY_ORDER:
        if table_name not in tables:
            continue
        expected_columns = set(Base.metadata.tables[table_name].columns.keys())
        source_columns = {column["name"] for column in inspector.get_columns(table_name)}
        missing_columns = expected_columns - source_columns
        policies = ALLOWED_MISSING_SOURCE_COLUMNS.get(table_name, {})
        allowed = {
            column_name: policies[column_name]
            for column_name in sorted(missing_columns & set(policies))
        }
        if allowed:
            allowed_missing_columns[table_name] = allowed
        incompatible_missing = sorted(missing_columns - set(policies))
        extra_columns = sorted(source_columns - expected_columns)
        if incompatible_missing or extra_columns:
            column_mismatches[table_name] = {
                "missing": incompatible_missing,
                "extra": extra_columns,
            }
    blockers: list[str] = []
    if missing_required_tables:
        blockers.append(f"Source schema is incomplete; missing tables: {missing_required_tables}")
    if column_mismatches:
        blockers.append(
            "Source schema has incompatible columns: "
            + json.dumps(column_mismatches, sort_keys=True)
        )
    return {
        "copyable_tables": copyable_tables,
        "absent_optional_tables": absent_optional_tables,
        "missing_required_tables": missing_required_tables,
        "allowed_missing_columns": allowed_missing_columns,
        "incompatible_columns": column_mismatches,
        "blockers": blockers,
    }


def source_copy_order(engine_or_connection: Engine | Connection) -> tuple[str, ...]:
    """Return present copyable tables after strict legacy schema validation."""

    analysis = analyze_source_schema(engine_or_connection)
    if analysis["missing_required_tables"]:
        raise RuntimeError(
            f"Source schema is incomplete; missing tables: {analysis['missing_required_tables']}"
        )
    if analysis["incompatible_columns"]:
        raise RuntimeError(
            "Source schema has incompatible columns: "
            + json.dumps(analysis["incompatible_columns"], sort_keys=True)
        )
    return tuple(analysis["copyable_tables"])


def missing_source_columns(
    analysis: dict[str, Any],
) -> dict[str, frozenset[str]]:
    return {
        table_name: frozenset(columns)
        for table_name, columns in analysis["allowed_missing_columns"].items()
    }


def normalize_copy_value(table_name: str, column_name: str, value: Any) -> Any:
    transforms = COPY_VALUE_TRANSFORMS.get(table_name, {}).get(column_name, {})
    return transforms.get(value, value)


def prepared_row(table_name: str, row: Any) -> dict[str, Any]:
    return {
        column_name: normalize_copy_value(table_name, column_name, value)
        for column_name, value in dict(row).items()
    }


def analyze_source_data(engine: Engine) -> dict[str, Any]:
    """Validate legacy data against constraints that exist at the destination head."""

    metadata = MetaData()
    with engine.connect() as connection:
        integrity_rows = connection.exec_driver_sql("PRAGMA integrity_check").fetchmany(20)
        integrity = [str(row[0]) for row in integrity_rows]
        foreign_key_violations = connection.exec_driver_sql("PRAGMA foreign_key_check").fetchmany(
            20
        )
        businesses = Table("businesses", metadata, autoload_with=connection)
        integrations = Table("business_channel_integrations", metadata, autoload_with=connection)
        settings = Table("conversation_automation_settings", metadata, autoload_with=connection)
        credits = Table("automation_credit_transactions", metadata, autoload_with=connection)
        bookings = Table("bookings", metadata, autoload_with=connection)
        services = Table("services", metadata, autoload_with=connection)
        availability = Table("availability_settings", metadata, autoload_with=connection)

        status_rows = connection.execute(
            select(businesses.c.status, func.count()).group_by(businesses.c.status)
        ).all()
        status_counts = {str(value): int(count) for value, count in status_rows}
        unsupported_statuses = sorted(
            value
            for value in status_counts
            if value not in BUSINESS_STATUS_VALUES and value != "inactive"
        )
        planned_value_transforms = []
        if status_counts.get("inactive"):
            planned_value_transforms.append(
                {
                    "table": "businesses",
                    "column": "status",
                    "from": "inactive",
                    "to": "suspended",
                    "rows": status_counts["inactive"],
                    "reason": "explicit 20260730_05 Alembic transition",
                }
            )

        missing_ciphertext = int(
            connection.execute(
                select(func.count())
                .select_from(integrations)
                .where(
                    integrations.c.integration_status.in_(("connected", "degraded")),
                    (
                        integrations.c.encrypted_access_token.is_(None)
                        | integrations.c.encryption_key_version.is_(None)
                    ),
                )
            ).scalar_one()
        )

        constraint_violations = {
            "conversation_automation_settings.credit_balances": int(
                connection.execute(
                    select(func.count())
                    .select_from(settings)
                    .where(
                        or_(
                            settings.c.included_credits_per_period < 0,
                            settings.c.included_credits_used < 0,
                            settings.c.included_credits_used
                            > settings.c.included_credits_per_period,
                            settings.c.additional_credits_balance < 0,
                            settings.c.auto_used_current_period < 0,
                        )
                    )
                ).scalar_one()
            ),
            "automation_credit_transactions.ledger": int(
                connection.execute(
                    select(func.count())
                    .select_from(credits)
                    .where(
                        or_(
                            and_(
                                credits.c.amount < 0,
                                credits.c.transaction_type.not_in(
                                    ("manual_adjustment", "correction")
                                ),
                            ),
                            credits.c.included_balance_after < 0,
                            credits.c.additional_balance_after < 0,
                            credits.c.total_balance_after < 0,
                            credits.c.total_balance_after
                            != credits.c.included_balance_after
                            + credits.c.additional_balance_after,
                            credits.c.payment_amount < 0,
                        )
                    )
                ).scalar_one()
            ),
            "bookings.modern_checks": int(
                connection.execute(
                    select(func.count())
                    .select_from(bookings)
                    .where(
                        or_(
                            bookings.c.duration_minutes <= 0,
                            and_(
                                bookings.c.start_datetime.is_not(None),
                                bookings.c.end_datetime.is_not(None),
                                bookings.c.end_datetime <= bookings.c.start_datetime,
                            ),
                        )
                    )
                ).scalar_one()
            ),
            "services.modern_checks": int(
                connection.execute(
                    select(func.count())
                    .select_from(services)
                    .where(services.c.duration_minutes <= 0)
                ).scalar_one()
            ),
            "availability_settings.modern_checks": int(
                connection.execute(
                    select(func.count())
                    .select_from(availability)
                    .where(
                        or_(
                            availability.c.slot_interval_minutes <= 0,
                            availability.c.min_notice_minutes < 0,
                            availability.c.max_days_ahead <= 0,
                        )
                    )
                ).scalar_one()
            ),
        }
    constraint_violations = {name: count for name, count in constraint_violations.items() if count}
    blockers: list[str] = []
    if integrity != ["ok"]:
        blockers.append(f"Source SQLite integrity validation failed: {integrity}")
    if foreign_key_violations:
        blockers.append("Source SQLite foreign-key validation failed")
    if missing_ciphertext:
        blockers.append("Source has active integrations without complete ciphertext metadata")
    if unsupported_statuses:
        blockers.append(f"Source has unsupported business statuses: {unsupported_statuses}")
    if constraint_violations:
        blockers.append(
            "Source data violates destination constraints: "
            + json.dumps(constraint_violations, sort_keys=True)
        )
    return {
        "integrity_check": integrity,
        "foreign_key_violations": len(foreign_key_violations),
        "missing_active_integration_ciphertext": missing_ciphertext,
        "business_status_counts": status_counts,
        "planned_value_transforms": planned_value_transforms,
        "constraint_violations": constraint_violations,
        "blockers": blockers,
    }


def require_complete_source(engine: Engine) -> tuple[str, ...]:
    copy_order = source_copy_order(engine)
    data_analysis = analyze_source_data(engine)
    if data_analysis["blockers"]:
        raise RuntimeError("; ".join(data_analysis["blockers"]))
    return copy_order


def table_counts(engine: Engine, table_names: tuple[str, ...] = COPY_ORDER) -> dict[str, int]:
    metadata = MetaData()
    result: dict[str, int] = {}
    with engine.connect() as connection:
        for table_name in table_names:
            table = Table(table_name, metadata, autoload_with=connection)
            result[table_name] = int(
                connection.execute(select(func.count()).select_from(table)).scalar_one()
            )
    return result


def require_empty_destination(engine: Engine) -> None:
    present = set(inspect(engine).get_table_names())
    missing = sorted(set(COPY_ORDER) - present)
    if missing:
        raise RuntimeError(f"Destination schema is incomplete despite Alembic head: {missing}")
    unexpected = sorted(present - set(COPY_ORDER) - set(DESTINATION_ONLY_TABLES))
    if unexpected:
        raise RuntimeError(f"Destination schema contains unexpected tables: {unexpected}")
    populated = {name: count for name, count in table_counts(engine).items() if count}
    if populated:
        raise RuntimeError(
            "Destination is populated or partially migrated; clean and recreate it before retrying: "
            + json.dumps(populated, sort_keys=True)
        )


def safe_json_value(value: Any) -> Any:
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if isinstance(value, Decimal):
        return str(value)
    return value


def structural_checksum(
    connection: Connection,
    table: Table,
    excluded_columns: frozenset[str] = frozenset(),
) -> str:
    column_names = structural_checksum_column_names(table, excluded_columns)
    columns = [table.c[column_name] for column_name in column_names]
    if not columns:
        return hashlib.sha256(b"").hexdigest()
    canonical_table = Base.metadata.tables[table.name]
    primary_key_names = sorted(
        column.name
        for column in canonical_table.primary_key.columns
        if column.name in table.c and column.name not in excluded_columns
    )
    order_columns = [table.c[column_name] for column_name in primary_key_names]
    statement = select(*columns)
    if order_columns:
        statement = statement.order_by(*order_columns)
    rows = connection.execute(statement).all()
    payload = {
        "columns": list(column_names),
        "rows": [
            [
                [
                    column_name,
                    safe_json_value(normalize_copy_value(table.name, column_name, value)),
                ]
                for column_name, value in zip(column_names, row, strict=True)
            ]
            for row in rows
        ],
    }
    return hashlib.sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()


def structural_checksum_column_names(
    table: Table,
    excluded_columns: frozenset[str] = frozenset(),
) -> tuple[str, ...]:
    """Select semantic checksum columns from canonical application metadata."""

    register_models()
    if table.name not in Base.metadata.tables:
        raise RuntimeError(f"No canonical metadata exists for table {table.name}")
    canonical_table = Base.metadata.tables[table.name]
    critical_names = CRITICAL_CHECKSUM_COLUMNS.get(table.name, frozenset())
    physical_names = set(table.columns.keys())
    return tuple(
        sorted(
            column.name
            for column in canonical_table.columns
            if column.name in physical_names
            and column.name not in SENSITIVE_COLUMNS
            and column.name not in excluded_columns
            and (column.primary_key or column.foreign_keys or column.name in critical_names)
        )
    )


def inspect_table(
    connection: Connection,
    table: Table,
    excluded_columns: frozenset[str] = frozenset(),
) -> dict[str, Any]:
    primary_keys = list(table.primary_key.columns)
    primary_key = primary_keys[0] if len(primary_keys) == 1 else None
    result: dict[str, Any] = {
        "present": True,
        "rows": int(connection.execute(select(func.count()).select_from(table)).scalar_one()),
        "structural_checksum": structural_checksum(connection, table, excluded_columns),
        "critical_nulls": {},
    }
    if primary_key is not None:
        minimum, maximum = connection.execute(
            select(func.min(primary_key), func.max(primary_key))
        ).one()
        result["pk_min"] = minimum
        result["pk_max"] = maximum
    for column in table.columns:
        if column.nullable or column.primary_key:
            continue
        null_count = connection.execute(
            select(func.count()).select_from(table).where(column.is_(None))
        ).scalar_one()
        if null_count:
            result["critical_nulls"][column.name] = int(null_count)
    for state_column in ("status", "integration_status", "period_status"):
        if state_column in table.c:
            column = table.c[state_column]
            state_rows = connection.execute(
                select(column, func.count()).group_by(column).order_by(column)
            ).all()
            result[f"{state_column}_counts"] = {
                str(value): int(count) for value, count in state_rows
            }
    if table.name == "business_channel_integrations":
        ciphertext = table.c.encrypted_access_token
        present = connection.execute(
            select(func.count()).select_from(table).where(ciphertext.is_not(None))
        ).scalar_one()
        lengths = connection.execute(
            select(func.min(func.length(ciphertext)), func.max(func.length(ciphertext))).where(
                ciphertext.is_not(None)
            )
        ).one()
        result["ciphertext"] = {
            "present": int(present),
            "min_length": lengths[0],
            "max_length": lengths[1],
        }
    return result


def safe_database_report(
    engine: Engine, table_names: tuple[str, ...] = COPY_ORDER
) -> dict[str, Any]:
    with engine.connect() as connection:
        return safe_connection_report(connection, table_names)


def safe_connection_report(
    connection: Connection,
    table_names: tuple[str, ...] = COPY_ORDER,
    excluded_columns: dict[str, frozenset[str]] | None = None,
) -> dict[str, Any]:
    metadata = MetaData()
    result: dict[str, Any] = {}
    for table_name in table_names:
        table = Table(table_name, metadata, autoload_with=connection)
        result[table_name] = inspect_table(
            connection,
            table,
            (excluded_columns or {}).get(table_name, frozenset()),
        )
    return result


def safe_source_connection_report(
    connection: Connection,
    source_tables: tuple[str, ...],
    excluded_columns: dict[str, frozenset[str]] | None = None,
) -> dict[str, Any]:
    present_report = safe_connection_report(connection, source_tables, excluded_columns)
    return {
        table_name: present_report.get(table_name, {"present": False, "rows": 0})
        for table_name in COPY_ORDER
    }


def safe_source_database_report(
    engine: Engine, source_tables: tuple[str, ...] | None = None
) -> dict[str, Any]:
    validated_tables = source_tables or source_copy_order(engine)
    excluded_columns = missing_source_columns(analyze_source_schema(engine))
    with engine.connect() as connection:
        return safe_source_connection_report(connection, validated_tables, excluded_columns)


def copy_rows(source: Engine, destination: Engine) -> None:
    source_metadata = MetaData()
    destination_metadata = MetaData()
    with source.connect() as source_connection, destination.begin() as destination_connection:
        for table_name in source_copy_order(source_connection):
            source_table = Table(table_name, source_metadata, autoload_with=source_connection)
            destination_table = Table(
                table_name, destination_metadata, autoload_with=destination_connection
            )
            rows = source_connection.execute(select(source_table)).mappings()
            while batch := rows.fetchmany(500):
                destination_connection.execute(
                    destination_table.insert(),
                    [prepared_row(table_name, row) for row in batch],
                )


def require_destination_column_policies(engine: Engine, source_analysis: dict[str, Any]) -> None:
    inspector = inspect(engine)
    incompatible: dict[str, dict[str, str]] = {}
    for table_name, policies in source_analysis["allowed_missing_columns"].items():
        destination_columns = {
            column["name"]: column for column in inspector.get_columns(table_name)
        }
        for column_name, policy in policies.items():
            destination_column = destination_columns[column_name]
            action = policy["action"]
            if action == "use_destination_default" and destination_column.get("default") is None:
                incompatible.setdefault(table_name, {})[column_name] = (
                    "destination default is missing"
                )
            if action == "omit_as_null" and not destination_column.get("nullable"):
                incompatible.setdefault(table_name, {})[column_name] = (
                    "destination column is not nullable"
                )
    if incompatible:
        raise RuntimeError(
            "Destination cannot apply legacy column policies: "
            + json.dumps(incompatible, sort_keys=True)
        )


def omitted_column_differences(
    connection: Connection, source_analysis: dict[str, Any]
) -> list[str]:
    metadata = MetaData()
    differences: list[str] = []
    for table_name, policies in source_analysis["allowed_missing_columns"].items():
        table = Table(table_name, metadata, autoload_with=connection)
        for column_name, policy in policies.items():
            column = table.c[column_name]
            expected = policy["expected_value"]
            mismatch = (
                column.is_not(None)
                if expected is None
                else or_(column.is_(None), column != expected)
            )
            count = connection.execute(
                select(func.count()).select_from(table).where(mismatch)
            ).scalar_one()
            if count:
                differences.append(f"{table_name}.{column_name}.legacy_policy")
    return differences


def reset_sequences(engine: Engine) -> dict[str, dict[str, int]]:
    with engine.begin() as connection:
        return reset_sequences_on_connection(connection)


def reset_sequences_on_connection(connection: Connection) -> dict[str, dict[str, int]]:
    result: dict[str, dict[str, int]] = {}
    metadata = MetaData()
    for table_name in COPY_ORDER:
        table = Table(table_name, metadata, autoload_with=connection)
        primary_keys = list(table.primary_key.columns)
        if len(primary_keys) != 1 or primary_keys[0].type.python_type is not int:
            continue
        column = primary_keys[0]
        sequence = connection.execute(
            text("SELECT pg_get_serial_sequence(:table_name, :column_name)"),
            {"table_name": table_name, "column_name": column.name},
        ).scalar_one_or_none()
        if not sequence:
            continue
        maximum = int(connection.execute(select(func.max(column))).scalar_one() or 0)
        if maximum:
            connection.execute(
                text("SELECT setval(CAST(:sequence AS regclass), :value, true)"),
                {"sequence": sequence, "value": maximum},
            )
        else:
            connection.execute(
                text("SELECT setval(CAST(:sequence AS regclass), 1, false)"),
                {"sequence": sequence},
            )
        candidate = int(
            connection.execute(
                text("SELECT nextval(CAST(:sequence AS regclass))"),
                {"sequence": sequence},
            ).scalar_one()
        )
        if candidate <= maximum:
            raise RuntimeError(f"Sequence validation failed for {table_name}.{column.name}")
        connection.execute(
            text("SELECT setval(CAST(:sequence AS regclass), :value, :called)"),
            {
                "sequence": sequence,
                "value": candidate - 1 if maximum else 1,
                "called": bool(maximum),
            },
        )
        result[table_name] = {"max_imported_id": maximum, "next_candidate": candidate}
    return result


def verify_migration(source: Engine, destination: Engine) -> dict[str, Any]:
    source_analysis = analyze_source_schema(source)
    source_tables = source_copy_order(source)
    excluded_columns = missing_source_columns(source_analysis)
    source_report = safe_source_database_report(source, source_tables)
    with destination.connect() as destination_connection:
        destination_report = safe_connection_report(
            destination_connection, COPY_ORDER, excluded_columns
        )
        policy_differences = omitted_column_differences(destination_connection, source_analysis)
    differences: list[str] = []
    for table_name in COPY_ORDER:
        source_table = source_report[table_name]
        destination_table = destination_report[table_name]
        if not source_table["present"]:
            if destination_table["rows"]:
                differences.append(f"{table_name}.unexpected_destination_rows")
            continue
        for key in ("rows", "pk_min", "pk_max", "structural_checksum", "critical_nulls"):
            if source_table.get(key) != destination_table.get(key):
                differences.append(f"{table_name}.{key}")
    differences.extend(policy_differences)
    if differences:
        raise RuntimeError(f"Migration validation failed: {differences}")
    source_metadata = MetaData()
    destination_metadata = MetaData()
    with source.connect() as source_connection, destination.connect() as destination_connection:
        source_table = Table(
            "business_channel_integrations", source_metadata, autoload_with=source_connection
        )
        destination_table = Table(
            "business_channel_integrations",
            destination_metadata,
            autoload_with=destination_connection,
        )
        source_ciphertext = source_connection.execute(
            select(source_table.c.id, source_table.c.encrypted_access_token).order_by(
                source_table.c.id
            )
        ).all()
        destination_ciphertext = destination_connection.execute(
            select(destination_table.c.id, destination_table.c.encrypted_access_token).order_by(
                destination_table.c.id
            )
        ).all()
    return {
        "source": source_report,
        "destination": destination_report,
        "ciphertext_exact_match": source_ciphertext == destination_ciphertext,
    }


def copy_and_validate_atomic(source: Engine, destination: Engine) -> dict[str, Any]:
    """Copy and validate all rows in one destination transaction."""

    source_metadata = MetaData()
    destination_metadata = MetaData()
    with source.connect() as source_connection, destination.connect() as destination_connection:
        source_analysis = analyze_source_schema(source_connection)
        source_tables = source_copy_order(source_connection)
        excluded_columns = missing_source_columns(source_analysis)
        transaction = destination_connection.begin()
        try:
            for table_name in source_tables:
                source_table = Table(table_name, source_metadata, autoload_with=source_connection)
                destination_table = Table(
                    table_name,
                    destination_metadata,
                    autoload_with=destination_connection,
                )
                rows = source_connection.execute(select(source_table)).mappings()
                while batch := rows.fetchmany(500):
                    destination_connection.execute(
                        destination_table.insert(),
                        [prepared_row(table_name, row) for row in batch],
                    )

            sequence_report = reset_sequences_on_connection(destination_connection)
            source_report = safe_source_connection_report(
                source_connection, source_tables, excluded_columns
            )
            destination_report = safe_connection_report(
                destination_connection, COPY_ORDER, excluded_columns
            )
            differences: list[str] = []
            for table_name in COPY_ORDER:
                if not source_report[table_name]["present"]:
                    if destination_report[table_name]["rows"]:
                        differences.append(f"{table_name}.unexpected_destination_rows")
                    continue
                for key in (
                    "rows",
                    "pk_min",
                    "pk_max",
                    "structural_checksum",
                    "critical_nulls",
                ):
                    if source_report[table_name].get(key) != destination_report[table_name].get(
                        key
                    ):
                        differences.append(f"{table_name}.{key}")
            differences.extend(omitted_column_differences(destination_connection, source_analysis))
            source_integration = Table(
                "business_channel_integrations",
                source_metadata,
                autoload_with=source_connection,
                extend_existing=True,
            )
            destination_integration = Table(
                "business_channel_integrations",
                destination_metadata,
                autoload_with=destination_connection,
                extend_existing=True,
            )
            source_ciphertext = source_connection.execute(
                select(
                    source_integration.c.id,
                    source_integration.c.encrypted_access_token,
                ).order_by(source_integration.c.id)
            ).all()
            destination_ciphertext = destination_connection.execute(
                select(
                    destination_integration.c.id,
                    destination_integration.c.encrypted_access_token,
                ).order_by(destination_integration.c.id)
            ).all()
            if source_ciphertext != destination_ciphertext:
                differences.append("business_channel_integrations.ciphertext")
            if differences:
                raise RuntimeError(f"Migration validation failed: {differences}")
            transaction.commit()
            return {
                "source": source_report,
                "destination": destination_report,
                "ciphertext_exact_match": True,
                "sequences": sequence_report,
            }
        except Exception:
            transaction.rollback()
            raise


def write_report(path: str, report: dict[str, Any]) -> None:
    destination = Path(path).expanduser().resolve()
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(
        json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True, default=safe_json_value),
        encoding="utf-8",
    )


def main() -> int:
    args = parse_args()
    sqlite_url = source_url(args.source)
    destination_url = args.destination_url.strip()
    if not destination_url:
        raise ValueError("DATABASE_URL or --destination-url is required")
    if args.upgrade_destination and not args.apply:
        raise ValueError("--upgrade-destination cannot be used during a read-only dry-run")
    validate_urls(sqlite_url, destination_url)
    validate_copy_order()
    source = create_engine(sqlite_url)
    destination = create_engine(destination_url, isolation_level="READ COMMITTED")
    try:
        source_analysis = analyze_source_schema(source)
        report: dict[str, Any] = {
            "mode": "apply" if args.apply else "dry-run",
            "source": "sqlite:///<local-file>",
            "destination": sanitize_database_url(destination_url),
            "alembic_head": list(head_revisions()),
            "copy_order": list(COPY_ORDER),
            "required_source_tables": list(REQUIRED_SOURCE_TABLES),
            "optional_source_tables": list(OPTIONAL_SOURCE_TABLES),
            "destination_only_tables": list(DESTINATION_ONLY_TABLES),
            "source_schema": source_analysis,
            "copyable_tables": source_analysis["copyable_tables"],
            "absent_optional_source_tables": source_analysis["absent_optional_tables"],
            "missing_required_source_tables": source_analysis["missing_required_tables"],
            "allowed_missing_source_columns": source_analysis["allowed_missing_columns"],
            "incompatible_source_columns": source_analysis["incompatible_columns"],
            "blockers": list(source_analysis["blockers"]),
            "ready_to_apply": False,
        }
        if report["blockers"]:
            write_report(args.report, report)
            raise RuntimeError("; ".join(report["blockers"]))

        source_data = analyze_source_data(source)
        report["source_data"] = source_data
        report["blockers"].extend(source_data["blockers"])
        if report["blockers"]:
            write_report(args.report, report)
            raise RuntimeError("; ".join(report["blockers"]))

        source_tables = tuple(source_analysis["copyable_tables"])
        report["source_preflight"] = safe_source_database_report(source, source_tables)
        if args.upgrade_destination:
            config = alembic_config()
            config.attributes["database_url"] = destination_url
            command.upgrade(config, "head")
        try:
            require_destination_at_head(destination)
            require_empty_destination(destination)
            require_destination_column_policies(destination, source_analysis)
            if args.apply:
                report["validation"] = copy_and_validate_atomic(source, destination)
            else:
                report["ready_to_apply"] = True
        except RuntimeError as error:
            report["blockers"].append(str(error))
            write_report(args.report, report)
            raise
        if not args.apply:
            report["ready_to_apply"] = True
        write_report(args.report, report)
        print(
            "Migration applied and validated" if args.apply else "Dry-run complete; no rows copied"
        )
        print(f"Safe report: {Path(args.report).resolve()}")
        return 0
    finally:
        source.dispose()
        destination.dispose()


if __name__ == "__main__":
    raise SystemExit(main())
