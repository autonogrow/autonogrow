from __future__ import annotations

from html.parser import HTMLParser
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
ADMIN_HTML = ROOT / "autonogrow-admin" / "index.html"
ADMIN_CSS = ROOT / "autonogrow-admin" / "styles.css"
ADMIN_JS = ROOT / "autonogrow-admin" / "admin.js"
ADMIN_ROUTER = ROOT / "backend" / "app" / "routers" / "admin.py"
REVIEW_SERVICE = ROOT / "backend" / "app" / "services" / "review_request_service.py"


class IdInventory(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.ids: list[str] = []

    def handle_starttag(self, _tag: str, attrs: list[tuple[str, str | None]]) -> None:
        element_id = dict(attrs).get("id")
        if element_id:
            self.ids.append(element_id)


def sources() -> tuple[str, str, str]:
    return (
        ADMIN_HTML.read_text(encoding="utf-8"),
        ADMIN_CSS.read_text(encoding="utf-8"),
        ADMIN_JS.read_text(encoding="utf-8"),
    )


def function_block(js: str, start: str, end: str) -> str:
    return js.split(start, 1)[1].split(end, 1)[0]


def test_growth_has_three_categories_and_preserves_legacy_contracts() -> None:
    html, _, js = sources()
    for section in ("growth", "reviews", "growth-opportunities"):
        assert html.count(f'data-admin-section="{section}"') == 1
        assert f'{{ id: "{section}"' in js
    for element_id in (
        "growth-progress-count",
        "growth-points",
        "growth-progress-percent",
        "growth-progress-bar",
        "growth-day-complete",
        "growth-tasks-list",
        "review-requests-pending-list",
        "review-requests-history-list",
    ):
        assert html.count(f'id="{element_id}"') == 1
    inventory = IdInventory()
    inventory.feed(html)
    assert sorted({item for item in inventory.ids if inventory.ids.count(item) > 1}) == []


def test_summary_uses_only_real_operational_counts() -> None:
    html, _, js = sources()
    for element_id in (
        "growth-metric-candidates",
        "growth-metric-prepared",
        "growth-metric-sent",
        "growth-metric-failed",
        "growth-metric-opportunities",
    ):
        assert html.count(f'id="{element_id}"') == 1
    render = function_block(js, "function renderGrowthOverview", "function renderGrowthOpportunities")
    for source in ("getReviewCandidates()", "reviewRequestsByBooking.values()", "getFailedReviewMessages()", "calculateGrowthTasks"):
        assert source in js
    for forbidden in ("conversion", "revenue", "roi", "rating", "reviews_received", "localStorage"):
        assert forbidden not in render.lower()
    assert "Marcadas como enviadas" in html
    assert "reseña publicada" in html


def test_review_candidates_are_completed_bookings_without_prior_request() -> None:
    _, _, js = sources()
    block = function_block(js, "function getReviewCandidates", "function getReviewOutboxMessage")
    assert 'booking.status === "completed"' in block
    assert "!reviewRequestsByBooking.has(booking.id)" in block
    candidate = function_block(js, "function renderReviewCandidateCard", "function reviewDeliveryState")
    for label in ("Cliente sin nombre", "Servicio sin indicar", "Fecha de la cita", "Canal disponible"):
        assert label in candidate
    assert "Cita #" not in candidate
    assert "customer_phone" not in candidate


def test_review_creation_reuses_tenant_scoped_idempotent_backend_flow() -> None:
    _, _, js = sources()
    router = ADMIN_ROUTER.read_text(encoding="utf-8")
    service = REVIEW_SERVICE.read_text(encoding="utf-8")
    creation = function_block(js, "async function createReviewRequest", "async function openReviewWhatsApp")
    assert "/api/admin/businesses/${getBusinessSlug()}/bookings/${bookingId}/review-request" in creation
    assert 'method: "POST"' in creation
    assert "reviewMutationKeys.has(mutationKey)" in creation
    assert "reviewRequestsByBooking.has(bookingId)" in creation
    assert 'booking.status !== "completed"' in creation
    assert "get_or_create_review_request" in router
    assert "Booking.business_id == business.id" in router
    assert "ReviewRequest.booking_id == booking.id" in service
    assert "UniqueConstraint" not in creation


def test_review_delivery_is_explicitly_assisted_not_integrated() -> None:
    html, _, js = sources()
    creation = function_block(js, "async function createReviewRequest", "async function copyReviewMessage")
    assert "WhatsApp asistido" in creation
    assert "la enviarás tú" in creation
    assert "AutonoGrow no la marcará como enviada" in creation
    assert "openBlankWhatsAppWindow" in creation
    assert "openPreparedWhatsAppMessage" in creation
    assert "integrated" not in creation.lower()
    assert "credit" not in creation.lower()
    assert "no envía automáticamente estas solicitudes ni consume créditos" in html


def test_only_existing_review_and_outbox_states_are_mapped() -> None:
    _, _, js = sources()
    request_states = function_block(js, "function renderReviewRequests", "function renderReviewCandidateCard")
    delivery = function_block(js, "function reviewDeliveryState", "function renderReviewSummaryCard")
    for state in ("pending", "copied", "sent", "skipped"):
        assert state in request_states
    for state in ("failed", "opened"):
        assert state in delivery
    assert "Entregado" not in delivery
    assert "Reseña recibida" not in delivery
    assert "no significa que la reseña se haya publicado" in delivery


def test_review_link_has_one_safe_source_of_truth() -> None:
    _, _, js = sources()
    safe_link = function_block(js, "function getSafeReviewUrl", "function getReviewCandidates")
    assert "currentBusiness?.reviews_url" in safe_link
    assert "isSafePublicUrl(value)" in safe_link
    render = function_block(js, "function renderReviewRequests", "function renderReviewCandidateCard")
    assert 'data-growth-action="configuration-reviews"' in render
    assert 'rel="noopener noreferrer"' in render
    assert "Enlace no válido" in render
    navigation = function_block(js, "function navigateToGrowthAction", "function setupGrowthHub")
    assert 'showAdminSection("business")' in navigation
    assert 'getElementById("business-setting-reviews-url")?.focus()' in navigation


def test_review_failures_are_safe_and_no_fake_retry_is_offered() -> None:
    _, _, js = sources()
    delivery = function_block(js, "function reviewDeliveryState", "function renderReviewSummaryCard")
    card = function_block(js, "function renderReviewSummaryCard", "function getAgendaWeekStart")
    actions = function_block(js, "async function createReviewRequest", "function formatBookingSlot")
    assert "no dispone de un reintento automático seguro" in delivery
    assert "data-review-retry" not in card
    for forbidden in ("traceback", "payload", "token", "job_id", "exception"):
        assert forbidden not in actions.lower()
    assert "result?.detail" not in actions


def test_growth_opportunities_are_real_and_navigate_to_exact_context() -> None:
    _, _, js = sources()
    tasks = function_block(js, "function calculateGrowthTasks", "function getSafeReviewUrl")
    for fact in (
        "pendingBookings",
        "pendingConversations",
        "adminServices.some",
        "dashboardHasConfiguredAvailability",
        "currentBusiness?.active",
        "adminGallery.length",
        "reconnection_required",
    ):
        assert fact in tasks
    for forbidden in ("reels", "anuncios", "sorteo", "promoción", "baja tus precios"):
        assert forbidden not in tasks.lower()
    navigation = function_block(js, "function navigateToGrowthAction", "function setupGrowthHub")
    for section in ("bookings", "services", "schedule", "public-page", "conversations", "messages"):
        assert f'"{section}"' in navigation
    assert 'showAdminSection(`channel-${button.dataset.channel}`)' in navigation


def test_partial_errors_and_background_refresh_preserve_loaded_data() -> None:
    _, _, js = sources()
    reviews = function_block(js, "async function loadReviewRequests", "function conversationErrorMessage")
    outbox = function_block(js, "async function loadMessageOutbox", "function renderMessageOutboxMetrics")
    assert "reviewRequestsLoadVersion" in reviews
    assert "requestVersion !== reviewRequestsLoadVersion" in reviews
    assert "messageOutboxLoadVersion" in outbox
    assert "requestVersion !== messageOutboxLoadVersion" in outbox
    assert 'growthLoadState.reviews = "error"' in reviews
    assert 'growthLoadState.outbox = "error"' in outbox
    assert "reviewRequestsByBooking = new Map" in reviews
    assert "messageOutbox = nextMessages" in outbox


def test_polling_is_reused_and_mutations_are_guarded() -> None:
    _, _, js = sources()
    polling = function_block(js, "function ensureAdminPollingTasks", "function updateAdminSyncIndicator")
    assert 'adminPollingTasks.set("operations"' in polling
    assert "loadReviewRequests({ background: true })" in polling
    assert "loadMessageOutbox({ background: true })" in polling
    assert "setInterval(" not in polling
    actions = function_block(js, "async function createReviewRequest", "function formatBookingSlot")
    assert actions.count("reviewMutationKeys.has") >= 4
    assert "requestAdminRefresh" in actions


def test_dashboard_agenda_and_outbox_share_the_same_review_state() -> None:
    _, _, js = sources()
    dashboard = function_block(js, "function getDashboardAttentionItems", "function renderAttentionItems")
    assert "getReviewCandidates()" in dashboard
    assert "getFailedReviewMessages()" in dashboard
    assert 'section: "reviews"' in dashboard
    agenda = function_block(js, "function renderReviewRequest", "function showGrowthReviewFeedback")
    assert 'data-review-create="${booking.id}"' in agenda
    assert "Gestionar en Crecimiento" in agenda
    assert "Cita #" not in agenda
    outbox = function_block(js, "function renderMessageCards", "function getMessageTypeLabel")
    assert 'message.message_type !== "booking_requested"' in js
    assert "Cita #" not in outbox
    assert "maskedOutboxPhone(message.customer_phone)" in outbox
    assert "WhatsApp terminado en" in js
    assert 'message.delivery_mode === "assisted"' in outbox
    assert "isSafeWhatsAppUrl(message.whatsapp_url)" in outbox
    assert "Abrir en WhatsApp" in outbox


def test_opportunity_actions_expose_integrated_assisted_and_unavailable_ux() -> None:
    html, _, js = sources()
    modal = function_block(js, "function openGrowthActionModal", "function closeGrowthActionModal")
    assisted = function_block(js, "async function openGrowthOpportunityWhatsApp", "async function copyGrowthOpportunityText")
    assert 'id="growth-action-send"' in html
    assert 'id="growth-action-whatsapp"' in html
    assert "Enviar por WhatsApp" in html
    assert "Abrir en WhatsApp" in html
    for mode in ("integrated", "assisted", "unavailable"):
        assert mode in js
    assert "Este cliente no tiene un teléfono válido" in js
    assert "AutonoGrow no lo marcará como enviado" in modal
    assert "opportunityAssistedOpening" in assisted
    assert "isSafeWhatsAppUrl(body.whatsapp_url)" in assisted
    assert 'response.status === 429' in assisted
    assert 'response.headers.get("Retry-After")' in js
    assert "whatsappWindow.location.href = body.whatsapp_url" in assisted


def test_accessibility_and_responsive_structure_are_explicit() -> None:
    html, css, js = sources()
    assert html.count("<h1") == 1
    assert html.count("data-growth-navigation") == 3
    assert 'aria-label="Crecimiento"' in js
    assert 'aria-current="page"' in js
    assert 'role="status" aria-live="polite"' in html
    assert 'aria-busy="true"' in html
    sprint_css = css.split("/* Sprint 5B.6", 1)[1]
    assert "@media (max-width: 1023px)" in sprint_css
    assert "@media (max-width: 639px)" in sprint_css
    assert "env(safe-area-inset-bottom)" in sprint_css
    assert "var(--ag-touch-target)" in sprint_css
    assert "@media (prefers-reduced-motion: reduce)" in sprint_css
