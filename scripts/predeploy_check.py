"""Conservative production dry-run checks. Never prints configuration values."""

from __future__ import annotations

import importlib
import importlib.util
import subprocess
import sys
from pathlib import Path


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
            completed = subprocess.run([str(candidate), str(Path(__file__).resolve()), *sys.argv[1:]], check=False)
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
        "scripts/backup_sqlite_uploads.py",
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
            "UPLOADS_DIR=/var/lib/autonogrow/uploads",
            "INSTAGRAM_PROVIDER_ENABLED=false",
            "INSTAGRAM_REQUIRE_SIGNATURE=true",
            "INCIDENT_ALERTS_ENABLED=false",
            "INCIDENT_ALERT_MIN_SEVERITY=high",
            "INCIDENT_DEDUP_WINDOW_MINUTES=30",
            "SMTP_USE_TLS=true",
        ),
        "deploy/staging.backend.env.example": (
            "APP_ENV=production",
            "FRONTEND_ORIGINS=https://staging.example.com",
            "DATABASE_URL=sqlite:////var/lib/autonogrow-staging/data/autonogrow.db",
            "UPLOADS_DIR=/var/lib/autonogrow-staging/uploads",
            "INSTAGRAM_PROVIDER_ENABLED=false",
            "INSTAGRAM_REQUIRE_SIGNATURE=true",
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
    consumers_ok = all("AutonoGrowAuth.API_BASE_URL" in path.read_text(encoding="utf-8-sig") for path in entrypoints)
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
        "GOOGLE_CLIENT_ID placeholder": {"google_client_id": "CHANGE_ME.apps.googleusercontent.com"},
        "OWNER_ALLOWED_EMAILS vacío": {"owner_allowed_emails": ""},
        "CORS wildcard": {"frontend_origins": "*"},
        "CORS HTTP": {"frontend_origins": "http://app.autonogrow.test"},
        "CORS placeholder": {"frontend_origins": "https://app.example.com"},
        "DATABASE_URL relativa": {"database_url": "sqlite:///./data/autonogrow.db"},
        "DATABASE_URL vacía": {"database_url": ""},
        "DATABASE_URL dentro del repo": {"database_url": f"sqlite:///{(BACKEND / 'data' / 'autonogrow.db').as_posix()}"},
        "UPLOADS_DIR relativa": {"uploads_dir": "backend/uploads"},
        "UPLOADS_DIR vacía": {"uploads_dir": ""},
        "UPLOADS_DIR pública": {"uploads_dir": "/var/www/autonogrow/uploads"},
        "UPLOADS_DIR dentro del frontend": {"uploads_dir": str(ROOT / "autonogrow-landing" )},
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
        reporter.passed(f"Las {len(unsafe_cases)} configuraciones production inseguras fueron rechazadas")


def check_real_env(reporter: Reporter, Settings) -> None:
    env_path = BACKEND / ".env"
    if not env_path.exists():
        reporter.warn("backend/.env no existe; correcto para repo, pero el VPS necesita /etc/autonogrow/backend.env")
        return
    try:
        values = parse_env_file(env_path)
    except OSError:
        reporter.fail("No se pudo leer backend/.env")
        return
    if values.get("app_env", "local").lower() != "production":
        reporter.warn("backend/.env existe pero no declara APP_ENV=production; válido solo para local")
        return
    try:
        Settings(_env_file=None, **values)
        reporter.passed("backend/.env production no contiene placeholders ni rutas inseguras")
    except Exception:
        reporter.fail("backend/.env production contiene valores ausentes, placeholders o rutas inseguras")


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
    Settings = check_application(reporter)
    if Settings is not None:
        check_production_validation(reporter, Settings)
        check_real_env(reporter, Settings)
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
