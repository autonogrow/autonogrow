"""Conservative production dry-run checks. Never prints configuration values."""

from __future__ import annotations

import importlib
import importlib.util
import re
import subprocess
import sys
from pathlib import Path

from sqlalchemy import create_engine

ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "backend"
sys.path.insert(0, str(BACKEND))


def relaunch_with_project_venv_if_needed() -> int | None:
    if importlib.util.find_spec("pydantic_settings") is not None:
        return None
    candidates = (
        ROOT / ".venv" / "Scripts" / "python.exe",
        ROOT / ".venv" / "bin" / "python",
    )
    current = Path(sys.executable).resolve()
    for candidate in candidates:
        if candidate.is_file() and candidate.resolve() != current:
            print("[INFO] Relanzando comprobaciones con el virtualenv del proyecto", flush=True)
            completed = subprocess.run(
                [str(candidate), str(Path(__file__).resolve()), *sys.argv[1:]], check=False
            )
            return completed.returncode
    return None


class Reporter:
    def __init__(self) -> None:
        self.counts = {"PASS": 0, "WARN": 0, "FAIL": 0}

    def add(self, level: str, message: str) -> None:
        self.counts[level] += 1
        print(f"[{level}] {message}")

    def passed(self, message: str) -> None:
        self.add("PASS", message)

    def warn(self, message: str) -> None:
        self.add("WARN", message)

    def fail(self, message: str) -> None:
        self.add("FAIL", message)


def parse_env_file(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    for raw_line in path.read_text(encoding="utf-8-sig").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        values[key.strip().lower()] = value.strip().strip('"').strip("'")
    return values


def check_required_files(reporter: Reporter) -> None:
    required = [
        "backend/.env.example",
        "deploy/backend.env.example",
        "deploy/staging.backend.env.example",
        "deploy/autonogrow.service.example",
        "deploy/autonogrow-worker.service",
        "deploy/Caddyfile.example",
        "privacy/index.html",
        "data-deletion/index.html",
        "autonogrow-shared/legal.css",
        "docs/security_predeploy_checklist.md",
        "docs/vps_security_deploy_plan.md",
        "docs/staging_deploy_checklist.md",
        "docs/instagram_multi_business_integrations.md",
        "docs/instagram_login_architecture.md",
        "docs/manual_test_instagram_login.md",
        "docs/database_migrations.md",
        "docs/dependency_management.md",
        "docs/ci_pipeline.md",
        "docs/sqlite_operations.md",
        "docs/database_backup_and_restore.md",
        "docs/pending_final_validation.md",
        "docs/final_release_validation_matrix.md",
        "docs/persistent_queue_architecture.md",
        "docs/channel_worker_operations.md",
        "docs/meta_integration_health_architecture.md",
        "docs/manual_test_meta_integration_health.md",
        "docs/meta_integration_recovery_runbook.md",
        "docs/whatsapp_cloud_api_inbound_architecture.md",
        "docs/manual_test_whatsapp_cloud_api_inbound.md",
        "docs/whatsapp_cloud_api_outbound_architecture.md",
        "docs/manual_test_whatsapp_cloud_api_outbound.md",
        "docs/webhook_inbox.md",
        "docs/channel_outbox.md",
        "docs/queue_incident_recovery.md",
        "docs/postgresql_architecture.md",
        "docs/sqlite_to_postgresql_migration.md",
        "docs/postgresql_operations.md",
        "docs/postgresql_backup_restore.md",
        "docs/database_concurrency.md",
        "docs/postgresql_rollback.md",
        "alembic.ini",
        "alembic/env.py",
        "alembic/script.py.mako",
        "backend/requirements.in",
        "backend/requirements.txt",
        "backend/requirements-dev.in",
        "backend/requirements-dev.txt",
        "pyproject.toml",
        ".github/workflows/backend-ci.yml",
        "scripts/backup_sqlite_uploads.py",
        "scripts/check_database_migration_state.py",
        "scripts/manage_migrations.py",
        "scripts/test_migration_on_copy.py",
        "scripts/rotate_integration_encryption.py",
        "scripts/smoke_test_staging.py",
        "scripts/cleanup_queue_history.py",
        "scripts/migrate_sqlite_to_postgresql.py",
        "scripts/seed_onboarding_templates.py",
        "deploy/docker-compose.postgresql.yml",
        "docs/business_onboarding_architecture.md",
        "docs/business_onboarding_operations.md",
        "docs/onboarding_templates.md",
        "docs/business_readiness.md",
        "docs/business_activation.md",
        "docs/configuration_cloning.md",
        "docs/manual_test_business_onboarding.md",
        "docs/operations_architecture.md",
        "docs/health_and_readiness.md",
        "docs/logging_and_redaction.md",
        "docs/metrics.md",
        "docs/alerting.md",
        "docs/postgresql_backup_automation.md",
        "docs/backup_verification.md",
        "docs/restore_testing.md",
        "docs/maintenance_operations.md",
        "docs/deployment_procedure.md",
        "docs/release_rollback.md",
        "docs/secret_rotation.md",
        "docs/go_no_go.md",
        "docs/systemd_operations.md",
        "docs/caddy_operations.md",
        "docs/incident_response.md",
        "docs/manual_test_operations.md",
        "scripts/backup_postgresql.py",
        "scripts/backup_uploads.py",
        "scripts/verify_backup.py",
        "scripts/test_postgresql_restore.py",
        "scripts/prune_backups.py",
        "scripts/run_maintenance.py",
        "scripts/manage_maintenance.py",
        "scripts/run_operational_checks.py",
        "scripts/deploy_release.py",
        "scripts/rollback_release.py",
        "scripts/release_readiness.py",
        "scripts/check_secret_rotation_readiness.py",
        "scripts/postgresql_health_check.py",
        "scripts/postgresql_slow_query_report.py",
        "scripts/postgresql_index_health.py",
        "scripts/generate_release_metadata.py",
        "alembic/versions/20260730_06_add_operational_state.py",
        "alembic/versions/20260803_08_add_instagram_oauth_attempts.py",
        "alembic/versions/20260803_09_add_whatsapp_embedded_signup_attempts.py",
        "alembic/versions/20260804_10_add_meta_integration_health.py",
        "alembic/versions/20260814_14_add_customer_opportunities.py",
        "docs/customer_opportunities_architecture.md",
        "docs/manual_test_customer_opportunities.md",
        "alembic/versions/20260814_15_add_opportunity_actions_attribution.py",
        "docs/growth_actions_architecture.md",
        "docs/manual_test_growth_actions.md",
        "alembic/versions/20260814_16_add_business_growth_signals.py",
        "docs/business_growth_signals_architecture.md",
        "docs/manual_test_business_growth_signals.md",
        "alembic/versions/20260814_17_add_customer_memory.py",
        "docs/customer_memory_architecture.md",
        "docs/manual_test_customer_memory.md",
        "alembic/versions/20260814_18_add_social_content_intelligence.py",
        "alembic/versions/20260814_19_add_social_content_generation.py",
        "docs/social_content_intelligence_architecture.md",
        "docs/manual_test_social_content_intelligence.md",
        "docs/whatsapp_embedded_signup_architecture.md",
        "docs/manual_test_whatsapp_embedded_signup.md",
        "deploy/autonogrow-operational-check.service",
        "deploy/autonogrow-operational-check.timer",
        "deploy/autonogrow-backup.service",
        "deploy/autonogrow-backup.timer",
        "deploy/autonogrow-maintenance.service",
        "deploy/autonogrow-maintenance.timer",
    ]
    for relative in required:
        if (ROOT / relative).is_file():
            reporter.passed(f"Existe {relative}")
        else:
            reporter.fail(f"Falta {relative}")


def check_deploy_templates(reporter: Reporter) -> None:
    checks = {
        "deploy/backend.env.example": (
            "APP_ENV=production",
            "COOKIE_SECURE=true",
            "DATABASE_URL=postgresql+psycopg://",
            "ALLOW_SQLITE_IN_PRODUCTION=false",
            "DATABASE_POOL_SIZE=5",
            "DATABASE_STATEMENT_TIMEOUT_MS=30000",
            "WORKER_CONCURRENCY_MODE=single",
            "DATABASE_MIGRATION_CHECK=true",
            "ENABLE_LEGACY_STARTUP_MIGRATIONS=false",
            "SQLITE_BUSY_TIMEOUT_MS=5000",
            "SQLITE_JOURNAL_MODE=WAL",
            "SQLITE_SYNCHRONOUS=NORMAL",
            "UPLOADS_DIR=/var/lib/autonogrow/uploads",
            "INSTAGRAM_PROVIDER_ENABLED=false",
            "INSTAGRAM_REQUIRE_SIGNATURE=true",
            "WHATSAPP_WEBHOOK_ENABLED=false",
            "WHATSAPP_VERIFY_TOKEN=",
            "WHATSAPP_REQUIRE_SIGNATURE=true",
            "WHATSAPP_CUSTOMER_SERVICE_WINDOW_HOURS=24",
            "INTEGRATION_ENCRYPTION_KEYS_JSON=CHANGE_ME_JSON_KEYRING",
            "INTEGRATION_ENCRYPTION_ACTIVE_KEY_VERSION=v1",
            "INCIDENT_ALERTS_ENABLED=false",
            "INCIDENT_ALERT_MIN_SEVERITY=high",
            "INCIDENT_DEDUP_WINDOW_MINUTES=30",
            "SMTP_USE_TLS=true",
        ),
        "deploy/staging.backend.env.example": (
            "APP_ENV=production",
            "FRONTEND_ORIGINS=https://staging.example.com",
            "DATABASE_URL=postgresql+psycopg://",
            "ALLOW_SQLITE_IN_PRODUCTION=false",
            "DATABASE_POOL_SIZE=5",
            "DATABASE_STATEMENT_TIMEOUT_MS=30000",
            "WORKER_CONCURRENCY_MODE=single",
            "DATABASE_MIGRATION_CHECK=true",
            "ENABLE_LEGACY_STARTUP_MIGRATIONS=false",
            "SQLITE_BUSY_TIMEOUT_MS=5000",
            "SQLITE_JOURNAL_MODE=WAL",
            "SQLITE_SYNCHRONOUS=NORMAL",
            "UPLOADS_DIR=/var/lib/autonogrow-staging/uploads",
            "INSTAGRAM_PROVIDER_ENABLED=false",
            "INSTAGRAM_REQUIRE_SIGNATURE=true",
            "WHATSAPP_WEBHOOK_ENABLED=false",
            "WHATSAPP_VERIFY_TOKEN=",
            "WHATSAPP_REQUIRE_SIGNATURE=true",
            "WHATSAPP_CUSTOMER_SERVICE_WINDOW_HOURS=24",
            "INTEGRATION_ENCRYPTION_KEYS_JSON=CHANGE_ME_JSON_KEYRING",
            "INTEGRATION_ENCRYPTION_ACTIVE_KEY_VERSION=v1",
            "INCIDENT_ALERTS_ENABLED=false",
            "INCIDENT_ALERT_MIN_SEVERITY=high",
            "INCIDENT_DEDUP_WINDOW_MINUTES=30",
            "SMTP_USE_TLS=true",
        ),
        "deploy/autonogrow.service.example": (
            "User=autonogrow",
            "EnvironmentFile=/etc/autonogrow/backend.env",
            "--host 127.0.0.1 --port 8000",
            "ProtectSystem=strict",
            "ReadWritePaths=/var/lib/autonogrow",
        ),
        "deploy/Caddyfile.example": (
            "app.example.com",
            "root * /var/www/autonogrow",
            "reverse_proxy 127.0.0.1:8000",
            "/uploads/businesses/*",
        ),
        "deploy/autonogrow-worker.service": (
            "User=autonogrow",
            "python -m app.workers.channel_worker",
            "KillSignal=SIGTERM",
            "NoNewPrivileges=true",
        ),
    }
    for relative, markers in checks.items():
        path = ROOT / relative
        if not path.is_file():
            continue
        text = path.read_text(encoding="utf-8-sig")
        if all(marker in text for marker in markers):
            reporter.passed(f"Plantilla coherente: {relative}")
        else:
            reporter.fail(f"Plantilla incompleta: {relative}")
    caddy = ROOT / "deploy/Caddyfile.example"
    if caddy.is_file() and "/var/lib/autonogrow/uploads" in caddy.read_text(encoding="utf-8-sig"):
        reporter.fail("Caddyfile expone o referencia la raíz privada de uploads")
    elif caddy.is_file():
        reporter.passed("Caddy no sirve la raíz privada de uploads")


def check_frontend_api_base(reporter: Reporter) -> None:
    shared = (ROOT / "autonogrow-shared/auth.js").read_text(encoding="utf-8-sig")
    entrypoints = [
        ROOT / "autonogrow-owner/owner.js",
        ROOT / "autonogrow-admin/admin.js",
        ROOT / "autonogrow-landing/script.js",
        ROOT / "autonogrow-customer/customer.js",
    ]
    shared_ok = "http://127.0.0.1:8000" in shared and "window.location.origin" in shared
    consumers_ok = all(
        "AutonoGrowAuth.API_BASE_URL" in path.read_text(encoding="utf-8-sig")
        for path in entrypoints
    )
    if shared_ok and consumers_ok:
        reporter.passed("Frontend usa backend local en desarrollo y mismo origen en production")
    else:
        reporter.fail("La resolución de API del frontend no es coherente local/production")


def check_git_env_tracking(reporter: Reporter) -> None:
    try:
        inside = subprocess.run(
            ["git", "-C", str(ROOT), "rev-parse", "--is-inside-work-tree"],
            capture_output=True,
            text=True,
            timeout=5,
            check=False,
        )
    except (FileNotFoundError, subprocess.TimeoutExpired):
        reporter.warn("Git no está disponible; no se pudo comprobar si .env está tracked")
        return
    if inside.returncode != 0 or inside.stdout.strip() != "true":
        reporter.warn("La carpeta no es un worktree Git válido; comprobación de .env omitida")
        return
    tracked = subprocess.run(
        ["git", "-C", str(ROOT), "ls-files", "--", ".env", "backend/.env"],
        capture_output=True,
        text=True,
        timeout=5,
        check=False,
    )
    if tracked.stdout.strip():
        reporter.fail("Un fichero .env real está tracked por Git")
    else:
        reporter.passed("Los ficheros .env reales no están tracked por Git")


def tracked_files() -> list[Path]:
    completed = subprocess.run(
        ["git", "-C", str(ROOT), "ls-files", "--cached", "--others", "--exclude-standard"],
        capture_output=True,
        text=True,
        timeout=10,
        check=False,
    )
    if completed.returncode:
        return []
    return [ROOT / item for item in completed.stdout.splitlines() if item]


def check_dependency_locks(reporter: Reporter) -> None:
    for relative in ("backend/requirements.txt", "backend/requirements-dev.txt"):
        path = ROOT / relative
        if not path.is_file():
            continue
        floating = []
        for line_number, raw_line in enumerate(
            path.read_text(encoding="utf-8-sig").splitlines(), start=1
        ):
            line = raw_line.strip()
            if not line or line.startswith("#") or line.startswith("--"):
                continue
            if "==" not in line:
                floating.append(line_number)
        if floating:
            reporter.fail(f"{relative} contiene dependencias no fijadas")
        else:
            reporter.passed(f"{relative} contiene solo versiones exactas")

    production_lock = (ROOT / "backend/requirements.txt").read_text(encoding="utf-8-sig")
    if "psycopg[binary]==3.3.4" in production_lock and "psycopg-binary==3.3.4" in production_lock:
        reporter.passed("psycopg 3 y su distribución binary están fijados")
    else:
        reporter.fail("El lock de producción no contiene psycopg 3 binary fijado")


def check_alembic(reporter: Reporter) -> None:
    try:
        from alembic.script import ScriptDirectory

        from app.core.migration_state import alembic_config

        heads = ScriptDirectory.from_config(alembic_config()).get_heads()
    except Exception:
        reporter.fail("Alembic no puede cargar su configuración o revisiones")
        return
    if len(heads) == 1:
        reporter.passed(f"Alembic tiene una única head: {heads[0]}")
        if heads[0] != "20260814_19":
            reporter.fail("La head operativa esperada es 20260814_19")
    else:
        reporter.fail("Alembic debe tener exactamente una head")


def check_database_revision(reporter: Reporter, config_module) -> None:
    from app.core.migration_state import inspect_database_migration_state

    database_url = config_module.get_database_url()
    database_path = config_module.sqlite_file_path(database_url)
    if database_path is not None and not Path(database_path).is_file():
        reporter.fail("La base configurada no existe; no se crea durante predeploy")
        return
    diagnostic_engine = create_engine(database_url)
    try:
        state = inspect_database_migration_state(diagnostic_engine)
    except Exception:
        reporter.fail("No se pudo comprobar la revisión de la base configurada")
        return
    finally:
        diagnostic_engine.dispose()
    if state.is_at_head:
        reporter.passed("La base configurada está en Alembic head")
    else:
        reporter.fail(f"La base configurada requiere: {state.recommendation}")


def check_tracked_secrets(reporter: Reporter) -> None:
    assignment = re.compile(
        r"(?im)^[ \t]*(session_secret|smtp_password|meta_app_secret|database_url|"
        r"integration_encryption_keys_json)[ \t]*=[ \t]*([^\s#]+)"
    )
    allowed_markers = (
        "change_me",
        "placeholder",
        "replace-with",
        "example",
        "test",
        "fake",
        "clave_",
        "aleatorio",
        "server-vault",
        "redacted",
        "<",
    )
    findings: list[str] = []
    for path in tracked_files():
        if path.suffix.lower() not in {".py", ".env", ".example", ".yml", ".yaml", ".md"}:
            continue
        try:
            content = path.read_text(encoding="utf-8-sig")
        except (OSError, UnicodeError):
            continue
        for match in assignment.finditer(content):
            raw_value = match.group(2)
            if path.suffix.lower() == ".py" and not raw_value.startswith(('"', "'")):
                continue
            value = raw_value.strip("\"'").lower()
            if match.group(1).lower() == "database_url" and value.startswith("sqlite:"):
                continue
            if value and not any(marker in value for marker in allowed_markers):
                findings.append(str(path.relative_to(ROOT)))
    if findings:
        reporter.fail("Posibles secretos reales detectados en: " + ", ".join(sorted(set(findings))))
    else:
        reporter.passed("No se detectaron secretos reales en archivos versionados")


def production_baseline() -> dict[str, object]:
    return {
        "app_env": "production",
        "cookie_secure": True,
        "csrf_enabled": True,
        "rate_limit_enabled": True,
        "security_headers_enabled": True,
        "frontend_origins": "https://autonogrow.test",
        "session_secret": "9f2d1e7a4c6b8a0d3e5f7a9c1b2d4e6f",
        "google_client_id": "1234567890-abcdef.apps.googleusercontent.com",
        "owner_allowed_emails": "owner@autonogrow.test",
        "database_url": "postgresql+psycopg://autonogrow:test-only@localhost/autonogrow",
        "uploads_dir": "/var/lib/autonogrow/uploads",
        "upload_max_size_mb": 5,
        "instagram_provider_enabled": False,
        "instagram_require_signature": True,
        "whatsapp_webhook_enabled": False,
        "whatsapp_require_signature": True,
        "whatsapp_customer_service_window_hours": 24,
    }


def check_production_validation(reporter: Reporter, Settings) -> None:
    baseline = production_baseline()
    try:
        Settings(_env_file=None, **baseline)
        reporter.passed("Una configuración production segura es aceptada")
    except Exception:
        reporter.fail("La configuración production segura de control fue rechazada")
        return

    unsafe_cases = {
        "COOKIE_SECURE=false": {"cookie_secure": False},
        "CSRF desactivado": {"csrf_enabled": False},
        "rate limit desactivado": {"rate_limit_enabled": False},
        "security headers desactivados": {"security_headers_enabled": False},
        "SESSION_SECRET placeholder": {"session_secret": "CHANGE_ME_LONG_RANDOM_SECRET_CHANGE_ME"},
        "SESSION_SECRET corto": {"session_secret": "too-short"},
        "GOOGLE_CLIENT_ID placeholder": {
            "google_client_id": "CHANGE_ME.apps.googleusercontent.com"
        },
        "OWNER_ALLOWED_EMAILS vacío": {"owner_allowed_emails": ""},
        "CORS wildcard": {"frontend_origins": "*"},
        "CORS HTTP": {"frontend_origins": "http://app.autonogrow.test"},
        "CORS placeholder": {"frontend_origins": "https://app.example.com"},
        "DATABASE_URL relativa": {"database_url": "sqlite:///./data/autonogrow.db"},
        "DATABASE_URL vacía": {"database_url": ""},
        "DATABASE_URL dentro del repo": {
            "database_url": f"sqlite:///{(BACKEND / 'data' / 'autonogrow.db').as_posix()}"
        },
        "UPLOADS_DIR relativa": {"uploads_dir": "backend/uploads"},
        "UPLOADS_DIR vacía": {"uploads_dir": ""},
        "UPLOADS_DIR pública": {"uploads_dir": "/var/www/autonogrow/uploads"},
        "UPLOADS_DIR dentro del frontend": {"uploads_dir": str(ROOT / "autonogrow-landing")},
        "firma Instagram desactivada": {"instagram_require_signature": False},
        "provider Instagram incompleto": {
            "instagram_provider_enabled": True,
            "meta_app_id": "",
            "meta_app_secret": "",
            "meta_verify_token": "",
            "integration_encryption_keys_json": "",
        },
        "firma WhatsApp desactivada": {
            "whatsapp_webhook_enabled": True,
            "whatsapp_require_signature": False,
        },
        "webhook WhatsApp incompleto": {
            "whatsapp_webhook_enabled": True,
            "meta_app_secret": "",
            "whatsapp_verify_token": "",
        },
        "ventana WhatsApp nula": {"whatsapp_customer_service_window_hours": 0},
        "ventana WhatsApp ilimitada": {"whatsapp_customer_service_window_hours": 25},
        "alertas de incidencias incompletas": {"incident_alerts_enabled": True},
    }
    accepted: list[str] = []
    for label, override in unsafe_cases.items():
        values = {**baseline, **override}
        try:
            Settings(_env_file=None, **values)
            accepted.append(label)
        except Exception:
            pass
    if accepted:
        reporter.fail("Configuraciones production inseguras no rechazadas: " + ", ".join(accepted))
    else:
        reporter.passed(
            f"Las {len(unsafe_cases)} configuraciones production inseguras fueron rechazadas"
        )


def check_real_env(reporter: Reporter, Settings) -> None:
    env_path = BACKEND / ".env"
    if not env_path.exists():
        reporter.warn(
            "backend/.env no existe; correcto para repo, pero el VPS necesita /etc/autonogrow/backend.env"
        )
        return
    try:
        values = parse_env_file(env_path)
    except OSError:
        reporter.fail("No se pudo leer backend/.env")
        return
    if values.get("app_env", "local").lower() != "production":
        reporter.warn(
            "backend/.env existe pero no declara APP_ENV=production; válido solo para local"
        )
        return
    try:
        Settings(_env_file=None, **values)
        reporter.passed("backend/.env production no contiene placeholders ni rutas inseguras")
    except Exception:
        reporter.fail(
            "backend/.env production contiene valores ausentes, placeholders o rutas inseguras"
        )


def check_application(reporter: Reporter):
    try:
        config_module = importlib.import_module("app.core.config")
        settings = config_module.get_settings()
        reporter.passed(f"La configuración actual carga correctamente en modo {settings.app_env}")
    except Exception:
        reporter.fail("La configuración actual no carga")
        return None

    try:
        main_module = importlib.import_module("app.main")
        schema = main_module.app.openapi()
        if not schema.get("paths"):
            raise RuntimeError("OpenAPI sin paths")
        reporter.passed("app.main importa y OpenAPI carga")
        queue_paths = {
            "/api/owner/system/queue-status",
            "/api/owner/queue/inbox/{job_id}/retry",
            "/api/owner/queue/inbox/{job_id}/cancel",
            "/api/owner/queue/outbox/{job_id}/retry",
            "/api/owner/queue/outbox/{job_id}/cancel",
        }
        if queue_paths <= set(schema.get("paths", {})):
            reporter.passed("Endpoints owner de colas registrados")
        else:
            reporter.fail("Faltan endpoints owner de colas")
    except Exception:
        reporter.fail("No se pudo importar app.main o generar OpenAPI")

    try:
        payload = importlib.import_module("app.routers.health").health_check()
        if payload == {"status": "ok"}:
            reporter.passed("El healthcheck es mínimo y no expone configuración")
        else:
            reporter.fail("El healthcheck contiene un payload inesperado")
    except Exception:
        reporter.fail("No se pudo validar el healthcheck")
    return config_module.Settings


def check_persistent_queue_contract(reporter: Reporter) -> None:
    from app.core.database import Base
    from app.models.registry import register_models

    register_models()
    required_tables = {"webhook_inbox_events", "channel_outbox_messages", "worker_heartbeats"}
    if required_tables <= set(Base.metadata.tables):
        reporter.passed("Modelos de cola registrados")
    else:
        reporter.fail("Faltan modelos de cola en metadata")
    env_text = "\n".join(
        (ROOT / path).read_text(encoding="utf-8-sig")
        for path in (
            "backend/.env.example",
            "deploy/backend.env.example",
            "deploy/staging.backend.env.example",
        )
    )
    required_vars = {
        "WEBHOOK_MAX_PAYLOAD_BYTES",
        "WORKER_ENABLED",
        "WORKER_LOCK_TIMEOUT_SECONDS",
        "WORKER_HEARTBEAT_INTERVAL_SECONDS",
        "PROCESS_WEBHOOK_SYNCHRONOUSLY=false",
    }
    if all(value in env_text for value in required_vars):
        reporter.passed("Variables de worker e inbox documentadas")
    else:
        reporter.fail("Faltan variables de worker documentadas")
    pending = (ROOT / "docs/pending_final_validation.md").read_text(encoding="utf-8-sig")
    if all(f"Q-S2-{index:02d}" in pending and "Pendiente" in pending for index in range(1, 31)):
        reporter.passed("Matriz contiene 30 pruebas manuales pendientes")
    else:
        reporter.fail("Faltan pruebas manuales pendientes de colas")


def check_postgresql_contract(reporter: Reporter) -> None:
    required_settings = {
        "ALLOW_SQLITE_IN_PRODUCTION",
        "DATABASE_POOL_SIZE",
        "DATABASE_MAX_OVERFLOW",
        "DATABASE_POOL_TIMEOUT_SECONDS",
        "DATABASE_POOL_RECYCLE_SECONDS",
        "DATABASE_CONNECT_TIMEOUT_SECONDS",
        "DATABASE_STATEMENT_TIMEOUT_MS",
        "DATABASE_LOCK_TIMEOUT_MS",
        "DATABASE_IDLE_TRANSACTION_TIMEOUT_MS",
        "DATABASE_APPLICATION_NAME",
        "WORKER_CONCURRENCY_MODE",
    }
    examples = "\n".join(
        (ROOT / relative).read_text(encoding="utf-8-sig")
        for relative in (
            "backend/.env.example",
            "deploy/backend.env.example",
            "deploy/staging.backend.env.example",
        )
    )
    if all(name in examples for name in required_settings):
        reporter.passed("Pool, timeouts y concurrencia PostgreSQL están documentados")
    else:
        reporter.fail("Faltan variables PostgreSQL en las plantillas")

    workflow = (ROOT / ".github/workflows/backend-ci.yml").read_text(encoding="utf-8-sig")
    if "postgres:16.10-alpine" in workflow and "pytest -m postgresql" in workflow:
        reporter.passed("CI contiene servicio y tests PostgreSQL reales")
    else:
        reporter.fail("CI PostgreSQL está incompleta")

    pending = (ROOT / "docs/pending_final_validation.md").read_text(encoding="utf-8-sig")
    rows = [line for line in pending.splitlines() if line.startswith("| PG-S3-")]
    if len(rows) == 30 and all("Pendiente" in row for row in rows):
        reporter.passed("Las 30 validaciones manuales PostgreSQL siguen pendientes")
    else:
        reporter.fail("La matriz PostgreSQL debe contener 30 pruebas pendientes")


def check_onboarding_contract(reporter: Reporter) -> None:
    from app.core.database import Base
    from app.models.registry import register_models
    from app.services.onboarding_template_catalog import (
        SYSTEM_ONBOARDING_TEMPLATES,
        template_has_forbidden_data,
    )

    register_models()
    required_tables = {
        "business_onboarding_sessions",
        "business_onboarding_templates",
        "business_staff_profiles",
        "business_staff_profile_services",
    }
    if required_tables <= set(Base.metadata.tables):
        reporter.passed("Modelos de onboarding registrados")
    else:
        reporter.fail("Faltan modelos de onboarding en metadata")
    if not any(template_has_forbidden_data(item) for item in SYSTEM_ONBOARDING_TEMPLATES):
        reporter.passed("Plantillas iniciales sin claves de secretos")
    else:
        reporter.fail("Una plantilla contiene campos sensibles")
    owner_router = (ROOT / "backend/app/routers/owner_onboarding.py").read_text(
        encoding="utf-8-sig"
    )
    owner_legacy = (ROOT / "backend/app/routers/owner.py").read_text(encoding="utf-8-sig")
    required_markers = (
        "/businesses/{business_id}/activate",
        "/businesses/{business_id}/suspend",
        "/businesses/{business_id}/preview",
        "evaluate_business_readiness",
        "lock_business",
    )
    if all(marker in owner_router for marker in required_markers):
        reporter.passed("Endpoints owner, preview y readiness registrados")
    else:
        reporter.fail("Contrato de endpoints onboarding incompleto")
    if 'business.status = "active" if active' not in owner_legacy:
        reporter.passed("No existe activación mediante PATCH owner genérico")
    else:
        reporter.fail("PATCH owner genérico todavía modifica el estado")
    manual = (ROOT / "docs/manual_test_business_onboarding.md").read_text(encoding="utf-8-sig")
    if manual.count("- [ ]") == 40:
        reporter.passed("Las 40 pruebas manuales de onboarding siguen pendientes")
    else:
        reporter.fail("La matriz manual de onboarding debe tener 40 pendientes")


def check_whatsapp_contract(reporter: Reporter) -> None:
    from app.services.channel_provider_service import (
        DELIVERY_PROVIDERS_BY_CHANNEL,
        INBOX_CHANNELS_BY_PROVIDER,
        INBOX_PROCESSORS,
        PROVIDER_SENDERS,
        delivery_supported,
    )

    if INBOX_CHANNELS_BY_PROVIDER.get("whatsapp") == "whatsapp" and "whatsapp" in INBOX_PROCESSORS:
        reporter.passed("WhatsApp registrado en el dispatcher de inbox")
    else:
        reporter.fail("WhatsApp no está registrado correctamente en el inbox")
    if (
        "whatsapp" in PROVIDER_SENDERS
        and DELIVERY_PROVIDERS_BY_CHANNEL.get("whatsapp") == "whatsapp"
        and delivery_supported(channel="whatsapp")
    ):
        reporter.passed("WhatsApp registrado con sender y soporte de entrega")
    else:
        reporter.fail("Sender o soporte de entrega WhatsApp incompleto")

    main_text = (ROOT / "backend/app/main.py").read_text(encoding="utf-8-sig")
    if (
        "whatsapp_webhook_router" in main_text
        and "include_router(whatsapp_webhook_router)" in main_text
    ):
        reporter.passed("Router WhatsApp registrado en app.main")
    else:
        reporter.fail("Router WhatsApp no está registrado en app.main")

    required_vars = {
        "WHATSAPP_WEBHOOK_ENABLED=false",
        "WHATSAPP_VERIFY_TOKEN=",
        "WHATSAPP_REQUIRE_SIGNATURE=",
        "WHATSAPP_CUSTOMER_SERVICE_WINDOW_HOURS=24",
    }
    env_paths = (
        "backend/.env.example",
        "deploy/backend.env.example",
        "deploy/staging.backend.env.example",
    )
    if all(
        all(marker in (ROOT / path).read_text(encoding="utf-8-sig") for marker in required_vars)
        for path in env_paths
    ):
        reporter.passed("Variables WhatsApp documentadas sin activar la integración")
    else:
        reporter.fail("Faltan variables WhatsApp en los ejemplos de entorno")

    admin_text = (ROOT / "autonogrow-admin/admin.js").read_text(encoding="utf-8-sig")
    conversation_router = (ROOT / "backend/app/routers/conversations.py").read_text(
        encoding="utf-8-sig"
    )
    if (
        all(
            marker in admin_text
            for marker in (
                "Enviar desde AutonoGrow",
                "Abrir en WhatsApp",
                "integrated_delivery_available",
                "assisted_delivery_available",
            )
        )
        and "assisted-delivery" in conversation_router
    ):
        reporter.passed("Fallback asistido WhatsApp conserva contrato separado")
    else:
        reporter.fail("Fallback asistido WhatsApp incompleto")


def check_instagram_login_contract(reporter: Reporter) -> None:
    from app.models.registry import register_models
    from app.services.instagram_login_provider import INSTAGRAM_LOGIN_SCOPES

    register_models()
    from app.core.database import Base

    if "instagram_oauth_attempts" in Base.metadata.tables:
        table = Base.metadata.tables["instagram_oauth_attempts"]
        required_columns = {
            "state_hash",
            "session_fingerprint_hash",
            "expires_at",
            "candidate_encrypted_access_token",
            "candidate_encryption_key_version",
        }
        if required_columns <= set(table.columns.keys()):
            reporter.passed("Estado OAuth hasheado y candidatura cifrada registrados")
        else:
            reporter.fail("Modelo temporal de Instagram Login incompleto")
    else:
        reporter.fail("Falta instagram_oauth_attempts en metadata")

    expected_scopes = (
        "instagram_business_basic",
        "instagram_business_manage_messages",
    )
    if INSTAGRAM_LOGIN_SCOPES == expected_scopes:
        reporter.passed("Instagram Login solicita solo identidad y mensajería")
    else:
        reporter.fail("Scopes de Instagram Login fuera del alcance aprobado")

    env_paths = (
        "backend/.env.example",
        "deploy/backend.env.example",
        "deploy/staging.backend.env.example",
    )
    required_env = {
        "INSTAGRAM_LOGIN_ENABLED=false",
        "INSTAGRAM_LOGIN_CLIENT_ID=",
        "INSTAGRAM_LOGIN_CLIENT_SECRET=",
        "INSTAGRAM_LOGIN_REDIRECT_URI=",
        "INSTAGRAM_LOGIN_GRAPH_API_VERSION=",
        "INSTAGRAM_OAUTH_ATTEMPT_TTL_SECONDS=600",
        "INSTAGRAM_SIMULATED_ONBOARDING_TEST_ONLY=false",
    }
    if all(
        all(marker in (ROOT / path).read_text(encoding="utf-8-sig") for marker in required_env)
        for path in env_paths
    ):
        reporter.passed("Variables Instagram Login documentadas y simulación desactivada")
    else:
        reporter.fail("Plantillas de entorno Instagram Login incompletas")

    oauth_router = (ROOT / "backend/app/routers/instagram_oauth.py").read_text(encoding="utf-8-sig")
    oauth_service = (ROOT / "backend/app/services/instagram_oauth_service.py").read_text(
        encoding="utf-8-sig"
    )
    required_markers = (
        'callback_router.get("/callback")',
        'admin_router.post("/oauth/start")',
        "session_fingerprint",
        'InstagramOAuthAttempt.status == "pending"',
        'attempt.status = "candidate_ready"',
        "integrated_delivery_enabled = False",
        "automation_enabled = False",
    )
    contract = oauth_router + oauth_service
    if all(marker in contract for marker in required_markers):
        reporter.passed("Callback, replay y aprobación Owner conservan capacidades apagadas")
    else:
        reporter.fail("Contrato seguro de Instagram Login incompleto")

    frontend = "\n".join(
        (ROOT / path).read_text(encoding="utf-8-sig")
        for path in ("autonogrow-admin/admin.js", "autonogrow-owner/owner.js")
    )
    if "authorization_url" in frontend and "instagram-client-secret" not in frontend.lower():
        reporter.passed("Frontend navega a autorización sin secretos OAuth")
    else:
        reporter.fail("Frontend Instagram Login no cumple el contrato de secretos")


def check_whatsapp_embedded_signup_contract(reporter: Reporter) -> None:
    from app.models.registry import register_models
    from app.services.whatsapp_embedded_signup_provider import (
        WHATSAPP_EMBEDDED_SIGNUP_EVENT_TYPE,
        WHATSAPP_EMBEDDED_SIGNUP_FINISH_EVENT,
        WHATSAPP_EMBEDDED_SIGNUP_SDK_URL,
    )

    register_models()
    from app.core.database import Base

    table = Base.metadata.tables.get("whatsapp_embedded_signup_attempts")
    required_columns = {
        "state_hash",
        "session_fingerprint_hash",
        "candidate_waba_id",
        "candidate_phone_number_id",
        "candidate_encrypted_access_token",
        "candidate_encryption_key_version",
        "app_subscription_status",
        "phone_registration_status",
    }
    if table is not None and required_columns <= set(table.columns.keys()):
        reporter.passed("Candidatura temporal WhatsApp hasheada y cifrada registrada")
    else:
        reporter.fail("Modelo temporal de WhatsApp Embedded Signup incompleto")

    if (
        WHATSAPP_EMBEDDED_SIGNUP_EVENT_TYPE == "WA_EMBEDDED_SIGNUP"
        and WHATSAPP_EMBEDDED_SIGNUP_FINISH_EVENT == "FINISH"
        and WHATSAPP_EMBEDDED_SIGNUP_SDK_URL == "https://connect.facebook.net/en_US/sdk.js"
    ):
        reporter.passed("Contrato público de Meta Embedded Signup fijado explícitamente")
    else:
        reporter.fail("Contrato público de Meta Embedded Signup inesperado")

    env_paths = (
        "backend/.env.example",
        "deploy/backend.env.example",
        "deploy/staging.backend.env.example",
    )
    required_env = {
        "WHATSAPP_EMBEDDED_SIGNUP_ENABLED=false",
        "WHATSAPP_EMBEDDED_SIGNUP_CONFIG_ID=",
        "WHATSAPP_EMBEDDED_SIGNUP_GRAPH_API_VERSION=v26.0",
        "WHATSAPP_EMBEDDED_SIGNUP_ATTEMPT_TTL_SECONDS=600",
        "WHATSAPP_EMBEDDED_SIGNUP_TEST_ONLY=false",
    }
    if all(
        all(marker in (ROOT / path).read_text(encoding="utf-8-sig") for marker in required_env)
        for path in env_paths
    ):
        reporter.passed("Configuración de WhatsApp Embedded Signup documentada y apagada")
    else:
        reporter.fail("Plantillas de WhatsApp Embedded Signup incompletas")

    contract = "\n".join(
        (ROOT / path).read_text(encoding="utf-8-sig")
        for path in (
            "backend/app/services/whatsapp_embedded_signup_service.py",
            "backend/app/routers/whatsapp_embedded_signup.py",
            "autonogrow-admin/admin.js",
        )
    )
    required_markers = (
        'WhatsAppEmbeddedSignupAttempt.status == "pending"',
        'attempt.status = "candidate_ready"',
        'control.connection_mode = "embedded_signup"',
        "integrated_delivery_enabled = False",
        "automation_enabled = False",
        "isTrustedMetaEventOrigin",
        "override_default_response_type: true",
    )
    if all(marker in contract for marker in required_markers):
        reporter.passed("Replay, origen, candidatura y aprobación separada están protegidos")
    else:
        reporter.fail("Contrato seguro de WhatsApp Embedded Signup incompleto")

    forbidden_frontend = (
        "meta_app_secret",
        "candidate_encrypted_access_token",
        "configuration.access_token",
    )
    embedded_frontend = (ROOT / "autonogrow-admin/admin.js").read_text(encoding="utf-8-sig")
    if not any(marker in embedded_frontend for marker in forbidden_frontend):
        reporter.passed("Frontend Embedded Signup no recibe ni persiste credenciales")
    else:
        reporter.fail("Frontend Embedded Signup contiene marcadores sensibles")


def check_meta_integration_health_contract(reporter: Reporter) -> None:
    from app.core.database import Base
    from app.models.registry import register_models
    from app.services.meta_integration_health_checkers import INTEGRATION_HEALTH_CHECKERS

    register_models()
    integration = Base.metadata.tables.get("business_channel_integrations")
    jobs = Base.metadata.tables.get("meta_integration_jobs")
    required_health_columns = {
        "health_status",
        "last_health_check_at",
        "next_health_check_at",
        "consecutive_health_failures",
        "health_error_code",
        "health_safe_error_message",
        "health_metadata_json",
    }
    if (
        integration is not None
        and required_health_columns <= {column.name for column in integration.columns}
        and jobs is not None
    ):
        reporter.passed("Persistencia de salud Meta registrada")
    else:
        reporter.fail("Falta persistencia de salud Meta")
    if set(INTEGRATION_HEALTH_CHECKERS) == {"instagram", "whatsapp"}:
        reporter.passed("Checkers Meta registrados sin proveedor controlable")
    else:
        reporter.fail("Registro de checkers Meta inesperado")
    env_text = "\n".join(
        (ROOT / path).read_text(encoding="utf-8-sig")
        for path in (
            "backend/.env.example",
            "deploy/backend.env.example",
            "deploy/staging.backend.env.example",
        )
    )
    required_vars = {
        "META_INTEGRATION_HEALTH_CHECK_ENABLED",
        "META_INTEGRATION_HEALTH_CHECK_INTERVAL_HOURS",
        "META_TOKEN_EXPIRY_WARNING_DAYS",
        "META_TOKEN_EXPIRY_CRITICAL_DAYS",
        "META_INTEGRATION_HEALTH_BATCH_SIZE",
        "META_INTEGRATION_HEALTH_LOCK_TTL_SECONDS",
    }
    if required_vars <= {line.split("=", 1)[0] for line in env_text.splitlines() if "=" in line}:
        reporter.passed("Configuración Meta health documentada")
    else:
        reporter.fail("Faltan variables Meta health")
    worker = (ROOT / "backend/app/workers/channel_worker.py").read_text(encoding="utf-8-sig")
    forbidden = ("send_instagram_text_message(", "send_whatsapp_text_message(")
    if "schedule_due_meta_jobs" in worker and not any(value in worker for value in forbidden):
        reporter.passed("Predeploy valida registro sin ejecutar llamadas Meta")
    else:
        reporter.fail("Contrato del scheduler Meta inesperado")


def main() -> int:
    reporter = Reporter()
    check_required_files(reporter)
    check_deploy_templates(reporter)
    check_frontend_api_base(reporter)
    check_git_env_tracking(reporter)
    check_dependency_locks(reporter)
    check_alembic(reporter)
    check_persistent_queue_contract(reporter)
    check_postgresql_contract(reporter)
    check_onboarding_contract(reporter)
    check_whatsapp_contract(reporter)
    check_instagram_login_contract(reporter)
    check_whatsapp_embedded_signup_contract(reporter)
    check_meta_integration_health_contract(reporter)
    check_tracked_secrets(reporter)
    Settings = check_application(reporter)
    if Settings is not None:
        config_module = importlib.import_module("app.core.config")
        check_production_validation(reporter, Settings)
        check_real_env(reporter, Settings)
        check_database_revision(reporter, config_module)
    else:
        reporter.fail("No se pudieron ejecutar las validaciones production")

    print(
        f"Resumen: {reporter.counts['PASS']} PASS, "
        f"{reporter.counts['WARN']} WARN, {reporter.counts['FAIL']} FAIL"
    )
    return 1 if reporter.counts["FAIL"] else 0


if __name__ == "__main__":
    relaunched = relaunch_with_project_venv_if_needed()
    raise SystemExit(main() if relaunched is None else relaunched)
