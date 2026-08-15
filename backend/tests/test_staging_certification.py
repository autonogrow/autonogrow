import json
from pathlib import Path
from types import SimpleNamespace

import pytest
from scripts import instagram_publication_preflight as publication_preflight_cli
from scripts.certify_staging import (
    HttpResult,
    Reporter,
    SystemdUnitState,
    check_build,
    check_caddy_config,
    check_caddy_runtime,
    check_health_and_headers,
    check_instagram_worker_preflight,
    check_publisher_systemd,
    check_readiness,
    normalize_base_url,
    tamper_signed_url,
)
from sqlalchemy import create_engine, inspect
from sqlalchemy.orm import sessionmaker

from app.core.config import Settings
from app.routers import config as config_router
from app.workers.instagram_publish_worker import worker_startup_check

ROOT = Path(__file__).resolve().parents[2]


def test_normalize_base_url_rejects_credentials_and_non_root_paths() -> None:
    assert normalize_base_url("https://staging.example.test") == "https://staging.example.test/"
    with pytest.raises(ValueError):
        normalize_base_url("https://user:secret@staging.example.test")
    with pytest.raises(ValueError):
        normalize_base_url("https://staging.example.test/private")


def test_reporter_machine_report_and_exit_gate(tmp_path: Path) -> None:
    reporter = Reporter()
    reporter.add("health", "PASS", "ok")
    reporter.add("manual", "MANUAL_REQUIRED", "human")
    assert reporter.exit_code() == 0

    output = tmp_path / "certification.json"
    reporter.write_json(output, base_url="https://staging.example.test/")
    payload = json.loads(output.read_text(encoding="utf-8"))
    assert payload["summary"]["PASS"] == 1
    assert payload["summary"]["MANUAL_REQUIRED"] == 1
    assert payload["certified"] is False

    reporter.add("environment", "BLOCKER", "wrong")
    assert reporter.exit_code() == 1


def test_build_check_requires_staging_and_real_sha(monkeypatch) -> None:
    reporter = Reporter()
    result = HttpResult(
        status=200,
        headers={},
        body=json.dumps(
            {
                "app_env": "production",
                "app_version": "0.1.0",
                "release_id": "release",
                "git_commit": "unknown",
                "build_time": "2026-08-14T10:00:00Z",
            }
        ).encode(),
        final_url="https://staging.example.test/api/config/build",
        elapsed_ms=10,
    )

    monkeypatch.setattr("scripts.certify_staging.fetch", lambda *_args, **_kwargs: result)
    check_build(reporter, "https://staging.example.test/", 1, "staging", None)

    assert [item.status for item in reporter.results] == ["BLOCKER", "BLOCKER"]


def test_missing_build_still_detects_legacy_environment(monkeypatch) -> None:
    def fake_fetch(_base_url, path, _timeout):
        if path == "/api/config/public":
            return HttpResult(
                200,
                {},
                b'{"app_env":"production"}',
                "https://staging.example.test/api/config/public",
                5,
            )
        return HttpResult(
            404,
            {},
            b'{"detail":"Not Found"}',
            "https://staging.example.test/api/config/build",
            5,
        )

    reporter = Reporter()
    monkeypatch.setattr("scripts.certify_staging.fetch", fake_fetch)

    check_build(reporter, "https://staging.example.test/", 1, "staging", None)

    assert [item.status for item in reporter.results] == ["BLOCKER", "BLOCKER"]
    assert "APP_ENV=production" in reporter.results[1].detail


def test_tamper_signed_url_changes_only_selected_query_field() -> None:
    source = "https://staging.example.test/asset?expires=10&signature=abcdef"
    result = tamper_signed_url(source, "signature", "0bcdef")
    assert result == "https://staging.example.test/asset?expires=10&signature=0bcdef"


def test_readiness_requires_exact_safe_contract() -> None:
    reporter = Reporter()
    for body in (b'{"status":"ready"}', b""):
        check_readiness(
            reporter,
            HttpResult(
                status=200,
                headers={},
                body=body,
                final_url="https://staging.example.test/ready",
                elapsed_ms=5,
            ),
        )

    assert [result.status for result in reporter.results] == ["PASS", "FAIL"]


def test_build_endpoint_exposes_only_release_metadata(monkeypatch) -> None:
    settings = SimpleNamespace(
        app_env="staging",
        app_version="0.1.0",
        app_release_id="staging-r1",
        app_git_commit="abcdef123456",
        app_build_time="2026-08-14T10:00:00Z",
        session_secret="test-session-secret-not-returned",
    )
    monkeypatch.setattr(config_router, "get_settings", lambda: settings)

    assert config_router.build_config() == {
        "app_env": "staging",
        "app_version": "0.1.0",
        "release_id": "staging-r1",
        "git_commit": "abcdef123456",
        "build_time": "2026-08-14T10:00:00Z",
    }


def test_worker_startup_check_is_read_only_and_does_not_claim_jobs() -> None:
    database_engine = create_engine("sqlite:///:memory:")
    session_factory = sessionmaker(bind=database_engine)
    settings = Settings(_env_file=None, app_env="test")

    before = inspect(database_engine).get_table_names()
    result = worker_startup_check(
        settings,
        session_factory=session_factory,
        database_engine=database_engine,
    )
    after = inspect(database_engine).get_table_names()

    assert result["ok"] is True
    assert result["publishing_mode"] == "simulated"
    assert result["worker_enabled"] is False
    assert result["database_dialect"] == "sqlite"
    assert before == after == []


def test_publication_preflight_cli_does_not_write_when_content_is_missing(
    monkeypatch, capsys
) -> None:
    class ReadOnlyQuery:
        def filter(self, *_args):
            return self

        def first(self):
            return None

    class ReadOnlySession:
        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return None

        def query(self, *_args):
            return ReadOnlyQuery()

    monkeypatch.setattr(
        publication_preflight_cli,
        "parse_args",
        lambda: SimpleNamespace(content_id=11, business_id=22, json=True),
    )
    monkeypatch.setattr(publication_preflight_cli, "get_settings", lambda: Settings(_env_file=None))
    monkeypatch.setattr(publication_preflight_cli, "SessionLocal", ReadOnlySession)

    assert publication_preflight_cli.main() == 1
    payload = json.loads(capsys.readouterr().out)
    assert payload["code"] == "content_not_found"
    assert payload["ok"] is False


def test_staging_systemd_services_match_the_deployed_runtime() -> None:
    publisher = (ROOT / "deploy/autonogrow-instagram-publisher.service").read_text(
        encoding="utf-8"
    )
    maintenance = (ROOT / "deploy/autonogrow-maintenance.service").read_text(encoding="utf-8")
    forbidden = (
        "/opt/autonogrow/.venv/bin/python",
        "User=autonogrow",
        "Group=autonogrow",
        "/var/lib/autonogrow",
        "/var/log/autonogrow",
    )

    assert all(marker not in publisher for marker in forbidden)
    assert all(marker not in maintenance for marker in forbidden)
    assert "User=deploy\nGroup=deploy" in publisher
    assert "WorkingDirectory=/opt/autonogrow/backend" in publisher
    assert publisher.count("EnvironmentFile=/etc/autonogrow/backend.env") == 1
    assert "/etc/autonogrow/worker.env" not in publisher
    assert (
        "ExecStartPre=/opt/autonogrow/backend/.venv-next/bin/python -m "
        "app.workers.instagram_publish_worker --check"
    ) in publisher
    assert (
        "ExecStart=/opt/autonogrow/backend/.venv-next/bin/python -m "
        "app.workers.instagram_publish_worker --poll-seconds 2"
    ) in publisher
    assert "ReadOnlyPaths=/var/lib/agw-staging" in publisher
    assert "ReadWritePaths=" not in publisher

    assert "User=deploy\nGroup=deploy" in maintenance
    assert "WorkingDirectory=/opt/autonogrow" in maintenance
    assert "EnvironmentFile=/etc/autonogrow/backend.env" in maintenance
    assert (
        "ExecStart=/usr/bin/flock -n /run/lock/autonogrow-maintenance.lock "
        "/opt/autonogrow/backend/.venv-next/bin/python "
        "/opt/autonogrow/scripts/run_maintenance.py --apply --json"
    ) in maintenance
    assert "ReadWritePaths=/run/lock" in maintenance
    assert (ROOT / "backend/app/workers/instagram_publish_worker.py").is_file()
    assert (ROOT / "scripts/run_maintenance.py").is_file()


def test_staging_maintenance_timer_runs_after_the_backup_window() -> None:
    timer = (ROOT / "deploy/autonogrow-maintenance.timer").read_text(encoding="utf-8")

    assert "OnCalendar=*-*-* 04:30:00" in timer
    assert "RandomizedDelaySec=10min" in timer
    assert "Persistent=true" in timer
    assert (ROOT / "deploy/autonogrow-maintenance.service").is_file()


def test_disabled_inactive_publisher_passes_with_valid_preflight(monkeypatch) -> None:
    reporter = Reporter()
    monkeypatch.setattr(
        "scripts.certify_staging.systemd_unit_state",
        lambda _unit: SystemdUnitState("inactive", "disabled", 0),
    )

    check_publisher_systemd(reporter, worker_enabled=False, preflight_ok=True)

    assert reporter.results[-1].status == "PASS"
    assert "deliberadamente deshabilitado" in reporter.results[-1].detail


def test_real_disabled_publisher_preflight_payload_is_consistent(monkeypatch) -> None:
    reporter = Reporter()
    payload = {
        "app_env": "staging",
        "database_dialect": "postgresql",
        "ok": True,
        "provider_adapter": "SimulatedInstagramPublishingAdapter",
        "publishing_mode": "simulated",
        "worker_enabled": False,
    }
    settings = SimpleNamespace(
        app_env="staging",
        instagram_publishing_mode="simulated",
        instagram_publishing_worker_enabled=False,
    )
    monkeypatch.setattr(
        "scripts.certify_staging.command_result",
        lambda *_args, **_kwargs: (0, json.dumps(payload)),
    )

    preflight_ok, worker_enabled = check_instagram_worker_preflight(
        reporter, ROOT / "backend", settings
    )

    assert preflight_ok is True
    assert worker_enabled is False
    assert reporter.results[-1].status == "PASS"


def test_enabled_inactive_publisher_fails(monkeypatch) -> None:
    reporter = Reporter()
    monkeypatch.setattr(
        "scripts.certify_staging.systemd_unit_state",
        lambda _unit: SystemdUnitState("inactive", "disabled", 0),
    )

    check_publisher_systemd(reporter, worker_enabled=True, preflight_ok=True)

    assert reporter.results[-1].status == "FAIL"


def test_invalid_preflight_keeps_disabled_publisher_failed(monkeypatch) -> None:
    reporter = Reporter()
    monkeypatch.setattr(
        "scripts.certify_staging.systemd_unit_state",
        lambda _unit: SystemdUnitState("inactive", "disabled", 0),
    )

    check_publisher_systemd(reporter, worker_enabled=False, preflight_ok=False)

    assert reporter.results[-1].status == "FAIL"


@pytest.mark.parametrize(
    "state",
    (
        SystemdUnitState("failed", "enabled", 0),
        SystemdUnitState("active", "enabled", 3),
    ),
)
def test_failed_or_restarting_publisher_fails(monkeypatch, state) -> None:
    reporter = Reporter()
    monkeypatch.setattr("scripts.certify_staging.systemd_unit_state", lambda _unit: state)

    check_publisher_systemd(reporter, worker_enabled=False, preflight_ok=True)

    assert reporter.results[-1].status == "FAIL"


def test_caddy_permission_error_uses_safe_privileged_validation(monkeypatch) -> None:
    reporter = Reporter()

    def fake_command(command, *_args, **_kwargs):
        if command[:2] == ["sudo", "-n"]:
            return 0, "Valid configuration"
        return 1, "opening log writer: permission denied"

    monkeypatch.setattr("scripts.certify_staging.command_result", fake_command)
    monkeypatch.setattr(
        "scripts.certify_staging.systemd_unit_state",
        lambda _unit: SystemdUnitState("active", "enabled", 0),
    )

    check_caddy_runtime(reporter)
    check_caddy_config(reporter, "/etc/caddy/Caddyfile")

    assert [result.status for result in reporter.results] == ["PASS", "PASS"]
    assert "log protegido" in reporter.results[-1].detail


def test_caddy_real_validation_failure_remains_fail(monkeypatch) -> None:
    reporter = Reporter()
    calls = []

    def fake_command(command, *_args, **_kwargs):
        calls.append(command)
        return 1, "adapting config: unrecognized directive"

    monkeypatch.setattr("scripts.certify_staging.command_result", fake_command)

    check_caddy_config(reporter, "/etc/caddy/Caddyfile")

    assert reporter.results[-1].status == "FAIL"
    assert calls == [["caddy", "validate", "--config", "/etc/caddy/Caddyfile"]]


def test_caddy_permission_error_without_noninteractive_sudo_is_manual(monkeypatch) -> None:
    reporter = Reporter()

    def fake_command(command, *_args, **_kwargs):
        if command[:2] == ["sudo", "-n"]:
            return 1, "sudo: a password is required"
        return 1, "opening log writer: permission denied"

    monkeypatch.setattr("scripts.certify_staging.command_result", fake_command)

    check_caddy_config(reporter, "/etc/caddy/Caddyfile")

    assert reporter.results[-1].status == "MANUAL_REQUIRED"


def test_server_header_check_uses_the_certified_staging_domain(monkeypatch) -> None:
    reporter = Reporter()
    base_url = "https://staging.autonogrow.es/"
    headers = {
        "Strict-Transport-Security": "max-age=31536000",
        "X-Content-Type-Options": "nosniff",
        "X-Frame-Options": "DENY",
        "Referrer-Policy": "strict-origin-when-cross-origin",
        "Permissions-Policy": "camera=(), microphone=(), geolocation=()",
        "X-Request-ID": "request-123",
    }

    def fake_fetch(actual_base_url, path, _timeout):
        assert actual_base_url == base_url
        body = b'{"status":"ok"}' if path == "/health" else b'{"status":"ready"}'
        return HttpResult(200, headers, body, actual_base_url + path.lstrip("/"), 5)

    monkeypatch.setattr("scripts.certify_staging.fetch", fake_fetch)

    check_health_and_headers(reporter, base_url, 1)

    server_check = next(
        result for result in reporter.results if result.component == "Server disclosure"
    )
    assert server_check.status == "PASS"
