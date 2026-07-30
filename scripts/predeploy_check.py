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
        "deploy/Caddyfile.example",
        "privacy/index.html",
        "data-deletion/index.html",
        "autonogrow-shared/legal.css",
        "docs/security_predeploy_checklist.md",
        "docs/vps_security_deploy_plan.md",
        "docs/staging_deploy_checklist.md",
        "docs/instagram_multi_business_integrations.md",
        "docs/database_migrations.md",
        "docs/dependency_management.md",
        "docs/ci_pipeline.md",
        "docs/sqlite_operations.md",
        "docs/database_backup_and_restore.md",
        "docs/pending_final_validation.md",
        "docs/final_release_validation_matrix.md",
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
            "DATABASE_URL=sqlite:////var/lib/autonogrow/data/autonogrow.db",
            "DATABASE_MIGRATION_CHECK=true",
            "ENABLE_LEGACY_STARTUP_MIGRATIONS=false",
            "SQLITE_BUSY_TIMEOUT_MS=5000",
            "SQLITE_JOURNAL_MODE=WAL",
            "SQLITE_SYNCHRONOUS=NORMAL",
            "UPLOADS_DIR=/var/lib/autonogrow/uploads",
            "INSTAGRAM_PROVIDER_ENABLED=false",
            "INSTAGRAM_REQUIRE_SIGNATURE=true",
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
            "DATABASE_URL=sqlite:////var/lib/autonogrow-staging/data/autonogrow.db",
            "DATABASE_MIGRATION_CHECK=true",
            "ENABLE_LEGACY_STARTUP_MIGRATIONS=false",
            "SQLITE_BUSY_TIMEOUT_MS=5000",
            "SQLITE_JOURNAL_MODE=WAL",
            "SQLITE_SYNCHRONOUS=NORMAL",
            "UPLOADS_DIR=/var/lib/autonogrow-staging/uploads",
            "INSTAGRAM_PROVIDER_ENABLED=false",
            "INSTAGRAM_REQUIRE_SIGNATURE=true",
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
        r"(?im)^[ \t]*(session_secret|smtp_password|meta_app_secret|"
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
            if path.suffix.lower() == ".py" and not raw_value.startswith(("\"", "'")):
                continue
            value = raw_value.strip("\"'").lower()
            if value and not any(marker in value for marker in allowed_markers):
                findings.append(str(path.relative_to(ROOT)))
    if findings:
        reporter.fail(
            "Posibles secretos reales detectados en: " + ", ".join(sorted(set(findings)))
        )
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
        "database_url": "sqlite:////var/lib/autonogrow/data/autonogrow.db",
        "uploads_dir": "/var/lib/autonogrow/uploads",
        "upload_max_size_mb": 5,
        "instagram_provider_enabled": False,
        "instagram_require_signature": True,
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
        "provider Instagram incompleto": {"instagram_provider_enabled": True},
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
        reporter.fail("Alguna configuración production insegura no fue rechazada")
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
    except Exception:
        reporter.fail("No se pudo importar app.main o generar OpenAPI")

    try:
        payload = importlib.import_module("app.routers.health").health_check()
        if payload == {"status": "ok", "app": "autonogrow"}:
            reporter.passed("El healthcheck es mínimo y no expone configuración")
        else:
            reporter.fail("El healthcheck contiene un payload inesperado")
    except Exception:
        reporter.fail("No se pudo validar el healthcheck")
    return config_module.Settings


def main() -> int:
    reporter = Reporter()
    check_required_files(reporter)
    check_deploy_templates(reporter)
    check_frontend_api_base(reporter)
    check_git_env_tracking(reporter)
    check_dependency_locks(reporter)
    check_alembic(reporter)
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
