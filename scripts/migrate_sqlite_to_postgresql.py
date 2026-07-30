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

from sqlalchemy import MetaData, Table, create_engine, func, inspect, select, text
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
    "businesses",
    "users",
    "business_users",
    "services",
    "business_user_services",
    "availability_settings",
    "weekly_availability",
    "blocked_dates",
    "availability_exceptions",
    "business_user_availability",
    "business_user_availability_exceptions",
    "customers",
    "bookings",
    "booking_attachments",
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
    "automation_credit_transactions",
    "business_channel_integrations",
    "system_incidents",
    "audit_logs",
    "business_gallery_images",
    "webhook_inbox_events",
    "channel_outbox_messages",
    "worker_heartbeats",
)

SENSITIVE_COLUMNS = {
    "encrypted_access_token",
    "body",
    "message",
    "payload_json",
    "safe_metadata_json",
    "email",
    "phone",
    "customer_email",
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


def require_complete_source(engine: Engine) -> None:
    tables = set(inspect(engine).get_table_names())
    missing = sorted(set(COPY_ORDER) - tables)
    if missing:
        raise RuntimeError(f"Source schema is incomplete; missing tables: {missing}")
    with engine.connect() as connection:
        violations = connection.exec_driver_sql("PRAGMA foreign_key_check").fetchmany(20)
        metadata = MetaData()
        integrations = Table("business_channel_integrations", metadata, autoload_with=connection)
        missing_ciphertext = connection.execute(
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
    if violations:
        raise RuntimeError("Source SQLite foreign-key validation failed")
    if missing_ciphertext:
        raise RuntimeError("Source has active integrations without complete ciphertext metadata")


def table_counts(engine: Engine) -> dict[str, int]:
    metadata = MetaData()
    result: dict[str, int] = {}
    with engine.connect() as connection:
        for table_name in COPY_ORDER:
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


def structural_checksum(connection: Connection, table: Table) -> str:
    primary_keys = list(table.primary_key.columns)
    columns = primary_keys + [
        column
        for column in table.columns
        if column.foreign_keys and column.name not in SENSITIVE_COLUMNS
    ]
    if not columns:
        return hashlib.sha256(b"").hexdigest()
    rows = connection.execute(select(*columns).order_by(*primary_keys)).all()
    payload = [[safe_json_value(value) for value in row] for row in rows]
    return hashlib.sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()


def inspect_table(connection: Connection, table: Table) -> dict[str, Any]:
    primary_keys = list(table.primary_key.columns)
    primary_key = primary_keys[0] if len(primary_keys) == 1 else None
    result: dict[str, Any] = {
        "rows": int(connection.execute(select(func.count()).select_from(table)).scalar_one()),
        "structural_checksum": structural_checksum(connection, table),
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


def safe_database_report(engine: Engine) -> dict[str, Any]:
    with engine.connect() as connection:
        return safe_connection_report(connection)


def safe_connection_report(connection: Connection) -> dict[str, Any]:
    metadata = MetaData()
    result: dict[str, Any] = {}
    for table_name in COPY_ORDER:
        table = Table(table_name, metadata, autoload_with=connection)
        result[table_name] = inspect_table(connection, table)
    return result


def copy_rows(source: Engine, destination: Engine) -> None:
    source_metadata = MetaData()
    destination_metadata = MetaData()
    with source.connect() as source_connection, destination.begin() as destination_connection:
        for table_name in COPY_ORDER:
            source_table = Table(table_name, source_metadata, autoload_with=source_connection)
            destination_table = Table(
                table_name, destination_metadata, autoload_with=destination_connection
            )
            rows = source_connection.execute(select(source_table)).mappings()
            while batch := rows.fetchmany(500):
                destination_connection.execute(
                    destination_table.insert(), [dict(row) for row in batch]
                )


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
    source_report = safe_database_report(source)
    destination_report = safe_database_report(destination)
    differences: list[str] = []
    for table_name in COPY_ORDER:
        source_table = source_report[table_name]
        destination_table = destination_report[table_name]
        for key in ("rows", "pk_min", "pk_max", "structural_checksum", "critical_nulls"):
            if source_table.get(key) != destination_table.get(key):
                differences.append(f"{table_name}.{key}")
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
        transaction = destination_connection.begin()
        try:
            for table_name in COPY_ORDER:
                source_table = Table(table_name, source_metadata, autoload_with=source_connection)
                destination_table = Table(
                    table_name,
                    destination_metadata,
                    autoload_with=destination_connection,
                )
                rows = source_connection.execute(select(source_table)).mappings()
                while batch := rows.fetchmany(500):
                    destination_connection.execute(
                        destination_table.insert(), [dict(row) for row in batch]
                    )

            sequence_report = reset_sequences_on_connection(destination_connection)
            source_report = safe_connection_report(source_connection)
            destination_report = safe_connection_report(destination_connection)
            differences: list[str] = []
            for table_name in COPY_ORDER:
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
    validate_urls(sqlite_url, destination_url)
    validate_copy_order()
    source = create_engine(sqlite_url)
    destination = create_engine(destination_url, isolation_level="READ COMMITTED")
    try:
        require_complete_source(source)
        if args.upgrade_destination:
            config = alembic_config()
            config.attributes["database_url"] = destination_url
            command.upgrade(config, "head")
        require_destination_at_head(destination)
        require_empty_destination(destination)
        report: dict[str, Any] = {
            "mode": "apply" if args.apply else "dry-run",
            "source": "sqlite:///<local-file>",
            "destination": sanitize_database_url(destination_url),
            "alembic_head": list(head_revisions()),
            "source_preflight": safe_database_report(source),
            "copy_order": list(COPY_ORDER),
        }
        if args.apply:
            report["validation"] = copy_and_validate_atomic(source, destination)
        else:
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
