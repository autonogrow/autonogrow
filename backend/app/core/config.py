import ipaddress
import json
import re
import shutil
from functools import lru_cache
from pathlib import Path, PurePosixPath, PureWindowsPath
from urllib.parse import urlsplit

from pydantic import model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict
from sqlalchemy.engine import make_url

BACKEND_DIR = Path(__file__).resolve().parents[2]
REPO_DIR = BACKEND_DIR.parent


def is_absolute_path_text(value: str) -> bool:
    return any(
        path.is_absolute() for path in (Path(value), PurePosixPath(value), PureWindowsPath(value))
    )


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


def sanitize_database_url(database_url: str) -> str:
    """Return a log-safe database label without credentials or query parameters."""

    value = database_url.strip()
    if not value:
        return "<not-configured>"
    try:
        url = make_url(value)
    except (TypeError, ValueError):
        return "<invalid-database-url>"
    if url.get_backend_name() == "sqlite":
        return "sqlite:///:memory:" if url.database == ":memory:" else "sqlite:///<local-file>"
    safe_url = url.set(
        username="***" if url.username else None, password="***" if url.password else None
    )
    return safe_url.difference_update_query(tuple(safe_url.query)).render_as_string(
        hide_password=False
    )


class Settings(BaseSettings):
    app_name: str = "AutonoGrow Backend"
    app_version: str = "0.1.0"
    app_release_id: str = "local"
    app_git_commit: str = "unknown"
    app_build_time: str = "unknown"
    environment: str = "development"
    database_url: str = ""
    allow_sqlite_in_production: bool = False
    database_pool_size: int = 5
    database_max_overflow: int = 5
    database_pool_timeout_seconds: int = 30
    database_pool_recycle_seconds: int = 1800
    database_connect_timeout_seconds: int = 10
    database_statement_timeout_ms: int = 30000
    database_lock_timeout_ms: int = 5000
    database_idle_transaction_timeout_ms: int = 30000
    database_application_name: str = "autonogrow"
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
    instagram_login_enabled: bool = False
    instagram_login_client_id: str = ""
    instagram_login_client_secret: str = ""
    instagram_login_redirect_uri: str = ""
    instagram_login_graph_api_version: str = "v23.0"
    instagram_oauth_attempt_ttl_seconds: int = 600
    instagram_candidate_review_ttl_hours: int = 72
    instagram_simulated_onboarding_test_only: bool = False
    instagram_publishing_worker_enabled: bool = False
    instagram_publishing_poll_seconds: float = 2.0
    instagram_publishing_max_attempts: int = 5
    instagram_publishing_claim_ttl_seconds: int = 120
    instagram_publishing_backoff_base_seconds: int = 30
    instagram_publishing_backoff_max_seconds: int = 3600
    instagram_publishing_simulated_mode: bool = True
    instagram_default_timezone: str = "Europe/Madrid"
    whatsapp_webhook_enabled: bool = False
    whatsapp_verify_token: str = ""
    whatsapp_require_signature: bool = True
    whatsapp_customer_service_window_hours: int = 24
    whatsapp_embedded_signup_enabled: bool = False
    whatsapp_embedded_signup_config_id: str = ""
    whatsapp_embedded_signup_graph_api_version: str = ""
    whatsapp_embedded_signup_attempt_ttl_seconds: int = 600
    whatsapp_embedded_signup_test_only: bool = False
    meta_integration_health_check_enabled: bool = True
    meta_integration_health_check_interval_hours: int = 24
    meta_token_expiry_warning_days: int = 14
    meta_token_expiry_critical_days: int = 3
    meta_integration_failure_threshold: int = 3
    meta_integration_cleanup_interval_hours: int = 24
    meta_expired_attempt_retention_days: int = 7
    meta_integration_health_batch_size: int = 5
    meta_integration_health_job_timeout_seconds: int = 20
    meta_integration_health_lock_ttl_seconds: int = 180
    integration_encryption_keys_json: str = ""
    integration_encryption_active_key_version: str = "v1"
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
    enable_legacy_startup_migrations: bool = False
    database_migration_check: bool = True
    sqlite_busy_timeout_ms: int = 5000
    sqlite_journal_mode: str = "WAL"
    sqlite_synchronous: str = "NORMAL"
    webhook_max_payload_bytes: int = 1_048_576
    worker_enabled: bool = True
    worker_concurrency_mode: str = "single"
    worker_id: str = ""
    worker_poll_interval_seconds: float = 1.0
    worker_batch_size: int = 10
    worker_lock_timeout_seconds: int = 60
    worker_max_attempts: int = 5
    worker_job_timeout_seconds: int = 30
    worker_heartbeat_interval_seconds: int = 15
    worker_stale_after_seconds: int = 60
    process_webhook_synchronously: bool = False
    webhook_inbox_retention_days: int = 30
    outbox_retention_days: int = 90
    worker_heartbeat_retention_days: int = 7
    readiness_timeout_seconds: float = 2.0
    readiness_min_disk_free_bytes: int = 268_435_456
    log_level: str = "INFO"
    log_format: str = "auto"
    log_include_source: bool = False
    log_max_field_length: int = 2048
    log_redact_sensitive: bool = True
    metrics_enabled: bool = False
    metrics_path: str = "/internal/metrics"
    metrics_auth_token: str = ""
    metrics_allowed_ips: str = "127.0.0.1,::1"
    operational_alerts_enabled: bool = False
    alert_email_recipients: str = ""
    alert_webhook_url: str = ""
    alert_webhook_secret: str = ""
    alert_cooldown_minutes: int = 30
    alert_queue_backlog_warning: int = 100
    alert_queue_backlog_critical: int = 500
    alert_queue_oldest_warning_seconds: int = 300
    alert_queue_oldest_critical_seconds: int = 1800
    alert_disk_free_warning_percent: float = 20.0
    alert_disk_free_critical_percent: float = 10.0
    alert_backup_max_age_hours: int = 30
    alert_restore_test_max_age_days: int = 14
    backup_enabled: bool = False
    backup_dir: str = ""
    backup_state_dir: str = ""
    backup_retention_days: int = 30
    backup_minimum_count: int = 7
    backup_pg_dump_path: str = "pg_dump"
    backup_pg_restore_path: str = "pg_restore"
    backup_timeout_seconds: int = 1800
    maintenance_worker_mode: str = "continue"
    maintenance_public_message: str = "Service temporarily unavailable"
    storage_cache_seconds: int = 60
    storage_scan_max_files: int = 10000

    model_config = SettingsConfigDict(
        env_file=(str(BACKEND_DIR / ".env"), ".env"),
        env_file_encoding="utf-8",
        extra="ignore",
    )

    @model_validator(mode="after")
    def validate_security_configuration(self):
        self.app_env = self.app_env.strip().lower()
        if self.app_env not in {"local", "test", "staging", "production"}:
            raise ValueError("APP_ENV debe ser local, test, staging o production")
        self.sqlite_journal_mode = self.sqlite_journal_mode.strip().upper()
        self.sqlite_synchronous = self.sqlite_synchronous.strip().upper()
        self.worker_concurrency_mode = self.worker_concurrency_mode.strip().lower()
        self.database_application_name = self.database_application_name.strip()
        self.log_level = self.log_level.strip().upper()
        self.log_format = self.log_format.strip().lower()
        if self.log_format == "auto":
            self.log_format = "json" if self.app_env in {"staging", "production"} else "text"
        self.maintenance_worker_mode = self.maintenance_worker_mode.strip().lower()
        self.metrics_path = "/" + self.metrics_path.strip().lstrip("/")
        self.app_release_id = self.app_release_id.strip() or "local"
        self.app_git_commit = self.app_git_commit.strip() or "unknown"
        self.app_build_time = self.app_build_time.strip() or "unknown"
        if not re.fullmatch(r"[A-Za-z0-9_.-]{1,120}", self.app_release_id):
            raise ValueError("APP_RELEASE_ID no es válido")
        if not re.fullmatch(r"(?:[0-9a-fA-F]{7,64}|unknown)", self.app_git_commit):
            raise ValueError("APP_GIT_COMMIT no es válido")
        if len(self.app_build_time) > 80:
            raise ValueError("APP_BUILD_TIME es demasiado largo")
        if not 3 <= len(self.maintenance_public_message.strip()) <= 200:
            raise ValueError("MAINTENANCE_PUBLIC_MESSAGE debe tener entre 3 y 200 caracteres")
        if self.sqlite_busy_timeout_ms < 1 or self.sqlite_busy_timeout_ms > 60000:
            raise ValueError("SQLITE_BUSY_TIMEOUT_MS debe estar entre 1 y 60000")
        if self.sqlite_journal_mode not in {"DELETE", "TRUNCATE", "PERSIST", "WAL"}:
            raise ValueError("SQLITE_JOURNAL_MODE debe ser DELETE, TRUNCATE, PERSIST o WAL")
        if self.sqlite_synchronous not in {"OFF", "NORMAL", "FULL", "EXTRA"}:
            raise ValueError("SQLITE_SYNCHRONOUS debe ser OFF, NORMAL, FULL o EXTRA")
        database_ranges = (
            ("DATABASE_POOL_SIZE", self.database_pool_size, 1, 50),
            ("DATABASE_MAX_OVERFLOW", self.database_max_overflow, 0, 100),
            ("DATABASE_POOL_TIMEOUT_SECONDS", self.database_pool_timeout_seconds, 1, 300),
            ("DATABASE_POOL_RECYCLE_SECONDS", self.database_pool_recycle_seconds, 30, 86400),
            ("DATABASE_CONNECT_TIMEOUT_SECONDS", self.database_connect_timeout_seconds, 1, 60),
            ("DATABASE_STATEMENT_TIMEOUT_MS", self.database_statement_timeout_ms, 100, 600000),
            ("DATABASE_LOCK_TIMEOUT_MS", self.database_lock_timeout_ms, 100, 600000),
            (
                "DATABASE_IDLE_TRANSACTION_TIMEOUT_MS",
                self.database_idle_transaction_timeout_ms,
                100,
                600000,
            ),
        )
        for name, value, minimum, maximum in database_ranges:
            if not minimum <= value <= maximum:
                raise ValueError(f"{name} debe estar entre {minimum} y {maximum}")
        if not re.fullmatch(r"[A-Za-z0-9_.-]{1,64}", self.database_application_name):
            raise ValueError("DATABASE_APPLICATION_NAME no es válido")
        if self.worker_concurrency_mode not in {"single", "multi"}:
            raise ValueError("WORKER_CONCURRENCY_MODE debe ser single o multi")
        if self.log_level not in {"DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"}:
            raise ValueError("LOG_LEVEL no es válido")
        if self.log_format not in {"text", "json"}:
            raise ValueError("LOG_FORMAT debe ser auto, text o json")
        if not 128 <= self.log_max_field_length <= 65536:
            raise ValueError("LOG_MAX_FIELD_LENGTH debe estar entre 128 y 65536")
        if not 0.1 <= self.readiness_timeout_seconds <= 10:
            raise ValueError("READINESS_TIMEOUT_SECONDS debe estar entre 0.1 y 10")
        if self.readiness_min_disk_free_bytes < 0:
            raise ValueError("READINESS_MIN_DISK_FREE_BYTES no puede ser negativo")
        if not re.fullmatch(r"/[A-Za-z0-9_./-]{1,120}", self.metrics_path):
            raise ValueError("METRICS_PATH no es válido")
        for allowed_ip in self.metrics_allowed_ip_list:
            try:
                ipaddress.ip_address(allowed_ip)
            except ValueError as exc:
                raise ValueError("METRICS_ALLOWED_IPS contiene una IP no válida") from exc
        if self.metrics_auth_token and len(self.metrics_auth_token) < 32:
            raise ValueError("METRICS_AUTH_TOKEN debe tener al menos 32 caracteres")
        if (
            self.metrics_enabled
            and not self.metrics_allowed_ip_list
            and not self.metrics_auth_token
        ):
            raise ValueError("METRICS_ENABLED requiere IPs permitidas o token")
        if self.maintenance_worker_mode not in {"continue", "pause"}:
            raise ValueError("MAINTENANCE_WORKER_MODE debe ser continue o pause")
        if not 1 <= self.storage_cache_seconds <= 3600:
            raise ValueError("STORAGE_CACHE_SECONDS debe estar entre 1 y 3600")
        if not 100 <= self.storage_scan_max_files <= 1_000_000:
            raise ValueError("STORAGE_SCAN_MAX_FILES debe estar entre 100 y 1000000")
        operational_ranges = (
            ("ALERT_COOLDOWN_MINUTES", self.alert_cooldown_minutes, 1, 10080),
            ("ALERT_QUEUE_BACKLOG_WARNING", self.alert_queue_backlog_warning, 1, 1_000_000),
            ("ALERT_QUEUE_BACKLOG_CRITICAL", self.alert_queue_backlog_critical, 1, 1_000_000),
            (
                "ALERT_QUEUE_OLDEST_WARNING_SECONDS",
                self.alert_queue_oldest_warning_seconds,
                1,
                604800,
            ),
            (
                "ALERT_QUEUE_OLDEST_CRITICAL_SECONDS",
                self.alert_queue_oldest_critical_seconds,
                1,
                604800,
            ),
            ("ALERT_BACKUP_MAX_AGE_HOURS", self.alert_backup_max_age_hours, 1, 8760),
            ("ALERT_RESTORE_TEST_MAX_AGE_DAYS", self.alert_restore_test_max_age_days, 1, 3650),
            ("BACKUP_RETENTION_DAYS", self.backup_retention_days, 1, 3650),
            ("BACKUP_MINIMUM_COUNT", self.backup_minimum_count, 1, 1000),
            ("BACKUP_TIMEOUT_SECONDS", self.backup_timeout_seconds, 30, 86400),
        )
        for name, value, minimum, maximum in operational_ranges:
            if not minimum <= value <= maximum:
                raise ValueError(f"{name} debe estar entre {minimum} y {maximum}")
        if self.alert_queue_backlog_critical <= self.alert_queue_backlog_warning:
            raise ValueError("El umbral crítico de cola debe superar al de warning")
        if self.alert_queue_oldest_critical_seconds <= self.alert_queue_oldest_warning_seconds:
            raise ValueError("El umbral crítico de antigüedad debe superar al de warning")
        if (
            not 0
            < self.alert_disk_free_critical_percent
            < self.alert_disk_free_warning_percent
            < 100
        ):
            raise ValueError("Los umbrales de disco deben cumplir 0 < critical < warning < 100")
        if self.alert_webhook_url and not self.alert_webhook_url.startswith("https://"):
            raise ValueError("ALERT_WEBHOOK_URL debe utilizar HTTPS")
        if self.alert_webhook_url and len(self.alert_webhook_secret) < 32:
            raise ValueError("ALERT_WEBHOOK_SECRET debe tener al menos 32 caracteres")
        if any("@" not in value for value in self.alert_email_recipient_list):
            raise ValueError("ALERT_EMAIL_RECIPIENTS contiene un email no válido")
        if self.backup_enabled:
            for name, path_value in (
                ("BACKUP_DIR", self.backup_dir),
                ("BACKUP_STATE_DIR", self.backup_state_dir),
            ):
                if (
                    not path_value
                    or not is_absolute_path_text(path_value)
                    or path_is_inside_repo(path_value)
                ):
                    raise ValueError(f"{name} debe ser una ruta absoluta fuera del repo")
        configured_url = self.database_url.strip()
        try:
            database_backend = (
                make_url(configured_url).get_backend_name() if configured_url else "sqlite"
            )
        except (TypeError, ValueError) as exc:
            raise ValueError("DATABASE_URL debe ser una URL de conexión válida") from exc
        if database_backend not in {"sqlite", "postgresql"}:
            raise ValueError("DATABASE_URL debe utilizar SQLite o PostgreSQL")
        if database_backend == "sqlite" and self.worker_concurrency_mode == "multi":
            raise ValueError("SQLite solo permite WORKER_CONCURRENCY_MODE=single")
        if not 1024 <= self.webhook_max_payload_bytes <= 10_485_760:
            raise ValueError("WEBHOOK_MAX_PAYLOAD_BYTES debe estar entre 1024 y 10485760")
        if not 1 <= self.whatsapp_customer_service_window_hours <= 24:
            raise ValueError("WHATSAPP_CUSTOMER_SERVICE_WINDOW_HOURS debe estar entre 1 y 24")
        if not 300 <= self.whatsapp_embedded_signup_attempt_ttl_seconds <= 1800:
            raise ValueError(
                "WHATSAPP_EMBEDDED_SIGNUP_ATTEMPT_TTL_SECONDS debe estar entre 300 y 1800"
            )
        signup_version = self.whatsapp_embedded_signup_graph_api_version.strip()
        if signup_version and not re.fullmatch(r"v\d+\.\d+", signup_version):
            raise ValueError("WHATSAPP_EMBEDDED_SIGNUP_GRAPH_API_VERSION no es válida")
        if self.whatsapp_embedded_signup_test_only and self.app_env != "test":
            raise ValueError("WHATSAPP_EMBEDDED_SIGNUP_TEST_ONLY solo se permite en test")
        if not 300 <= self.instagram_oauth_attempt_ttl_seconds <= 1800:
            raise ValueError("INSTAGRAM_OAUTH_ATTEMPT_TTL_SECONDS debe estar entre 300 y 1800")
        if not 1 <= self.instagram_candidate_review_ttl_hours <= 168:
            raise ValueError("INSTAGRAM_CANDIDATE_REVIEW_TTL_HOURS debe estar entre 1 y 168")
        if not re.fullmatch(r"v\d+\.\d+", self.instagram_login_graph_api_version.strip()):
            raise ValueError("INSTAGRAM_LOGIN_GRAPH_API_VERSION no es válida")
        if self.instagram_simulated_onboarding_test_only and self.app_env != "test":
            raise ValueError("INSTAGRAM_SIMULATED_ONBOARDING_TEST_ONLY solo se permite en test")
        publishing_ranges = (
            ("INSTAGRAM_PUBLISHING_POLL_SECONDS", self.instagram_publishing_poll_seconds, 0.1, 60),
            ("INSTAGRAM_PUBLISHING_MAX_ATTEMPTS", self.instagram_publishing_max_attempts, 1, 20),
            (
                "INSTAGRAM_PUBLISHING_CLAIM_TTL_SECONDS",
                self.instagram_publishing_claim_ttl_seconds,
                10,
                3600,
            ),
            (
                "INSTAGRAM_PUBLISHING_BACKOFF_BASE_SECONDS",
                self.instagram_publishing_backoff_base_seconds,
                1,
                86400,
            ),
            (
                "INSTAGRAM_PUBLISHING_BACKOFF_MAX_SECONDS",
                self.instagram_publishing_backoff_max_seconds,
                1,
                604800,
            ),
        )
        for (
            publishing_name,
            publishing_value,
            publishing_minimum,
            publishing_maximum,
        ) in publishing_ranges:
            if not publishing_minimum <= publishing_value <= publishing_maximum:
                raise ValueError(
                    f"{publishing_name} debe estar entre {publishing_minimum} y {publishing_maximum}"
                )
        if (
            self.instagram_publishing_backoff_max_seconds
            < self.instagram_publishing_backoff_base_seconds
        ):
            raise ValueError("INSTAGRAM_PUBLISHING_BACKOFF_MAX_SECONDS debe ser >= al valor base")
        try:
            from zoneinfo import ZoneInfo

            ZoneInfo(self.instagram_default_timezone)
        except (KeyError, ValueError) as exc:
            raise ValueError("INSTAGRAM_DEFAULT_TIMEZONE no es válida") from exc
        health_ranges = (
            (
                "META_INTEGRATION_HEALTH_CHECK_INTERVAL_HOURS",
                self.meta_integration_health_check_interval_hours,
                1,
                168,
            ),
            ("META_TOKEN_EXPIRY_WARNING_DAYS", self.meta_token_expiry_warning_days, 2, 90),
            ("META_TOKEN_EXPIRY_CRITICAL_DAYS", self.meta_token_expiry_critical_days, 1, 30),
            (
                "META_INTEGRATION_FAILURE_THRESHOLD",
                self.meta_integration_failure_threshold,
                2,
                20,
            ),
            (
                "META_INTEGRATION_CLEANUP_INTERVAL_HOURS",
                self.meta_integration_cleanup_interval_hours,
                1,
                168,
            ),
            (
                "META_EXPIRED_ATTEMPT_RETENTION_DAYS",
                self.meta_expired_attempt_retention_days,
                1,
                365,
            ),
            (
                "META_INTEGRATION_HEALTH_BATCH_SIZE",
                self.meta_integration_health_batch_size,
                1,
                50,
            ),
            (
                "META_INTEGRATION_HEALTH_JOB_TIMEOUT_SECONDS",
                self.meta_integration_health_job_timeout_seconds,
                1,
                300,
            ),
            (
                "META_INTEGRATION_HEALTH_LOCK_TTL_SECONDS",
                self.meta_integration_health_lock_ttl_seconds,
                10,
                3600,
            ),
        )
        for name, value, minimum, maximum in health_ranges:
            if not minimum <= value <= maximum:
                raise ValueError(f"{name} debe estar entre {minimum} y {maximum}")
        if self.meta_token_expiry_warning_days <= self.meta_token_expiry_critical_days:
            raise ValueError(
                "META_TOKEN_EXPIRY_WARNING_DAYS debe superar META_TOKEN_EXPIRY_CRITICAL_DAYS"
            )
        if (
            self.meta_integration_health_lock_ttl_seconds
            <= self.meta_integration_health_job_timeout_seconds * 6
        ):
            raise ValueError(
                "META_INTEGRATION_HEALTH_LOCK_TTL_SECONDS debe superar seis veces el timeout"
            )
        if not 0.1 <= self.worker_poll_interval_seconds <= 60:
            raise ValueError("WORKER_POLL_INTERVAL_SECONDS debe estar entre 0.1 y 60")
        if not 1 <= self.worker_batch_size <= 100:
            raise ValueError("WORKER_BATCH_SIZE debe estar entre 1 y 100")
        if not self.worker_poll_interval_seconds < self.worker_lock_timeout_seconds <= 3600:
            raise ValueError(
                "WORKER_LOCK_TIMEOUT_SECONDS debe ser mayor que poll y no superar 3600"
            )
        if not 1 <= self.worker_max_attempts <= 20:
            raise ValueError("WORKER_MAX_ATTEMPTS debe estar entre 1 y 20")
        if not 1 <= self.worker_job_timeout_seconds <= 600:
            raise ValueError("WORKER_JOB_TIMEOUT_SECONDS debe estar entre 1 y 600")
        if not 1 <= self.worker_heartbeat_interval_seconds <= 300:
            raise ValueError("WORKER_HEARTBEAT_INTERVAL_SECONDS debe estar entre 1 y 300")
        if not self.worker_heartbeat_interval_seconds < self.worker_stale_after_seconds <= 3600:
            raise ValueError("WORKER_STALE_AFTER_SECONDS debe ser mayor que heartbeat")
        for name, value in (
            ("WEBHOOK_INBOX_RETENTION_DAYS", self.webhook_inbox_retention_days),
            ("OUTBOX_RETENTION_DAYS", self.outbox_retention_days),
            ("WORKER_HEARTBEAT_RETENTION_DAYS", self.worker_heartbeat_retention_days),
        ):
            if not 1 <= value <= 3650:
                raise ValueError(f"{name} debe estar entre 1 y 3650")
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
                raise ValueError("Configuración de alertas incompleta: " + ", ".join(alert_errors))
        if self.upload_max_size_mb < 1 or self.upload_max_size_mb > 25:
            raise ValueError("UPLOAD_MAX_SIZE_MB debe estar entre 1 y 25")
        if self.app_env not in {"staging", "production"}:
            return self

        errors: list[str] = []
        secret = self.session_secret.strip()
        origins = self.frontend_origin_list
        if not self.cookie_secure:
            errors.append("COOKIE_SECURE debe ser true")
        if len(secret) < 32 or any(
            marker in secret.lower()
            for marker in ("replace-with", "change-me", "change_me", "changeme", "placeholder")
        ):
            errors.append("SESSION_SECRET debe ser real y tener al menos 32 caracteres")
        google_client_id = self.google_client_id.strip().lower()
        if not google_client_id.endswith(".apps.googleusercontent.com") or any(
            marker in google_client_id
            for marker in ("placeholder", "change_me", "change-me", "example")
        ):
            errors.append("GOOGLE_CLIENT_ID debe estar configurado")
        owner_emails = [
            item.strip().lower() for item in self.owner_allowed_emails.split(",") if item.strip()
        ]
        if not owner_emails or any(
            "@" not in email or email.endswith("@example.com") for email in owner_emails
        ):
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
        database_url = configured_url
        database_path = sqlite_file_path(database_url)
        if not database_url:
            errors.append("DATABASE_URL debe estar configurado")
        elif database_backend == "sqlite":
            if not self.allow_sqlite_in_production:
                errors.append(
                    "PostgreSQL es obligatorio; ALLOW_SQLITE_IN_PRODUCTION solo sirve para emergencias"
                )
            elif database_path is None or not is_absolute_path_text(database_path):
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
        if self.enable_legacy_startup_migrations:
            errors.append("ENABLE_LEGACY_STARTUP_MIGRATIONS debe ser false")
        if self.process_webhook_synchronously:
            errors.append("PROCESS_WEBHOOK_SYNCHRONOUSLY debe ser false")
        if not self.database_migration_check:
            errors.append("DATABASE_MIGRATION_CHECK debe ser true")
        if self.instagram_provider_enabled:
            instagram_required = {
                "META_APP_ID": self.meta_app_id,
                "META_APP_SECRET": self.meta_app_secret,
                "META_VERIFY_TOKEN": self.meta_verify_token,
                "INTEGRATION_ENCRYPTION_KEYS_JSON": self.integration_encryption_keys_json,
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
                errors.append("Configuración Instagram incompleta: " + ", ".join(missing_instagram))
            if not re.fullmatch(r"v\d+\.\d+", self.meta_graph_api_version.strip()):
                errors.append("META_GRAPH_API_VERSION no es válida")
            try:
                encryption_keys = json.loads(self.integration_encryption_keys_json)
            except (TypeError, ValueError):
                encryption_keys = None
            active_version = self.integration_encryption_active_key_version.strip()
            if (
                not isinstance(encryption_keys, dict)
                or not encryption_keys
                or not active_version
                or active_version not in encryption_keys
            ):
                errors.append("Configuración de cifrado de integraciones no válida")
        if self.instagram_login_enabled:
            if not self.instagram_provider_enabled:
                errors.append("INSTAGRAM_LOGIN_ENABLED requiere INSTAGRAM_PROVIDER_ENABLED=true")
            instagram_login_required = {
                "INSTAGRAM_LOGIN_CLIENT_ID": self.instagram_login_client_id,
                "INSTAGRAM_LOGIN_CLIENT_SECRET": self.instagram_login_client_secret,
                "INSTAGRAM_LOGIN_REDIRECT_URI": self.instagram_login_redirect_uri,
                "INTEGRATION_ENCRYPTION_KEYS_JSON": self.integration_encryption_keys_json,
            }
            missing_login = [
                name
                for name, value in instagram_login_required.items()
                if not value.strip()
                or any(
                    marker in value.strip().lower()
                    for marker in ("change_me", "change-me", "placeholder", "example.com")
                )
            ]
            if missing_login:
                errors.append(
                    "Configuración Instagram Login incompleta: " + ", ".join(missing_login)
                )
            redirect = urlsplit(self.instagram_login_redirect_uri.strip())
            redirect_origin = f"{redirect.scheme}://{redirect.netloc}" if redirect.netloc else ""
            if (
                redirect.scheme != "https"
                or not redirect.netloc
                or redirect_origin not in origins
                or redirect.query
                or redirect.fragment
                or redirect.path != "/api/integrations/instagram/callback"
            ):
                errors.append(
                    "INSTAGRAM_LOGIN_REDIRECT_URI debe ser HTTPS y terminar exactamente en "
                    "/api/integrations/instagram/callback"
                )
        if self.whatsapp_webhook_enabled:
            if not self.whatsapp_require_signature:
                errors.append("WHATSAPP_REQUIRE_SIGNATURE debe estar activo")
            whatsapp_required = {
                "META_APP_SECRET": self.meta_app_secret,
                "WHATSAPP_VERIFY_TOKEN": self.whatsapp_verify_token,
            }
            missing_whatsapp = [
                name
                for name, value in whatsapp_required.items()
                if not value.strip()
                or any(
                    marker in value.strip().lower()
                    for marker in ("change_me", "change-me", "placeholder")
                )
            ]
            if missing_whatsapp:
                errors.append("Configuración WhatsApp incompleta: " + ", ".join(missing_whatsapp))
        if self.whatsapp_embedded_signup_enabled:
            signup_required = {
                "META_APP_ID": self.meta_app_id,
                "META_APP_SECRET": self.meta_app_secret,
                "WHATSAPP_EMBEDDED_SIGNUP_CONFIG_ID": self.whatsapp_embedded_signup_config_id,
                "WHATSAPP_EMBEDDED_SIGNUP_GRAPH_API_VERSION": (
                    self.whatsapp_embedded_signup_graph_api_version
                ),
                "INTEGRATION_ENCRYPTION_KEYS_JSON": self.integration_encryption_keys_json,
            }
            missing_signup = [
                name
                for name, value in signup_required.items()
                if not value.strip()
                or any(
                    marker in value.strip().lower()
                    for marker in ("change_me", "change-me", "placeholder", "example.com")
                )
            ]
            if missing_signup:
                errors.append(
                    "Configuración WhatsApp Embedded Signup incompleta: "
                    + ", ".join(missing_signup)
                )
            if not self.whatsapp_webhook_enabled:
                errors.append(
                    "WHATSAPP_EMBEDDED_SIGNUP_ENABLED requiere WHATSAPP_WEBHOOK_ENABLED=true"
                )
        if errors:
            raise ValueError("Configuración de producción insegura: " + "; ".join(errors))
        return self

    @property
    def frontend_origin_list(self) -> list[str]:
        return [
            origin.strip().rstrip("/")
            for origin in self.frontend_origins.split(",")
            if origin.strip()
        ]

    @property
    def metrics_allowed_ip_list(self) -> list[str]:
        return [value.strip() for value in self.metrics_allowed_ips.split(",") if value.strip()]

    @property
    def alert_email_recipient_list(self) -> list[str]:
        return [
            value.strip().lower()
            for value in self.alert_email_recipients.split(",")
            if value.strip()
        ]


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
