from __future__ import annotations

import os
import subprocess
import sys
import tempfile
import time
import urllib.request
from pathlib import Path
from typing import Iterator

import pytest
from playwright.sync_api import Browser, BrowserContext, Page

ROOT = Path(__file__).resolve().parents[1]
E2E_ROOT = Path(tempfile.gettempdir()) / "autonogrow-e2e"
DATABASE_PATH = E2E_ROOT / "autonogrow-e2e.db"
UPLOADS_PATH = E2E_ROOT / "uploads"
BASE_URL = "http://127.0.0.1:8765"

E2E_ROOT.mkdir(parents=True, exist_ok=True)
UPLOADS_PATH.mkdir(parents=True, exist_ok=True)
if str(ROOT / "backend") not in sys.path:
    sys.path.insert(0, str(ROOT / "backend"))
os.environ.update(
    {
        "APP_ENV": "test",
        "PYTHONPATH": str(ROOT / "backend"),
        "DATABASE_URL": f"sqlite:///{DATABASE_PATH.as_posix()}",
        "DATABASE_MIGRATION_CHECK": "false",
        "ENABLE_LEGACY_STARTUP_MIGRATIONS": "false",
        "SESSION_SECRET": "e2e-session-secret-that-is-never-used-outside-tests",
        "GOOGLE_CLIENT_ID": "e2e-client.apps.googleusercontent.com",
        "OWNER_ALLOWED_EMAILS": "owner@e2e.test",
        "FRONTEND_ORIGINS": BASE_URL,
        "CSRF_ENABLED": "true",
        "COOKIE_SECURE": "false",
        "RATE_LIMIT_ENABLED": "false",
        "UPLOADS_DIR": str(UPLOADS_PATH),
        "WORKER_ENABLED": "false",
        "INSTAGRAM_PROVIDER_ENABLED": "false",
        "INSTAGRAM_PUBLISHING_WORKER_ENABLED": "false",
        "INSTAGRAM_PUBLISHING_MODE": "simulated",
        "WHATSAPP_WEBHOOK_ENABLED": "false",
        "WHATSAPP_EMBEDDED_SIGNUP_ENABLED": "false",
        "PROCESS_WEBHOOK_SYNCHRONOUSLY": "false",
    }
)

from e2e.seed import reset_database, session_cookie_for  # noqa: E402

GOOGLE_MOCK_SCRIPT = """
(() => {
  window.AUTONOGROW_API_BASE_URL = window.location.origin;
  const token = location.pathname.includes('owner') ? 'e2e-owner'
    : location.pathname.includes('admin') ? 'e2e-admin-a' : 'e2e-customer';
  let callback = null;
  window.google = { accounts: { id: {
    initialize(options) { callback = options.callback; },
    renderButton(container) {
      const button = document.createElement('button');
      button.type = 'button';
      button.textContent = 'Continuar con Google';
      button.setAttribute('aria-label', 'Continuar con Google');
      button.addEventListener('click', () => callback({ credential: token }));
      container.replaceChildren(button);
    }
  } } };
})();
"""


def _wait_for_server(process: subprocess.Popen[str], log_path: Path) -> None:
    deadline = time.monotonic() + 30
    while time.monotonic() < deadline:
        if process.poll() is not None:
            output = log_path.read_text(encoding="utf-8", errors="replace")
            raise RuntimeError(f"E2E server exited during startup:\n{output}")
        try:
            with urllib.request.urlopen(f"{BASE_URL}/health", timeout=1) as response:
                if response.status == 200:
                    return
        except OSError:
            time.sleep(0.1)
    raise RuntimeError("E2E server did not become ready within 30 seconds")


@pytest.fixture(scope="session", autouse=True)
def e2e_server() -> Iterator[None]:
    reset_database()
    environment = os.environ.copy()
    environment["PYTHONPATH"] = os.pathsep.join((str(ROOT), str(ROOT / "backend")))
    log_path = E2E_ROOT / "server.log"
    with log_path.open("w", encoding="utf-8") as log_output:
        process = subprocess.Popen(
            [
                sys.executable,
                "-m",
                "uvicorn",
                "e2e.server:app",
                "--host",
                "127.0.0.1",
                "--port",
                "8765",
                "--log-level",
                "warning",
            ],
            cwd=ROOT,
            env=environment,
            stdout=log_output,
            stderr=subprocess.STDOUT,
            text=True,
        )
        try:
            _wait_for_server(process, log_path)
            yield
        finally:
            process.terminate()
            try:
                process.wait(timeout=10)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=5)


@pytest.fixture(autouse=True)
def isolated_e2e_data(e2e_server: None) -> Iterator[None]:
    reset_database()
    yield


@pytest.hookimpl(hookwrapper=True)
def pytest_runtest_makereport(item, call):
    outcome = yield
    setattr(item, f"rep_{outcome.get_result().when}", outcome.get_result())


class Journey:
    def __init__(
        self,
        browser: Browser,
        request: pytest.FixtureRequest,
        *,
        email: str | None = None,
        mobile: bool = False,
    ) -> None:
        viewport = {"width": 390, "height": 844} if mobile else {"width": 1440, "height": 900}
        self.request = request
        self.whatsapp_urls: list[str] = []
        self.context: BrowserContext = browser.new_context(
            base_url=BASE_URL,
            locale="es-ES",
            timezone_id="Europe/Madrid",
            viewport=viewport,
        )
        self.context.add_init_script(GOOGLE_MOCK_SCRIPT)
        self.context.route(
            "https://accounts.google.com/**",
            lambda route: route.fulfill(status=200, content_type="application/javascript", body=""),
        )
        self.context.route(
            "https://wa.me/**",
            self._intercept_whatsapp,
        )
        if email:
            self.context.add_cookies(
                [
                    {
                        "name": "autonogrow_session",
                        "value": session_cookie_for(email),
                        "url": BASE_URL,
                        "httpOnly": True,
                        "sameSite": "Lax",
                    }
                ]
            )
        self.page = self.context.new_page()
        self.console_errors: list[str] = []
        self.network_errors: list[str] = []
        self.expected_response_errors: set[tuple[int, str, str]] = set()
        self.observed_response_errors: set[tuple[int, str, str]] = set()
        self.page.on(
            "console",
            lambda message: (
                self.console_errors.append(message.text)
                if message.type == "error"
                and "server responded with a status of 401" not in message.text
                else None
            ),
        )
        self.page.on("response", self._record_response)
        self.page.on("requestfailed", self._record_failed_request)
        self.context.tracing.start(screenshots=True, snapshots=True, sources=True)

    def _intercept_whatsapp(self, route) -> None:
        self.whatsapp_urls.append(route.request.url)
        route.fulfill(status=204, content_type="text/plain", body="")

    def _record_response(self, response) -> None:
        for expected in self.expected_response_errors:
            status, method, url_fragment = expected
            if (
                response.status == status
                and response.request.method == method
                and url_fragment in response.url
            ):
                self.observed_response_errors.add(expected)
                return
        if response.status >= 500:
            self.network_errors.append(
                f"{response.status} {response.request.method} {response.url}"
            )

    def _record_failed_request(self, request) -> None:
        if "accounts.google.com" not in request.url:
            self.network_errors.append(f"FAILED {request.method} {request.url}")

    def goto(self, path: str) -> Page:
        self.page.goto(path, wait_until="domcontentloaded")
        return self.page

    def expect_response_error(self, status: int, method: str, url_fragment: str) -> None:
        self.expected_response_errors.add((status, method.upper(), url_fragment))

    def close(self) -> None:
        result_dir = ROOT / "test-results"
        failed = bool(
            getattr(self.request.node, "rep_call", None) and self.request.node.rep_call.failed
        )
        if failed:
            result_dir.mkdir(parents=True, exist_ok=True)
            stem = self.request.node.nodeid.replace("/", "-").replace("::", "-").replace("\\", "-")
            self.page.screenshot(path=result_dir / f"{stem}.png", full_page=True)
            self.context.tracing.stop(path=result_dir / f"{stem}.zip")
        else:
            self.context.tracing.stop()
        self.context.close()
        observed_statuses = {item[0] for item in self.observed_response_errors}
        unexpected_console = [
            item
            for item in self.console_errors
            if not (
                item.startswith("Failed to load resource: the server responded with a status of ")
                and any(f"status of {status}" in item for status in observed_statuses)
            )
        ]
        missing_expected = self.expected_response_errors - self.observed_response_errors
        issues = [
            *(f"console: {item}" for item in unexpected_console),
            *self.network_errors,
            *(f"EXPECTED RESPONSE NOT OBSERVED: {item}" for item in sorted(missing_expected)),
        ]
        assert not issues, "Unexpected browser/network errors:\n" + "\n".join(issues)


@pytest.fixture
def journey(browser: Browser, request: pytest.FixtureRequest):
    sessions: list[Journey] = []

    def create(*, email: str | None = None, mobile: bool = False) -> Journey:
        session = Journey(browser, request, email=email, mobile=mobile)
        sessions.append(session)
        return session

    yield create
    for session in reversed(sessions):
        session.close()
