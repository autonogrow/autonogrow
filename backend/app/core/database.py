import logging
import sqlite3
import warnings
from collections.abc import Generator
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from typing import Any

from sqlalchemy import Engine, create_engine, event, inspect, text
from sqlalchemy.engine import make_url
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from app.core.config import Settings, get_database_url, get_settings


class Base(DeclarativeBase):
    pass


logger = logging.getLogger(__name__)

DATABASE_URL = get_database_url()


def _sqlite_is_memory(database_url: str) -> bool:
    url = make_url(database_url)
    return url.database in {None, "", ":memory:"} or url.query.get("mode") == "memory"


def create_database_engine(
    database_url: str,
    *,
    settings: Settings | None = None,
    echo: bool = False,
) -> Engine:
    """Create exactly one engine using the safety policy for its SQL dialect."""

    active_settings = settings or get_settings()
    backend = make_url(database_url).get_backend_name()
    if backend == "sqlite":
        return configure_sqlite_engine(database_url, active_settings, echo=echo)
    if backend == "postgresql":
        return configure_postgresql_engine(database_url, active_settings, echo=echo)
    raise ValueError("Only SQLite and PostgreSQL database URLs are supported")


def configure_postgresql_engine(
    database_url: str,
    settings: Settings,
    *,
    echo: bool = False,
) -> Engine:
    session_options = " ".join(
        (
            f"-c statement_timeout={settings.database_statement_timeout_ms}",
            f"-c lock_timeout={settings.database_lock_timeout_ms}",
            "-c idle_in_transaction_session_timeout="
            f"{settings.database_idle_transaction_timeout_ms}",
        )
    )
    return create_engine(
        database_url,
        echo=echo,
        isolation_level="READ COMMITTED",
        pool_pre_ping=True,
        pool_size=settings.database_pool_size,
        max_overflow=settings.database_max_overflow,
        pool_timeout=settings.database_pool_timeout_seconds,
        pool_recycle=settings.database_pool_recycle_seconds,
        connect_args={
            "connect_timeout": settings.database_connect_timeout_seconds,
            "application_name": settings.database_application_name,
            "options": session_options,
        },
    )


def configure_sqlite_engine(
    database_url: str,
    settings: Settings,
    *,
    echo: bool = False,
) -> Engine:
    """Create a SQLite engine and install its per-connection PRAGMA policy."""

    timeout_seconds = settings.sqlite_busy_timeout_ms / 1000
    database_engine = create_engine(
        database_url,
        connect_args={
            "check_same_thread": False,
            "timeout": timeout_seconds,
        },
        echo=echo,
    )
    memory_database = _sqlite_is_memory(database_url)

    @event.listens_for(database_engine, "connect")
    def configure_sqlite_connection(
        dbapi_connection: sqlite3.Connection,
        _connection_record: object,
    ) -> None:
        cursor = dbapi_connection.cursor()
        try:
            cursor.execute("PRAGMA foreign_keys = ON")
            cursor.execute(f"PRAGMA busy_timeout = {settings.sqlite_busy_timeout_ms}")
            if not memory_database:
                cursor.execute(f"PRAGMA journal_mode = {settings.sqlite_journal_mode}")
                actual_mode = str(cursor.fetchone()[0]).upper()
                if actual_mode != settings.sqlite_journal_mode:
                    raise RuntimeError("SQLite no pudo activar el journal_mode configurado")
            cursor.execute(f"PRAGMA synchronous = {settings.sqlite_synchronous}")
        finally:
            cursor.close()

    return database_engine


engine = create_database_engine(DATABASE_URL)

SessionLocal = sessionmaker(
    bind=engine,
    autoflush=False,
    autocommit=False,
)


def get_db() -> Generator[Session, None, None]:
    db = SessionLocal()

    try:
        yield db
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


@contextmanager
def session_scope() -> Generator[Session, None, None]:
    """Own a short transaction and always rollback failures and close the session."""

    db = SessionLocal()
    try:
        yield db
        db.commit()
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


transactional_session = session_scope


def safe_database_pool_status(database_engine: Engine | None = None) -> dict[str, Any]:
    """Return non-sensitive, best-effort pool telemetry for the owner status page."""

    active_engine = database_engine or engine
    result: dict[str, Any] = {"dialect": active_engine.dialect.name}
    pool = active_engine.pool
    for public_name, attribute_name in (
        ("size", "size"),
        ("checked_out", "checkedout"),
        ("overflow", "overflow"),
    ):
        method = getattr(pool, attribute_name, None)
        if callable(method):
            try:
                result[public_name] = int(method())
            except (TypeError, ValueError, RuntimeError):
                result[public_name] = None
    return result


def initialize_database() -> None:
    """Prepare local databases or validate managed environments without mutating them."""

    from app.models.registry import register_models

    register_models()
    settings = get_settings()
    managed_environment = settings.app_env in {"staging", "production"}

    if managed_environment:
        if settings.database_migration_check:
            from app.core.migration_state import assert_database_at_head

            assert_database_at_head(engine)
        return

    # Local and test environments retain an intentionally simple bootstrap.
    # Integration tests and CI exercise Alembic directly against empty databases.
    Base.metadata.create_all(bind=engine)
    if not settings.enable_legacy_startup_migrations:
        return

    warnings.warn(
        "ENABLE_LEGACY_STARTUP_MIGRATIONS está activo. Esta ruta está obsoleta; "
        "no debe usarse después de adoptar Alembic.",
        DeprecationWarning,
        stacklevel=2,
    )
    logger.warning(
        "Ejecutando migraciones legacy solicitadas explícitamente; no se ejecutó Alembic"
    )
    run_lightweight_migrations()
    from app.services.instagram_integration_service import initialize_instagram_integrations

    db = SessionLocal()
    try:
        initialize_instagram_integrations(db)
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


def create_db_and_tables() -> None:
    """Compatibility alias for callers predating the Alembic transition."""

    initialize_database()


def is_sqlite_locked_error(exc: BaseException) -> bool:
    """Return true only for SQLite lock contention, not general DB failures."""

    return isinstance(exc, OperationalError) and "database is locked" in str(exc).lower()


def run_lightweight_migrations(target_engine=None) -> None:
    """Deprecated compatibility migrations; use Alembic for structural changes."""

    migration_engine = target_engine or engine
    inspector = inspect(migration_engine)

    table_names = inspector.get_table_names()
    if "bookings" not in table_names:
        return

    existing_columns = {column["name"] for column in inspector.get_columns("bookings")}
    booking_columns = {
        "duration_minutes": "INTEGER",
        "start_datetime": "DATETIME",
        "end_datetime": "DATETIME",
        "customer_user_id": "INTEGER",
        "customer_email": "VARCHAR(320)",
        "public_manage_token": "VARCHAR(255)",
        "created_by_user": "BOOLEAN NOT NULL DEFAULT 0",
        "staff_business_user_id": "INTEGER",
        "internal_notes": "TEXT",
    }

    with migration_engine.begin() as connection:
        connection.execute(
            text(
                "CREATE TABLE IF NOT EXISTS app_migrations ("
                "name VARCHAR(200) PRIMARY KEY, "
                "applied_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP)"
            )
        )
        for column_name, column_type in booking_columns.items():
            if column_name not in existing_columns:
                connection.execute(
                    text(f"ALTER TABLE bookings ADD COLUMN {column_name} {column_type}")
                )

        connection.execute(
            text(
                "CREATE INDEX IF NOT EXISTS ix_bookings_customer_user_id ON bookings (customer_user_id)"
            )
        )
        connection.execute(
            text(
                "CREATE INDEX IF NOT EXISTS ix_bookings_customer_email ON bookings (customer_email)"
            )
        )
        connection.execute(
            text(
                "CREATE UNIQUE INDEX IF NOT EXISTS ix_bookings_public_manage_token ON bookings (public_manage_token)"
            )
        )
        connection.execute(
            text(
                "CREATE INDEX IF NOT EXISTS ix_bookings_staff_business_user_id ON bookings (staff_business_user_id)"
            )
        )

        if "business_users" in table_names:
            business_user_columns = {
                column["name"] for column in inspector.get_columns("business_users")
            }
            staff_columns = {
                "public_name": "VARCHAR(200)",
                "bookable": "BOOLEAN NOT NULL DEFAULT 0",
                "show_schedule": "BOOLEAN NOT NULL DEFAULT 1",
                "bio": "TEXT",
                "avatar_url": "TEXT",
                "removed_at": "DATETIME",
            }
            for column_name, column_type in staff_columns.items():
                if column_name not in business_user_columns:
                    connection.execute(
                        text(f"ALTER TABLE business_users ADD COLUMN {column_name} {column_type}")
                    )

        if "businesses" in table_names:
            business_columns = {column["name"] for column in inspector.get_columns("businesses")}
            branding_columns = {
                "secondary_color": "VARCHAR(20)",
                "accent_color": "VARCHAR(20)",
                "background_color": "VARCHAR(20)",
                "theme_key": "VARCHAR(40)",
                "template_key": "VARCHAR(40)",
                "logo_url": "TEXT",
                "logo_alt": "VARCHAR(240)",
            }
            for column_name, column_type in branding_columns.items():
                if column_name not in business_columns:
                    connection.execute(
                        text(f"ALTER TABLE businesses ADD COLUMN {column_name} {column_type}")
                    )

        if "system_incidents" in table_names:
            incident_columns = {
                column["name"] for column in inspector.get_columns("system_incidents")
            }
            if "integration_id" not in incident_columns:
                connection.execute(
                    text("ALTER TABLE system_incidents ADD COLUMN integration_id INTEGER")
                )
            connection.execute(
                text(
                    "CREATE INDEX IF NOT EXISTS ix_system_incidents_integration_id "
                    "ON system_incidents (integration_id)"
                )
            )

        if "business_channel_integrations" in table_names:
            connection.execute(
                text(
                    "CREATE UNIQUE INDEX IF NOT EXISTS "
                    "uq_channel_integration_provider_account "
                    "ON business_channel_integrations (provider, external_account_id)"
                )
            )
            connection.execute(
                text(
                    "CREATE UNIQUE INDEX IF NOT EXISTS "
                    "uq_channel_integration_business_provider "
                    "ON business_channel_integrations (business_id, provider)"
                )
            )

        if "conversations" in table_names:
            conversation_columns = {
                column["name"] for column in inspector.get_columns("conversations")
            }
            automation_columns = {
                "detected_intent": "VARCHAR(60)",
                "intent_confidence": "INTEGER",
                "matched_patterns_json": "TEXT",
                "automation_mode": "VARCHAR(20) NOT NULL DEFAULT 'automatic'",
                "automation_paused_until": "DATETIME",
                "automation_pause_reason": "VARCHAR(60)",
                "automation_pause_updated_by": "INTEGER",
                "automation_pause_updated_at": "DATETIME",
            }
            for column_name, column_type in automation_columns.items():
                if column_name not in conversation_columns:
                    connection.execute(
                        text(f"ALTER TABLE conversations ADD COLUMN {column_name} {column_type}")
                    )
            connection.execute(
                text(
                    "CREATE INDEX IF NOT EXISTS ix_conversations_detected_intent "
                    "ON conversations (detected_intent)"
                )
            )
            connection.execute(
                text(
                    "CREATE INDEX IF NOT EXISTS ix_conversations_automation_paused_until "
                    "ON conversations (automation_paused_until)"
                )
            )

        if "conversation_automation_settings" in table_names:
            automation_settings_columns = {
                column["name"]
                for column in inspector.get_columns("conversation_automation_settings")
            }
            if "human_reply_pause_minutes" not in automation_settings_columns:
                connection.execute(
                    text(
                        "ALTER TABLE conversation_automation_settings "
                        "ADD COLUMN human_reply_pause_minutes INTEGER NOT NULL DEFAULT 60"
                    )
                )
            automation_commercial_columns = {
                "plan_key": "VARCHAR(60)",
                "automation_feature_enabled": "BOOLEAN NOT NULL DEFAULT 1",
                "instagram_channel_enabled": "BOOLEAN NOT NULL DEFAULT 1",
                "whatsapp_channel_enabled": "BOOLEAN NOT NULL DEFAULT 1",
                "allowed_limit_behaviors_json": (
                    'TEXT NOT NULL DEFAULT \'["semi_automatic", "disabled"]\''
                ),
            }
            for column_name, column_type in automation_commercial_columns.items():
                if column_name not in automation_settings_columns:
                    connection.execute(
                        text(
                            "ALTER TABLE conversation_automation_settings "
                            f"ADD COLUMN {column_name} {column_type}"
                        )
                    )

            automation_credit_columns = {
                "included_credits_per_period": "INTEGER NOT NULL DEFAULT 1000",
                "included_credits_used": "INTEGER NOT NULL DEFAULT 0",
                "additional_credits_balance": "INTEGER NOT NULL DEFAULT 0",
            }
            for column_name, column_type in automation_credit_columns.items():
                if column_name not in automation_settings_columns:
                    connection.execute(
                        text(
                            "ALTER TABLE conversation_automation_settings "
                            f"ADD COLUMN {column_name} {column_type}"
                        )
                    )

            credit_migration = "2026_07_automation_credit_wallets"
            credit_migration_applied = connection.execute(
                text("SELECT 1 FROM app_migrations WHERE name = :name"),
                {"name": credit_migration},
            ).first()
            if credit_migration_applied is None:
                connection.execute(
                    text(
                        "UPDATE conversation_automation_settings SET "
                        "included_credits_per_period = CASE "
                        "WHEN monthly_auto_limit < 0 THEN 0 ELSE monthly_auto_limit END, "
                        "included_credits_used = CASE "
                        "WHEN auto_used_current_period < 0 THEN 0 "
                        "WHEN auto_used_current_period > monthly_auto_limit "
                        "THEN monthly_auto_limit ELSE auto_used_current_period END, "
                        "additional_credits_balance = 0"
                    )
                )
                if "automation_credit_transactions" in table_names:
                    connection.execute(
                        text(
                            "INSERT INTO automation_credit_transactions ("
                            "business_id, transaction_type, amount, included_delta, "
                            "additional_delta, included_balance_after, "
                            "additional_balance_after, total_balance_after, reason, "
                            "period_started_at, idempotency_key, safe_metadata_json, created_at"
                            ") SELECT business_id, 'migration_opening_balance', "
                            "included_credits_per_period - included_credits_used, "
                            "included_credits_per_period - included_credits_used, 0, "
                            "included_credits_per_period - included_credits_used, 0, "
                            "included_credits_per_period - included_credits_used, "
                            "'Migración segura desde contadores heredados', "
                            "NULL, 'migration-opening-' || business_id, "
                            ":safe_metadata, "
                            "CURRENT_TIMESTAMP FROM conversation_automation_settings"
                        ),
                        {
                            "safe_metadata": (
                                '{"source":"legacy_fields","additional_credits_granted":0}'
                            )
                        },
                    )
                connection.execute(
                    text("INSERT INTO app_migrations (name) VALUES (:name)"),
                    {"name": credit_migration},
                )

            moving_period_columns = {
                "period_started_at": "DATETIME",
                "period_ends_at": "DATETIME",
                "payment_confirmed_at": "DATETIME",
                "period_status": "VARCHAR(30) NOT NULL DEFAULT 'pending_renewal'",
            }
            for column_name, column_type in moving_period_columns.items():
                if column_name not in automation_settings_columns:
                    connection.execute(
                        text(
                            "ALTER TABLE conversation_automation_settings "
                            f"ADD COLUMN {column_name} {column_type}"
                        )
                    )

            # One-time compatibility window for legacy businesses. It preserves
            # usage and entitlements, does not fabricate a historical payment,
            # and prevents an upgrade from blocking all existing automations.
            moving_period_migration = "2026_07_moving_automation_periods"
            moving_period_applied = connection.execute(
                text("SELECT 1 FROM app_migrations WHERE name = :name"),
                {"name": moving_period_migration},
            ).first()
            if moving_period_applied is None:
                migration_started_at = datetime.now(timezone.utc)
                connection.execute(
                    text(
                        "UPDATE conversation_automation_settings "
                        "SET period_started_at = :started_at, "
                        "period_ends_at = :ends_at, "
                        "period_status = CASE "
                        "WHEN automation_feature_enabled IS TRUE THEN 'active' "
                        "ELSE 'suspended' END "
                        "WHERE period_started_at IS NULL AND period_ends_at IS NULL"
                    ),
                    {
                        "started_at": migration_started_at,
                        "ends_at": migration_started_at + timedelta(days=30),
                    },
                )
                connection.execute(
                    text("INSERT INTO app_migrations (name) VALUES (:name)"),
                    {"name": moving_period_migration},
                )

        migration_name = "2026_07_backfill_business_user_services"
        migration_applied = connection.execute(
            text("SELECT 1 FROM app_migrations WHERE name = :name"),
            {"name": migration_name},
        ).first()
        if migration_applied is None:
            connection.execute(
                text(
                    "INSERT INTO business_user_services "
                    "(business_user_id, service_id, created_at) "
                    "SELECT bu.id, s.id, CURRENT_TIMESTAMP "
                    "FROM business_users bu "
                    "JOIN services s ON s.business_id = bu.business_id "
                    "WHERE bu.active IS TRUE AND bu.bookable IS TRUE "
                    "AND bu.show_schedule IS TRUE AND bu.removed_at IS NULL "
                    "AND s.active IS TRUE "
                    "AND NOT EXISTS ("
                    "SELECT 1 FROM business_user_services existing "
                    "WHERE existing.business_user_id = bu.id)"
                )
            )
            connection.execute(
                text("INSERT INTO app_migrations (name) VALUES (:name)"),
                {"name": migration_name},
            )
