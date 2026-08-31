from __future__ import annotations

import re
from collections import Counter
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import urlparse

ROOT = Path(__file__).resolve().parents[2]
HTML_FILES = (
    ROOT / "autonogrow-owner" / "index.html",
    ROOT / "autonogrow-admin" / "index.html",
    ROOT / "autonogrow-landing" / "index.html",
    ROOT / "autonogrow-customer" / "index.html",
    ROOT / "privacy" / "index.html",
    ROOT / "data-deletion" / "index.html",
)
JS_FILES = tuple(
    path
    for directory in (
        ROOT / "autonogrow-owner",
        ROOT / "autonogrow-admin",
        ROOT / "autonogrow-landing",
        ROOT / "autonogrow-customer",
        ROOT / "autonogrow-shared",
    )
    for path in directory.glob("*.js")
)
CSS_FILES = tuple(
    path
    for directory in (
        ROOT / "autonogrow-owner",
        ROOT / "autonogrow-admin",
        ROOT / "autonogrow-landing",
        ROOT / "autonogrow-customer",
        ROOT / "autonogrow-shared",
    )
    for path in directory.glob("*.css")
)


class HtmlInventory(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.tags: list[tuple[str, dict[str, str | None]]] = []
        self.ids: list[str] = []
        self.label_depth = 0
        self.nested_label_controls: set[str] = set()

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        values = dict(attrs)
        if tag in {"input", "select", "textarea"} and self.label_depth:
            values["_nested_label"] = "true"
        self.tags.append((tag, values))
        if values.get("id"):
            self.ids.append(str(values["id"]))
        if tag == "label":
            self.label_depth += 1
        elif tag in {"input", "select", "textarea"} and self.label_depth:
            if values.get("id"):
                self.nested_label_controls.add(str(values["id"]))

    def handle_endtag(self, tag: str) -> None:
        if tag == "label":
            self.label_depth -= 1


def inventory(path: Path) -> HtmlInventory:
    parsed = HtmlInventory()
    parsed.feed(path.read_text(encoding="utf-8"))
    return parsed


def text(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def function_block(source: str, start: str, end: str) -> str:
    return source.split(start, 1)[1].split(end, 1)[0]


def test_all_real_frontend_surfaces_and_local_assets_are_present() -> None:
    for path in HTML_FILES:
        assert path.is_file(), path
        parsed = inventory(path)
        for tag, attrs in parsed.tags:
            reference = (
                attrs.get("src")
                if tag == "script"
                else attrs.get("href")
                if tag == "link"
                else None
            )
            if not reference or urlparse(reference).scheme or reference.startswith("//"):
                continue
            local_path = reference.split("?", 1)[0].split("#", 1)[0]
            assert (path.parent / local_path).resolve().is_file(), f"{path}: {reference}"


def test_script_order_and_changed_asset_cachebusters_are_explicit() -> None:
    expected = {
        "autonogrow-admin": (
            "styles.css?v=20260831-p15b3-a",
            "responsive.css?v=5f1",
            "auth.js?v=10b5",
            "admin.js?v=20260831-p15b3-a",
        ),
        "autonogrow-owner": (
            "styles.css?v=20260825-p12-b",
            "responsive.css?v=5f1",
            "auth.js?v=10b5",
            "owner.js?v=20260828-p123-a",
            "owner-onboarding.js?v=5f1",
        ),
        "autonogrow-landing": ("styles.css?v=10b6", "auth.js?v=10b5", "script.js?v=10b7"),
        "autonogrow-customer": ("styles.css?v=10b5", "auth.js?v=10b5", "customer.js?v=10b5"),
    }
    for directory, fragments in expected.items():
        source = text(ROOT / directory / "index.html")
        for fragment in fragments:
            assert fragment in source
        scripts = re.findall(r'<script\b[^>]*src="([^"]+)"', source)
        assert "accounts.google.com/gsi/client" in scripts[0]
        assert next(i for i, item in enumerate(scripts) if "auth.js" in item) < len(scripts) - 1


def test_admin_instagram_planning_preserves_the_business_civil_time() -> None:
    source = text(ROOT / "autonogrow-admin" / "admin.js")
    assert "function adminInstagramLocalInput(isoValue, timeZone)" in source
    assert "timeZone: item.business_timezone" in source
    assert "data-admin-instagram-publication" not in source
    assert "new Date(localValue).toISOString()" not in source


def test_static_ids_aria_references_and_rendered_page_headings_are_coherent() -> None:
    single_heading = {"autonogrow-admin", "privacy", "data-deletion"}
    stateful_heading = {"autonogrow-owner", "autonogrow-landing", "autonogrow-customer"}
    for path in HTML_FILES:
        parsed = inventory(path)
        assert [key for key, count in Counter(parsed.ids).items() if count > 1] == []
        headings = sum(tag == "h1" for tag, _ in parsed.tags)
        if path.parent.name in single_heading:
            assert headings == 1
        elif path.parent.name in stateful_heading:
            assert headings == 2  # one per mutually exclusive auth/error and application state
            assert " hidden" in text(path)
        for _, attrs in parsed.tags:
            for name in ("aria-controls", "aria-labelledby", "aria-describedby"):
                for reference in (attrs.get(name) or "").split():
                    if reference in {
                        "business-detail-title",
                        "owner-integration-detail-title",
                        "owner-incident-detail-title",
                        "owner-candidate-review-title",
                    }:
                        continue  # title is created with the corresponding dynamic panel
                    assert reference in parsed.ids, f"{path.name}: {name}={reference}"


def test_native_controls_have_labels_types_and_no_inline_handlers() -> None:
    handler_pattern = re.compile(r"\bon(?:click|change|submit|input|keydown)\s*=", re.I)
    for path in HTML_FILES:
        source = text(path)
        parsed = inventory(path)
        assert not handler_pattern.search(source)
        label_targets = {
            str(attrs["for"]) for tag, attrs in parsed.tags if tag == "label" and attrs.get("for")
        }
        for tag, attrs in parsed.tags:
            if tag == "button":
                assert attrs.get("type") in {"button", "submit", "reset"}
            if tag not in {"input", "select", "textarea"}:
                continue
            if "hidden" in attrs or attrs.get("type") == "hidden":
                continue
            control_id = attrs.get("id")
            assert (
                (control_id and control_id in label_targets)
                or attrs.get("_nested_label") == "true"
                or attrs.get("aria-label")
                or attrs.get("aria-labelledby")
            ), f"{path.name}: {control_id} lacks a label"

    for path in JS_FILES:
        source = text(path)
        assert not handler_pattern.search(source), path
        assert not re.search(r"<button\b(?![^>]*\btype=)[^>]*>", source, re.I), path


def test_admin_dynamic_actions_use_one_complete_delegated_contract() -> None:
    html = text(ROOT / "autonogrow-admin" / "index.html")
    js = text(ROOT / "autonogrow-admin" / "admin.js")
    actions = set(re.findall(r'data-admin-action="([a-z0-9-]+)"', html + js))
    handled = set(re.findall(r'action === "([a-z0-9-]+)"', js))
    assert actions
    assert actions <= handled
    assert js.count("function setupAdminDelegatedActions") == 1
    assert js.count("setupAdminDelegatedActions();") == 1
    assert "button[data-admin-action], button[data-booking-action]" in js
    assert "setInterval(" not in js


def test_literal_dom_references_resolve_or_are_created_deliberately() -> None:
    surfaces = {
        "autonogrow-owner": (
            "owner.js",
            "owner-businesses.js",
            "owner-onboarding.js",
            "owner-operations.js",
        ),
        "autonogrow-admin": ("admin.js",),
        "autonogrow-landing": ("script.js",),
        "autonogrow-customer": ("customer.js",),
    }
    for directory, scripts in surfaces.items():
        parsed = inventory(ROOT / directory / "index.html")
        source = "\n".join(text(ROOT / directory / filename) for filename in scripts)
        references = set(re.findall(r'(?:getElementById|byId|q)\(["\']([^"\']+)["\']\)', source))
        created = set(re.findall(r'\.id\s*=\s*["\']([^"\']+)["\']', source))
        created.update(re.findall(r'id=["\']([^"\'${}]+)["\']', source))
        missing = references - set(parsed.ids) - created
        assert missing <= {"my-staff-availability"}, f"{directory}: {sorted(missing)}"
        if "my-staff-availability" in missing:
            assert 'panel.id = "my-staff-availability"' in source


def test_dialogs_are_labelled_scrollable_and_keyboard_managed() -> None:
    for path in HTML_FILES[:4]:
        parsed = inventory(path)
        for _, attrs in parsed.tags:
            if attrs.get("role") != "dialog":
                continue
            assert attrs.get("aria-modal") == "true"
            assert attrs.get("aria-labelledby") in parsed.ids
    owner = text(ROOT / "autonogrow-owner" / "owner-businesses.js") + text(
        ROOT / "autonogrow-owner" / "owner-onboarding.js"
    )
    admin = text(ROOT / "autonogrow-admin" / "admin.js")
    landing = text(ROOT / "autonogrow-landing" / "script.js")
    customer = text(ROOT / "autonogrow-customer" / "customer.js")
    for source in (owner, admin, landing, customer):
        assert 'event.key === "Escape"' in source
        assert "focus" in source
    assert "trapModalFocus" in admin
    assert "returnFocus" in owner
    assert "galleryReturnFocus" in landing
    assert "detailReturnFocus" in customer
    for css in (
        text(ROOT / "autonogrow-owner" / "styles.css"),
        text(ROOT / "autonogrow-admin" / "styles.css"),
        text(ROOT / "autonogrow-landing" / "styles.css"),
        text(ROOT / "autonogrow-customer" / "styles.css"),
    ):
        assert "100dvh" in css
        assert "overflow" in css


def test_loading_empty_error_and_http_failure_states_remain_distinct() -> None:
    owner_html = text(ROOT / "autonogrow-owner" / "index.html")
    admin_html = text(ROOT / "autonogrow-admin" / "index.html")
    landing_js = text(ROOT / "autonogrow-landing" / "script.js")
    customer_js = text(ROOT / "autonogrow-customer" / "customer.js")
    assert owner_html.count('aria-busy="true"') >= 5
    assert admin_html.count('aria-busy="true"') >= 5
    for message in (
        "Comprobando servicios disponibles…",
        "No hay servicios disponibles para reserva online.",
        "No se pudieron comprobar los servicios reservables. Vuelve a intentarlo.",
    ):
        assert message in landing_js
    assert "Tu sesión ha caducado" in customer_js
    assert "No tienes próximas citas" in customer_js
    assert "Aún no tienes servicios anteriores" in customer_js
    for status in (401, 403, 404, 409, 422, 429, 500):
        assert str(status) in landing_js or str(status) in customer_js


def test_unknown_states_and_invalid_dates_have_safe_fallbacks() -> None:
    owner = text(ROOT / "autonogrow-owner" / "owner.js")
    onboarding = text(ROOT / "autonogrow-owner" / "owner-onboarding.js")
    admin = text(ROOT / "autonogrow-admin" / "admin.js")
    for function_name in (
        "ownerChannelControlStatusLabel",
        "ownerAutomationStatusLabel",
        "ownerIntegrationStatusLabel",
    ):
        block = function_block(owner, f"function {function_name}", "\nfunction ")
        assert '|| "Estado no disponible"' in block
    for function_name in ("getMessageStatusLabel", "getStatusLabel"):
        block = function_block(admin, f"function {function_name}", "\nfunction ")
        assert '|| "Estado no disponible"' in block
    assert '|| "Sin clasificar"' in function_block(
        admin, "function conversationIntentLabel", "\nfunction "
    )
    assert "Number.isNaN(parsed.getTime())" in onboarding
    assert 'return "No disponible"' in function_block(
        admin, "function formatDateTime", "\nfunction "
    )


def test_security_avoids_executable_html_sensitive_storage_and_verbose_auth_logs() -> None:
    all_js = "\n".join(text(path) for path in JS_FILES)
    for forbidden in (
        "eval(",
        "new Function",
        "document.write",
        "javascript:",
        "data:text/html",
        "console.log",
        "console.debug",
        "localStorage",
    ):
        assert forbidden not in all_js
    assert set(
        re.findall(r'sessionStorage\.(?:getItem|setItem|removeItem)\("([^"]+)"', all_js)
    ) <= {
        "adminMediaPending",
        "ownerMediaPending",
    }
    auth = text(ROOT / "autonogrow-shared" / "auth.js")
    assert 'console.error("Google login failed", { status: error.status || 0 })' in auth
    assert 'console.error("Google login failed", { status: error.status, body:' not in auth
    for path in (
        ROOT / "autonogrow-landing" / "script.js",
        ROOT / "autonogrow-customer" / "customer.js",
    ):
        assert "innerHTML" not in text(path)
        assert "insertAdjacentHTML" not in text(path)
    for path in (
        ROOT / "autonogrow-admin" / "index.html",
        ROOT / "autonogrow-owner" / "index.html",
    ):
        source = text(path).lower()
        for secret in ("access_token", "refresh_token", "app_secret", "verify_token"):
            assert secret not in source


def test_external_links_are_safe_in_static_and_generated_markup() -> None:
    for path in (*HTML_FILES, *JS_FILES):
        source = text(path)
        for tag in re.findall(r"<a\b[^>]*target=[\"']_blank[\"'][^>]*>", source, re.I):
            assert re.search(r"rel=[\"'][^\"']*noopener", tag, re.I), f"{path}: {tag}"
    admin = text(ROOT / "autonogrow-admin" / "admin.js")
    assert "whatsappWindow.opener = null" in admin


def test_responsive_reflow_touch_and_long_content_contracts_cover_all_shells() -> None:
    combined = "\n".join(text(path) for path in CSS_FILES)
    for breakpoint in ("1199px", "1023px", "900px", "767px", "639px", "600px", "390px"):
        assert breakpoint in combined
    assert "minmax(0, 1fr)" in combined
    assert "overflow-x: auto" in combined
    assert "overflow-wrap: anywhere" in combined
    assert "env(safe-area-inset-bottom)" in combined
    assert "env(safe-area-inset-top)" in combined
    assert ".ag-app :where(input, select, textarea) { font-size: 1rem; }" in text(
        ROOT / "autonogrow-shared" / "responsive.css"
    )
    assert "font-size: 16px" in text(ROOT / "autonogrow-landing" / "styles.css")
    assert "font-size: 16px" in text(ROOT / "autonogrow-customer" / "styles.css")
    assert "text-overflow: ellipsis" not in function_block(
        text(ROOT / "autonogrow-shared" / "responsive.css"),
        ".ag-topbar__title h1",
        "\n",
    )


def test_reduced_motion_forced_colors_and_print_are_not_color_only() -> None:
    shared = text(ROOT / "autonogrow-shared" / "accessibility.css")
    landing = text(ROOT / "autonogrow-landing" / "styles.css")
    customer = text(ROOT / "autonogrow-customer" / "styles.css")
    for source in (shared, landing, customer):
        assert "prefers-reduced-motion: reduce" in source
        assert "forced-colors: active" in source
        assert "border" in source.split("forced-colors: active", 1)[1]
    assert "@media print" in landing
    assert "@media print" in customer


def test_auth_gates_keep_protected_apps_hidden_and_preserve_the_current_document() -> None:
    owner_html = text(ROOT / "autonogrow-owner" / "index.html")
    admin_html = text(ROOT / "autonogrow-admin" / "index.html")
    customer_html = text(ROOT / "autonogrow-customer" / "index.html")
    assert 'id="owner-app"' in owner_html and "data-ag-shell hidden" in owner_html
    assert re.search(r'id="admin-app"[^>]*\bhidden\b', admin_html)
    assert 'id="customer-app" hidden' in customer_html
    for directory, script_name in (
        ("autonogrow-owner", "owner.js"),
        ("autonogrow-admin", "admin.js"),
        ("autonogrow-customer", "customer.js"),
    ):
        source = text(ROOT / directory / script_name)
        assert "AutonoGrowAuth.getMe()" in source
        assert "AutonoGrowAuth.logout()" in source
    auth = text(ROOT / "autonogrow-shared" / "auth.js")
    assert 'credentials: "include"' in auth
    assert 'headers.set("X-CSRF-Token", token)' in auth


def test_frontend_function_names_and_scripts_are_not_duplicated() -> None:
    for path in JS_FILES:
        names = re.findall(r"(?m)^\s*(?:async\s+)?function\s+([A-Za-z_$][\w$]*)\s*\(", text(path))
        assert [name for name, count in Counter(names).items() if count > 1] == [], path
    for path in HTML_FILES:
        scripts = [
            attrs["src"]
            for tag, attrs in inventory(path).tags
            if tag == "script" and attrs.get("src")
        ]
        assert [item for item, count in Counter(scripts).items() if count > 1] == []


def test_no_backend_contract_was_copied_into_frontend_as_a_new_route() -> None:
    admin = text(ROOT / "autonogrow-admin" / "admin.js")
    owner = "\n".join(text(path) for path in JS_FILES if path.parent.name == "autonogrow-owner")
    landing = text(ROOT / "autonogrow-landing" / "script.js")
    customer = text(ROOT / "autonogrow-customer" / "customer.js")
    assert "/api/admin/businesses/" in admin
    assert "/api/owner/" in owner
    assert "/api/businesses/" in landing
    assert "/api/customer/home" in customer
    assert 'params.get("b")' in admin
    assert '.get("b")' in landing
    assert '|| "demo-manicura"' not in landing
