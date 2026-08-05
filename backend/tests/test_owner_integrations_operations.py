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
OPERATIONS_JS = OWNER / "owner-operations.js"
DOC = ROOT / "docs" / "ux" / "24_owner_integrations_operations.md"


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
        OPERATIONS_JS.read_text(encoding="utf-8"),
    )


def function(js: str, name: str, next_name: str) -> str:
    return js.split(f"function {name}", 1)[1].split(f"function {next_name}", 1)[0]


def test_high_level_navigation_matches_owner_architecture() -> None:
    html, _, _, _, _ = sources()
    labels = (
        "Resumen",
        "Negocios",
        "Altas y aprobaciones",
        "Integraciones",
        "Incidencias",
        "Operaciones",
        "Auditoría",
    )
    nav = html.split('<nav class="tabs"', 1)[1].split("</nav>", 1)[0]
    assert [label for label in labels if label in nav] == list(labels)
    assert 'data-tab="queues"' not in nav


def test_operations_module_is_isolated_and_cache_busted() -> None:
    html, _, _, _, operations = sources()
    assert 'owner-operations.js?v=' in html
    assert "use strict" in operations
    assert len(operations.splitlines()) < 900


def test_integrations_has_summary_filters_list_and_detail() -> None:
    html, _, _, _, _ = sources()
    for element_id in (
        "owner-integrations-summary",
        "owner-integration-search",
        "owner-integration-filter",
        "owner-integrations-list",
        "owner-integration-detail",
    ):
        assert f'id="{element_id}"' in html
    for value in (
        "all",
        "instagram",
        "whatsapp",
        "pending",
        "problems",
        "reconnect",
        "suspended",
        "revoked",
    ):
        assert f'value="{value}"' in html


def test_integration_summary_uses_six_requested_real_indicators() -> None:
    _, _, _, _, operations = sources()
    summary = function(
        operations, "renderOwnerIntegrationsSummary", "ownerIntegrationRow"
    )
    for label in (
        "Integraciones activas",
        "Pendientes de revisión",
        "Necesitan reconexión",
        "Salud degradada",
        "Envío habilitado",
        "Automatización habilitada",
    ):
        assert label in summary
    for fictional in ("Uptime", "SLA", "Tasa de éxito", "Disponibilidad porcentual"):
        assert fictional not in summary


def test_integration_search_is_local_and_uses_only_safe_public_fields() -> None:
    _, _, _, _, operations = sources()
    filtered = function(operations, "ownerFilteredIntegrations", "renderOwnerIntegrationsSummary")
    for field in ("business.name", "business.slug", "record.publicAccount"):
        assert field in filtered
    for field in ("access_token", "granted_scopes", "integration_id"):
        assert field not in filtered


def test_integration_row_separates_all_operational_states() -> None:
    _, _, _, _, operations = sources()
    row = function(operations, "ownerIntegrationRow", "renderOwnerIntegrationsList")
    for label in (
        "Disponibilidad",
        "Integración activa",
        "Aprobación",
        "Envío",
        "Automatización",
        "Salud",
        "Última comprobación",
        "Abrir integración",
    ):
        assert label in row
    assert "account_id" not in row
    assert "token" not in row.lower()


def test_integration_detail_has_seven_requested_sections() -> None:
    _, _, _, _, operations = sources()
    nav = function(operations, "ownerIntegrationDetailNav", "ownerIntegrationControlActions")
    for key in ("summary", "control", "capabilities", "health", "recovery", "candidates", "activity"):
        assert f'"{key}"' in nav


def test_commercial_control_actions_use_existing_endpoints_and_confirmation() -> None:
    _, _, _, _, operations = sources()
    mutation = function(operations, "mutateOwnerIntegrationControl", "saveOwnerIntegrationCapabilities")
    for endpoint in ('grant: "access"', 'approve: "approve"', 'suspend: "suspend"', 'revoke: "revoke"'):
        assert endpoint in mutation
    assert "confirmOwnerCriticalAction" in mutation
    assert "reason" in mutation
    assert "await refreshOwnerIntegrationContext()" in mutation


def test_capabilities_are_independent_blocked_and_not_optimistic() -> None:
    _, _, _, _, operations = sources()
    detail = function(operations, "ownerIntegrationDetailMarkup", "renderOwnerIntegrationDetail")
    for label in ("Envío integrado", "Automatización", "Modo asistido"):
        assert label in detail
    assert "canChangeCapabilities" in detail
    mutation = function(operations, "saveOwnerIntegrationCapabilities", "runOwnerIntegrationHealthCheck")
    assert 'method: "PATCH"' in mutation
    assert "confirmOwnerCriticalAction" in mutation
    assert "refreshOwnerIntegrationContext" in mutation


def test_health_states_are_mapped_and_raw_diagnostics_are_not_rendered() -> None:
    _, _, _, _, operations = sources()
    for state, label in (
        ("unknown", "Aún no comprobada"),
        ("healthy", "Operativa"),
        ("warning", "Funciona con avisos"),
        ("degraded", "Funciona con problemas"),
        ("action_required", "Requiere intervención"),
        ("revoked", "Acceso revocado"),
        ("suspended", "Suspendida"),
        ("error", "No se pudo comprobar"),
    ):
        assert f'{state}: "{label}"' in operations
    detail = function(operations, "ownerIntegrationDetailMarkup", "renderOwnerIntegrationDetail")
    for forbidden in ("consecutive_health_failures", "health_error_code", "diagnostic_metadata"):
        assert forbidden not in detail


def test_health_check_is_single_action_and_backend_idempotent() -> None:
    _, _, _, _, operations = sources()
    health = function(operations, "runOwnerIntegrationHealthCheck", "retryOwnerIntegrationSubscription")
    assert "button.disabled" in health
    assert "/health-check" in health
    assert "result.created" in health
    assert "loadOwnerMetaJobs" in health


def test_reconnection_validates_destination_and_preserves_previous_integration_copy() -> None:
    _, _, _, _, operations = sources()
    reconnect = function(operations, "requestOwnerIntegrationReconnection", "openOwnerCandidateFromIntegration")
    assert "/request-reconnection" in reconnect
    assert 'url.startsWith("https://www.instagram.com/oauth/authorize?")' in reconnect
    assert "La integración actual seguirá disponible" in reconnect
    assert "window.location.assign" in reconnect


def test_subscription_retry_is_hidden_while_an_equivalent_business_job_is_active() -> None:
    _, _, _, _, operations = sources()
    detail = function(operations, "ownerIntegrationDetailMarkup", "renderOwnerIntegrationDetail")
    assert "subscriptionJobActive" in detail
    assert "Ya existe un reintento de suscripción activo" in detail
    assert "retry-subscription" in operations


def test_candidates_link_to_approvals_without_duplicate_decision_actions() -> None:
    _, _, _, _, operations = sources()
    candidate = function(operations, "openOwnerCandidateFromIntegration", "ownerIncidentStatusLabel")
    assert 'setActiveTab("new-business")' in candidate
    assert "openOwnerApprovalContext" in candidate
    detail = function(operations, "ownerIntegrationDetailMarkup", "renderOwnerIntegrationDetail")
    assert "Revisar en Altas y aprobaciones" in detail
    assert "Aprobar candidatura" not in detail
    assert "Rechazar candidatura" not in detail
    assert "no expone historial Owner de candidaturas resueltas" in detail


def test_incidents_have_real_views_filters_search_list_and_detail() -> None:
    html, _, _, _, operations = sources()
    for state in ("active", "acknowledged", "resolved", "all"):
        assert f'data-owner-incident-view="{state}"' in html
    for name in ("status", "severity", "business_id", "channel"):
        assert f'name="{name}"' in html
    assert 'id="owner-incident-origin"' in html
    assert 'id="owner-incident-search"' in html
    assert "ownerIncidentRow" in operations
    assert "renderOwnerIncidentDetail" in operations


def test_incident_origins_are_operational_and_include_bookings() -> None:
    _, _, _, _, operations = sources()
    origin = function(operations, "ownerIncidentOrigin", "ownerIncidentSafeMessage")
    for label in ("Instagram", "WhatsApp", "Mensajería", "Reservas", "Integraciones", "Procesamiento", "Plataforma"):
        assert label in origin


def test_incident_safe_message_uses_an_explicit_allowlist() -> None:
    _, _, _, _, operations = sources()
    safe = function(operations, "ownerIncidentSafeMessage", "ownerFilteredIncidents")
    assert '["message", "safe_message", "summary", "recommendation"]' in safe
    for forbidden in ("traceback", "request_body", "response_body", "provider_error_code"):
        assert forbidden not in safe


def test_incident_detail_has_context_timeline_safe_info_and_navigation() -> None:
    _, _, _, _, operations = sources()
    detail = function(operations, "renderOwnerIncidentDetail", "openOwnerIncidentDetail")
    for label in ("Resumen", "Impacto", "Contexto", "Cronología", "Información técnica segura"):
        assert label in detail
    for action in ("Abrir negocio", "Abrir integración", "Abrir operaciones"):
        assert action in detail
    for forbidden in ("provider_error_code", "conversation_id", "message_id", "incident_id"):
        assert forbidden not in detail


def test_incident_actions_are_confirmed_wait_for_backend_and_refresh_context() -> None:
    _, _, _, _, operations = sources()
    mutation = operations.split("updateIncident = async function", 1)[1].split(
        "/* Operaciones", 1
    )[0]
    for action in ("acknowledge", "resolve", "ignore", "reopen"):
        assert action in mutation
    assert "confirmOwnerCriticalAction" in mutation
    assert 'method: "PATCH"' in mutation
    assert "Promise.allSettled([loadIncidents(), loadOwnerDashboardIncidents()])" in mutation


def test_operations_has_summary_outbox_workers_jobs_and_maintenance() -> None:
    html, _, _, _, operations = sources()
    for panel in ("messages", "workers", "jobs", "maintenance"):
        assert f'data-owner-operations-panel="{panel}"' in html
    for renderer in (
        "renderOwnerOperationsSummary",
        "renderOwnerOutboxProblems",
        "renderOwnerWorkers",
        "renderOwnerIntegrationJobs",
        "renderOwnerMaintenance",
    ):
        assert f"function {renderer}" in operations


def test_outbox_uses_real_aggregates_and_hides_unavailable_ones() -> None:
    html, _, _, _, operations = sources()
    summary = function(operations, "renderOwnerOutboxSummary", "ownerQueueProblemRow")
    for field in ("pending_outbox", "retry_outbox", "blocked_outbox", "dead_letter_outbox"):
        assert field in summary
    assert "no expone agregados" in html
    assert 'job.job_type === "outbox"' in operations


def test_queue_rows_do_not_render_internal_ids_or_error_codes() -> None:
    _, _, _, _, operations = sources()
    row = function(operations, "ownerQueueProblemRow", "renderOwnerOutboxProblems")
    heading = row.split("<h4>", 1)[1].split("</h4>", 1)[0]
    assert "job.id" not in heading
    assert "last_error_code" not in row
    assert "provider_message" not in row
    assert "payload" not in row
    assert 'data-job-id="${escapeHtml(job.id)}"' in row


def test_workers_ignore_internal_implementation_fields() -> None:
    _, _, _, _, operations = sources()
    workers = function(operations, "renderOwnerWorkers", "renderOwnerIntegrationJobs")
    for visible in ("Procesamiento activo", "Última actividad", "Pendientes", "Reintentos", "Agotados"):
        assert visible in workers
    for forbidden in ("current_job_id", "locked_by", "version", "worker.pid", "SKIP LOCKED"):
        assert forbidden not in workers


def test_integration_jobs_are_translated_and_have_no_manual_retry() -> None:
    _, _, _, _, operations = sources()
    for raw, label in (
        ("health_check", "Comprobación de salud"),
        ("retry_subscription", "Reintento de suscripción"),
        ("attempt_cleanup", "Limpieza de intentos caducados"),
    ):
        assert f'{raw}: "{label}"' in operations
    jobs = function(operations, "renderOwnerIntegrationJobs", "renderOwnerMaintenance")
    assert "No existe un endpoint Owner seguro para reintentar este job manualmente" in jobs
    assert "entry.job.id" not in jobs
    assert "safe_error_code" not in jobs


def test_maintenance_is_contextual_confirmed_and_non_optimistic() -> None:
    _, _, _, _, operations = sources()
    mutation = operations.split("toggleMaintenance = async function", 1)[1].split(
        "/* Auditoría", 1
    )[0]
    assert "confirmOwnerCriticalAction" in mutation
    assert "El procesamiento automático se pausará según el alcance real" in mutation
    assert "/api/owner/system/maintenance/" in mutation
    assert "loadOwnerOperationsHub(true)" in mutation
    assert "No se vacían colas ni se eliminan datos" in mutation


def test_audit_is_explicitly_derived_because_no_read_endpoint_exists() -> None:
    html, _, _, _, operations = sources()
    assert "no expone actualmente un endpoint Owner" in html
    assert "no inventa actores ni payloads" in html
    assert "function ownerAuditEvents" in operations
    assert "Actor y resultado detallado: no expuestos" in operations
    assert "data-owner-audit-business" in operations


def test_partial_errors_stay_scoped_to_each_source() -> None:
    _, _, _, _, operations = sources()
    for source in ("queue", "platform", "jobs", "maintenance"):
        assert source in operations
    assert "Workers y jobs conservan sus fuentes independientes" in operations
    assert "Outbox y workers permanecen visibles" in operations
    assert "Actividad parcial" in operations
    assert "No se convierten fuentes fallidas en indicadores a cero" in operations


def test_manual_refresh_single_flight_and_no_new_polling() -> None:
    _, _, _, _, operations = sources()
    assert "integrationsInFlight" in operations
    assert "operationsInFlight" in operations
    assert "setInterval(" not in operations
    assert "setTimeout(" not in operations


def test_context_navigation_connects_all_safe_destinations() -> None:
    _, _, owner, businesses, operations = sources()
    for target in ("integrations", "incidents", "operations", "audit"):
        assert f'"{target}"' in owner
    assert "openOwnerIntegrationContext" in owner
    assert "openOwnerIncidentContext" in owner
    assert "data-owner-business-integration" in businesses
    for destination in ("data-owner-integration-business", "data-owner-integration-incidents", "data-owner-incident-business", "data-owner-incident-integration", "data-owner-operation-business"):
        assert destination in operations


def test_all_dynamic_visible_data_is_escaped() -> None:
    _, _, _, _, operations = sources()
    renderers = "".join(
        (
            function(operations, "ownerIntegrationRow", "renderOwnerIntegrationsList"),
            function(operations, "ownerIntegrationDetailMarkup", "renderOwnerIntegrationDetail"),
            function(operations, "ownerIncidentRow", "renderOwnerIncidentsHub"),
            function(operations, "renderOwnerIncidentDetail", "openOwnerIncidentDetail"),
            function(operations, "renderOwnerAuditEvents", "loadOwnerAuditHub"),
        )
    )
    unsafe = re.findall(r"\$\{(record\.business\.name|incident\.business_name|event\.label|entry\.businessName)\}", renderers)
    assert not unsafe
    assert operations.count("escapeHtml(") >= 70


def test_external_urls_are_fixed_or_protocol_validated() -> None:
    _, _, _, _, operations = sources()
    assert 'url.startsWith("https://www.instagram.com/oauth/authorize?")' in operations
    assert 'rel="noopener"' in operations
    assert "window.open" not in operations


def test_owner_gate_and_backend_contracts_are_preserved() -> None:
    _, _, owner, _, operations = sources()
    assert "if (!ownerAuthUser.is_owner)" in owner
    endpoints = set(re.findall(r'"(/api/owner/[^"`?${ ]+)', operations))
    assert endpoints <= {
        "/api/owner/businesses/",
        "/api/owner/incidents/",
        "/api/owner/queue/",
        "/api/owner/system/health",
        "/api/owner/system/maintenance",
        "/api/owner/system/maintenance/",
        "/api/owner/system/queue-status",
    }


def test_dom_ids_are_unique_and_required_contracts_exist() -> None:
    html, _, _, _, _ = sources()
    inventory = IdInventory()
    inventory.feed(html)
    assert len(inventory.ids) == len(set(inventory.ids))
    for element_id in (
        "owner-integrations-section",
        "owner-incidents-section",
        "owner-operations-section",
        "owner-audit-section",
        "owner-critical-dialog",
    ):
        assert inventory.ids.count(element_id) == 1


def test_responsive_accessibility_contracts_are_structural() -> None:
    html, css, _, _, _ = sources()
    assert '@media (max-width: 1199px)' in css
    assert '@media (max-width: 767px)' in css
    assert "grid-template-columns: minmax(0, 1fr)" in css
    assert "100dvh" in css
    assert "safe-area-inset" in css
    assert "prefers-reduced-motion" in css
    for contract in ('role="list"', 'aria-busy="true"', 'aria-current="page"', 'aria-live="polite"'):
        assert contract in html


def test_no_new_backend_or_migration_is_part_of_the_frontend_sprint() -> None:
    _, _, _, _, operations = sources()
    assert "fetch(" not in operations or "ownerHubRequest" in operations
    assert "CREATE TABLE" not in operations
    assert "ALTER TABLE" not in operations
    assert "alembic" not in operations.lower()


def test_documentation_records_limitations_and_visual_qa_debt() -> None:
    assert DOC.is_file()
    doc = DOC.read_text(encoding="utf-8")
    for topic in (
        "AuditLog",
        "candidaturas resueltas",
        "polling",
        "390 × 844",
        "validación visual autenticada",
    ):
        assert topic.lower() in doc.lower()
