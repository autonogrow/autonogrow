from __future__ import annotations

from html.parser import HTMLParser
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
OWNER_HTML = ROOT / "autonogrow-owner" / "index.html"
OWNER_CSS = ROOT / "autonogrow-owner" / "styles.css"
OWNER_JS = ROOT / "autonogrow-owner" / "owner.js"


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
        OWNER_HTML.read_text(encoding="utf-8"),
        OWNER_CSS.read_text(encoding="utf-8"),
        OWNER_JS.read_text(encoding="utf-8"),
    )


def dashboard_html(html: str) -> str:
    return html.split('id="owner-overview"', 1)[1].split('id="businesses-section"', 1)[0]


def dashboard_javascript(js: str) -> str:
    return js.split("const OWNER_DASHBOARD_HEALTH_ATTENTION", 1)[1].split(
        "function slugify", 1
    )[0]


def test_dashboard_architecture_prioritizes_operational_blocks() -> None:
    html, _, _ = read_sources()
    overview = dashboard_html(html)
    for element_id in (
        "owner-dashboard-metrics",
        "owner-dashboard-decisions",
        "owner-dashboard-integrations",
        "owner-dashboard-incidents",
        "owner-dashboard-operations",
        "owner-dashboard-businesses",
        "owner-dashboard-platform",
        "owner-dashboard-activity",
    ):
        assert html.count(f'id="{element_id}"') == 1
    assert overview.index("owner-dashboard-decisions") < overview.index(
        "owner-dashboard-integrations"
    )
    assert overview.index("owner-dashboard-integrations") < overview.index(
        "owner-dashboard-incidents"
    )


def test_dashboard_has_six_real_actionable_indicators_and_no_fictional_metrics() -> None:
    html, _, js = read_sources()
    overview = dashboard_html(html)
    assert overview.count('class="owner-dashboard-metric ag-card"') == 6
    for metric_id in (
        "owner-metric-active",
        "owner-metric-pending-businesses",
        "owner-metric-decisions",
        "owner-metric-integrations",
        "owner-metric-incidents",
        "owner-metric-messages",
    ):
        assert f'id="{metric_id}"' in overview
    for forbidden in ("MRR", "ARR", "Churn", "Ingresos", "Conversión", "99,9", "ROI"):
        assert forbidden not in overview
        assert forbidden not in dashboard_javascript(js)


def test_pending_decisions_are_review_links_not_approval_actions() -> None:
    html, _, js = read_sources()
    overview = dashboard_html(html)
    dashboard = dashboard_javascript(js)
    assert "Necesita tu decisión" in overview
    assert "Cuenta pendiente de revisión" in dashboard
    assert "Revisar solicitud" in dashboard
    assert 'data-owner-navigate="businesses"' in dashboard
    assert "candidate-approve" not in overview
    assert "whatsapp-approve" not in overview
    assert "data-incident-action" not in overview


def test_integration_attention_preserves_independent_state_layers() -> None:
    _, _, js = read_sources()
    dashboard = dashboard_javascript(js)
    for contract in (
        "OWNER_DASHBOARD_HEALTH_ATTENTION",
        "ownerApprovalLabel",
        "integrated_delivery_enabled",
        "automation_enabled",
        "last_health_check_at",
        "reconnection_required",
        "Aprobación",
        "Envío",
        "Automatización",
    ):
        assert contract in dashboard


def test_incidents_and_message_operations_use_safe_operational_summaries() -> None:
    _, _, js = read_sources()
    dashboard = dashboard_javascript(js)
    assert "safeIncidentTitle" in dashboard
    assert "incident.business_name" in dashboard
    assert "incident.severity" in dashboard
    assert "incident.last_occurred_at" in dashboard
    assert "Reintentos programados" in dashboard
    assert "Casos que necesitan revisión" in dashboard
    assert "worker_active" in dashboard
    for technical_render in (
        "incident.incident_id",
        "incident.provider_error_code",
        "job.id",
        "attempt_count",
        "current_job_id",
        "diagnostic_metadata",
    ):
        assert technical_render not in dashboard


def test_business_attention_and_activity_derive_from_existing_records() -> None:
    _, _, js = read_sources()
    dashboard = dashboard_javascript(js)
    for source in (
        "business.status",
        "business.health?.has_basic_info",
        "business.health?.has_active_services",
        "business.health?.has_schedule",
        "business.created_at",
        "control.approved_at",
        "control.suspended_at",
        "control.revoked_at",
        "incident.resolved_at",
    ):
        assert source in dashboard
    assert ".slice(0, 8)" in dashboard


def test_empty_loading_partial_and_error_states_are_distinct() -> None:
    html, css, js = read_sources()
    dashboard = dashboard_javascript(js)
    assert dashboard_html(html).count('aria-busy="true"') >= 8
    for message in (
        "No hay decisiones pendientes",
        "No hay integraciones que requieran atención.",
        "No hay incidencias abiertas",
        "El procesamiento no presenta problemas detectados.",
        "Fuente no disponible",
        "Comprobación incompleta",
        "se conservan los últimos datos válidos",
    ):
        assert message in dashboard
    for selector in (
        ".owner-dashboard-loading",
        ".owner-dashboard-empty",
        ".owner-dashboard-error",
        ".owner-dashboard-partial",
    ):
        assert selector in css


def test_sources_fail_and_retry_independently() -> None:
    html, _, js = read_sources()
    overview = dashboard_html(html)
    dashboard = dashboard_javascript(js)
    for source in ("businesses", "channels", "incidents", "queue", "platform"):
        assert f'"{source}"' in js.split("const OWNER_DASHBOARD_SOURCE_NAMES", 1)[1].split(
            ";", 1
        )[0]
        assert f"ownerDashboardSourceVersions.{source}" in dashboard
    for retry in ("channels", "incidents", "queue", "businesses", "platform"):
        assert f'data-owner-retry="{retry}"' in overview
    assert "Promise.allSettled" in dashboard
    assert "retryOwnerDashboardSource" in dashboard
    assert "safeOwnerDashboardError" in dashboard


def test_dashboard_refresh_is_single_flight_without_new_polling() -> None:
    _, _, js = read_sources()
    dashboard = dashboard_javascript(js)
    assert "ownerDashboardLoadInFlight" in dashboard
    assert "ownerDashboardRerunRequested" in dashboard
    assert "ownerDashboardSourceVersions" in dashboard
    assert "version !== ownerDashboardSourceVersions" in dashboard
    assert "setInterval(" not in dashboard
    assert "setTimeout(" not in dashboard


def test_context_navigation_reuses_existing_owner_sections() -> None:
    html, _, js = read_sources()
    for tab in ("overview", "businesses", "new-business", "incidents", "queues", "operations"):
        assert f'data-tab="{tab}"' in html
        assert f'data-panel="{tab}"' in html
    assert "function navigateOwnerContext" in js
    assert "setActiveTab(target);" in js
    assert 'data-business-card-id="${escapeHtml(business.id)}"' in js
    assert '"[data-owner-integration-id]"' in js
    assert '"[data-owner-channel-control-id]"' in js


def test_owner_permissions_and_legacy_sections_remain() -> None:
    html, _, js = read_sources()
    assert "if (!ownerAuthUser.is_owner)" in js
    assert "No tienes permiso para acceder al panel interno." in js
    for element_id in (
        "business-list",
        "onboarding-wizard",
        "incident-list",
        "queue-jobs",
        "operations-details",
    ):
        assert html.count(f'id="{element_id}"') == 1
    for legacy_metric in (
        "total-businesses",
        "active-businesses",
        "pending-bookings",
        "pending-messages",
        "pending-reviews",
        "open-incidents",
    ):
        assert html.count(f'id="{legacy_metric}"') == 1


def test_dashboard_uses_only_existing_get_endpoints() -> None:
    _, _, js = read_sources()
    dashboard = dashboard_javascript(js)
    for endpoint in (
        "/api/owner/businesses",
        "/channel-controls",
        "/integrations/whatsapp/embedded-signup/candidates",
        "/channels/health",
        "/integrations/instagram/oauth/candidates",
        "/api/owner/incidents?limit=30",
        "/api/owner/system/queue-status",
        "/api/owner/system/health",
    ):
        assert endpoint in dashboard
    assert "/api/owner/dashboard" not in js
    assert 'method: "POST"' not in dashboard
    assert 'method: "PATCH"' not in dashboard
    assert 'method: "DELETE"' not in dashboard


def test_dashboard_escapes_external_text_and_exposes_no_sensitive_detail() -> None:
    html, _, js = read_sources()
    overview = dashboard_html(html)
    dashboard = dashboard_javascript(js)
    for escaped in (
        "escapeHtml(item.business.name)",
        "escapeHtml(business.name)",
        "escapeHtml(safeIncidentTitle(incident))",
        "escapeHtml(incident.business_name",
        "escapeHtml(item.text)",
        "escapeHtml(item.at)",
    ):
        assert escaped in dashboard
    for forbidden in (
        "access token",
        "refresh token",
        "App Secret",
        "verify token",
        "WABA ID",
        "phone_number_id",
        "account ID",
        "scopes",
        "payload",
        "metadata JSON",
        "traceback",
        "SQL",
    ):
        assert forbidden.lower() not in overview.lower()
        assert forbidden.lower() not in dashboard.lower()


def test_dashboard_dom_accessibility_and_responsive_contracts() -> None:
    html, css, js = read_sources()
    inventory = IdInventory()
    inventory.feed(html)
    duplicates = sorted({item for item in inventory.ids if inventory.ids.count(item) > 1})
    assert duplicates == []
    assert 'href="#owner-main-content"' in html
    assert 'id="owner-page-title"' in html
    assert 'aria-current="page"' in html
    assert 'role="status"' in html
    assert 'tabindex="-1"' in html
    assert html.count("<h1") == 2  # gate and authenticated app are mutually exclusive
    for selector in (
        ".owner-dashboard-metrics",
        ".owner-dashboard-layout",
        ".owner-dashboard-block--priority",
        ".owner-dashboard-item__layers",
        ".owner-dashboard-activity-list",
    ):
        assert selector in css
    assert "@media (min-width: 640px) and (max-width: 1199px)" in css
    assert "@media (max-width: 767px)" in css
    assert "@media (max-width: 399px)" in css
    assert "prefers-reduced-motion: reduce" in js
