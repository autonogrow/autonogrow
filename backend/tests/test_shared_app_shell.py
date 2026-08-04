from __future__ import annotations

from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import urlparse

ROOT = Path(__file__).resolve().parents[2]
ADMIN_HTML = ROOT / "autonogrow-admin" / "index.html"
OWNER_HTML = ROOT / "autonogrow-owner" / "index.html"
SHARED = ROOT / "autonogrow-shared"

SHARED_STYLES = (
    "tokens.css",
    "base.css",
    "components.css",
    "layout.css",
    "responsive.css",
    "accessibility.css",
)


class StaticHtmlInventory(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.ids: list[str] = []
        self.local_references: list[str] = []
        self.attributes: list[dict[str, str | None]] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        values = dict(attrs)
        self.attributes.append(values)
        if values.get("id"):
            self.ids.append(str(values["id"]))
        reference = values.get("href") if tag == "link" else values.get("src") if tag == "script" else None
        if reference and not urlparse(reference).scheme and not reference.startswith("//"):
            self.local_references.append(reference.split("?", 1)[0].split("#", 1)[0])


def parse(path: Path) -> StaticHtmlInventory:
    inventory = StaticHtmlInventory()
    inventory.feed(path.read_text(encoding="utf-8"))
    return inventory


def test_shared_design_system_files_exist_and_are_loaded() -> None:
    for filename in SHARED_STYLES + ("app-shell.js",):
        assert (SHARED / filename).is_file(), filename

    for html_path in (ADMIN_HTML, OWNER_HTML):
        html = html_path.read_text(encoding="utf-8")
        for filename in SHARED_STYLES:
            assert f'../autonogrow-shared/{filename}' in html
        assert '../autonogrow-shared/app-shell.js' in html


def test_static_local_styles_and_scripts_resolve() -> None:
    for html_path in (ADMIN_HTML, OWNER_HTML):
        inventory = parse(html_path)
        for reference in inventory.local_references:
            assert (html_path.parent / reference).resolve().is_file(), f"{html_path.name}: {reference}"


def test_no_duplicate_static_ids_were_introduced() -> None:
    for html_path in (ADMIN_HTML, OWNER_HTML):
        ids = parse(html_path).ids
        duplicates = sorted({item for item in ids if ids.count(item) > 1})
        assert duplicates == []


def test_critical_admin_contracts_and_navigation_remain() -> None:
    html = ADMIN_HTML.read_text(encoding="utf-8")
    for element_id in (
        "admin-app",
        "business-name",
        "refresh-button",
        "public-page-link",
        "bookings-list",
        "conversation-list",
        "reschedule-modal",
        "staff-removal-modal",
    ):
        assert html.count(f'id="{element_id}"') == 1
    for section in (
        "summary",
        "growth",
        "bookings",
        "conversations",
        "messages",
        "services",
        "staff",
        "schedule",
        "channels",
        "business",
        "reviews",
    ):
        assert f'data-section="{section}"' in html
        assert f'data-admin-section="{section}"' in html


def test_critical_owner_contracts_and_navigation_remain() -> None:
    html = OWNER_HTML.read_text(encoding="utf-8")
    for element_id in (
        "owner-app",
        "refresh-button",
        "business-list",
        "onboarding-wizard",
        "incident-list",
        "queue-jobs",
        "operations-details",
    ):
        assert html.count(f'id="{element_id}"') == 1
    for tab in ("businesses", "new-business", "incidents", "queues", "operations"):
        assert f'data-tab="{tab}"' in html
        assert f'data-panel="{tab}"' in html


def test_shell_accessibility_contracts_are_present() -> None:
    admin = ADMIN_HTML.read_text(encoding="utf-8")
    owner = OWNER_HTML.read_text(encoding="utf-8")
    for html, content_id, sidebar_id in (
        (admin, "admin-main-content", "admin-sidebar"),
        (owner, "owner-main-content", "owner-sidebar"),
    ):
        assert f'href="#{content_id}"' in html
        assert f'id="{content_id}"' in html
        assert f'aria-controls="{sidebar_id}"' in html
        assert 'aria-expanded="false"' in html
        assert "data-ag-shell-open" in html
        assert "data-ag-shell-close" in html
        assert "data-ag-shell-nav" in html
    assert 'role="dialog"' in admin
    assert 'aria-labelledby="reschedule-modal-title"' in admin
    assert admin.count('class="ag-mobile-nav__item"') == 4


def test_component_api_and_core_tokens_are_declared() -> None:
    tokens = (SHARED / "tokens.css").read_text(encoding="utf-8")
    components = (SHARED / "components.css").read_text(encoding="utf-8")
    for token in (
        "--ag-color-blue-500: #1e90ff",
        "--ag-color-coral-500: #ff6f61",
        "--ag-color-green-500: #2ecc71",
        "--ag-font-heading",
        "--ag-font-interface",
        "--ag-sidebar-width",
        "--ag-touch-target",
    ):
        assert token in tokens
    for component in (
        ".ag-button--primary",
        ".ag-card__header",
        ".ag-badge--success",
        ".ag-field-error",
        ".ag-alert--danger",
        ".ag-empty-state__title",
        ".ag-loader",
        ".ag-skeleton",
        ".ag-modal--danger",
        ".ag-toast",
    ):
        assert component in components
