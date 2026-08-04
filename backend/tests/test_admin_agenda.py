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


def test_agenda_has_three_accessible_views_and_today_is_default() -> None:
    html, _, js = read_sources()
    assert 'role="tablist"' in html
    for view in ("today", "pending", "week"):
        assert html.count(f'data-booking-view="{view}"') == 1
    assert 'data-booking-view="today">Hoy</button>' in html
    assert 'aria-selected="true" data-booking-view="today"' in html
    assert 'let currentBookingView = "today";' in js
    assert 'let agendaSelectedDate = "";' in js


def test_agenda_preserves_dom_contracts_without_duplicate_ids() -> None:
    html, _, _ = read_sources()
    inventory = IdInventory()
    inventory.feed(html)
    duplicates = sorted({item for item in inventory.ids if inventory.ids.count(item) > 1})
    assert duplicates == []
    for element_id in (
        "bookings-list",
        "booking-staff-filter",
        "reschedule-modal",
        "reschedule-modal-title",
        "reschedule-modal-content",
    ):
        assert html.count(f'id="{element_id}"') == 1
    assert 'data-internal-notes="${bookingId}"' in ADMIN_JS.read_text(encoding="utf-8")


def test_agenda_translates_all_existing_booking_states() -> None:
    _, _, js = read_sources()
    block = function_block(js, "function getStatusLabel", "function formatDateTime")
    for internal, label in (
        ("requested", "Solicitud nueva"),
        ("pending", "Por confirmar"),
        ("confirmed", "Confirmada"),
        ("completed", "Completada"),
        ("cancelled", "Cancelada"),
        ("rejected", "Rechazada"),
        ("no_show", "No presentado"),
    ):
        assert f'{internal}: "{label}"' in block


def test_agenda_orders_chronologically_and_filters_locally() -> None:
    _, _, js = read_sources()
    ordering = function_block(js, "function getBookingSortValue", "function syncAgendaServiceFilter")
    assert "getBookingSortValue(first).localeCompare(getBookingSortValue(second))" in ordering
    assert "staff_business_user_id" in ordering
    assert "selectedBookingStatusFilter" in ordering
    assert "selectedBookingServiceFilter" in ordering
    assert "bookingCustomerSearch" in ordering
    assert "fetch(" not in ordering
    assert "function resetAgendaFilters" in js


def test_agenda_supports_day_and_week_navigation_and_empty_states() -> None:
    _, _, js = read_sources()
    assert "function getAgendaWeekDates" in js
    assert "addDaysToDateKey(agendaSelectedDate" in js
    assert "function navigateAgendaDate" in js
    assert 'availabilitySettings?.timezone || currentBusiness?.timezone || "Europe/Madrid"' in js
    assert "function parseBusinessCivilDateTime" in js
    for message in (
        "No tienes citas para este día.",
        "Todo está revisado",
        "No hay solicitudes esperando confirmación.",
        "No hay citas con estos filtros.",
        "No pudimos cargar la agenda.",
    ):
        assert message in js


def test_booking_actions_follow_real_state_matrix_and_block_double_submit() -> None:
    _, _, js = read_sources()
    block = function_block(js, "function renderBookingActions", "async function saveInternalNotes")
    assert '["requested", "pending"].includes(booking.status)' in block
    assert 'booking.status === "confirmed"' in block
    for status in ("confirmed", "rejected", "completed", "cancelled", "no_show"):
        assert f'"{status}"' in block
    assert "bookingMutationIds.has(bookingId)" in js
    assert "setBookingMutationBusy(bookingId, true)" in js
    assert "setBookingMutationBusy(bookingId, false)" in js


def test_dynamic_booking_content_is_escaped() -> None:
    _, _, js = read_sources()
    block = function_block(js, "function renderBookingCard", "function renderBookings")
    for value in (
        "booking.customer_name",
        "booking.service_name",
        "booking.staff_display_name",
        "booking.customer_phone",
        "booking.internal_notes",
    ):
        assert f"escapeHtml({value}" in block


def test_reschedule_reuses_real_slots_and_handles_conflict() -> None:
    _, _, js = read_sources()
    block = function_block(js, "function openRescheduleModal", "async function updateBookingStatus")
    assert "/available-slots?${params.toString()}" in block
    assert 'exclude_booking_id: booking.id' in block
    assert 'params.set("staff_business_user_id"' in block
    assert 'method: "PATCH"' in block
    assert "/api/bookings/${booking.id}/reschedule" in block
    assert "response.status === 409" in block
    assert "Ese hueco acaba de dejar de estar disponible" in block
    assert "rescheduleSlotsLoadVersion" in block


def test_reschedule_dialog_has_focus_management_and_safe_mobile_layout() -> None:
    html, css, js = read_sources()
    modal = html.split('id="reschedule-modal"', 1)[1].split('id="staff-removal-modal"', 1)[0]
    assert 'role="dialog"' in modal
    assert 'aria-modal="true"' in modal
    assert 'aria-describedby="reschedule-modal-description"' in modal
    assert 'aria-hidden="true"' in modal
    for marker in (
        "handleRescheduleModalKeydown",
        'event.key === "Escape"',
        'event.key !== "Tab"',
        "rescheduleReturnFocus",
        'document.body.classList.add("modal-scroll-locked")',
    ):
        assert marker in js
    assert "#reschedule-modal { align-items: flex-end" in css
    assert "env(safe-area-inset-bottom)" in css


def test_agenda_keeps_single_polling_pipeline_and_dashboard_refresh() -> None:
    _, _, js = read_sources()
    assert 'adminPollingTasks.set("operations"' in js
    assert "loadBookings({ background: true })" in js
    assert "bookingsLoadVersion" in js
    assert "renderStats(allBookings);" in js
    assert "renderDashboard();" in js
    assert "setInterval(" not in function_block(
        js,
        "function getAgendaWeekStart",
        "function renderReviewRequest",
    )
