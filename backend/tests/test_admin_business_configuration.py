from __future__ import annotations

from html.parser import HTMLParser
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
ADMIN_HTML = ROOT / "autonogrow-admin" / "index.html"
ADMIN_CSS = ROOT / "autonogrow-admin" / "styles.css"
ADMIN_JS = ROOT / "autonogrow-admin" / "admin.js"


class IdInventory(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.ids: list[str] = []

    def handle_starttag(self, _tag: str, attrs: list[tuple[str, str | None]]) -> None:
        element_id = dict(attrs).get("id")
        if element_id:
            self.ids.append(element_id)


def read_sources() -> tuple[str, str, str]:
    return (
        ADMIN_HTML.read_text(encoding="utf-8"),
        ADMIN_CSS.read_text(encoding="utf-8"),
        ADMIN_JS.read_text(encoding="utf-8"),
    )


def function_block(js: str, start: str, end: str) -> str:
    return js.split(start, 1)[1].split(end, 1)[0]


def test_configuration_groups_five_categories_without_breaking_legacy_contracts() -> None:
    html, _, js = read_sources()
    assert 'data-section="configuration"' in html
    for section in ("business", "services", "staff", "schedule", "public-page"):
        assert html.count(f'data-admin-section="{section}"') == 1
        assert f'{{ id: "{section}"' in js
    for legacy in ("services", "staff", "schedule", "business"):
        assert f'data-section="{legacy}"' in html
    assert "admin-tab--legacy" in html
    assert "CONFIGURATION_SECTIONS.has(targetSection)" in js


def test_configuration_has_no_duplicate_ids_and_preserves_critical_fields() -> None:
    html, _, _ = read_sources()
    inventory = IdInventory()
    inventory.feed(html)
    duplicates = sorted({item for item in inventory.ids if inventory.ids.count(item) > 1})
    assert duplicates == []
    for element_id in (
        "business-setting-name",
        "business-setting-description",
        "business-setting-phone",
        "business-setting-theme",
        "business-setting-template",
        "admin-gallery-list",
        "admin-services-list",
        "admin-staff-list",
        "weekly-schedule-editor",
        "availability-exceptions-list",
    ):
        assert html.count(f'id="{element_id}"') == 1


def test_preparation_states_use_five_documented_real_criteria() -> None:
    _, _, js = read_sources()
    block = function_block(js, "function configurationState", "function configurationNavigationMarkup")
    assert "currentBusiness.name?.trim()" in block
    assert "adminServices.filter((service) => service.active).length" in block
    assert "member.active && member.bookable" in block
    assert "availabilitySettings?.weekly_schedule" in block
    assert "currentBusiness.active" in block
    for state in ("complete", "missing", "review", "error"):
        assert f'state: "{state}"' in block
    overview = function_block(js, "function renderConfigurationOverview", "function setupBusinessConfiguration")
    assert "`${ready} de ${states.length} apartados preparados`" in overview
    assert "%" not in overview


def test_business_information_has_persistent_help_and_safe_validation() -> None:
    html, _, js = read_sources()
    assert 'id="business-setting-name"' in html and "required" in html
    assert 'aria-describedby="business-setting-name-help business-setting-name-error"' in html
    assert "Este texto aparece destacado en tu página pública." in html
    assert "no modifica la disponibilidad de Agenda" in html
    assert 'id="business-settings-errors"' in html
    validation = function_block(js, "function isSafePublicUrl", "async function saveBusinessSettings")
    assert '["https:", "http:"]' in validation
    assert "!url.username && !url.password" in validation
    assert 'field?.setAttribute("aria-invalid", "true")' in validation
    assert "errors[0].id" in validation


def test_services_keep_real_endpoints_validation_impact_and_safe_rendering() -> None:
    html, _, js = read_sources()
    assert 'id="new-service-duration" type="number" min="1" max="1440"' in html
    assert "/services`" in js
    assert "/services/${serviceId}`" in js
    assert "method: \"POST\"" in function_block(js, "async function createAdminService", "async function loadStaffMembers")
    save = function_block(js, "async function saveAdminService", "async function createAdminService")
    assert "duration_minutes < 1 || payload.duration_minutes > 1440" in js
    assert "configurationMutationKeys.has(mutationKey)" in save
    assert "nuevas reservas" in save
    assert "Las reservas existentes se conservarán" in save
    render = function_block(js, "function renderAdminServices", "function validateServicePayload")
    for value in ("service.name", "service.description", "service.price_text"):
        assert f"escapeHtml({value}" in render
    assert "staffMembers.filter" in render
    assert 'aria-describedby="service-${service.id}-name-error"' in render
    assert 'setAttribute("aria-invalid", "true")' in js


def test_team_separates_access_from_public_identity_and_reuses_staff_routes() -> None:
    html, _, js = read_sources()
    assert "Rol de acceso" in html
    assert "no es un título público" in html
    assert "Nombre público" in html
    assert 'id="new-staff-bookable"' in html
    assert "/staff/${memberId}/services`" in js
    assert "/staff/${memberId}/availability`" in js
    assert 'method: "PUT"' in js
    render = function_block(js, "function renderStaffMembers", "function toggleStaffServiceControls")
    for value in ("member.email", "member.public_name", "member.bio"):
        assert f"escapeHtml({value}" in render
    assert "member.role === \"business_admin\"" in render
    assert "member.bookable" in render
    assert "configurationLoadState.staff = \"error\"" in js
    assert "Reintentar equipo" in js


def test_availability_explains_rules_and_validates_windows_without_new_calculation() -> None:
    html, _, js = read_sources()
    for label in (
        "Cada cuánto puede empezar una cita",
        "Margen entre citas",
        "Antelación mínima",
        "Hasta cuándo se puede reservar",
        "Excepciones y cierres",
    ):
        assert label in html
    assert "/availability-settings`" in js
    assert "/availability-exceptions`" in js
    validation = function_block(js, "function validateAvailabilityPayload", "async function saveAvailabilitySettings")
    assert "windowItem.start >= windowItem.end" in validation
    assert "sorted[index - 1].end > windowItem.start" in validation
    assert 'setAttribute("aria-invalid", "true")' in validation
    assert "errors[0].field?.focus()" in validation
    assert "available-slots" not in validation


def test_public_page_preserves_six_templates_themes_and_upload_controls() -> None:
    html, _, js = read_sources()
    for template in ("classic", "elegant", "beauty", "clinic", "urban", "minimal"):
        assert html.count(f'<option value="{template}">') == 1
    for theme in (
        "slate_gold",
        "rose_beauty",
        "emerald_clean",
        "blue_clinic",
        "amber_barber",
        "violet_modern",
    ):
        assert html.count(f'<option value="{theme}">') == 1
        assert theme in js
    assert 'accept="image/jpeg,image/png,image/webp"' in html
    assert "/media/${kind}`" in js
    assert "/media/gallery`" in js
    assert "resolveSafeAdminMediaUrl" in js
    safe_media = function_block(js, "function resolveSafeAdminMediaUrl", "function showAdminSection")
    assert '["https:", "http:"]' in safe_media
    assert "window.location.origin" in safe_media and "apiOrigin" in safe_media
    public_link = function_block(js, "function applyBusinessData", "function renderBusinessSettings")
    assert "encodeURIComponent(getBusinessSlug())" in public_link
    assert "<iframe" not in html.lower()


def test_dirty_state_is_per_form_and_guards_navigation_reload_and_rerenders() -> None:
    html, _, js = read_sources()
    for key in ("business-info", "public-page", "service-new", "staff-new", "availability", "exception"):
        assert f'data-config-dirty-key="{key}"' in html
    assert "const configurationSnapshots = new Map();" in js
    assert "const configurationDirtyKeys = new Set();" in js
    assert 'window.addEventListener("beforeunload"' in js
    assert "confirmConfigurationNavigation(targetSection)" in js
    assert "snapshotConfigurationForm" in js
    assert "configurationMutationKeys.has(mutationKey)" in js
    assert "Guarda o revisa" in js
    assert '["business-info", "public-page"].some((key) => configurationDirtyKeys.has(key))' in js
    assert 'key.startsWith("gallery-") && key !== mutationKey' in js
    setup = function_block(js, "function setupBusinessConfiguration", "function applyRoleVisibility")
    assert setup.count('addEventListener("input"') == 1
    assert setup.count('addEventListener("change"') == 1
    assert "setInterval(" not in setup


def test_configuration_has_accessible_partial_states_and_responsive_structure() -> None:
    html, css, js = read_sources()
    assert html.count("data-configuration-navigation") == 6
    assert 'aria-label="Apartados de configuración"' in js
    assert 'aria-current="page"' in js
    assert "color: transparent" not in css.split("/* Sprint 5B.4", 1)[1]
    assert 'aria-busy="true"' in html
    assert 'role="alert" tabindex="-1" hidden' in html
    for retry in ("Reintentar servicios", "Reintentar equipo", "Reintentar horarios", "Reintentar galería"):
        assert retry in js
    assert "configuration-empty-state" in js
    assert "@media (max-width: 1023px)" in css
    assert "@media (max-width: 639px)" in css
    assert "env(safe-area-inset-bottom)" in css
    assert ".business-configuration-layout" in css
    assert ".configuration-navigation" in css


def test_staff_removal_dialog_has_focus_trap_escape_and_return_focus() -> None:
    html, _, js = read_sources()
    modal = html.split('id="staff-removal-modal"', 1)[1]
    assert 'role="dialog"' in modal
    assert 'aria-modal="true"' in modal
    assert 'aria-describedby="staff-removal-modal-message"' in modal
    assert 'aria-hidden="true"' in modal
    assert "staffRemovalReturnFocus" in js
    assert "trapModalFocus(event, staffModal)" in js
    assert 'event.key === "Escape"' in js
    assert "returnFocus?.isConnected" in js


def test_configuration_does_not_add_polling_or_replace_other_admin_areas() -> None:
    _, _, js = read_sources()
    setup = function_block(js, "function setupBusinessConfiguration", "function applyRoleVisibility")
    assert "fetch(" not in setup
    assert "setInterval(" not in setup
    for contract in (
        'adminPollingTasks.set("operations"',
        'adminPollingTasks.set("conversationThread"',
        "captureBookingEditorState",
        "captureConversationUiState",
        "renderDashboard();",
    ):
        assert contract in js
