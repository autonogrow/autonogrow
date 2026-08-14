import json
from pathlib import Path
from types import SimpleNamespace

import pytest
from scripts import instagram_publication_preflight as publication_preflight_cli
from scripts.certify_staging import (
    HttpResult,
    Reporter,
    check_build,
    check_readiness,
    normalize_base_url,
    tamper_signed_url,
)
from sqlalchemy import create_engine, inspect
from sqlalchemy.orm import sessionmaker

from app.core.config import Settings
from app.routers import config as config_router
from app.workers.instagram_publish_worker import worker_startup_check


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
