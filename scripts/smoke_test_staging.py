"""Credential-free HTTP smoke tests for an AutonoGrow staging deployment."""

from __future__ import annotations

import argparse
import json
from dataclasses import dataclass
from urllib.error import HTTPError, URLError
from urllib.parse import urljoin, urlsplit, urlunsplit
from urllib.request import Request, urlopen

MAX_BODY_BYTES = 64 * 1024


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


@dataclass
class HttpResult:
    status: int | None
    headers: object | None
    body: bytes
    final_url: str
    error: str | None = None


def normalize_base_url(value: str) -> str:
    parsed = urlsplit(value.strip())
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise ValueError("--base-url debe ser una URL http(s) absoluta")
    if parsed.username or parsed.password or parsed.query or parsed.fragment:
        raise ValueError("--base-url no puede incluir credenciales, query ni fragment")
    if parsed.path not in {"", "/"}:
        raise ValueError("--base-url debe apuntar a la raíz del staging")
    return urlunsplit((parsed.scheme, parsed.netloc, "/", "", ""))


def fetch(
    base_url: str,
    path: str,
    timeout: float,
    *,
    method: str = "GET",
    headers: dict[str, str] | None = None,
) -> HttpResult:
    url = urljoin(base_url, path.lstrip("/"))
    parsed_url = urlsplit(url)
    if parsed_url.scheme not in {"http", "https"} or parsed_url.username or parsed_url.password:
        raise ValueError("La URL resultante del smoke test no es HTTP(S) segura")
    request = Request(
        url,
        method=method,
        headers={
            "Accept": "application/json",
            "User-Agent": "AutonoGrow-Staging-Smoke/1.0",
            **(headers or {}),
        },
    )
    try:
        # The scheme and absence of URL credentials are checked immediately above.
        with urlopen(request, timeout=timeout) as response:  # nosec B310
            return HttpResult(
                status=response.status,
                headers=response.headers,
                body=response.read(MAX_BODY_BYTES),
                final_url=response.geturl(),
            )
    except HTTPError as exc:
        return HttpResult(
            status=exc.code,
            headers=exc.headers,
            body=exc.read(MAX_BODY_BYTES),
            final_url=exc.geturl(),
        )
    except (URLError, TimeoutError, OSError):
        return HttpResult(
            status=None, headers=None, body=b"", final_url=url, error="connection_failed"
        )


def parse_json(result: HttpResult):
    try:
        return json.loads(result.body.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        return None


def check_health(reporter: Reporter, result: HttpResult) -> None:
    if result.status != 200:
        reporter.fail("GET /health no devuelve 200")
        return
    if parse_json(result) == {"status": "ok"}:
        reporter.passed("GET /health devuelve el JSON mínimo esperado")
    else:
        reporter.fail("GET /health expone un payload inesperado o no válido")


def check_security_headers(reporter: Reporter, result: HttpResult, requested_base: str) -> None:
    if result.headers is None:
        reporter.fail("No se pudieron comprobar security headers")
        return
    expected = {
        "X-Content-Type-Options": "nosniff",
        "X-Frame-Options": "DENY",
        "Referrer-Policy": "strict-origin-when-cross-origin",
    }
    for name, value in expected.items():
        actual = result.headers.get(name)
        if actual and actual.lower() == value.lower():
            reporter.passed(f"Header presente y correcto: {name}")
        else:
            reporter.fail(f"Header ausente o incorrecto: {name}")
    if result.headers.get("Permissions-Policy"):
        reporter.passed("Header presente: Permissions-Policy")
    else:
        reporter.fail("Header ausente: Permissions-Policy")

    requested_https = urlsplit(requested_base).scheme == "https"
    final_https = urlsplit(result.final_url).scheme == "https"
    if requested_https and not final_https:
        reporter.fail("La petición HTTPS terminó fuera de HTTPS")
    elif final_https:
        if result.headers.get("Strict-Transport-Security"):
            reporter.passed("Header presente: Strict-Transport-Security")
        else:
            reporter.fail("Falta Strict-Transport-Security en HTTPS")
    else:
        reporter.warn("Smoke test ejecutado por HTTP; HSTS se validará únicamente en staging HTTPS")


def check_status(reporter: Reporter, label: str, result: HttpResult, allowed: set[int]) -> None:
    if result.status in allowed:
        reporter.passed(label)
    elif result.status is None:
        reporter.fail(f"{label}: no se pudo conectar")
    else:
        reporter.fail(f"{label}: status inesperado {result.status}")


def check_build_metadata(reporter: Reporter, result: HttpResult) -> None:
    payload = parse_json(result)
    expected = {"app_env", "app_version", "release_id", "git_commit", "build_time"}
    if result.status == 200 and isinstance(payload, dict) and expected <= payload.keys():
        reporter.passed("GET /api/config/build expone metadata técnica sin secretos")
    else:
        reporter.fail("GET /api/config/build no permite correlacionar la release")


def check_error_sanity(reporter: Reporter, result: HttpResult) -> None:
    unsafe = any(
        marker in result.body.lower() for marker in (b"traceback", b"sqlalchemy", b'file "')
    )
    if result.status == 404 and not unsafe:
        reporter.passed("404 API no filtra stack trace")
    else:
        reporter.fail("404 API devuelve status o detalle inseguro")


def check_legal_page(
    reporter: Reporter,
    label: str,
    result: HttpResult,
    required_text: tuple[bytes, ...],
) -> None:
    if result.status != 200:
        reporter.fail(f"{label}: no devuelve 200")
        return
    content_type = result.headers.get("Content-Type", "") if result.headers else ""
    if "text/html" not in content_type.lower():
        reporter.fail(f"{label}: no devuelve HTML")
        return
    if all(text in result.body for text in required_text):
        reporter.passed(f"{label}: HTML público y enlaces legales presentes")
    else:
        reporter.fail(f"{label}: contenido o enlaces legales incompletos")


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Smoke test HTTP sin credenciales para staging AutonoGrow"
    )
    parser.add_argument("--base-url", required=True, help="Ejemplo: https://staging.example.com")
    parser.add_argument(
        "--timeout", type=float, default=10.0, help="Timeout por request en segundos"
    )
    args = parser.parse_args()
    if args.timeout <= 0 or args.timeout > 60:
        parser.error("--timeout debe estar entre 0 y 60 segundos")
    try:
        base_url = normalize_base_url(args.base_url)
    except ValueError as exc:
        parser.error(str(exc))

    reporter = Reporter()
    health = fetch(base_url, "/health", args.timeout)
    check_health(reporter, health)
    check_security_headers(reporter, health, base_url)
    if health.headers and health.headers.get("X-Request-ID"):
        reporter.passed("GET /health incluye X-Request-ID")
    else:
        reporter.fail("GET /health no incluye X-Request-ID")

    ready = fetch(base_url, "/ready", args.timeout)
    if ready.status == 200 and parse_json(ready) == {"status": "ready"}:
        reporter.passed("GET /ready confirma readiness sin exponer detalles")
    else:
        reporter.fail("GET /ready no confirma readiness")

    landing = fetch(base_url, "/autonogrow-landing/", args.timeout)
    if landing.status == 200 and b"AutonoGrow" in landing.body:
        reporter.passed("Landing pública corresponde a AutonoGrow")
    else:
        reporter.fail("Landing pública ausente o inesperada")

    check_build_metadata(reporter, fetch(base_url, "/api/config/build", args.timeout))

    auth_me = fetch(base_url, "/api/auth/me", args.timeout)
    check_status(reporter, "GET /api/auth/me sin sesión devuelve 401", auth_me, {401})

    public_businesses = fetch(base_url, "/api/businesses", args.timeout)
    if public_businesses.status == 200 and isinstance(parse_json(public_businesses), list):
        reporter.passed("GET /api/businesses continúa siendo público")
    else:
        reporter.fail("GET /api/businesses no devuelve una lista pública válida")

    privacy = fetch(base_url, "/privacy/", args.timeout)
    check_legal_page(
        reporter,
        "GET /privacy/",
        privacy,
        (b"Pol\xc3\xadtica de privacidad", b"../data-deletion/"),
    )

    data_deletion = fetch(base_url, "/data-deletion/", args.timeout)
    check_legal_page(
        reporter,
        "GET /data-deletion/",
        data_deletion,
        (b"eliminaci\xc3\xb3n de datos", b"../privacy/"),
    )

    public_upload_root = fetch(base_url, "/uploads/businesses/", args.timeout)
    if public_upload_root.status in {403, 404}:
        reporter.passed("La raíz de uploads públicos no expone listado")
    elif public_upload_root.status is None:
        reporter.fail("No se pudo comprobar la raíz de uploads públicos")
    else:
        reporter.fail("La raíz de uploads públicos responde de forma potencialmente sensible")

    private_owner = fetch(base_url, "/api/owner/businesses", args.timeout)
    check_status(
        reporter, "Ruta owner sin sesión rechazada sin error 500", private_owner, {401, 403}
    )

    private_customer = fetch(base_url, "/api/customer/profile", args.timeout)
    check_status(reporter, "Ruta customer sin sesión devuelve 401", private_customer, {401})

    private_admin = fetch(base_url, "/api/admin/businesses/certification/settings", args.timeout)
    check_status(reporter, "Ruta admin sin sesión rechazada", private_admin, {401, 403})

    unknown = fetch(base_url, "/api/certification-route-does-not-exist", args.timeout)
    check_error_sanity(reporter, unknown)

    hostile_origin = "https://attacker.invalid"
    cors = fetch(
        base_url,
        "/api/auth/logout",
        args.timeout,
        method="OPTIONS",
        headers={"Origin": hostile_origin, "Access-Control-Request-Method": "POST"},
    )
    allowed_origin = cors.headers.get("Access-Control-Allow-Origin", "") if cors.headers else ""
    if allowed_origin not in {hostile_origin, "*"}:
        reporter.passed("CORS no autoriza origen hostil ni wildcard")
    else:
        reporter.fail("CORS autoriza un origen hostil o wildcard")

    print(
        f"Resumen: {reporter.counts['PASS']} PASS, "
        f"{reporter.counts['WARN']} WARN, {reporter.counts['FAIL']} FAIL"
    )
    return 1 if reporter.counts["FAIL"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
