from __future__ import annotations

import sqlite3
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace

import pytest
from alembic import command
from sqlalchemy import inspect, text
from sqlalchemy.exc import IntegrityError, OperationalError
from sqlalchemy.orm import Session

from app.core.config import Settings
from app.core.database import (
    Base,
    create_database_engine,
    is_sqlite_locked_error,
)
from app.core.migration_state import (
    BASELINE_REVISION,
    alembic_config,
    assert_database_at_head,
    inspect_database_migration_state,
)
from app.models.registry import register_models
from app.services.integration_crypto_service import decrypt_secret, encrypt_secret


def test_settings_reject_invalid_sqlite_policy() -> None:
    with pytest.raises(ValueError, match="SQLITE_JOURNAL_MODE"):
        Settings(_env_file=None, app_env="test", sqlite_journal_mode="unsafe")
    with pytest.raises(ValueError, match="SQLITE_SYNCHRONOUS"):
        Settings(_env_file=None, app_env="test", sqlite_synchronous="sometimes")
    with pytest.raises(ValueError, match="SQLITE_BUSY_TIMEOUT_MS"):
        Settings(_env_file=None, app_env="test", sqlite_busy_timeout_ms=0)


def sqlite_settings(**overrides: object) -> Settings:
    return Settings(_env_file=None, app_env="test", **overrides)


def upgrade(path: Path, revision: str = "head") -> str:
    database_url = f"sqlite:///{path.as_posix()}"
    config = alembic_config()
    config.attributes["database_url"] = database_url
    command.upgrade(config, revision)
    return database_url


@pytest.fixture
def migrated_database(tmp_path: Path):
    path = tmp_path / "migrated.db"
    database_url = upgrade(path)
    engine = create_database_engine(database_url, settings=sqlite_settings())
    yield path, engine
    engine.dispose()


def test_sqlite_file_pragmas_and_foreign_keys(tmp_path: Path) -> None:
    engine = create_database_engine(
        f"sqlite:///{(tmp_path / 'pragmas.db').as_posix()}",
        settings=sqlite_settings(
            sqlite_busy_timeout_ms=750,
            sqlite_journal_mode="WAL",
            sqlite_synchronous="NORMAL",
        ),
    )
    with engine.connect() as connection:
        assert connection.exec_driver_sql("PRAGMA foreign_keys").scalar_one() == 1
        assert connection.exec_driver_sql("PRAGMA journal_mode").scalar_one().lower() == "wal"
        assert connection.exec_driver_sql("PRAGMA busy_timeout").scalar_one() == 750
        assert connection.exec_driver_sql("PRAGMA synchronous").scalar_one() == 1
    engine.dispose()


def test_sqlite_memory_database_remains_usable() -> None:
    engine = create_database_engine("sqlite:///:memory:", settings=sqlite_settings())
    with engine.begin() as connection:
        connection.exec_driver_sql("CREATE TABLE sample (id INTEGER PRIMARY KEY)")
        connection.exec_driver_sql("INSERT INTO sample DEFAULT VALUES")
        assert connection.exec_driver_sql("SELECT count(*) FROM sample").scalar_one() == 1
        assert connection.exec_driver_sql("PRAGMA foreign_keys").scalar_one() == 1
    engine.dispose()


def test_two_sessions_read_and_locked_write_is_classified(tmp_path: Path) -> None:
    engine = create_database_engine(
        f"sqlite:///{(tmp_path / 'locking.db').as_posix()}",
        settings=sqlite_settings(sqlite_busy_timeout_ms=500),
    )
    with engine.begin() as connection:
        connection.exec_driver_sql("CREATE TABLE counters (id INTEGER PRIMARY KEY, value INTEGER)")
        connection.exec_driver_sql("INSERT INTO counters VALUES (1, 0)")

    first = engine.connect()
    second = engine.connect()
    try:
        assert first.exec_driver_sql("SELECT value FROM counters").scalar_one() == 0
        assert second.exec_driver_sql("SELECT value FROM counters").scalar_one() == 0
        first.exec_driver_sql("BEGIN IMMEDIATE")
        first.exec_driver_sql("UPDATE counters SET value = 1 WHERE id = 1")
        with pytest.raises(OperationalError) as caught:
            second.exec_driver_sql("UPDATE counters SET value = 2 WHERE id = 1")
        assert is_sqlite_locked_error(caught.value)
        first.rollback()
    finally:
        first.close()
        second.close()
        engine.dispose()


def test_invalid_foreign_key_is_rejected(migrated_database) -> None:
    _path, engine = migrated_database
    with Session(engine) as session:
        with pytest.raises(IntegrityError):
            session.execute(
                text(
                    "INSERT INTO services "
                    "(business_id, name, active, created_at) "
                    "VALUES (999999, 'No válido', 1, :created_at)"
                ),
                {"created_at": datetime.utcnow()},
            )
            session.commit()


def test_empty_database_upgrades_to_single_head_with_complete_schema(
    migrated_database,
) -> None:
    _path, engine = migrated_database
    state = inspect_database_migration_state(engine)
    assert state.is_at_head
    assert len(state.head_revisions) == 1
    assert not state.missing_tables
    assert not state.missing_critical_columns

    inspector = inspect(engine)
    integration_indexes = {
        item["name"] for item in inspector.get_indexes("business_channel_integrations")
    }
    assert "ix_channel_integrations_provider_account_status" in integration_indexes
    message_indexes = {item["name"] for item in inspector.get_indexes("conversation_messages")}
    assert "ix_conversation_messages_timeline" in message_indexes
    integration_foreign_keys = inspector.get_foreign_keys("business_channel_integrations")
    assert any(item["referred_table"] == "businesses" for item in integration_foreign_keys)


def test_raw_asset_link_migration_backfills_legacy_editorial_references(
    tmp_path: Path,
) -> None:
    path = tmp_path / "raw-asset-backfill.db"
    database_url = upgrade(path, "20260815_20")
    engine = create_database_engine(database_url, settings=sqlite_settings())
    now = datetime.utcnow()
    with engine.begin() as connection:
        connection.execute(
            text(
                "INSERT INTO businesses "
                "(id, slug, name, status, created_at, updated_at) "
                "VALUES (1, 'migration-business', 'Migration Business', 'active', :now, :now)"
            ),
            {"now": now},
        )
        connection.execute(
            text(
                "INSERT INTO instagram_raw_assets "
                "(id, business_id, active, original_filename, storage_key, media_type, "
                "size_bytes, created_at) VALUES "
                "(10, 1, 1, 'source.jpg', 'raw/source.jpg', 'image/jpeg', 4, :now)"
            ),
            {"now": now},
        )
        connection.execute(
            text(
                "INSERT INTO instagram_contents "
                "(id, business_id, title, status, created_at, updated_at) "
                "VALUES (20, 1, 'Legacy draft', 'draft', :now, :now)"
            ),
            {"now": now},
        )
        connection.execute(
            text(
                "INSERT INTO instagram_content_versions "
                "(id, business_id, content_id, version_number, caption, format, "
                "editorial_package_json, created_at) VALUES "
                "(30, 1, 20, 1, '', 'single_image', :package, :now)"
            ),
            {
                "package": '{"asset_plan":{"recommended":['
                '{"source":"instagram_raw_asset","id":10}]}}',
                "now": now,
            },
        )
        connection.execute(
            text(
                "INSERT INTO instagram_content_versions "
                "(id, business_id, content_id, version_number, caption, format, "
                "editorial_package_json, created_at) VALUES "
                "(31, 1, 20, 2, '', 'single_image', :package, :now)"
            ),
            {"package": '{"asset_plan":[]}', "now": now},
        )
    engine.dispose()

    upgrade(path)
    engine = create_database_engine(database_url, settings=sqlite_settings())
    with engine.connect() as connection:
        link = connection.execute(
            text(
                "SELECT business_id, content_id, raw_asset_id, associated_by_user_id "
                "FROM instagram_content_raw_assets"
            )
        ).one()
        assert link == (1, 20, 10, None)
    engine.dispose()


def test_diagnostic_distinguishes_empty_legacy_and_current(tmp_path: Path) -> None:
    empty_engine = create_database_engine(
        f"sqlite:///{(tmp_path / 'empty.db').as_posix()}", settings=sqlite_settings()
    )
    empty = inspect_database_migration_state(empty_engine)
    assert empty.is_empty and empty.recommendation == "upgrade"
    empty_engine.dispose()

    register_models()
    legacy_engine = create_database_engine(
        f"sqlite:///{(tmp_path / 'legacy.db').as_posix()}", settings=sqlite_settings()
    )
    Base.metadata.create_all(legacy_engine)
    legacy = inspect_database_migration_state(legacy_engine)
    assert legacy.is_legacy and legacy.recommendation == "stamp baseline"
    legacy_engine.dispose()

    current_path = tmp_path / "current.db"
    current_engine = create_database_engine(upgrade(current_path), settings=sqlite_settings())
    current = inspect_database_migration_state(current_engine)
    assert current.is_at_head and current.recommendation == "sin acción: base en head"
    current_engine.dispose()


def test_legacy_stamp_then_upgrade_preserves_encrypted_data(tmp_path: Path) -> None:
    path = tmp_path / "legacy-data.db"
    database_url = f"sqlite:///{path.as_posix()}"
    engine = create_database_engine(database_url, settings=sqlite_settings())
    register_models()
    Base.metadata.create_all(engine)
    with engine.begin() as connection:
        connection.execute(text("DROP TABLE channel_outbox_messages"))
        connection.execute(text("DROP TABLE webhook_inbox_events"))
        connection.execute(text("DROP TABLE worker_heartbeats"))
    now = datetime.utcnow()
    with engine.begin() as connection:
        connection.execute(
            text(
                "INSERT INTO businesses (id, slug, name, status, created_at, updated_at) "
                "VALUES (1, 'legacy', 'Legacy', 'active', :now, :now)"
            ),
            {"now": now},
        )
        connection.execute(
            text(
                "INSERT INTO business_channel_integrations "
                "(id, business_id, channel, provider, external_account_id, "
                "encrypted_access_token, encryption_key_version, integration_status, "
                "created_at, updated_at) VALUES "
                "(1, 1, 'instagram', 'meta', 'account-1', :ciphertext, 'v1', "
                "'connected', :now, :now)"
            ),
            {"ciphertext": "encrypted-test-value", "now": now},
        )
        connection.execute(
            text(
                "INSERT INTO users "
                "(id, email, email_verified, is_active, is_owner, created_at, updated_at) "
                "VALUES (1, 'legacy-user@autonogrow.test', 1, 1, 0, :now, :now)"
            ),
            {"now": now},
        )
        connection.execute(
            text(
                "INSERT INTO business_users "
                "(id, business_id, user_id, role, active, bookable, show_schedule, "
                "created_at, updated_at) VALUES "
                "(1, 1, 1, 'business_admin', 1, 1, 1, :now, :now)"
            ),
            {"now": now},
        )
        connection.execute(
            text(
                "INSERT INTO conversations "
                "(id, business_id, channel, status, automation_mode, created_at, updated_at) "
                "VALUES (1, 1, 'instagram', 'open', 'automatic', :now, :now)"
            ),
            {"now": now},
        )
        connection.execute(
            text(
                "INSERT INTO conversation_messages "
                "(id, conversation_id, direction, sender_type, body, created_at) "
                "VALUES (1, 1, 'inbound', 'customer', 'preserved', :now)"
            ),
            {"now": now},
        )
    engine.dispose()

    config = alembic_config()
    config.attributes["database_url"] = database_url
    command.stamp(config, BASELINE_REVISION)
    command.upgrade(config, "head")

    migrated = create_database_engine(database_url, settings=sqlite_settings())
    with migrated.connect() as connection:
        row = connection.execute(
            text(
                "SELECT encrypted_access_token, encryption_key_version "
                "FROM business_channel_integrations WHERE id = 1"
            )
        ).one()
    assert row == ("encrypted-test-value", "v1")
    with migrated.connect() as connection:
        relation_count = connection.execute(
            text(
                "SELECT count(*) FROM businesses b "
                "JOIN business_users bu ON bu.business_id = b.id "
                "JOIN users u ON u.id = bu.user_id "
                "JOIN conversations c ON c.business_id = b.id "
                "JOIN conversation_messages m ON m.conversation_id = c.id"
            )
        ).scalar_one()
    assert relation_count == 1
    assert inspect_database_migration_state(migrated).is_at_head
    migrated.dispose()


def test_startup_check_rejects_baseline_and_accepts_head(tmp_path: Path) -> None:
    baseline_path = tmp_path / "baseline.db"
    baseline_engine = create_database_engine(
        upgrade(baseline_path, BASELINE_REVISION), settings=sqlite_settings()
    )
    with pytest.raises(RuntimeError, match="no está en la revisión"):
        assert_database_at_head(baseline_engine)
    baseline_engine.dispose()

    head_path = tmp_path / "head.db"
    head_engine = create_database_engine(upgrade(head_path), settings=sqlite_settings())
    assert_database_at_head(head_engine)
    head_engine.dispose()


def test_legacy_startup_migrations_are_disabled_by_default(monkeypatch) -> None:
    from app.core import database

    settings = SimpleNamespace(
        app_env="test",
        database_migration_check=True,
        enable_legacy_startup_migrations=False,
    )
    legacy_called = False

    def legacy_migrations(*_args, **_kwargs):
        nonlocal legacy_called
        legacy_called = True

    monkeypatch.setattr(database, "get_settings", lambda: settings)
    monkeypatch.setattr(database.Base.metadata, "create_all", lambda **_kwargs: None)
    monkeypatch.setattr(database, "run_lightweight_migrations", legacy_migrations)
    database.initialize_database()
    assert not legacy_called


def test_managed_startup_fails_behind_head_and_starts_at_head(tmp_path: Path, monkeypatch) -> None:
    from app.core import database

    settings = SimpleNamespace(
        app_env="production",
        database_migration_check=True,
        enable_legacy_startup_migrations=False,
    )
    monkeypatch.setattr(database, "get_settings", lambda: settings)
    monkeypatch.setattr(
        database.Base.metadata,
        "create_all",
        lambda **_kwargs: pytest.fail("create_all no debe ejecutarse en production"),
    )

    baseline_engine = create_database_engine(
        upgrade(tmp_path / "startup-baseline.db", BASELINE_REVISION),
        settings=sqlite_settings(),
    )
    monkeypatch.setattr(database, "engine", baseline_engine)
    with pytest.raises(RuntimeError, match="no está en la revisión"):
        database.initialize_database()
    baseline_engine.dispose()

    head_engine = create_database_engine(
        upgrade(tmp_path / "startup-head.db"), settings=sqlite_settings()
    )
    monkeypatch.setattr(database, "engine", head_engine)
    database.initialize_database()
    head_engine.dispose()


def test_application_starts_and_serves_health_with_schema_at_head(
    migrated_database, monkeypatch
) -> None:
    from fastapi.testclient import TestClient

    from app import main

    _path, engine = migrated_database
    monkeypatch.setattr(main, "migrate_legacy_uploads", lambda: None)
    monkeypatch.setattr(main, "initialize_database", lambda: assert_database_at_head(engine))
    with TestClient(main.app) as client:
        assert client.get("/health").json() == {"status": "ok"}


def test_stamp_baseline_requires_confirmation_and_rejects_incomplete_db(
    tmp_path: Path, monkeypatch
) -> None:
    from scripts import manage_migrations

    complete_path = tmp_path / "complete-legacy.db"
    engine = create_database_engine(
        f"sqlite:///{complete_path.as_posix()}", settings=sqlite_settings()
    )
    register_models()
    Base.metadata.create_all(engine)
    engine.dispose()
    stamp_called = False

    def fake_stamp(*_args, **_kwargs):
        nonlocal stamp_called
        stamp_called = True

    monkeypatch.setattr(manage_migrations.command, "stamp", fake_stamp)
    monkeypatch.setattr(
        "sys.argv",
        [
            "manage_migrations.py",
            "stamp-baseline",
            "--database-url",
            f"sqlite:///{complete_path.as_posix()}",
        ],
    )
    assert manage_migrations.main() == 2
    assert not stamp_called

    incomplete_path = tmp_path / "incomplete.db"
    with sqlite3.connect(incomplete_path) as connection:
        connection.execute("CREATE TABLE businesses (id INTEGER PRIMARY KEY)")
    monkeypatch.setattr(
        "sys.argv",
        [
            "manage_migrations.py",
            "stamp-baseline",
            "--database-url",
            f"sqlite:///{incomplete_path.as_posix()}",
            "--confirm",
            manage_migrations.CONFIRMATION,
        ],
    )
    assert manage_migrations.main() == 2
    assert not stamp_called


def test_copy_utility_never_changes_source(tmp_path: Path) -> None:
    from scripts.test_migration_on_copy import copy_database, file_digest

    source = tmp_path / "source.db"
    destination = tmp_path / "destination.db"
    with sqlite3.connect(source) as connection:
        connection.execute("CREATE TABLE preserved (value TEXT NOT NULL)")
        connection.execute("INSERT INTO preserved VALUES ('original')")
    before = file_digest(source)
    copy_database(source, destination)
    after = file_digest(source)
    assert before == after
    with sqlite3.connect(destination) as connection:
        assert connection.execute("SELECT value FROM preserved").fetchone() == ("original",)


def test_fake_keyring_encrypts_and_decrypts() -> None:
    settings = Settings(
        _env_file=None,
        app_env="test",
        integration_encryption_keys_json=('{"v1":"AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA="}'),
        integration_encryption_active_key_version="v1",
    )
    ciphertext, version = encrypt_secret("fake-provider-token", settings=settings)
    assert ciphertext != "fake-provider-token"
    assert version == "v1"
    assert decrypt_secret(ciphertext, version, settings=settings) == "fake-provider-token"


def test_locks_ci_and_validation_documents_are_complete() -> None:
    root = Path(__file__).resolve().parents[2]
    for relative in ("backend/requirements.txt", "backend/requirements-dev.txt"):
        lines = (root / relative).read_text(encoding="utf-8").splitlines()
        requirements = [
            line.strip()
            for line in lines
            if line.strip() and not line.lstrip().startswith(("#", "--"))
        ]
        assert requirements
        assert all("==" in requirement for requirement in requirements)

    workflow = (root / ".github/workflows/backend-ci.yml").read_text(encoding="utf-8")
    assert "secrets." not in workflow
    assert "pip-audit -r backend/requirements.txt" in workflow
    assert "alembic upgrade head" in workflow

    pending = (root / "docs/pending_final_validation.md").read_text(encoding="utf-8")
    pending_rows = [line for line in pending.splitlines() if line.startswith("| IG-S1-")]
    assert len(pending_rows) == 40
    assert all("| Pendiente |" in row for row in pending_rows)
    assert not any("| Correcta |" in row for row in pending_rows)

    matrix = (root / "docs/final_release_validation_matrix.md").read_text(encoding="utf-8")
    matrix_rows = [line for line in matrix.splitlines() if line.startswith("| IG-S1-")]
    assert len(matrix_rows) == 40


def test_predeploy_detects_pending_revision_without_modifying_database(
    tmp_path: Path,
) -> None:
    from scripts import predeploy_check

    path = tmp_path / "predeploy-baseline.db"
    upgrade(path, BASELINE_REVISION)
    before = path.read_bytes()
    reporter = predeploy_check.Reporter()
    config_module = SimpleNamespace(
        get_database_url=lambda: f"sqlite:///{path.as_posix()}",
        sqlite_file_path=lambda _url: str(path),
    )
    predeploy_check.check_database_revision(reporter, config_module)
    assert reporter.counts["FAIL"] == 1
    assert path.read_bytes() == before
