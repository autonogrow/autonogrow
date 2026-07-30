from types import SimpleNamespace

import pytest
from sqlalchemy.exc import OperationalError

from app.core.config import Settings, sanitize_database_url
from app.core.database import create_database_engine
from app.services.database_error_service import (
    classify_database_error,
    report_database_incident,
)


def production_settings(**overrides: object) -> Settings:
    values: dict[str, object] = {
        "app_env": "production",
        "database_url": "postgresql+psycopg://app:secret@db.internal/autonogrow",
        "cookie_secure": True,
        "session_secret": "a-real-session-secret-with-32-characters",
        "google_client_id": "123456789.apps.googleusercontent.com",
        "owner_allowed_emails": "owner@autonogrow.test",
        "frontend_origins": "https://app.autonogrow.test",
        "uploads_dir": "/var/lib/autonogrow/uploads",
        "csrf_enabled": True,
        "rate_limit_enabled": True,
        "security_headers_enabled": True,
        "instagram_require_signature": True,
    }
    values.update(overrides)
    return Settings(_env_file=None, **values)


def test_managed_environments_require_postgresql_except_explicit_emergency_override() -> None:
    sqlite_url = "sqlite:////var/lib/autonogrow/autonogrow.db"
    with pytest.raises(ValueError, match="PostgreSQL es obligatorio"):
        production_settings(database_url=sqlite_url)

    settings = production_settings(
        database_url=sqlite_url,
        allow_sqlite_in_production=True,
    )
    assert settings.allow_sqlite_in_production is True


def test_sqlite_rejects_multi_worker_mode_and_database_ranges_are_bounded() -> None:
    with pytest.raises(ValueError, match="SQLite solo permite"):
        Settings(_env_file=None, app_env="test", worker_concurrency_mode="multi")
    with pytest.raises(ValueError, match="DATABASE_POOL_SIZE"):
        Settings(_env_file=None, app_env="test", database_pool_size=0)


def test_database_url_sanitizer_removes_credentials_and_query_parameters() -> None:
    safe = sanitize_database_url(
        "postgresql+psycopg://private-user:private-password@db.internal:5432/app?sslmode=require"
    )
    assert "private-user" not in safe
    assert "private-password" not in safe
    assert "sslmode" not in safe
    assert "db.internal" in safe
    assert sanitize_database_url("sqlite:////private/path.db") == "sqlite:///<local-file>"


def test_postgresql_engine_receives_pool_isolation_and_session_limits(monkeypatch) -> None:
    captured: dict[str, object] = {}
    sentinel = object()

    def fake_create_engine(url: str, **kwargs: object):
        captured["url"] = url
        captured.update(kwargs)
        return sentinel

    monkeypatch.setattr("app.core.database.create_engine", fake_create_engine)
    settings = Settings(
        _env_file=None,
        app_env="test",
        database_url="postgresql+psycopg://app:fake-password@db.internal/autonogrow",
        worker_concurrency_mode="multi",
    )
    result = create_database_engine(settings.database_url, settings=settings)
    assert result is sentinel
    assert captured["isolation_level"] == "READ COMMITTED"
    assert captured["pool_pre_ping"] is True
    assert captured["pool_size"] == 5
    assert captured["max_overflow"] == 5
    connect_args = captured["connect_args"]
    assert isinstance(connect_args, dict)
    assert connect_args["connect_timeout"] == 10
    assert "statement_timeout=30000" in str(connect_args["options"])
    assert "lock_timeout=5000" in str(connect_args["options"])


def test_database_error_classification_uses_safe_postgresql_categories() -> None:
    original = SimpleNamespace(sqlstate="40P01")
    deadlock = OperationalError("statement", {}, original)
    classification = classify_database_error(deadlock)
    assert classification.code == "deadlock_detected"
    assert classification.retryable is True
    assert "statement" not in classification.safe_message

    connection_timeout = OperationalError("connect", {}, TimeoutError("private endpoint details"))
    classification = classify_database_error(connection_timeout)
    assert classification.code == "connection_timeout"
    assert classification.retryable is True
    assert "private endpoint details" not in classification.safe_message


def test_database_incident_contains_only_safe_classification(monkeypatch) -> None:
    reported: dict[str, object] = {}

    def fake_report_incident(_db, **kwargs: object) -> None:
        reported.update(kwargs)

    monkeypatch.setattr("app.services.incident_service.report_incident", fake_report_incident)
    original = SimpleNamespace(sqlstate="40P01")
    classification = report_database_incident(
        object(),  # type: ignore[arg-type]
        OperationalError("private SQL", {"token": "private"}, original),
        operation="worker_cycle",
    )

    assert classification.code == "deadlock_detected"
    assert reported["category"] == "deadlock_detected"
    assert reported["safe_details"] == {"retryable": True}
    assert "private SQL" not in str(reported)
    assert "private" not in str(reported)
