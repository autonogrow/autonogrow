"""Repeatable, non-destructive certification checks for an AutonoGrow staging release."""

from __future__ import annotations

import argparse
import json
import os
import socket
import ssl
import subprocess
import sys
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import parse_qsl, urlencode, urljoin, urlsplit, urlunsplit
from urllib.request import HTTPRedirectHandler, Request, build_opener

ROOT = Path(__file__).resolve().parents[1]
MAX_BODY_BYTES = 128 * 1024
EXPECTED_HSTS = "max-age=31536000"
FAILURE_STATES = {"FAIL", "BLOCKER"}


@dataclass(frozen=True)
class CheckResult:
    component: str
    status: str
    detail: str


@dataclass(frozen=True)
class HttpResult:
    status: int | None
    headers: Any
    body: bytes
    final_url: str
    elapsed_ms: int
    error: str | None = None


@dataclass(frozen=True)
class SystemdUnitState:
    active_state: str
    unit_file_state: str
    restarts: int


class Reporter:
    def __init__(self) -> None:
        self.results: list[CheckResult] = []

    def add(self, component: str, status: str, detail: str) -> None:
        if status not in {"PASS", "WARN", "FAIL", "BLOCKER", "MANUAL_REQUIRED"}:
            raise ValueError(f"Estado desconocido: {status}")
        self.results.append(CheckResult(component, status, detail))
        print(f"[{status}] {component}: {detail}")

    def counts(self) -> dict[str, int]:
        return {
            status: sum(item.status == status for item in self.results)
            for status in ("PASS", "WARN", "FAIL", "BLOCKER", "MANUAL_REQUIRED")
        }

    def exit_code(self) -> int:
        return 1 if any(item.status in FAILURE_STATES for item in self.results) else 0

    def write_json(self, path: Path, *, base_url: str) -> None:
        payload = {
            "schema_version": 1,
            "base_url": base_url,
            "generated_at_epoch": int(time.time()),
            "summary": self.counts(),
            "results": [asdict(item) for item in self.results],
            "certified": not any(item.status != "PASS" for item in self.results),
        }
        path.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):  # noqa: ANN001
        return None


def normalize_base_url(value: str) -> str:
    parsed = urlsplit(value.strip())
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise ValueError("--base-url debe ser una URL HTTP(S) absoluta")
    if parsed.username or parsed.password or parsed.query or parsed.fragment:
        raise ValueError("--base-url no puede contener credenciales, query ni fragment")
    if parsed.path not in {"", "/"}:
        raise ValueError("--base-url debe apuntar a la raíz del entorno")
    return urlunsplit((parsed.scheme, parsed.netloc, "/", "", ""))


def fetch(
    base_url: str,
    path: str,
    timeout: float,
    *,
    method: str = "GET",
    headers: dict[str, str] | None = None,
    follow_redirects: bool = True,
) -> HttpResult:
    url = path if path.startswith(("http://", "https://")) else urljoin(base_url, path.lstrip("/"))
    parsed = urlsplit(url)
    if parsed.scheme not in {"http", "https"} or parsed.username or parsed.password:
        raise ValueError("URL de certificación no segura")
    request_headers = {
        "Accept": "application/json, text/html;q=0.9, */*;q=0.5",
        "User-Agent": "AutonoGrow-Staging-Certification/1.0",
        **(headers or {}),
    }
    request = Request(url, method=method, headers=request_headers)
    opener = build_opener() if follow_redirects else build_opener(NoRedirect)
    started = time.perf_counter()
    try:
        with opener.open(request, timeout=timeout) as response:  # nosec B310
            body = b"" if method == "HEAD" else response.read(MAX_BODY_BYTES)
            return HttpResult(
                response.status,
                response.headers,
                body,
                response.geturl(),
                round((time.perf_counter() - started) * 1000),
            )
    except HTTPError as exc:
        body = b"" if method == "HEAD" else exc.read(MAX_BODY_BYTES)
        return HttpResult(
            exc.code,
            exc.headers,
            body,
            exc.geturl(),
            round((time.perf_counter() - started) * 1000),
        )
    except (URLError, TimeoutError, OSError) as exc:
        return HttpResult(
            None,
            None,
            b"",
            url,
            round((time.perf_counter() - started) * 1000),
            type(exc).__name__,
        )


def parse_json(result: HttpResult) -> Any:
    try:
        return json.loads(result.body.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        return None


def check_tls(reporter: Reporter, base_url: str, timeout: float) -> None:
    parsed = urlsplit(base_url)
    if parsed.scheme != "https":
        reporter.add("HTTPS/TLS", "BLOCKER", "La URL base no usa HTTPS")
        return
    host = parsed.hostname or ""
    port = parsed.port or 443
    try:
        context = ssl.create_default_context()
        with socket.create_connection((host, port), timeout=timeout) as raw:
            with context.wrap_socket(raw, server_hostname=host) as secure:
                version = secure.version() or "unknown"
                certificate = secure.getpeercert()
        if version not in {"TLSv1.2", "TLSv1.3"}:
            reporter.add("HTTPS/TLS", "FAIL", f"Versión TLS no moderna: {version}")
        elif not certificate:
            reporter.add("HTTPS/TLS", "FAIL", "No se obtuvo certificado validado")
        else:
            reporter.add(
                "HTTPS/TLS",
                "PASS",
                f"Certificado, cadena y hostname validados; negociación {version}",
            )
    except (OSError, ssl.SSLError):
        reporter.add("HTTPS/TLS", "BLOCKER", "Falló la validación de certificado/cadena/hostname")


def check_redirect(reporter: Reporter, base_url: str, timeout: float) -> None:
    parsed = urlsplit(base_url)
    http_url = urlunsplit(("http", parsed.netloc, "/", "", ""))
    result = fetch(base_url, http_url, timeout, follow_redirects=False)
    location = result.headers.get("Location", "") if result.headers else ""
    if result.status not in {301, 302, 307, 308}:
        reporter.add("HTTP -> HTTPS", "FAIL", f"HTTP no redirige (status {result.status})")
    elif urlsplit(urljoin(http_url, location)).scheme != "https":
        reporter.add("HTTP -> HTTPS", "FAIL", "La redirección no termina en HTTPS")
    else:
        final = fetch(base_url, urljoin(http_url, location), timeout)
        status = (
            "PASS"
            if final.status == 200 and urlsplit(final.final_url).scheme == "https"
            else "FAIL"
        )
        reporter.add(
            "HTTP -> HTTPS",
            status,
            "Redirección segura sin bucle" if status == "PASS" else "Destino HTTPS inválido",
        )


def check_health_and_headers(reporter: Reporter, base_url: str, timeout: float) -> None:
    result = fetch(base_url, "/health", timeout)
    if result.status == 200 and parse_json(result) == {"status": "ok"}:
        status = "PASS" if result.elapsed_ms <= 2000 else "WARN"
        reporter.add("Backend health", status, f"JSON mínimo correcto en {result.elapsed_ms} ms")
    else:
        reporter.add("Backend health", "BLOCKER", "GET /health no cumple el contrato mínimo")
        return
    if b"traceback" in result.body.lower() or b"debug" in result.body.lower():
        reporter.add("Debug exposure", "FAIL", "Health contiene información de depuración")
    else:
        reporter.add("Debug exposure", "PASS", "Health no expone debug ni configuración")
    expected = {
        "Strict-Transport-Security": EXPECTED_HSTS,
        "X-Content-Type-Options": "nosniff",
        "X-Frame-Options": "DENY",
        "Referrer-Policy": "strict-origin-when-cross-origin",
        "Permissions-Policy": "camera=(), microphone=(), geolocation=()",
    }
    for name, value in expected.items():
        actual = result.headers.get(name, "") if result.headers else ""
        reporter.add(
            f"Header {name}",
            "PASS" if actual.lower() == value.lower() else "FAIL",
            f"valor exacto {value}"
            if actual.lower() == value.lower()
            else "ausente o distinto de la política versionada",
        )
    csp = result.headers.get("Content-Security-Policy") if result.headers else None
    reporter.add(
        "Content-Security-Policy",
        "PASS" if csp else "WARN",
        "Política presente"
        if csp
        else "No aplica todavía: frontend estático usa scripts inline y Google GIS",
    )
    server = result.headers.get("Server", "") if result.headers else ""
    reporter.add(
        "Server disclosure",
        "WARN" if server else "PASS",
        "El proxy expone una firma de servidor" if server else "Firma de servidor eliminada",
    )
    request_id = result.headers.get("X-Request-ID", "") if result.headers else ""
    reporter.add(
        "Request correlation",
        "PASS" if request_id and len(request_id) <= 64 else "FAIL",
        "X-Request-ID seguro presente" if request_id else "Falta X-Request-ID",
    )
    check_readiness(reporter, fetch(base_url, "/ready", timeout))


def check_readiness(reporter: Reporter, result: HttpResult) -> None:
    if result.status == 200 and parse_json(result) == {"status": "ready"}:
        reporter.add("Backend readiness", "PASS", "GET /ready confirma dependencias sin detalles")
    else:
        reporter.add("Backend readiness", "FAIL", "GET /ready no cumple el contrato profundo")


def check_build(
    reporter: Reporter, base_url: str, timeout: float, expected_env: str, expected_sha: str | None
) -> None:
    result = fetch(base_url, "/api/config/build", timeout)
    payload = parse_json(result)
    if result.status != 200 or not isinstance(payload, dict):
        reporter.add("Version correlation", "BLOCKER", "No existe metadata pública de build válida")
        fallback = parse_json(fetch(base_url, "/api/config/public", timeout))
        actual_env = str(fallback.get("app_env", "")) if isinstance(fallback, dict) else ""
        reporter.add(
            "Environment separation",
            "PASS" if actual_env == expected_env else "BLOCKER",
            f"APP_ENV={actual_env or 'missing'}; esperado {expected_env}",
        )
        return
    actual_env = str(payload.get("app_env", ""))
    reporter.add(
        "Environment separation",
        "PASS" if actual_env == expected_env else "BLOCKER",
        f"APP_ENV={actual_env or 'missing'}; esperado {expected_env}",
    )
    sha = str(payload.get("git_commit", ""))
    valid_sha = 7 <= len(sha) <= 64 and all(
        character in "0123456789abcdefABCDEF" for character in sha
    )
    if not valid_sha:
        reporter.add("Version correlation", "BLOCKER", "APP_GIT_COMMIT ausente o unknown")
    elif expected_sha and not sha.lower().startswith(expected_sha.lower()):
        reporter.add(
            "Version correlation", "FAIL", "El SHA desplegado no coincide con --expected-git-commit"
        )
    else:
        reporter.add("Version correlation", "PASS", f"Commit desplegado {sha[:12]}")


def check_public_contracts(reporter: Reporter, base_url: str, timeout: float) -> None:
    pages = {
        "Landing": ("/autonogrow-landing/", b"AutonoGrow"),
        "Privacy": ("/privacy/", b"Pol\xc3\xadtica de privacidad"),
        "Data deletion": ("/data-deletion/", b"eliminaci\xc3\xb3n de datos"),
    }
    for name, (path, marker) in pages.items():
        result = fetch(base_url, path, timeout)
        html = result.headers and "text/html" in result.headers.get("Content-Type", "").lower()
        ok = result.status == 200 and html and marker.lower() in result.body.lower()
        reporter.add(
            name,
            "PASS" if ok else "FAIL",
            f"GET {path} público por HTTPS" if ok else f"GET {path} no cumple contrato",
        )
    for component, path in {
        "Auth protection": "/api/auth/me",
        "Admin protection": "/api/admin/businesses/demo/settings",
        "Owner protection": "/api/owner/businesses",
        "Customer protection": "/api/customer/profile",
        "Growth protection": "/api/admin/businesses/demo/opportunities",
        "Social protection": "/api/admin/businesses/demo/social-content-proposals",
    }.items():
        result = fetch(base_url, path, timeout)
        reporter.add(
            component,
            "PASS" if result.status in {401, 403} else "FAIL",
            f"Acceso anónimo rechazado con {result.status}",
        )
    public_businesses = fetch(base_url, "/api/businesses", timeout)
    reporter.add(
        "Customer public API",
        "PASS"
        if public_businesses.status == 200 and isinstance(parse_json(public_businesses), list)
        else "FAIL",
        "Contrato público de negocios disponible",
    )
    unknown = fetch(base_url, "/api/certification-route-does-not-exist", timeout)
    unsafe = any(
        marker in unknown.body.lower() for marker in (b"traceback", b'file "', b"sqlalchemy")
    )
    reporter.add(
        "API error sanity",
        "PASS" if unknown.status == 404 and not unsafe else "FAIL",
        "404 estable sin stack trace",
    )


def check_cors_and_rate(reporter: Reporter, base_url: str, timeout: float) -> None:
    hostile = "https://attacker.invalid"
    result = fetch(
        base_url,
        "/api/auth/logout",
        timeout,
        method="OPTIONS",
        headers={
            "Origin": hostile,
            "Access-Control-Request-Method": "POST",
            "Access-Control-Request-Headers": "X-CSRF-Token",
        },
    )
    allowed = result.headers.get("Access-Control-Allow-Origin", "") if result.headers else ""
    reporter.add(
        "CORS hostile origin",
        "PASS" if allowed != hostile and allowed != "*" else "FAIL",
        "Origen externo no autorizado",
    )
    statuses = [fetch(base_url, "/api/auth/me", timeout).status for _ in range(3)]
    reporter.add(
        "Rate limit light probe",
        "PASS" if all(status in {401, 429} for status in statuses) else "FAIL",
        "Tres requests controladas sin 5xx; activación se valida también en configuración local",
    )


def check_webhook(reporter: Reporter, base_url: str, timeout: float, token_env: str) -> None:
    endpoint = "/api/webhooks/instagram"
    no_token = fetch(base_url, endpoint, timeout)
    invalid = fetch(
        base_url,
        endpoint
        + "?hub.mode=subscribe&hub.verify_token=invalid-certification-token&hub.challenge=x",
        timeout,
    )
    reporter.add(
        "Meta webhook rejection",
        "PASS" if no_token.status == 403 and invalid.status == 403 else "FAIL",
        "Sin token y token inválido son rechazados sin información sensible",
    )
    token = os.getenv(token_env, "")
    if not token:
        reporter.add(
            "Meta webhook challenge",
            "MANUAL_REQUIRED",
            f"Definir {token_env} solo en el proceso para validar challenge real",
        )
        return
    query = urlencode(
        {"hub.mode": "subscribe", "hub.verify_token": token, "hub.challenge": "autonogrow-cert-ok"}
    )
    valid = fetch(base_url, endpoint + "?" + query, timeout)
    reporter.add(
        "Meta webhook challenge",
        "PASS" if valid.status == 200 and valid.body == b"autonogrow-cert-ok" else "FAIL",
        "Challenge real validado sin imprimir el token",
    )


def tamper_signed_url(url: str, field: str, value: str) -> str:
    parsed = urlsplit(url)
    values = dict(parse_qsl(parsed.query, keep_blank_values=True))
    values[field] = value
    return urlunsplit((parsed.scheme, parsed.netloc, parsed.path, urlencode(values), ""))


def check_signed_media(reporter: Reporter, base_url: str, timeout: float, url_env: str) -> None:
    url = os.getenv(url_env, "")
    if not url:
        reporter.add(
            "Signed media", "MANUAL_REQUIRED", f"Definir {url_env} con una URL efímera aprobada"
        )
        return
    parsed_base = urlsplit(base_url)
    parsed_url = urlsplit(url)
    if parsed_url.scheme != "https" or parsed_url.netloc != parsed_base.netloc:
        reporter.add("Signed media", "BLOCKER", "La URL firmada no pertenece al staging HTTPS")
        return
    valid = fetch(base_url, url, timeout)
    content_type = valid.headers.get("Content-Type", "") if valid.headers else ""
    valid_ok = (
        valid.status == 200 and content_type.lower().startswith("image/jpeg") and bool(valid.body)
    )
    reporter.add(
        "Signed media download",
        "PASS" if valid_ok else "FAIL",
        "JPEG accesible anónimamente por HTTPS" if valid_ok else "La descarga firmada válida falló",
    )
    signature = dict(parse_qsl(parsed_url.query)).get("signature", "")
    bad_signature = ("0" if signature[:1] != "0" else "1") + signature[1:]
    tampered = fetch(base_url, tamper_signed_url(url, "signature", bad_signature), timeout)
    expired = fetch(base_url, tamper_signed_url(url, "expires", "1"), timeout)
    reporter.add(
        "Signed media tamper",
        "PASS" if tampered.status in {403, 404} and expired.status in {403, 404} else "FAIL",
        "Firma alterada y expiración rechazadas",
    )


def command_result(command: list[str], timeout: float = 20, *, cwd: Path = ROOT) -> tuple[int, str]:
    try:
        result = subprocess.run(  # noqa: S603
            command,
            cwd=cwd,
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
        )
        return result.returncode, (result.stdout + result.stderr).strip()
    except (OSError, subprocess.TimeoutExpired):
        return 127, ""


def systemd_unit_state(unit: str) -> SystemdUnitState | None:
    code, output = command_result(
        ["systemctl", "show", unit, "--property=ActiveState,UnitFileState,NRestarts"]
    )
    if code != 0:
        return None
    values = dict(line.split("=", 1) for line in output.splitlines() if "=" in line)
    try:
        restarts = int(values["NRestarts"])
        return SystemdUnitState(
            active_state=values["ActiveState"],
            unit_file_state=values["UnitFileState"],
            restarts=restarts,
        )
    except (KeyError, ValueError):
        return None


def check_systemd_unit(reporter: Reporter, unit: str) -> None:
    state = systemd_unit_state(unit)
    ok = bool(
        state
        and state.active_state == "active"
        and state.unit_file_state == "enabled"
        and state.restarts < 3
    )
    reporter.add(
        f"systemd {unit}",
        "PASS" if ok else "FAIL",
        "active/enabled sin restart loop"
        if ok
        else "Revisar estado o reinicios recientes",
    )


def check_publisher_systemd(
    reporter: Reporter,
    *,
    worker_enabled: bool | None,
    preflight_ok: bool,
) -> None:
    unit = "autonogrow-instagram-publisher.service"
    state = systemd_unit_state(unit)
    if state is None:
        reporter.add(f"systemd {unit}", "FAIL", "No se pudo consultar la unidad publisher")
        return
    if state.active_state == "failed" or state.restarts >= 3:
        reporter.add(
            f"systemd {unit}",
            "FAIL",
            "Publisher en estado failed o con reinicios recientes",
        )
        return
    if not preflight_ok or worker_enabled is None:
        reporter.add(
            f"systemd {unit}",
            "FAIL",
            "Preflight inválido o configuración publisher inconsistente",
        )
        return
    if not worker_enabled:
        deliberately_disabled = (
            state.active_state == "inactive" and state.unit_file_state == "disabled"
        )
        reporter.add(
            f"systemd {unit}",
            "PASS" if deliberately_disabled else "FAIL",
            "Publisher deliberadamente deshabilitado; preflight correcto y no puede reclamar jobs."
            if deliberately_disabled
            else "Publisher deshabilitado por configuración, pero la unidad no está inactive/disabled",
        )
        return
    operational = state.active_state == "active" and state.unit_file_state == "enabled"
    reporter.add(
        f"systemd {unit}",
        "PASS" if operational else "FAIL",
        "Publisher habilitado y active/enabled"
        if operational
        else "Publisher habilitado por configuración, pero la unidad no está active/enabled",
    )


def check_instagram_worker_preflight(
    reporter: Reporter, backend: Path, settings: Any | None
) -> tuple[bool, bool | None]:
    code, output = command_result(
        [sys.executable, "-m", "app.workers.instagram_publish_worker", "--check"],
        timeout=30,
        cwd=backend,
    )
    try:
        payload = json.loads(output)
    except json.JSONDecodeError:
        payload = None
    worker_enabled = payload.get("worker_enabled") if isinstance(payload, dict) else None
    expected_adapter = (
        {
            "simulated": "SimulatedInstagramPublishingAdapter",
            "meta": "MetaInstagramPublishingAdapter",
        }.get(settings.instagram_publishing_mode)
        if settings is not None
        else None
    )
    consistent = bool(
        code == 0
        and isinstance(payload, dict)
        and payload.get("ok") is True
        and isinstance(worker_enabled, bool)
        and settings is not None
        and payload.get("app_env") == settings.app_env
        and payload.get("database_dialect") == "postgresql"
        and payload.get("publishing_mode") == settings.instagram_publishing_mode
        and payload.get("provider_adapter") == expected_adapter
        and worker_enabled == settings.instagram_publishing_worker_enabled
    )
    reporter.add(
        "Instagram worker preflight",
        "PASS" if consistent else "FAIL",
        "Configuración y DB válidas sin reclamar jobs"
        if consistent
        else "El check seguro del worker falló o no coincide con la configuración cargada",
    )
    return consistent, worker_enabled if isinstance(worker_enabled, bool) else None


def _privilege_required(code: int, output: str) -> bool:
    lowered = output.lower()
    return code == 127 or any(
        marker in lowered
        for marker in (
            "a password is required",
            "password is required",
            "no tty present",
            "not allowed to execute",
            "permission denied",
            "operation not permitted",
        )
    )


def check_caddy_config(reporter: Reporter, caddy_config: str) -> None:
    command = ["caddy", "validate", "--config", caddy_config]
    code, output = command_result(command)
    if code == 0:
        reporter.add("Caddy config", "PASS", "Configuración instalada válida")
        return
    if not _privilege_required(code, output):
        reporter.add("Caddy config", "FAIL", "caddy validate detectó un fallo real")
        return

    sudo_code, sudo_output = command_result(["sudo", "-n", *command])
    if sudo_code == 0:
        reporter.add(
            "Caddy config",
            "PASS",
            "Configuración válida con sudo no interactivo; el log protegido no es legible por deploy",
        )
    elif _privilege_required(sudo_code, sudo_output):
        reporter.add(
            "Caddy config",
            "MANUAL_REQUIRED",
            "El log está protegido; ejecutar sudo caddy validate y registrar la evidencia",
        )
    else:
        reporter.add("Caddy config", "FAIL", "La validación privilegiada de Caddy falló")


def check_caddy_runtime(reporter: Reporter) -> None:
    state = systemd_unit_state("caddy.service")
    ok = bool(state and state.active_state == "active" and state.restarts < 3)
    reporter.add(
        "Caddy runtime",
        "PASS" if ok else "FAIL",
        "Servicio activo sin restart loop" if ok else "Servicio inactivo, failed o inestable",
    )


def run_local_system_checks(reporter: Reporter, caddy_config: str) -> None:
    backend = ROOT / "backend"
    sys.path.insert(0, str(backend))
    settings = None
    try:
        from sqlalchemy import text

        from app.core.config import get_settings, get_uploads_dir
        from app.core.database import engine, safe_database_pool_status
        from app.core.migration_state import inspect_database_migration_state

        settings = get_settings()
        reporter.add(
            "Local APP_ENV",
            "PASS" if settings.app_env == "staging" else "BLOCKER",
            f"APP_ENV={settings.app_env}",
        )
        reporter.add(
            "Publishing mode", "PASS", f"Modo explícito: {settings.instagram_publishing_mode}"
        )
        reporter.add(
            "Security flags",
            "PASS"
            if settings.cookie_secure
            and settings.csrf_enabled
            and settings.rate_limit_enabled
            and settings.security_headers_enabled
            else "FAIL",
            "Cookie Secure, CSRF, rate limit y headers activos",
        )
        pool = safe_database_pool_status(engine)
        with engine.connect() as connection:
            connection.execute(text("SELECT 1"))
        reporter.add(
            "PostgreSQL connectivity",
            "PASS" if pool.get("dialect") == "postgresql" else "BLOCKER",
            f"dialecto={pool.get('dialect')}; conexión y pool operativos",
        )
        state = inspect_database_migration_state(engine)
        reporter.add(
            "Alembic",
            "PASS" if state.is_at_head and len(state.head_revisions) == 1 else "BLOCKER",
            "current=head y head única" if state.is_at_head else state.recommendation,
        )
        uploads = get_uploads_dir()
        free = os.statvfs(uploads).f_bavail * os.statvfs(uploads).f_frsize
        reporter.add(
            "Storage",
            "PASS"
            if uploads.is_dir() and free >= settings.readiness_min_disk_free_bytes
            else "FAIL",
            "Uploads disponible y espacio sobre el mínimo",
        )
        reporter.add(
            "Media URL separation",
            "PASS"
            if settings.instagram_publishing_mode != "meta"
            or settings.instagram_asset_url_base == "https://staging.autonogrow.es"
            else "BLOCKER",
            "Signed media apunta al dominio de staging",
        )
    except Exception:
        reporter.add(
            "Local runtime/DB",
            "BLOCKER",
            "No se pudo cargar configuración, conectar a DB o validar Alembic",
        )
    for unit in (
        "autonogrow.service",
        "autonogrow-worker.service",
        "autonogrow-maintenance.timer",
    ):
        check_systemd_unit(reporter, unit)
    preflight_ok, worker_enabled = check_instagram_worker_preflight(reporter, backend, settings)
    check_publisher_systemd(
        reporter,
        worker_enabled=worker_enabled,
        preflight_ok=preflight_ok,
    )
    check_caddy_runtime(reporter)
    check_caddy_config(reporter, caddy_config)
    code, _ = command_result([sys.executable, "scripts/run_maintenance.py", "--json"], timeout=60)
    reporter.add(
        "Maintenance dry-run",
        "PASS" if code == 0 else "FAIL",
        "Mantenimiento ejecutado en rollback/dry-run"
        if code == 0
        else "Dry-run de mantenimiento falló",
    )
    code, _ = command_result([sys.executable, "-m", "pip", "check"])
    reporter.add(
        "Python dependencies",
        "PASS" if code == 0 else "FAIL",
        "pip check correcto; psycopg se valida al conectar",
    )
    reporter.add(
        "Service restart",
        "MANUAL_REQUIRED",
        "Reinicio controlado y persistencia de jobs requieren ventana operativa",
    )
    reporter.add(
        "Logs and backups",
        "MANUAL_REQUIRED",
        "Revisar journald/Caddy y evidencia del backup sin exponer secretos",
    )


def add_manual_gates(reporter: Reporter) -> None:
    reporter.add(
        "Authenticated E2E",
        "MANUAL_REQUIRED",
        "Login owner/admin/customer, cookies, CSRF e aislamiento multi-tenant",
    )
    reporter.add(
        "Booking cleanup flow", "MANUAL_REQUIRED", "Ejecutar con negocio demo y limpiar la reserva"
    )
    reporter.add(
        "Upload limits",
        "MANUAL_REQUIRED",
        "JPEG, tipo inválido y exceso requieren sesión staging y limpieza",
    )
    reporter.add(
        "Meta integration health",
        "MANUAL_REQUIRED",
        "Validar cuenta controlada, permisos y token cifrado",
    )
    reporter.add(
        "Meta real publish",
        "MANUAL_REQUIRED",
        "Primera publicación JPEG controlada y comprobación visual",
    )
    reporter.add(
        "Meta retry/recovery",
        "MANUAL_REQUIRED",
        "Fallo no destructivo, retry y recovery sin duplicado",
    )


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-url", required=True)
    parser.add_argument("--timeout", type=float, default=10.0)
    parser.add_argument("--expected-environment", default="staging")
    parser.add_argument("--expected-git-commit")
    parser.add_argument("--json-output", type=Path)
    parser.add_argument(
        "--local-system", action="store_true", help="Ejecuta checks read-only en el VPS"
    )
    parser.add_argument("--caddy-config", default="/etc/caddy/Caddyfile")
    parser.add_argument("--webhook-token-env", default="AUTONOGROW_CERT_META_VERIFY_TOKEN")
    parser.add_argument("--signed-media-url-env", default="AUTONOGROW_CERT_SIGNED_MEDIA_URL")
    args = parser.parse_args()
    if not 0 < args.timeout <= 60:
        parser.error("--timeout debe estar entre 0 y 60")
    return args


def main() -> int:
    args = parse_args()
    try:
        base_url = normalize_base_url(args.base_url)
    except ValueError as exc:
        raise SystemExit(str(exc)) from exc
    reporter = Reporter()
    print("AUTONOGROW STAGING CERTIFICATION\n")
    check_tls(reporter, base_url, args.timeout)
    check_redirect(reporter, base_url, args.timeout)
    check_health_and_headers(reporter, base_url, args.timeout)
    check_build(
        reporter, base_url, args.timeout, args.expected_environment, args.expected_git_commit
    )
    check_public_contracts(reporter, base_url, args.timeout)
    check_cors_and_rate(reporter, base_url, args.timeout)
    check_webhook(reporter, base_url, args.timeout, args.webhook_token_env)
    check_signed_media(reporter, base_url, args.timeout, args.signed_media_url_env)
    if args.local_system:
        run_local_system_checks(reporter, args.caddy_config)
    else:
        reporter.add(
            "VPS runtime", "MANUAL_REQUIRED", "Ejecutar de nuevo con --local-system dentro del VPS"
        )
    add_manual_gates(reporter)
    counts = reporter.counts()
    print("\nResumen: " + ", ".join(f"{counts[key]} {key}" for key in counts))
    if args.json_output:
        reporter.write_json(args.json_output, base_url=base_url)
        print(f"Informe JSON: {args.json_output}")
    return reporter.exit_code()


if __name__ == "__main__":
    raise SystemExit(main())
