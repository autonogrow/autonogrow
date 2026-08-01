from __future__ import annotations

import json
import logging
import tarfile
from datetime import datetime, timedelta
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from scripts.backup_common import atomic_json, load_manifest, manifest_for
from scripts.backup_uploads import validate_archive, validate_tree
from scripts.prune_backups import plan_prune
from scripts.verify_backup import verify
from scripts.verify_latest_backups import verify_latest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from app.core.config import Settings
from app.core.database import Base
from app.core.observability import OperationalFormatter, redact_sensitive
from app.middleware.request_context import RequestContextMiddleware, safe_request_id
from app.models import BackupRecord
from app.models.registry import register_models
from app.routers.health import health_check
from app.services.backup_record_service import record_backup_manifest
from app.services.maintenance_service import maintenance_enabled, set_maintenance
from app.services.metrics_service import metrics_authorized
from app.services.operational_alert_service import (
    AlertSignal,
    evaluate_operational_alerts,
    persist_operational_alerts,
)


def test_liveness_payload_is_process_only() -> None:
    assert health_check() == {"status": "ok"}


@pytest.mark.parametrize(
    "value",
    ("abc", "trace-123", "client.request:1", "A" * 64),
)
def test_safe_external_request_id_is_preserved(value: str) -> None:
    assert safe_request_id(value) == value


@pytest.mark.parametrize(
    "value",
    ("", "bad value", "line\r\nbreak", "x" * 65, "💥"),
)
def test_unsafe_request_id_is_replaced(value: str) -> None:
    generated = safe_request_id(value)
    assert generated != value
    assert len(generated) == 36


def test_request_id_is_returned_in_response() -> None:
    app = FastAPI()
    app.add_middleware(RequestContextMiddleware)

    @app.get("/probe")
    def probe():
        return {"ok": True}

    with TestClient(app) as client:
        response = client.get("/probe", headers={"X-Request-ID": "safe-id"})
    assert response.headers["X-Request-ID"] == "safe-id"


@pytest.mark.parametrize(
    "key",
    ("token", "Authorization", "cookie", "password", "api_key", "ciphertext", "database_url"),
)
def test_sensitive_mapping_fields_are_redacted(key: str) -> None:
    assert redact_sensitive({key: "do-not-log"})[key] == "[REDACTED]"


def test_sensitive_text_and_database_credentials_are_redacted() -> None:
    safe = redact_sensitive("token=abc postgresql://user:pass@db/service")
    assert "abc" not in safe and "user" not in safe and "pass" not in safe


def test_json_formatter_includes_release_and_hides_secret() -> None:
    settings = Settings(_env_file=None, app_env="test", log_format="json", app_release_id="r1")
    formatter = OperationalFormatter(settings)
    record = logging.LogRecord("test", logging.INFO, __file__, 1, "token=secret-value", (), None)
    payload = json.loads(formatter.format(record))
    assert payload["release_id"] == "r1"
    assert "secret-value" not in json.dumps(payload)


def test_log_format_auto_follows_environment() -> None:
    assert Settings(_env_file=None, app_env="test").log_format == "text"
    baseline = {
        "app_env": "production",
        "cookie_secure": True,
        "csrf_enabled": True,
        "rate_limit_enabled": True,
        "security_headers_enabled": True,
        "session_secret": "s" * 40,
        "google_client_id": "123.apps.googleusercontent.com",
        "owner_allowed_emails": "owner@autonogrow.test",
        "frontend_origins": "https://app.autonogrow.test",
        "database_url": "postgresql+psycopg://user:pass@localhost/app",
        "uploads_dir": "/srv/autonogrow/uploads",
        "instagram_require_signature": True,
    }
    assert Settings(_env_file=None, **baseline).log_format == "json"


@pytest.mark.parametrize(
    ("field", "value"),
    (
        ("log_max_field_length", 10),
        ("readiness_timeout_seconds", 20),
        ("metrics_allowed_ips", "not-an-ip"),
        ("alert_disk_free_critical_percent", 30),
    ),
)
def test_operational_configuration_rejects_unsafe_ranges(field: str, value: object) -> None:
    with pytest.raises(ValueError):
        Settings(_env_file=None, app_env="test", **{field: value})


def request_from(ip: str, token: str | None = None):
    from starlette.requests import Request

    headers = [] if token is None else [(b"authorization", f"Bearer {token}".encode())]
    return Request(
        {
            "type": "http",
            "method": "GET",
            "path": "/internal/metrics",
            "headers": headers,
            "client": (ip, 1234),
            "scheme": "http",
            "server": ("test", 80),
        }
    )


def test_metrics_allow_loopback_without_token() -> None:
    settings = Settings(_env_file=None, app_env="test", metrics_enabled=True)
    assert metrics_authorized(request_from("127.0.0.1"), settings)


def test_metrics_accept_matching_token_and_reject_wrong_token() -> None:
    token = "metric-secret-that-is-at-least-32-chars"
    settings = Settings(
        _env_file=None, app_env="test", metrics_enabled=True, metrics_auth_token=token
    )
    assert metrics_authorized(request_from("10.0.0.8", token), settings)
    assert not metrics_authorized(request_from("10.0.0.8", "wrong"), settings)


def test_metrics_disabled_rejects_even_loopback() -> None:
    settings = Settings(_env_file=None, app_env="test", metrics_enabled=False)
    assert not metrics_authorized(request_from("127.0.0.1"), settings)


def alert_settings(**values) -> Settings:
    return Settings(_env_file=None, app_env="test", worker_enabled=True, **values)


@pytest.mark.parametrize(
    ("snapshot", "component", "severity"),
    (
        (
            {
                "ready": False,
                "workers": {"active": 1},
                "storage": {"free_percent": 100},
                "queues": {},
                "backups": {"last_at": datetime.utcnow()},
            },
            "readiness",
            "critical",
        ),
        (
            {
                "ready": True,
                "workers": {"active": 0},
                "storage": {"free_percent": 100},
                "queues": {},
                "backups": {"last_at": datetime.utcnow()},
            },
            "worker",
            "critical",
        ),
        (
            {
                "ready": True,
                "workers": {"active": 1},
                "storage": {"free_percent": 5},
                "queues": {},
                "backups": {"last_at": datetime.utcnow()},
            },
            "storage",
            "critical",
        ),
        (
            {
                "ready": True,
                "workers": {"active": 1},
                "storage": {"free_percent": 100},
                "queues": {"dead_letters": 1},
                "backups": {"last_at": datetime.utcnow()},
            },
            "queues",
            "critical",
        ),
    ),
)
def test_alert_engine_detects_critical_conditions(snapshot, component: str, severity: str) -> None:
    signals = evaluate_operational_alerts(snapshot, alert_settings())
    assert any(item.component == component and item.severity == severity for item in signals)


def database_session() -> Session:
    register_models()
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    return Session(engine)


def test_alert_dedup_cooldown_and_recovery_notification() -> None:
    db = database_session()
    sent: list[tuple[str, bool]] = []

    def sender(signal, recovery):
        sent.append((signal.condition, recovery))
        return True

    settings = alert_settings(operational_alerts_enabled=True, alert_cooldown_minutes=30)
    now = datetime.utcnow()
    signal = AlertSignal("worker", "none_active", "critical")
    persist_operational_alerts(db, [signal], settings=settings, sender=sender, now=now)
    persist_operational_alerts(
        db, [signal], settings=settings, sender=sender, now=now + timedelta(minutes=5)
    )
    persist_operational_alerts(
        db, [], settings=settings, sender=sender, now=now + timedelta(minutes=6)
    )
    db.commit()
    assert sent == [("none_active", False), ("none_active", True)]
    db.close()


def test_recovery_is_not_notified_when_opening_was_not_notified() -> None:
    db = database_session()
    sent: list[bool] = []
    settings = alert_settings(operational_alerts_enabled=False)
    persist_operational_alerts(
        db,
        [AlertSignal("storage", "disk_free", "warning")],
        settings=settings,
        sender=lambda _s, recovery: sent.append(recovery) or True,
    )
    persist_operational_alerts(
        db, [], settings=settings, sender=lambda _s, recovery: sent.append(recovery) or True
    )
    assert sent == []
    db.close()


def test_maintenance_state_is_persistent() -> None:
    db = database_session()
    assert not maintenance_enabled(db)
    set_maintenance(db, enabled=True, safe_reason="planned")
    db.commit()
    assert maintenance_enabled(db)
    set_maintenance(db, enabled=False, safe_reason="complete")
    db.commit()
    assert not maintenance_enabled(db)
    db.close()


def create_upload_backup(tmp_path: Path) -> tuple[Path, Path]:
    source = tmp_path / "uploads"
    source.mkdir()
    (source / "image.txt").write_text("safe", encoding="utf-8")
    artifact = tmp_path / "uploads.tar.gz"
    with tarfile.open(artifact, "w:gz") as archive:
        archive.add(source, arcname="uploads")
    manifest = manifest_for(
        artifact=artifact, kind="uploads", environment="test", release="r1", set_id="set-1"
    )
    manifest_path = tmp_path / "uploads.tar.gz.manifest.json"
    atomic_json(manifest_path, manifest)
    return artifact, manifest_path


def test_upload_archive_and_manifest_verify(tmp_path: Path) -> None:
    artifact, manifest = create_upload_backup(tmp_path)
    assert validate_archive(artifact) == 1
    assert verify(manifest) == ("valid", [])



def test_verify_latest_persists_verification_status(tmp_path: Path) -> None:
    artifact, manifest_path = create_upload_backup(tmp_path)

    db = database_session()
    engine = db.get_bind()

    record_backup_manifest(db, load_manifest(manifest_path))
    db.commit()
    db.close()

    factory = sessionmaker(bind=engine)
    results = verify_latest(tmp_path.resolve(), session_factory=factory)

    assert results == {"uploads": "valid"}

    with factory() as check:
        row = (
            check.query(BackupRecord)
            .filter(BackupRecord.artifact_name == artifact.name)
            .one()
        )

        assert row.verification_status == "valid"
        assert row.verified_at is not None


def test_checksum_mismatch_is_invalid(tmp_path: Path) -> None:
    artifact, manifest = create_upload_backup(tmp_path)
    artifact.write_bytes(b"tampered")
    status, issues = verify(manifest)
    assert status == "invalid" and "size_mismatch" in issues


def test_upload_tree_rejects_symbolic_links_when_supported(tmp_path: Path) -> None:
    source = tmp_path / "uploads"
    source.mkdir()
    target = source / "target.txt"
    target.write_text("safe", encoding="utf-8")
    link = source / "link.txt"
    try:
        link.symlink_to(target)
    except OSError:
        pytest.skip("Symlinks require additional Windows privileges")
    with pytest.raises(ValueError, match="symbolic"):
        validate_tree(source)


def test_prune_keeps_minimum_and_removes_old_complete_set(tmp_path: Path) -> None:
    now = datetime.utcnow().astimezone()
    for index, age in enumerate((1, 40), 1):
        for kind, suffix in (("uploads", "tar.gz"), ("postgresql", "dump")):
            artifact = tmp_path / f"backup-{index}-{kind}.{suffix}"
            artifact.write_bytes(b"backup")
            manifest = manifest_for(
                artifact=artifact,
                kind=kind,
                environment="test",
                release="r1",
                set_id=f"set-{index}",
            )
            manifest["created_at"] = (now - timedelta(days=age)).isoformat()
            atomic_json(tmp_path / f"{artifact.name}.manifest.json", manifest)
    removable = plan_prune(tmp_path.resolve(), retention_days=30, minimum_count=1)
    assert {path.name for path in removable} == {
        "backup-2-uploads.tar.gz",
        "backup-2-uploads.tar.gz.manifest.json",
        "backup-2-postgresql.dump",
        "backup-2-postgresql.dump.manifest.json",
    }


def test_operational_manual_matrix_has_exactly_50_pending_rows() -> None:
    path = Path(__file__).resolve().parents[2] / "docs" / "manual_test_operations.md"
    rows = [
        line
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.startswith("| OPS-S7-")
    ]
    assert len(rows) == 50
    assert all("| Pendiente |" in row for row in rows)


def test_caddy_blocks_internal_metrics_and_systemd_timers_are_not_enabled_by_repo() -> None:
    root = Path(__file__).resolve().parents[2]
    caddy = (root / "deploy" / "Caddyfile.example").read_text(encoding="utf-8")
    assert "@internal path /internal/*" in caddy and "respond @internal 404" in caddy
    timers = list((root / "deploy").glob("autonogrow-*.timer"))
    assert len(timers) >= 4
    assert all("WantedBy=timers.target" in path.read_text(encoding="utf-8") for path in timers)
