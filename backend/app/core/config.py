from functools import lru_cache
from pathlib import Path, PurePosixPath, PureWindowsPath
import shutil
import re
from urllib.parse import urlsplit

from pydantic import model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


BACKEND_DIR = Path(__file__).resolve().parents[2]
REPO_DIR = BACKEND_DIR.parent


def is_absolute_path_text(value: str) -> bool:
    return any(path.is_absolute() for path in (Path(value), PurePosixPath(value), PureWindowsPath(value)))


def sqlite_file_path(database_url: str) -> str | None:
    prefix = "sqlite:///"
    if not database_url.startswith(prefix) or database_url == "sqlite:///:memory:":
        return None
    return database_url.removeprefix(prefix).split("?", 1)[0]


def path_is_inside_repo(value: str) -> bool:
    path = Path(value)
    if not path.is_absolute():
        return False
    try:
        path.resolve().relative_to(REPO_DIR.resolve())
        return True
    except ValueError:
        return False


def uploads_path_looks_public(value: str) -> bool:
    normalized = value.replace("\\", "/").lower().rstrip("/")
    parts = [part for part in normalized.split("/") if part]
    if normalized.endswith(("/public", "/static", "/www")) or "var/www" in normalized:
        return True
    return any(part.startswith("autonogrow-") for part in parts)


class Settings(BaseSettings):
    app_name: str = "AutonoGrow Backend"
    app_version: str = "0.1.0"
    environment: str = "development"
    database_url: str = ""
    google_client_id: str = ""
    session_secret: str = ""
    owner_allowed_emails: str = ""
    app_env: str = "local"
    cookie_secure: bool = False
    frontend_origins: str = "http://127.0.0.1:5500,http://localhost:5500"
    csrf_enabled: bool = False
    rate_limit_enabled: bool = False
    security_headers_enabled: bool = True
    upload_max_size_mb: int = 5
    uploads_dir: str = ""
    webhook_test_secret: str = ""
    meta_app_id: str = ""
    meta_app_secret: str = ""
    meta_verify_token: str = ""
    meta_graph_api_version: str = "v23.0"
    instagram_access_token: str = ""
    instagram_business_account_id: str = ""
    instagram_default_business_slug: str = ""
    instagram_provider_enabled: bool = False
    instagram_require_signature: bool = True
    incident_alerts_enabled: bool = False
    incident_alert_email: str = ""
    incident_alert_min_severity: str = "high"
    incident_dedup_window_minutes: int = 30
    incident_recovery_email_enabled: bool = True
    smtp_host: str = ""
    smtp_port: int = 587
    smtp_username: str = ""
    smtp_password: str = ""
    smtp_from: str = ""
    smtp_use_tls: bool = True

    model_config = SettingsConfigDict(
        env_file=(str(BACKEND_DIR / ".env"), ".env"),
        env_file_encoding="utf-8",
        extra="ignore",
    )

    @model_validator(mode="after")
    def validate_security_configuration(self):
        self.app_env = self.app_env.strip().lower()
        if self.app_env not in {"local", "production"}:
            raise ValueError("APP_ENV debe ser local o production")
        self.incident_alert_min_severity = self.incident_alert_min_severity.strip().lower()
        if self.incident_alert_min_severity not in {"low", "medium", "high", "critical"}:
            raise ValueError("INCIDENT_ALERT_MIN_SEVERITY debe ser low, medium, high o critical")
        if self.incident_dedup_window_minutes < 1 or self.incident_dedup_window_minutes > 10080:
            raise ValueError("INCIDENT_DEDUP_WINDOW_MINUTES debe estar entre 1 y 10080")
        if self.smtp_port < 1 or self.smtp_port > 65535:
            raise ValueError("SMTP_PORT no es válido")
        if self.incident_alerts_enabled:
            alert_errors = []
            if "@" not in self.incident_alert_email.strip():
                alert_errors.append("INCIDENT_ALERT_EMAIL")
            if not self.smtp_host.strip():
                alert_errors.append("SMTP_HOST")
            if "@" not in self.smtp_from.strip():
                alert_errors.append("SMTP_FROM")
            if bool(self.smtp_username.strip()) != bool(self.smtp_password):
                alert_errors.append("SMTP_USERNAME/SMTP_PASSWORD")
            if alert_errors:
                raise ValueError(
                    "Configuración de alertas incompleta: " + ", ".join(alert_errors)
                )
        if self.upload_max_size_mb < 1 or self.upload_max_size_mb > 25:
            raise ValueError("UPLOAD_MAX_SIZE_MB debe estar entre 1 y 25")
        if self.app_env != "production":
            return self

        errors: list[str] = []
        secret = self.session_secret.strip()
        origins = self.frontend_origin_list
        if not self.cookie_secure:
            errors.append("COOKIE_SECURE debe ser true")
        if len(secret) < 32 or any(marker in secret.lower() for marker in ("replace-with", "change-me", "change_me", "changeme", "placeholder")):
            errors.append("SESSION_SECRET debe ser real y tener al menos 32 caracteres")
        google_client_id = self.google_client_id.strip().lower()
        if (
            not google_client_id.endswith(".apps.googleusercontent.com")
            or any(marker in google_client_id for marker in ("placeholder", "change_me", "change-me", "example"))
        ):
            errors.append("GOOGLE_CLIENT_ID debe estar configurado")
        owner_emails = [item.strip().lower() for item in self.owner_allowed_emails.split(",") if item.strip()]
        if not owner_emails or any("@" not in email or email.endswith("@example.com") for email in owner_emails):
            errors.append("OWNER_ALLOWED_EMAILS debe contener emails reales")
        if not origins:
            errors.append("FRONTEND_ORIGINS no puede estar vacío")
        if any("*" in origin for origin in origins):
            errors.append("FRONTEND_ORIGINS no puede contener wildcard")
        for origin in origins:
            parsed = urlsplit(origin)
            if (
                parsed.scheme != "https"
                or not parsed.netloc
                or parsed.hostname == "example.com"
                or (parsed.hostname or "").endswith(".example.com")
                or parsed.path not in {"", "/"}
                or parsed.query
                or parsed.fragment
            ):
                errors.append("FRONTEND_ORIGINS debe contener orígenes HTTPS exactos")
                break
        database_url = self.database_url.strip()
        database_path = sqlite_file_path(database_url)
        if not database_url:
            errors.append("DATABASE_URL debe estar configurado")
        elif database_url.startswith("sqlite"):
            if database_path is None or not is_absolute_path_text(database_path):
                errors.append("DATABASE_URL SQLite debe usar una ruta absoluta fuera del repo")
            elif path_is_inside_repo(database_path):
                errors.append("DATABASE_URL no puede guardar producción dentro del repo")
        elif "://" not in database_url:
            errors.append("DATABASE_URL debe ser una URL de conexión válida")
        uploads_dir = self.uploads_dir.strip()
        if not uploads_dir or not is_absolute_path_text(uploads_dir):
            errors.append("UPLOADS_DIR debe ser una ruta absoluta")
        elif path_is_inside_repo(uploads_dir) or uploads_path_looks_public(uploads_dir):
            errors.append("UPLOADS_DIR debe estar fuera del repo y del frontend público")
        if not self.csrf_enabled:
            errors.append("CSRF_ENABLED debe estar activo")
        if not self.rate_limit_enabled:
            errors.append("RATE_LIMIT_ENABLED debe estar activo")
        if not self.security_headers_enabled:
            errors.append("SECURITY_HEADERS_ENABLED debe estar activo")
        if not self.instagram_require_signature:
            errors.append("INSTAGRAM_REQUIRE_SIGNATURE debe estar activo")
        if self.instagram_provider_enabled:
            instagram_required = {
                "META_APP_ID": self.meta_app_id,
                "META_APP_SECRET": self.meta_app_secret,
                "META_VERIFY_TOKEN": self.meta_verify_token,
                "INSTAGRAM_ACCESS_TOKEN": self.instagram_access_token,
                "INSTAGRAM_BUSINESS_ACCOUNT_ID": self.instagram_business_account_id,
                "INSTAGRAM_DEFAULT_BUSINESS_SLUG": self.instagram_default_business_slug,
            }
            missing_instagram = [
                name
                for name, value in instagram_required.items()
                if not value.strip()
                or any(
                    marker in value.strip().lower()
                    for marker in ("change_me", "change-me", "placeholder")
                )
            ]
            if missing_instagram:
                errors.append(
                    "Configuración Instagram incompleta: "
                    + ", ".join(missing_instagram)
                )
            if not re.fullmatch(r"v\d+\.\d+", self.meta_graph_api_version.strip()):
                errors.append("META_GRAPH_API_VERSION no es válida")
        if errors:
            raise ValueError("Configuración de producción insegura: " + "; ".join(errors))
        return self

    @property
    def frontend_origin_list(self) -> list[str]:
        return [origin.strip().rstrip("/") for origin in self.frontend_origins.split(",") if origin.strip()]


@lru_cache
def get_settings() -> Settings:
    return Settings()


def get_backend_dir() -> Path:
    return BACKEND_DIR


def get_data_dir() -> Path:
    data_dir = get_backend_dir() / "data"
    data_dir.mkdir(parents=True, exist_ok=True)
    return data_dir


def get_uploads_dir() -> Path:
    configured = get_settings().uploads_dir.strip()
    uploads_dir = Path(configured) if configured else get_backend_dir() / "uploads"
    if not uploads_dir.is_absolute():
        uploads_dir = get_backend_dir() / uploads_dir
    uploads_dir = uploads_dir.resolve()
    uploads_dir.mkdir(parents=True, exist_ok=True)
    return uploads_dir


def migrate_legacy_uploads() -> None:
    """Copy pre-branding booking uploads without overwriting newer files."""
    legacy_dir = get_data_dir() / "uploads"
    uploads_dir = get_uploads_dir()
    if not legacy_dir.exists():
        return
    for source in legacy_dir.rglob("*"):
        if not source.is_file():
            continue
        relative = source.relative_to(legacy_dir)
        destination = uploads_dir / relative
        if destination.exists():
            continue
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, destination)


def get_database_url() -> str:
    settings = get_settings()

    if settings.database_url:
        return settings.database_url

    db_path = get_data_dir() / "autonogrow.db"
    return f"sqlite:///{db_path}"


def get_owner_allowed_emails() -> set[str]:
    return {
        email.strip().lower()
        for email in get_settings().owner_allowed_emails.split(",")
        if email.strip()
    }
