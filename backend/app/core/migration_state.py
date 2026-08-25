"""Read-only Alembic and schema diagnostics shared by startup and admin scripts."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from alembic.config import Config
from alembic.migration import MigrationContext
from alembic.script import ScriptDirectory
from sqlalchemy import Engine, inspect

from app.core.database import Base
from app.models.registry import register_models

REPO_ROOT = Path(__file__).resolve().parents[3]
ALEMBIC_CONFIG_PATH = REPO_ROOT / "alembic.ini"
BASELINE_REVISION = "20260730_01"
POST_BASELINE_TABLES = {
    "webhook_inbox_events",
    "channel_outbox_messages",
    "worker_heartbeats",
    "operational_states",
    "backup_records",
    "instagram_content_settings",
    "instagram_raw_assets",
    "instagram_content_raw_assets",
    "instagram_contents",
    "instagram_final_assets",
    "instagram_content_versions",
    "instagram_content_version_assets",
    "instagram_content_editorial_reviews",
    "instagram_content_validations",
    "instagram_content_comments",
    "instagram_publish_jobs",
    "scheduled_customer_followups",
    "customer_opportunities",
    "opportunity_actions",
    "booking_attributions",
    "business_calendar_events",
    "business_growth_signals",
    "social_content_proposals",
    "social_content_proposal_signals",
    "social_idea_reviews",
    "social_promotions",
    "social_promotion_revisions",
    "customer_memory_items",
}
POST_BASELINE_COLUMNS = {
    "bookings.follow_up_enabled_snapshot",
    "services.follow_up_enabled",
    "services.follow_up_interval_days",
    "bookings.price_amount_snapshot",
    "instagram_contents.archived_at",
    "instagram_final_assets.source_raw_asset_id",
}

CRITICAL_COLUMNS: dict[str, set[str]] = {
    "businesses": {"id", "slug", "name"},
    "users": {"id", "email", "google_sub"},
    "business_users": {"id", "business_id", "user_id", "role"},
    "bookings": {
        "id",
        "business_id",
        "customer_id",
        "start_datetime",
        "follow_up_enabled_snapshot",
        "price_amount_snapshot",
    },
    "services": {
        "id",
        "business_id",
        "follow_up_enabled",
        "follow_up_interval_days",
    },
    "conversations": {"id", "business_id", "channel", "automation_mode"},
    "conversation_messages": {"id", "conversation_id", "direction", "body"},
    "automation_credit_transactions": {
        "id",
        "business_id",
        "included_delta",
        "additional_delta",
    },
    "business_channel_integrations": {
        "id",
        "business_id",
        "provider",
        "encrypted_access_token",
        "encryption_key_version",
    },
    "system_incidents": {"id", "incident_key", "integration_id"},
    "audit_logs": {"id", "created_at", "action"},
    "webhook_inbox_events": {
        "id",
        "idempotency_key",
        "payload_hash",
        "status",
        "lock_expires_at",
        "request_id",
    },
    "channel_outbox_messages": {
        "id",
        "business_id",
        "conversation_message_id",
        "status",
        "lock_expires_at",
        "request_id",
    },
    "worker_heartbeats": {"id", "worker_id", "status", "last_seen_at"},
    "operational_states": {"id", "key", "enabled", "updated_at"},
    "backup_records": {"id", "backup_set_id", "backup_type", "status", "created_at"},
    "instagram_publish_jobs": {
        "id",
        "business_id",
        "content_version_id",
        "status",
        "idempotency_key",
        "claim_expires_at",
    },
    "scheduled_customer_followups": {
        "id",
        "business_id",
        "customer_id",
        "due_at",
        "dedupe_key",
    },
    "customer_opportunities": {
        "id",
        "business_id",
        "customer_id",
        "type",
        "status",
        "dedupe_key",
    },
    "opportunity_actions": {
        "id",
        "business_id",
        "opportunity_id",
        "customer_id",
        "status",
        "action_type",
        "message_id",
    },
    "booking_attributions": {
        "id",
        "business_id",
        "opportunity_id",
        "action_id",
        "booking_id",
        "method",
    },
    "business_calendar_events": {
        "id",
        "business_id",
        "title",
        "starts_at",
        "ends_at",
    },
    "business_growth_signals": {
        "id",
        "business_id",
        "type",
        "status",
        "severity",
        "dedupe_key",
    },
    "customer_memory_items": {
        "id",
        "business_id",
        "customer_id",
        "category",
        "key",
        "status",
        "source_type",
    },
}


@dataclass(frozen=True)
class DatabaseMigrationState:
    database: str
    has_alembic_version: bool
    current_revisions: tuple[str, ...]
    head_revisions: tuple[str, ...]
    expected_tables: tuple[str, ...]
    missing_tables: tuple[str, ...]
    missing_critical_columns: tuple[str, ...]
    is_empty: bool
    is_legacy: bool
    recommendation: str

    @property
    def is_at_head(self) -> bool:
        return bool(self.current_revisions) and set(self.current_revisions) == set(
            self.head_revisions
        )

    @property
    def is_baseline_compatible_legacy(self) -> bool:
        missing_baseline_tables = set(self.missing_tables) - POST_BASELINE_TABLES
        missing_baseline_columns = set(self.missing_critical_columns) - POST_BASELINE_COLUMNS
        return self.is_legacy and not missing_baseline_tables and not missing_baseline_columns


def alembic_config() -> Config:
    return Config(str(ALEMBIC_CONFIG_PATH))


def head_revisions() -> tuple[str, ...]:
    script = ScriptDirectory.from_config(alembic_config())
    return tuple(sorted(script.get_heads()))


def _safe_database_label(engine: Engine) -> str:
    url = engine.url
    if url.get_backend_name() == "sqlite":
        return "SQLite en memoria" if url.database == ":memory:" else f"SQLite: {url.database}"
    host = url.host or "host-no-disponible"
    database = url.database or "base-no-disponible"
    return f"{url.get_backend_name()}://{host}/{database}"


def inspect_database_migration_state(engine: Engine) -> DatabaseMigrationState:
    register_models()
    inspector = inspect(engine)
    existing_tables = set(inspector.get_table_names())
    expected_tables = set(Base.metadata.tables)
    has_version = "alembic_version" in existing_tables
    current: tuple[str, ...] = ()
    if has_version:
        with engine.connect() as connection:
            current = tuple(sorted(MigrationContext.configure(connection).get_current_heads()))

    missing_tables = expected_tables - existing_tables
    missing_columns: list[str] = []
    for table_name, columns in CRITICAL_COLUMNS.items():
        if table_name not in existing_tables:
            continue
        actual = {column["name"] for column in inspector.get_columns(table_name)}
        missing_columns.extend(
            f"{table_name}.{column_name}" for column_name in sorted(columns - actual)
        )

    user_tables = existing_tables - {"alembic_version", "sqlite_sequence"}
    is_empty = not user_tables
    is_legacy = bool(user_tables) and not has_version
    heads = head_revisions()
    if len(heads) != 1:
        recommendation = "revisión manual: el repositorio no tiene una única head"
    elif is_empty:
        recommendation = "upgrade"
    elif (
        is_legacy
        and not (missing_tables - POST_BASELINE_TABLES)
        and not (set(missing_columns) - POST_BASELINE_COLUMNS)
    ):
        recommendation = "stamp baseline"
    elif is_legacy:
        recommendation = "revisión manual: la base heredada está incompleta"
    elif set(current) == set(heads):
        recommendation = "sin acción: base en head"
    else:
        recommendation = "upgrade"

    return DatabaseMigrationState(
        database=_safe_database_label(engine),
        has_alembic_version=has_version,
        current_revisions=current,
        head_revisions=heads,
        expected_tables=tuple(sorted(expected_tables)),
        missing_tables=tuple(sorted(missing_tables)),
        missing_critical_columns=tuple(missing_columns),
        is_empty=is_empty,
        is_legacy=is_legacy,
        recommendation=recommendation,
    )


def assert_database_at_head(engine: Engine) -> None:
    state = inspect_database_migration_state(engine)
    if state.is_at_head:
        return
    if state.is_legacy:
        raise RuntimeError(
            "La base no tiene historial Alembic. Ejecute el diagnóstico y aplique "
            "stamp baseline solo después de verificar esquema y backup."
        )
    raise RuntimeError(
        "La base de datos no está en la revisión Alembic head. "
        "Ejecute las migraciones antes de arrancar la aplicación."
    )
