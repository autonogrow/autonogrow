from __future__ import annotations

import re
from html.parser import HTMLParser
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
OWNER = ROOT / "autonogrow-owner"
HTML = OWNER / "index.html"
CSS = OWNER / "styles.css"
OWNER_JS = OWNER / "owner.js"
BUSINESSES_JS = OWNER / "owner-businesses.js"
ONBOARDING_JS = OWNER / "owner-onboarding.js"
ROUTER = ROOT / "backend" / "app" / "routers" / "owner_onboarding.py"
SERVICE = ROOT / "backend" / "app" / "services" / "business_onboarding_service.py"
DOC = ROOT / "docs" / "ux" / "25_owner_onboarding_complete.md"

REAL_STEPS = [
    "template",
    "business_identity",
    "contact_and_location",
    "services",
    "staff",
    "schedules",
    "booking_rules",
    "branding",
    "landing_content",
    "automations",
    "integrations",
    "credits_and_plan",
    "readiness_review",
    "preview",
    "activation",
]


class IdInventory(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.ids: list[str] = []

    def handle_starttag(self, _tag: str, attrs: list[tuple[str, str | None]]) -> None:
        element_id = dict(attrs).get("id")
        if element_id:
            self.ids.append(element_id)


def sources() -> tuple[str, str, str, str, str]:
    return (
        HTML.read_text(encoding="utf-8"),
        CSS.read_text(encoding="utf-8"),
        OWNER_JS.read_text(encoding="utf-8"),
        BUSINESSES_JS.read_text(encoding="utf-8"),
        ONBOARDING_JS.read_text(encoding="utf-8"),
    )


def function(js: str, name: str, next_name: str) -> str:
    return js.split(name, 1)[1].split(next_name, 1)[0]


def test_onboarding_is_an_isolated_cache_busted_module_after_dependencies() -> None:
    html, _, _, _, onboarding = sources()
    assert 'owner-onboarding.js?v=' in html
    assert html.index("owner-operations.js") < html.index("owner-onboarding.js")
    assert '"use strict"' in onboarding
    assert "owner-onboarding.js" not in OWNER_JS.read_text(encoding="utf-8")


def test_owner_js_keeps_only_shared_onboarding_state_and_bootstrap_hook() -> None:
    owner = OWNER_JS.read_text(encoding="utf-8")
    for declaration in (
        "let onboardingData = null;",
        "let onboardingStepIndex = 0;",
        "let onboardingReadiness = null;",
    ):
        assert declaration in owner
    assert "window.loadOwnerOnboardingTemplates" in owner
    for forbidden in (
        "const ONBOARDING_STEPS",
        "function onboardingFields",
        "function renderOnboardingStep",
        "function renderOnboarding()",
        "async function startOnboarding",
        "async function resumeOnboarding",
        "async function saveOnboardingStep",
        'business_identity: `<div',
        'booking_rules: `<div',
        'credits_and_plan: `<div',
        'else if (step === "business_identity")',
        'else if (step === "booking_rules")',
        'else if (step === "credits_and_plan")',
    ):
        assert forbidden not in owner


def test_wizard_listeners_and_opening_implementation_live_only_in_new_module() -> None:
    _, _, owner, hub, onboarding = sources()
    listener_ids = (
        "onboarding-start",
        "onboarding-save",
        "onboarding-back",
        "onboarding-later",
        "onboarding-steps",
        "onboarding-step-content",
    )
    for element_id in listener_ids:
        assert f'q("{element_id}").addEventListener' in onboarding
        assert f'byId("{element_id}").addEventListener' not in owner
    assert "async function openOwnerOnboarding" not in hub
    assert "window.openOwnerOnboarding = async function" in onboarding
    assert "window.OWNER_ONBOARDING_STEPS" in onboarding
    assert "window.ownerOnboardingStepLabel" in onboarding


def test_real_fifteen_step_keys_and_order_are_preserved() -> None:
    _, _, _, _, onboarding = sources()
    positions = [onboarding.index(f'["{key}"') for key in REAL_STEPS]
    assert positions == sorted(positions)
    assert len(positions) == 15
    service = SERVICE.read_text(encoding="utf-8")
    assert positions and all(f'"{key}"' in service for key in REAL_STEPS)


def test_shell_exposes_business_status_current_step_progress_and_real_save_time() -> None:
    html, _, _, _, onboarding = sources()
    for element_id in (
        "owner-onboarding-business-name",
        "owner-onboarding-business-status",
        "owner-onboarding-current-summary",
        "owner-onboarding-progress-text",
        "owner-onboarding-last-saved",
        "owner-onboarding-initiator",
    ):
        assert f'id="{element_id}"' in html
    assert "session.step_activity?.[stepKey()]?.updated_at || session.last_activity_at" in onboarding
    assert "confirmados por backend" in onboarding


def test_initiator_limitation_is_explicit_without_rendering_user_id() -> None:
    html, _, _, _, _ = sources()
    initiator = html.split('id="owner-onboarding-initiator"', 1)[1].split("</span>", 1)[0]
    assert "no expone su identidad" in initiator
    assert "user_id" not in initiator


def test_creation_uses_real_endpoint_validates_slug_and_blocks_double_submit() -> None:
    html, _, _, _, onboarding = sources()
    assert 'id="onboarding-name"' in html and "required" in html.split('id="onboarding-name"', 1)[1].split(">", 1)[0]
    assert 'pattern="[a-z0-9]+(?:-[a-z0-9]+)*"' in html
    creation = function(onboarding, "window.startOnboarding", "function renderSteps")
    assert 'request("/businesses/onboarding"' in creation
    assert "if (state.creating) return" in creation
    assert "q(\"onboarding-create\").disabled = true" in creation
    assert "template_version" in creation
    assert "name.value" not in creation.split("catch", 1)[1]


def test_all_four_entry_points_target_the_selected_business() -> None:
    _, _, owner, hub, onboarding = sources()
    assert 'data-owner-detail="onboarding"' in owner
    assert "openOwnerOnboarding(businessId)" in owner
    assert "data-owner-business-onboarding" in hub
    assert "window.openOwnerOnboarding" in onboarding
    assert "businessId" in function(onboarding, "window.openOwnerOnboarding", "window.startOnboarding")
    assert "businesses[0]" not in onboarding


def test_load_is_single_flight_and_secondary_failures_do_not_hide_main_data() -> None:
    _, _, _, _, onboarding = sources()
    load = function(onboarding, "async function loadOwnerOnboarding", "window.resumeOnboarding")
    assert "if (state.loadPromise)" in load
    assert "const pending = state.loadPromise" in load
    supplemental = function(onboarding, "async function loadSupplemental", "async function loadOwnerOnboarding")
    assert "Promise.all" in supplemental
    assert 'status: "error"' in supplemental
    assert "renderOnboarding(false)" in supplemental
    assert "state.dirty || state.saving" in supplemental
    assert "loadingBusinessId" in load


def test_step_statuses_are_backend_values_with_text_not_color_only() -> None:
    _, _, _, _, onboarding = sources()
    for status in ("pending", "in_progress", "completed", "skipped", "blocked"):
        assert re.search(rf"\b{status}: \"", onboarding)
    render = function(onboarding, "function renderSteps", "function renderShell")
    assert "item.status" in render
    assert "aria-current=\"step\"" in render
    assert "STATUS[status]" in render


def test_navigation_has_previous_save_save_continue_next_and_return() -> None:
    html, _, _, _, onboarding = sources()
    for label in ("Anterior", "Guardar", "Guardar y continuar", "Siguiente", "Volver a Altas"):
        assert label in html
    assert "ownerOnboardingNavigate" in onboarding
    assert "onboarding-step-title\").focus" in onboarding
    assert 'id="owner-onboarding-origin"' in html
    assert "state.entryOrigin" in onboarding


def test_unsaved_changes_offer_save_discard_and_cancel_with_focus_trap() -> None:
    html, _, _, _, onboarding = sources()
    for element_id in (
        "owner-onboarding-unsaved-dialog",
        "owner-onboarding-unsaved-save",
        "owner-onboarding-unsaved-discard",
        "owner-onboarding-unsaved-cancel",
    ):
        assert f'id="{element_id}"' in html
    assert "warnUnsaved" in onboarding
    assert 'event.key === "Escape"' in onboarding
    assert 'event.key !== "Tab"' in onboarding
    assert 'window.addEventListener("beforeunload"' in onboarding
    assert "localStorage" not in onboarding


def test_explicit_save_waits_for_backend_then_reloads_progress() -> None:
    _, _, _, _, onboarding = sources()
    save = function(onboarding, "window.saveOwnerOnboardingStep", "window.saveOnboardingStep")
    assert "if (state.saving" in save
    assert "form.reportValidity()" in save
    assert "await request" in save
    assert "await reloadMain(false)" in save
    assert "state.readiness = null" in save
    assert "renderOnboarding" in save
    assert "business.status =" not in save


def test_conflict_is_safe_and_preserves_temporary_form_copy() -> None:
    _, _, _, _, onboarding = sources()
    assert "Este paso cambió desde otra sesión" in onboarding
    assert "copia temporal" in onboarding
    assert "data-ob-reload" in onboarding
    save = function(onboarding, "window.saveOwnerOnboardingStep", "window.saveOnboardingStep")
    conflict_branch = save.rsplit("catch (error)", 1)[1].split("finally", 1)[0]
    assert "renderOnboarding" not in conflict_branch


def test_identity_and_contact_use_only_real_schema_fields() -> None:
    _, _, _, _, onboarding = sources()
    for field in (
        "legal_name", "tax_identifier", "language_code", "timezone", "currency",
        "postal_code", "region", "country_code", "tiktok_url", "external_website_url",
    ):
        assert field in onboarding
    assert "confirm_active_slug_change" in onboarding


def test_services_support_add_edit_deactivate_order_and_real_validation() -> None:
    _, _, _, _, onboarding = sources()
    for field in ("name", "description", "duration_minutes", "price_amount", "currency", "position", "active", "visible", "bookable"):
        assert f'data-field="{field}"' in onboarding
    assert "data-ob-add-service" in onboarding
    assert "min=\"1\" max=\"1440\"" in onboarding
    assert "Los nombres de servicio no pueden repetirse" in onboarding
    assert "el endpoint no elimina registros existentes" in onboarding


def test_staff_profiles_are_distinct_from_application_access() -> None:
    _, _, _, _, onboarding = sources()
    staff = function(onboarding, "function staffRow", "function staffForm") + function(onboarding, "function staffForm", "const DAYS")
    assert "crear personal no concede acceso" in onboarding.lower()
    assert "has_application_access" in staff
    assert "Gestionar usuarios y roles" in staff
    assert "último administrador activo" in staff
    assert 'role === "owner"' not in staff


def test_schedule_validates_days_order_overlap_and_closed_days() -> None:
    _, _, _, _, onboarding = sources()
    assert len(re.findall(r'\["[0-6]", "', onboarding)) == 7
    assert "el cierre debe ser posterior" in onboarding
    assert "los intervalos no pueden solaparse" in onboarding
    assert "Cerrado" in onboarding
    assert "weekly_schedule" in onboarding


def test_booking_separates_rules_from_server_calculated_availability() -> None:
    _, _, _, _, onboarding = sources()
    for field in ("min_notice_minutes", "max_days_ahead", "slot_interval_minutes", "buffer_between_bookings_minutes", "cancellation_notice_minutes", "max_simultaneous_bookings"):
        assert field in onboarding
    assert "se calculan en backend" in onboarding
    assert "confirm_booking_defaults" in onboarding


def test_exceptions_are_read_from_real_source_and_edited_canonically() -> None:
    _, _, _, _, onboarding = sources()
    assert "/availability-exceptions" in onboarding
    assert "Gestionar excepciones en Business Admin" in onboarding
    assert "data-ob-create-exception" not in onboarding


def test_brand_and_public_page_reuse_canonical_media_editor() -> None:
    _, _, _, _, onboarding = sources()
    for field in ("theme_key", "template_key", "primary_color", "secondary_color", "accent_color", "background_color", "headline", "landing_cta", "seo_title"):
        assert field in onboarding
    assert "Editar medios en Negocios" in onboarding
    assert "data-ob-media-input" not in onboarding
    assert "noindex" in onboarding


def test_channels_are_informative_and_never_request_or_approve_secrets() -> None:
    _, _, _, _, onboarding = sources()
    channels = function(onboarding, "function integrationsForm", "function creditsForm")
    for layer in ("Disponibilidad comercial", "Conexión", "Candidatura", "Aprobación", "Salud"):
        assert layer in channels
    assert "Configurar Instagram o WhatsApp" in channels
    assert "Continuar sin conectar" in onboarding
    for forbidden in ("access_token", "app_secret", "verify_token", "phone_number_id", "waba_id"):
        assert forbidden not in onboarding.lower()
    assert "/approve" not in channels


def test_plan_is_initialization_not_billing_or_activation() -> None:
    _, _, _, _, onboarding = sources()
    for field in ("plan_key", "included_credits", "additional_credits", "period_days"):
        assert f'data-ob="{field}"' in onboarding
    assert "idempotente" in onboarding
    assert "No representa precio, IVA, renovación ni cobro" in onboarding
    assert "no activa el negocio" in onboarding


def test_review_groups_real_backend_steps_and_links_to_exact_step() -> None:
    _, _, _, _, onboarding = sources()
    review = function(onboarding, "function reviewForm", "function previewForm")
    for group in ("Identidad", "Servicios", "Equipo", "Horarios y disponibilidad", "Página pública", "Canales", "Plan"):
        assert group in review
    assert "sessionStep" in review
    assert "data-ob-go-step" in review
    assert "no sustituye la decisión de readiness" in review


def test_readiness_keeps_version_internal_and_groups_server_checks() -> None:
    _, _, _, _, onboarding = sources()
    for group in ("Bloqueos", "Recomendaciones", "Comprobaciones correctas", "Errores de comprobación"):
        assert group in onboarding
    assert "item.related_step" in onboarding
    assert "expected_readiness_version: expectedVersion" in onboarding
    rendered = function(onboarding, "function readinessHtml", "function reviewForm")
    assert "state.readiness.version" not in rendered


def test_preview_uses_real_route_without_publishing_or_spending() -> None:
    _, _, _, _, onboarding = sources()
    preview = function(onboarding, "async function loadPreview", "async function activate")
    assert "/preview" in preview
    markup = function(onboarding, "function previewForm", "function activationForm")
    for statement in ("noindex", "Reservas", "Automatizaciones", "Créditos", "Todavía no está publicada"):
        assert statement in markup
    assert "/activate" not in preview


def test_activation_is_critical_versioned_non_optimistic_and_refreshes_context() -> None:
    _, _, _, _, onboarding = sources()
    activation = function(onboarding, "async function activate", "function closeUnsavedDialog")
    assert "state.readiness.ready" in activation
    assert "expected_readiness_version: expectedVersion" in activation
    assert "confirmOwnerCriticalAction" in activation
    assert "request(`/businesses/" in activation
    assert "await reloadMain(false)" in activation
    assert "await refreshContext()" in activation
    assert "state.activation = true" in activation.split("await action", 1)[-1]


def test_activation_result_has_only_real_safe_destinations() -> None:
    _, _, _, _, onboarding = sources()
    result = function(onboarding, "function activeSummary", "function sourceWarning")
    for action in ("Abrir Business Admin", "Abrir página pública", "Revisar canales", "Volver a Negocios"):
        assert action in result
    assert 'rel="noopener"' in result
    assert "encodeURIComponent(onboardingData.business.slug)" in onboarding
    assert "business.id}</" not in result


def test_accessible_structure_has_unique_ids_labels_busy_and_mobile_selector() -> None:
    html, css, _, _, _ = sources()
    parser = IdInventory()
    parser.feed(html)
    assert len(parser.ids) == len(set(parser.ids))
    assert 'role="dialog" aria-modal="true"' in html
    assert 'aria-current="step"' in ONBOARDING_JS.read_text(encoding="utf-8")
    assert 'id="owner-onboarding-step-select"' in html
    assert 'aria-busy="true"' in html or "aria-busy" in ONBOARDING_JS.read_text(encoding="utf-8")
    assert "font-size: 16px" in css
    assert "100dvh" in css


def test_responsive_structure_covers_compact_navigation_and_stacked_actions() -> None:
    _, css, _, _, _ = sources()
    assert "@media (max-width: 900px)" in css
    assert ".owner-onboarding-mobile-step { display: grid" in css
    assert "#onboarding-steps { display: none" in css
    assert "@media (max-width: 600px)" in css
    assert ".onboarding-step-panel footer" in css
    assert "env(safe-area-inset-bottom)" in css


def test_existing_backend_router_is_unchanged_and_no_frontend_endpoint_is_new() -> None:
    router = ROUTER.read_text(encoding="utf-8")
    _, _, _, _, onboarding = sources()
    allowed = (
        "/onboarding/templates", "/businesses/onboarding", "/onboarding", "/availability-settings",
        "/availability-exceptions", "/automation-settings", "/automation-credits", "/users", "/readiness", "/preview", "/activate", "/businesses/", "/api/admin/", "/api/owner/businesses/",
    )
    request_paths = [path for path in re.findall(r'(?:request|secondaryRequest)\(`?([^`"$]+)', onboarding) if not path.startswith("path")]
    assert request_paths
    assert all(any(fragment in path for fragment in allowed) for path in request_paths)
    assert '@router.post("/businesses/onboarding"' in router
    assert '@router.post("/businesses/{business_id}/activate"' in router


def test_documentation_records_sources_limits_tests_and_deferred_visual_qa() -> None:
    doc = DOC.read_text(encoding="utf-8")
    for heading in (
        "Arquitectura", "Matriz de pasos", "Matriz de estados", "Guardado", "Readiness",
        "Activación", "Errores parciales", "Responsive", "Accesibilidad", "Seguridad", "Pruebas", "Validación visual pendiente", "Deuda",
    ):
        assert heading.casefold() in doc.casefold()
    assert "15" in doc and "5E.1" in doc
