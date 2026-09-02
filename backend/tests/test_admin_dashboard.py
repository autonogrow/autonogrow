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


def dashboard_javascript(js: str) -> str:
    start = js.index("function setDashboardDataState")
    end = js.index("function calculateGrowthTasks")
    return js[start:end]


def test_dashboard_has_required_operational_blocks_and_four_metrics() -> None:
    html, _, _ = read_sources()
    for element_id in (
        "dashboard-title",
        "dashboard-date",
        "dashboard-stat-today",
        "dashboard-stat-pending",
        "dashboard-stat-messages",
        "stat-business-status",
        "dashboard-today-bookings",
        "dashboard-attention-list",
        "dashboard-next-booking",
        "dashboard-message-summary",
        "dashboard-weekly-activity",
    ):
        assert html.count(f'id="{element_id}"') == 1
    metrics = html.split('<section class="dashboard-metrics"', 1)[1].split("</section>", 1)[0]
    assert metrics.count('class="dashboard-metric ag-card"') == 4


def test_legacy_contracts_and_ids_remain_unique() -> None:
    html, _, _ = read_sources()
    inventory = IdInventory()
    inventory.feed(html)
    duplicates = sorted({element_id for element_id in inventory.ids if inventory.ids.count(element_id) > 1})
    assert duplicates == []
    assert html.count("<h1") == 1
    for element_id in (
        "admin-app",
        "business-name",
        "bookings-list",
        "conversation-list",
        "reschedule-modal",
        "stat-total",
        "stat-requested",
        "stat-confirmed",
        "stat-completed",
    ):
        assert html.count(f'id="{element_id}"') == 1
    for section in ("summary", "bookings", "conversations", "growth", "services", "channels"):
        assert f'data-section="{section}"' in html
        assert f'data-admin-section="{section}"' in html


def test_dashboard_navigation_reuses_bookings_and_conversations() -> None:
    html, _, js = read_sources()
    assert 'data-dashboard-section="bookings" data-dashboard-booking-view="today"' in html
    assert 'data-dashboard-section="conversations"' in html
    assert "function navigateFromDashboard" in js
    assert "showAdminSection(section);" in js
    assert 'currentBookingView = bookingView;' in js
    assert "setupDashboardInteractions();" in js


def test_dashboard_translates_booking_states_and_defines_empty_states() -> None:
    _, _, js = read_sources()
    for internal, label in (
        ('requested: "Por confirmar"', "Por confirmar"),
        ('pending: "Pendiente"', "Pendiente"),
        ('confirmed: "Confirmada"', "Confirmada"),
        ('completed: "Completada"', "Completada"),
        ('cancelled: "Cancelada"', "Cancelada"),
        ('rejected: "Rechazada"', "Rechazada"),
    ):
        assert internal in js, label
    for message in (
        "No tienes citas para hoy",
        "Todo está al día",
        "No hay una próxima cita",
        "No hay mensajes pendientes",
        "Aún no hay actividad reciente",
    ):
        assert message in js


def test_dashboard_has_partial_errors_retries_and_accessible_loading() -> None:
    html, _, js = read_sources()
    assert 'id="dashboard-live-region"' in html
    assert 'aria-live="polite"' in html
    assert html.count('aria-busy="true"') >= 6
    assert 'class="ag-visually-hidden">Cargando' in html
    assert "function renderDashboardBlockError" in js
    assert 'announce ? "alert" : "group"' in js
    for source in ("bookings", "conversations", "services", "availability", "channels"):
        assert f'{source}: () => load' in js
    assert 'data-dashboard-retry="${escapeHtml(retrySource)}"' in js


def test_external_dashboard_content_is_escaped() -> None:
    _, _, js = read_sources()
    dashboard = dashboard_javascript(js)
    for escaped_expression in (
        "escapeHtml(booking.customer_name",
        "escapeHtml(booking.service_name",
        "escapeHtml(booking.staff_display_name",
        "escapeHtml(conversationDisplayName(conversation))",
        "escapeHtml(truncateDashboardText(conversation.last_message_text",
    ):
        assert escaped_expression in dashboard
    assert "insertAdjacentHTML" not in dashboard
    assert "outerHTML" not in dashboard


def test_dashboard_reuses_existing_loaders_without_fetching() -> None:
    _, _, js = read_sources()
    dashboard = dashboard_javascript(js)
    assert "fetch(" not in dashboard
    assert "API_BASE_URL" not in dashboard
    for render_call in (
        "renderDashboardHeader();",
        "renderDashboardMetrics();",
        "renderTodayBookings();",
        "renderAttentionItems();",
        "renderNextBooking();",
        "renderMessageSummary();",
        "renderRecentActivity();",
    ):
        assert render_call in dashboard


def test_dashboard_css_covers_desktop_tablet_and_mobile() -> None:
    _, css, _ = read_sources()
    for selector in (
        ".dashboard-hero",
        ".dashboard-metrics",
        ".dashboard-grid",
        ".dashboard-panel--agenda",
        ".dashboard-attention-item",
        ".dashboard-booking-row",
        ".dashboard-message-row",
        ".dashboard-activity-list",
        ".dashboard-block-state--error",
    ):
        assert selector in css
    assert "@media (min-width: 640px) and (max-width: 1023px)" in css
    assert "@media (max-width: 639px)" in css
    mobile = css.split("@media (max-width: 639px)", 1)[1]
    for area in ('"attention"', '"next"', '"agenda"', '"messages"', '"activity"'):
        assert area in mobile


def test_dashboard_renders_derived_booking_close_tasks_with_closure_actions() -> None:
    _, css, js = read_sources()
    dashboard = dashboard_javascript(js)
    assert "Citas pendientes de cerrar" in dashboard
    assert "bookingCloseTasks.map" in dashboard
    assert 'data-booking-action="completed"' in dashboard
    assert 'data-booking-action="no_show"' in dashboard
    assert "Marcar completada" in dashboard
    assert "No se presentó" in dashboard
    assert "booking.customer_name" in dashboard
    assert "booking.service_name" in dashboard
    assert "booking.staff_display_name" in dashboard
    assert "formatBookingSlot(booking)" in dashboard
    assert ".dashboard-close-task__actions" in css
    assert "@media (max-width: 1023px)" in css
    assert "grid-column: 1 / -1" in css
    assert "overflow-wrap: anywhere" in css


def test_dashboard_growth_empty_copy_is_not_an_operational_all_clear() -> None:
    _, _, js = read_sources()
    dashboard = dashboard_javascript(js)

    assert "No hay oportunidades comerciales pendientes" in dashboard
    assert "No hemos detectado oportunidades Growth" in dashboard
    assert "formatGrowthDays(recurrence)" in dashboard


def test_dashboard_renders_deduplicated_growth_follow_ups_with_useful_access() -> None:
    _, _, js = read_sources()
    dashboard = dashboard_javascript(js)

    assert "function getDashboardGrowthFollowUps" in dashboard
    assert "const byCustomer = new Map()" in dashboard
    assert "opportunity.customer.id" in dashboard
    assert 'opportunity.status === "pending"' in dashboard
    assert "Oportunidades para hoy" in dashboard
    assert "opportunity.reason_text" in dashboard
    assert "formatDateTime(opportunity.due_at)" in dashboard
    assert "data-dashboard-opportunity-id" in dashboard
    assert "opportunity.channel?.conversation_id" in dashboard
    assert "dashboardConversations.find" in dashboard
    assert "conversation.customer_id === customerId" in dashboard
    assert "focusGrowthOpportunity(opportunityId)" in dashboard
    mutation = js.split("async function updateCustomerOpportunity", 1)[1].split(
        "function renderGrowth", 1
    )[0]
    assert "customerOpportunities = customerOpportunities.filter" in mutation
    assert "renderDashboard()" in mutation


def test_close_tasks_load_independently_from_bounded_agenda_and_refresh_after_closure() -> None:
    _, _, js = read_sources()
    loader = js.split("async function loadBookingCloseTasks", 1)[1].split(
        "async function loadReviewRequests", 1
    )[0]
    assert "/booking-close-tasks" in loader
    assert "from:" not in loader
    assert "to:" not in loader
    assert 'setDashboardDataState("closeTasks", "ready")' in loader
    status_update = js.split("async function updateBookingStatus", 1)[1].split(
        "function getStatusClass", 1
    )[0]
    assert 'bookingCloseTasks.find((item) => item.id === bookingId)' in status_update
    assert "bookingCloseTasks = bookingCloseTasks.filter" in status_update
    assert '["completed", "no_show", "cancelled", "rejected"]' in status_update
    assert "loadBookingCloseTasks({ background: true })" in js
