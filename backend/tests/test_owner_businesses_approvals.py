from __future__ import annotations

from html.parser import HTMLParser
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
OWNER_HTML = ROOT / "autonogrow-owner" / "index.html"
OWNER_CSS = ROOT / "autonogrow-owner" / "styles.css"
OWNER_JS = ROOT / "autonogrow-owner" / "owner.js"
HUB_JS = ROOT / "autonogrow-owner" / "owner-businesses.js"
DOC = ROOT / "docs" / "ux" / "23_owner_businesses_approvals.md"


class IdInventory(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.ids: list[str] = []

    def handle_starttag(self, _tag: str, attrs: list[tuple[str, str | None]]) -> None:
        element_id = dict(attrs).get("id")
        if element_id:
            self.ids.append(element_id)


def sources() -> tuple[str, str, str, str]:
    return (
        OWNER_HTML.read_text(encoding="utf-8"),
        OWNER_CSS.read_text(encoding="utf-8"),
        OWNER_JS.read_text(encoding="utf-8"),
        HUB_JS.read_text(encoding="utf-8"),
    )


def test_owner_navigation_names_the_two_sprint_areas() -> None:
    html, _, _, _ = sources()
    assert '>Negocios</button>' in html
    assert '>Altas y aprobaciones</button>' in html
    for inherited in ("Incidencias", "Colas y worker", "Operaciones"):
        assert inherited in html


def test_business_directory_has_search_reliable_filters_and_local_state() -> None:
    html, _, _, hub = sources()
    for contract in (
        'id="business-hub-search"',
        'id="business-hub-filter"',
        'value="active"',
        'value="onboarding"',
        'value="pending"',
        'value="suspended"',
        'value="attention"',
        'value="no-admin"',
    ):
        assert contract in html
    assert "ownerNormalizeSearch" in hub
    assert "adminEmails" in hub
    assert "renderOwnerBusinessRows" in hub


def test_default_order_is_attention_onboarding_suspended_active_rest() -> None:
    _, _, _, hub = sources()
    priority = hub.split("function ownerBusinessPriority", 1)[1].split(
        "function ownerNormalizeSearch", 1
    )[0]
    assert priority.index("ownerBusinessNeedsAttention") < priority.index(
        "OWNER_ONBOARDING_STATUSES"
    )
    assert priority.index('status === "suspended"') < priority.index(
        'status === "active"'
    )
    assert "localeCompare" in hub


def test_business_rows_are_compact_and_have_no_critical_direct_action() -> None:
    _, _, _, hub = sources()
    row = hub.split("function ownerBusinessRow", 1)[1].split(
        "function renderOwnerBusinessRows", 1
    )[0]
    for content in (
        "Administrador",
        "Canales",
        "Incidencias",
        "Creado:",
        "Abrir negocio",
        "Continuar alta",
        "Abrir Admin",
    ):
        assert content in row
    for forbidden in ("Suspender negocio", "Revocar", "Aprobar candidatura"):
        assert forbidden not in row


def test_business_state_readiness_publication_admin_and_channels_are_separate() -> None:
    _, _, _, hub = sources()
    activation = hub.split("function ownerActivationPanel", 1)[1].split(
        "function ownerChannelsPanel", 1
    )[0]
    for layer in (
        "Onboarding",
        "Estado comercial",
        "Página pública",
        "Readiness",
    ):
        assert layer in activation
    summary = hub.split("function ownerBusinessSummary", 1)[1].split(
        "function renderOwnerBusinessDetail", 1
    )[0]
    for layer in ("Publicación", "Administrador", "Servicios", "Horarios", "Canales"):
        assert layer in summary


def test_detail_has_six_requested_sections() -> None:
    _, _, _, hub = sources()
    detail = hub.split("function renderOwnerBusinessDetail", 1)[1].split(
        "function activateOwnerBusinessDetailSection", 1
    )[0]
    for key, label in (
        ("summary", "Resumen"),
        ("brand", "Datos y marca"),
        ("users", "Usuarios y acceso"),
        ("activation", "Activación"),
        ("channels", "Canales"),
        ("activity", "Actividad"),
    ):
        assert f'["{key}", "{label}"]' in detail


def test_data_and_brand_reuse_existing_dom_and_admin_destination() -> None:
    _, _, _, hub = sources()
    brand = hub.split("function ownerBrandEditor", 1)[1].split(
        "function ownerUsersEditor", 1
    )[0]
    for contract in (
        "data-owner-editor",
        "data-owner-theme",
        "data-owner-template",
        "data-owner-media-input",
        "data-owner-gallery",
        "data-owner-brand-save",
        "#business",
    ):
        assert contract in brand


def test_users_only_offer_real_business_roles_and_hide_internal_ids() -> None:
    _, _, _, hub = sources()
    users = hub.split("function ownerUsersEditor", 1)[1].split(
        "function ownerActivationPanel", 1
    )[0]
    assert 'value="business_admin"' in users
    assert 'value="business_staff"' in users
    assert 'value="owner"' not in users
    assert 'value="customer"' not in users
    rendered = hub.split("loadOwnerUsers =", 1)[1].split(
        "handleOwnerUserAction =", 1
    )[0]
    assert "membership_id" not in rendered
    assert "user_id" not in rendered


def test_last_active_admin_is_protected_before_mutation() -> None:
    _, _, _, hub = sources()
    handler = hub.split("handleOwnerUserAction =", 1)[1].split(
        "changeBusinessState =", 1
    )[0]
    assert 'item.active && item.role === "business_admin"' in handler
    assert "activeAdmins.length === 1" in handler
    assert "Asigna otro administrador primero" in handler
    assert "return;" in handler


def test_user_sensitive_changes_have_specific_context_and_consequence() -> None:
    _, _, _, hub = sources()
    handler = hub.split("handleOwnerUserAction =", 1)[1].split(
        "changeBusinessState =", 1
    )[0]
    for text in (
        "Asignar acceso",
        "Cambiar rol",
        "Reactivar acceso",
        "Desactivar acceso",
        '["Negocio", business.name]',
        "Este flujo nunca concede permisos Owner",
    ):
        assert text in handler


def test_activation_uses_fresh_readiness_and_expected_version() -> None:
    _, _, _, hub = sources()
    onboarding = (ROOT / "autonogrow-owner" / "owner-onboarding.js").read_text(
        encoding="utf-8"
    )
    activation = hub.split("async function activateOwnerBusiness", 1)[1].split(
        "/* Altas y aprobaciones.", 1
    )[0]
    assert "loadOwnerBusinessReadiness(businessId, true)" in activation
    assert "readiness?.ready" in activation
    assert "expected_readiness_version: readiness.version" in activation
    assert "/activate" in activation
    assert "const expectedVersion = state.readiness.version" in onboarding
    assert "expected_readiness_version: expectedVersion" in onboarding


def test_suspend_and_reactivate_use_existing_endpoints_without_optimism() -> None:
    _, _, _, hub = sources()
    state = hub.split("changeBusinessState =", 1)[1].split(
        "async function activateOwnerBusiness", 1
    )[0]
    assert 'const action = suspending ? "suspend" : "reactivate"' in state
    assert "confirmOwnerCriticalAction" in state
    assert "await refreshOwnerBusinessContext()" in state
    assert "business.status =" not in state


def test_onboarding_progress_counts_real_steps_not_invented_percentages() -> None:
    _, _, _, hub = sources()
    onboarding = hub.split("function ownerOnboardingProgress", 1)[1].split(
        "function ownerCandidateItems", 1
    )[0]
    assert "session.completed_steps" in onboarding
    assert "session.skipped_steps" in onboarding
    assert "Object.keys(session.steps" in onboarding
    assert " de ${progress.total} pasos" in onboarding
    assert "Math.round" not in onboarding
    assert "%" not in onboarding


def test_onboarding_reuses_existing_wizard_and_all_real_steps() -> None:
    html, _, js, hub = sources()
    onboarding = (ROOT / "autonogrow-owner" / "owner-onboarding.js").read_text(
        encoding="utf-8"
    )
    assert html.count('id="onboarding-wizard"') == 1
    assert "ONBOARDING_STEPS" not in js
    assert "window.OWNER_ONBOARDING_STEPS" in onboarding
    assert "window.openOwnerOnboarding" in onboarding
    assert "window.ownerOnboardingStepLabel" in hub
    assert "async function openOwnerOnboarding" not in hub
    assert '"readiness_review"' in onboarding


def test_readiness_maps_status_message_remediation_and_destination() -> None:
    _, _, _, hub = sources()
    readiness = hub.split("async function loadOwnerBusinessReadiness", 1)[1].split(
        "async function showOwnerBusinessPreview", 1
    )[0]
    for field in (
        "item.label",
        "item.status",
        "item.message",
        "item.remediation",
        "item.related_step",
        "Correcto",
        "Recomendado",
        "Bloqueante",
        "No se pudo comprobar",
    ):
        assert field in readiness
    assert "readiness.version" not in readiness


def test_preview_is_read_only_and_explains_guarantees() -> None:
    _, _, _, hub = sources()
    preview = hub.split("async function showOwnerBusinessPreview", 1)[1].split(
        "async function refreshOwnerBusinessContext", 1
    )[0]
    for text in (
        "todavía no está publicada",
        "reservas permanecen deshabilitadas",
        "no se consumen créditos",
        "Volver al onboarding",
        "Revisar bloqueos",
    ):
        assert text in preview
    assert 'method: "POST"' not in preview


def test_instagram_and_whatsapp_candidates_are_independent_sources() -> None:
    _, _, _, hub = sources()
    items = hub.split("function ownerCandidateItems", 1)[1].split(
        "function ownerCandidatePublicName", 1
    )[0]
    assert "snapshot.instagramCandidates" in items
    assert "snapshot.whatsappCandidates" in items
    assert 'channel: "instagram"' in items
    assert 'channel: "whatsapp"' in items
    assert "Promise.all" not in items


def test_candidate_review_separates_candidate_integration_control_and_health() -> None:
    _, _, _, hub = sources()
    review = hub.split("async function openOwnerCandidateReview", 1)[1].split(
        "async function decideOwnerCandidate", 1
    )[0]
    for layer in ("Candidatura", "Integración activa", "Control comercial", "Salud conocida"):
        assert layer in review
    assert "integrated_delivery_enabled" in review
    assert "automation_enabled" in review
    assert "La salud no equivale a aprobación" in review


def test_safe_replacement_and_rejection_preserve_previous_integration() -> None:
    _, _, _, hub = sources()
    decision = hub.split("async function decideOwnerCandidate", 1)[1].split(
        "function setOwnerHubView", 1
    )[0]
    assert "conexión anterior se conservará" in decision
    assert "no se habilitarán automáticamente" in decision
    assert "no se revocará" in decision
    assert "/oauth/candidates/" in decision
    assert "/embedded-signup/candidates/" in decision


def test_candidate_ui_exposes_no_raw_provider_identifiers_or_scopes() -> None:
    _, _, js, hub = sources()
    review = hub.split("function ownerCandidateItems", 1)[1].split(
        "function setOwnerHubView", 1
    )[0]
    for forbidden in (
        "candidate_external_account_id_masked",
        "candidate_granted_scopes",
        "phone_number_id",
        "waba_id",
        "state_hash",
        "access_token",
        "App Secret",
    ):
        assert forbidden not in review
    integration_render = js.split("function renderOwnerIntegration", 1)[1].split(
        "async function loadOwnerIntegration", 1
    )[0]
    assert "external_account_id_masked" not in integration_render
    assert "granted_scopes" not in integration_render
    assert "Conexión manual avanzada" not in integration_render


def test_critical_dialog_waits_for_backend_and_blocks_double_action() -> None:
    html, _, _, hub = sources()
    assert 'role="dialog"' in html
    assert 'aria-modal="true"' in html
    dialog = hub.split("function confirmOwnerCriticalAction", 1)[1].split(
        "/* Usuarios:", 1
    )[0]
    assert "if (ownerCriticalDialogState)" in dialog
    assert "state.busy = true" in dialog
    assert "await state.config.action(reason)" in dialog
    assert dialog.index("await state.config.action(reason)") < dialog.index(
        "closeOwnerCriticalDialog(true)"
    )


def test_critical_dialog_traps_focus_escape_and_returns_focus() -> None:
    _, _, _, hub = sources()
    dialog = hub.split("function closeOwnerCriticalDialog", 1)[1].split(
        "/* Usuarios:", 1
    )[0]
    assert "state.returnFocus?.focus?.()" in dialog
    assert 'event.key === "Escape"' in dialog
    assert 'event.key !== "Tab"' in dialog
    assert "last.focus()" in dialog
    assert "first.focus()" in dialog


def test_partial_errors_do_not_claim_empty_or_erase_other_sources() -> None:
    _, _, _, hub = sources()
    assert "no se clasifican como sin administrador" in hub
    assert "no se afirma que la cola esté vacía" in hub.lower()
    assert "Instagram y WhatsApp disponibles se muestran por separado" in hub
    assert "Promise.allSettled" in hub


def test_dashboard_decision_navigates_to_exact_approvals_area() -> None:
    _, _, js, hub = sources()
    dashboard = js.split("function renderPendingDecisions", 1)[1].split(
        "function ownerApprovalLabel", 1
    )[0]
    assert 'data-owner-navigate="new-business"' in dashboard
    assert 'data-owner-business-id="${escapeHtml(item.business.id)}"' in dashboard
    assert 'data-owner-detail="${escapeHtml(item.channel)}"' in dashboard
    assert "function openOwnerApprovalContext" in hub


def test_filters_and_selected_detail_are_preserved_across_refresh() -> None:
    _, _, _, hub = sources()
    refresh = hub.split("async function refreshOwnerBusinessContext", 1)[1].split(
        "/* Diálogo crítico", 1
    )[0]
    assert "const selected = ownerBusinessHubState.selectedBusinessId" in refresh
    assert "ownerBusinessHubState.selectedBusinessId = selected" in refresh
    assert "ownerBusinessHubState.query =" in hub
    assert "ownerBusinessHubState.filter =" in hub
    assert "window.location.reload" not in hub


def test_dynamic_text_is_escaped_and_routes_are_encoded() -> None:
    _, _, _, hub = sources()
    assert hub.count("escapeHtml(") >= 70
    assert hub.count("encodeURIComponent(") >= 20
    assert "innerHTML = error.message" not in hub
    assert "console.log" not in hub


def test_responsive_and_dialog_css_cover_desktop_tablet_mobile_and_safe_area() -> None:
    _, css, _, _ = sources()
    for contract in (
        "grid-template-columns: minmax(13rem",
        "@media (max-width: 1199px)",
        "@media (max-width: 767px)",
        "100dvh",
        "env(safe-area-inset-top)",
        "prefers-reduced-motion",
    ):
        assert contract in css
    assert "overflow-x: auto" in css
    assert ".owner-dialog" in css


def test_dom_contracts_are_unique_and_legacy_sections_coexist() -> None:
    html, _, _, _ = sources()
    parser = IdInventory()
    parser.feed(html)
    assert len(parser.ids) == len(set(parser.ids))
    for element_id in (
        "owner-overview",
        "business-list",
        "business-detail",
        "onboarding-wizard",
        "incident-list",
        "queue-jobs",
        "operations-details",
        "owner-critical-dialog",
    ):
        assert parser.ids.count(element_id) == 1


def test_hub_uses_only_existing_owner_endpoints_and_no_polling() -> None:
    _, _, _, hub = sources()
    for endpoint in (
        "/api/owner/businesses/${encodeURIComponent(business.slug)}/users",
        "/onboarding",
        "/readiness",
        "/preview",
        "/activate",
        "/oauth/candidates/",
        "/embedded-signup/candidates/",
        "/channel-controls/",
    ):
        assert endpoint in hub
    assert 'suspending ? "suspend" : "reactivate"' in hub
    for forbidden in ("/api/owner/businesses-hub", "/api/owner/approvals", "setInterval(", "setTimeout("):
        assert forbidden not in hub


def test_documentation_records_sources_actions_limits_and_visual_qa() -> None:
    doc = DOC.read_text(encoding="utf-8")
    for heading in (
        "Arquitectura final",
        "Fuentes y datos seguros",
        "Matriz de acciones",
        "Directorio, filtros y orden",
        "Usuarios y roles",
        "Altas, onboarding, readiness y preview",
        "Candidaturas y reemplazo seguro",
        "Acciones críticas, concurrencia y errores parciales",
        "Responsive y accesibilidad",
        "Seguridad y rendimiento",
        "Pruebas y validación pendiente",
        "Limitaciones y deuda",
    ):
        assert heading in doc
    for viewport in ("1440×900", "1024×768", "768×1024", "390×844", "360×800"):
        assert viewport in doc
