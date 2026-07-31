from __future__ import annotations

from pathlib import Path

import pytest
from alembic import command
from scripts.migrate_sqlite_to_postgresql import (
    COPY_ORDER,
    DESTINATION_ONLY_TABLES,
    OPTIONAL_SOURCE_TABLES,
    REQUIRED_SOURCE_TABLES,
    copy_rows,
    require_complete_source,
    require_empty_destination,
    safe_source_database_report,
    validate_copy_order,
)
from sqlalchemy import create_engine, text

from app.core.database import Base
from app.core.migration_state import alembic_config, head_revisions
from app.models.registry import register_models


def upgraded_sqlite(tmp_path: Path, revision: str = "head"):
    path = tmp_path / f"source-{revision}.db"
    url = f"sqlite:///{path.as_posix()}"
    config = alembic_config()
    config.attributes["database_url"] = url
    command.upgrade(config, revision)
    return create_engine(url)


def test_copy_order_matches_current_metadata_and_foreign_keys() -> None:
    register_models()
    validate_copy_order()
    assert set(COPY_ORDER) == set(Base.metadata.tables)
    assert "operational_states" in COPY_ORDER
    assert "backup_records" in COPY_ORDER
    assert COPY_ORDER.index("users") < COPY_ORDER.index("operational_states")


def test_source_table_classifications_are_explicit_and_complete() -> None:
    assert OPTIONAL_SOURCE_TABLES == ("operational_states", "backup_records")
    assert DESTINATION_ONLY_TABLES == ("alembic_version",)
    assert set(REQUIRED_SOURCE_TABLES).isdisjoint(OPTIONAL_SOURCE_TABLES)
    assert set(REQUIRED_SOURCE_TABLES) | set(OPTIONAL_SOURCE_TABLES) == set(COPY_ORDER)


def test_legacy_20260730_05_source_without_alembic_version_is_valid(
    tmp_path: Path,
) -> None:
    source = upgraded_sqlite(tmp_path, "20260730_05")
    with source.begin() as connection:
        connection.execute(text("DROP TABLE alembic_version"))
        connection.execute(
            text("CREATE TABLE app_migrations (name VARCHAR(255) PRIMARY KEY, applied_at DATETIME)")
        )
        connection.execute(
            text("INSERT INTO app_migrations (name) VALUES ('legacy-schema-marker')")
        )

    source_tables = require_complete_source(source)
    assert source_tables == REQUIRED_SOURCE_TABLES
    report = safe_source_database_report(source, source_tables)
    assert report["operational_states"] == {"present": False, "rows": 0}
    assert report["backup_records"] == {"present": False, "rows": 0}
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


def test_missing_essential_legacy_table_is_still_rejected(tmp_path: Path) -> None:
    source = upgraded_sqlite(tmp_path)
    with source.begin() as connection:
        connection.execute(text("DROP TABLE worker_heartbeats"))
    with pytest.raises(RuntimeError, match="missing tables.*worker_heartbeats"):
        require_complete_source(source)
    source.dispose()


def test_partial_destination_schema_is_rejected(tmp_path: Path) -> None:
    destination = upgraded_sqlite(tmp_path)
    with destination.begin() as connection:
        connection.execute(text("DROP TABLE backup_records"))
    with pytest.raises(RuntimeError, match="schema is incomplete.*backup_records"):
        require_empty_destination(destination)
    destination.dispose()


def test_alembic_has_expected_single_head() -> None:
    assert head_revisions() == ("20260730_06",)
