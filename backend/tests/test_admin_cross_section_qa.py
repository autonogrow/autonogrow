from __future__ import annotations

import re
from html.parser import HTMLParser
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
ADMIN_HTML = ROOT / "autonogrow-admin" / "index.html"
ADMIN_CSS = ROOT / "autonogrow-admin" / "styles.css"
ADMIN_JS = ROOT / "autonogrow-admin" / "admin.js"
SHARED_SHELL_JS = ROOT / "autonogrow-shared" / "app-shell.js"
SHARED_RESPONSIVE_CSS = ROOT / "autonogrow-shared" / "responsive.css"
ADMIN_ROUTER = ROOT / "backend" / "app" / "routers" / "admin.py"
CONVERSATION_SERVICE = ROOT / "backend" / "app" / "services" / "conversation_service.py"


class HtmlInventory(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.ids: list[str] = []
        self.tags: list[tuple[str, dict[str, str | None]]] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        values = dict(attrs)
        self.tags.append((tag, values))
        if values.get("id"):
            self.ids.append(str(values["id"]))

    def attributes_for_id(self, element_id: str) -> dict[str, str | None]:
        return next(attrs for _, attrs in self.tags if attrs.get("id") == element_id)


def sources() -> tuple[str, str, str, str]:
    return (
        ADMIN_HTML.read_text(encoding="utf-8"),
        ADMIN_CSS.read_text(encoding="utf-8"),
        ADMIN_JS.read_text(encoding="utf-8"),
        SHARED_SHELL_JS.read_text(encoding="utf-8"),
    )


def function_block(js: str, start: str, end: str) -> str:
    return js.split(start, 1)[1].split(end, 1)[0]


def test_admin_document_keeps_unique_landmarks_and_all_business_sections() -> None:
    html, _, _, _ = sources()
    inventory = HtmlInventory()
    inventory.feed(html)
    assert sorted({item for item in inventory.ids if inventory.ids.count(item) > 1}) == []
    assert sum(1 for tag, _ in inventory.tags if tag == "h1") == 1
    for section in (
        "summary",
        "growth",
        "growth-opportunities",
        "reviews",
        "bookings",
        "conversations",
        "configuration",
        "business",
        "services",
        "staff",
        "schedule",
        "public-page",
        "channels",
        "channel-instagram",
        "channel-whatsapp",
        "messages",
        "instagram-content",
    ):
        assert html.count(f'data-admin-section="{section}"') == 1


def test_main_admin_section_visibility_depends_only_on_active_state() -> None:
    html, css, js, _ = sources()
    inventory = HtmlInventory()
    inventory.feed(html)
    sections = [attrs for _, attrs in inventory.tags if attrs.get("data-admin-section")]
    tabs = [
        attrs for _, attrs in inventory.tags if "admin-tab" in str(attrs.get("class") or "").split()
    ]
    required_destinations = {
        "summary",
        "growth",
        "bookings",
        "conversations",
        "configuration",
        "channels",
        "instagram-content",
    }
    assert required_destinations <= {str(attrs["data-admin-section"]) for attrs in sections}
    assert required_destinations <= {str(attrs["data-section"]) for attrs in tabs}
    assert [
        attrs["data-admin-section"]
        for attrs in sections
        if "admin-section-active" in str(attrs.get("class") or "").split()
    ] == ["summary"]
    assert [
        attrs["data-section"]
        for attrs in tabs
        if "admin-tab-active" in str(attrs.get("class") or "").split()
    ] == ["summary"]

    section_classes = {
        class_name
        for _, attrs in inventory.tags
        if attrs.get("data-admin-section") is not None
        for class_name in str(attrs.get("class") or "").split()
    }
    section_classes.discard("admin-section-active")

    css_without_comments = re.sub(r"/\*.*?\*/", "", css, flags=re.DOTALL)
    display_rules = re.findall(
        r"([^{}]+)\{([^{}]*\bdisplay\s*:[^{}]+)\}",
        css_without_comments,
        flags=re.DOTALL,
    )
    unsafe_selectors: list[str] = []
    for selector_list, declarations in display_rules:
        if not re.search(r"(?:^|;)\s*display\s*:", declarations):
            continue
        for selector in selector_list.split(","):
            rightmost_compound = re.split(r"\s+|[>+~]", selector.strip())[-1]
            selector_classes = set(re.findall(r"\.([a-zA-Z0-9_-]+)", rightmost_compound))
            if not selector_classes.intersection(section_classes):
                continue
            if rightmost_compound == ".admin-section":
                assert re.search(r"(?:^|;)\s*display\s*:\s*none\s*;", declarations)
            elif "admin-section-active" not in selector_classes:
                unsafe_selectors.append(selector.strip())

    assert unsafe_selectors == []
    assert re.search(r"\.admin-section-active\s*\{\s*display\s*:\s*block\s*;", css)
    assert ".agenda-section.admin-section-active { display: grid;" in css
    assert ".conversations-section.admin-section-active { display: grid;" in css

    navigation = function_block(js, "function showAdminSection", "function setupAdminNavigation")
    assert (
        'section.classList.toggle("admin-section-active", '
        "section.dataset.adminSection === targetSection)"
    ) in navigation
    assert 'tab.classList.toggle("admin-tab-active", isActive)' in navigation
    assert 'tab.setAttribute("aria-selected", String(isActive))' in navigation


def test_primary_navigation_has_one_synchronous_current_item_and_normalizes_bad_hashes() -> None:
    html, _, js, _ = sources()
    assert html.count('aria-current="page"') >= 2  # desktop and mobile initial state
    navigation = function_block(js, "function showAdminSection", "function setupAdminNavigation")
    for mapping in (
        'CONFIGURATION_SECTIONS.has(targetSection) ? "configuration"',
        'CHANNEL_HUB_SECTIONS.has(targetSection) ? "channels"',
        'GROWTH_HUB_SECTIONS.has(targetSection) ? "growth"',
    ):
        assert mapping in navigation
    assert 'if (isActive) tab.setAttribute("aria-current", "page")' in navigation
    assert 'else tab.removeAttribute("aria-current")' in navigation
    assert "updateHash || (sectionName && !sectionExists)" in navigation
    assert 'window.history.replaceState(null, "", `#${targetSection}`)' in navigation


def test_secondary_navigation_uses_the_exact_active_context() -> None:
    _, _, js, _ = sources()
    for function_name, attribute in (
        ("configurationNavigationMarkup", "data-configuration-target"),
        ("growthNavigationMarkup", "data-growth-target"),
        ("channelHubNavigationMarkup", "data-channel-hub-target"),
    ):
        block = function_block(js, f"function {function_name}", "\nfunction ")
        assert attribute in block
        assert "category.id === activeSection ? 'aria-current=\"page\"'" in block


def test_contextual_links_reach_the_exact_existing_section_and_subview() -> None:
    html, _, js, _ = sources()
    dashboard_attention = function_block(
        js, "function getDashboardAttentionItems", "function renderAttentionItems"
    )
    for destination in (
        'section: "bookings", view: "pending"',
        'section: "conversations"',
        'section: "channels"',
        'section: "reviews"',
    ):
        assert destination in dashboard_attention
    dashboard_navigation = function_block(
        js, "function navigateFromDashboard", "async function retryDashboardSource"
    )
    assert "setBookingView(bookingView, { clearDeepLink: false })" in dashboard_navigation
    assert "showAdminSection(section)" in dashboard_navigation
    growth_navigation = function_block(
        js, "function navigateToGrowthAction", "function setupGrowthHub"
    )
    assert 'showAdminSection("business")' in growth_navigation
    assert 'getElementById("business-setting-reviews-url")?.focus()' in growth_navigation
    assert "showAdminSection(`channel-${button.dataset.channel}`)" in growth_navigation
    assert 'showAdminSection("messages")' in growth_navigation
    assert 'data-admin-action="navigate-section" data-section="reviews"' in js
    assert "function setupAdminDelegatedActions" in js
    assert 'data-channel-hub-target="messages"' in html


def test_polling_is_single_flight_backed_off_and_does_not_announce_repaints() -> None:
    html, _, js, _ = sources()
    inventory = HtmlInventory()
    inventory.feed(html)
    for element_id in ("admin-sync-status", "conversation-result-count", "bookings-list"):
        assert "aria-live" not in inventory.attributes_for_id(element_id)
    polling = function_block(js, "function ensureAdminPollingTasks", "function stopAdminPolling")
    for task in ("conversationThread", "conversationList", "operations"):
        assert f'adminPollingTasks.set("{task}"' in polling
    for guard in ("inFlight", "rerunRequested", "failures", "ADMIN_POLL_MAX_BACKOFF_MULTIPLIER"):
        assert guard in js
    assert "window.setTimeout" in polling
    assert "setInterval(" not in polling
    assert "captureBookingEditorState()" in js
    assert "captureConversationUiState(conversationId)" in js


def test_stale_async_responses_are_discarded_before_rendering() -> None:
    _, _, js, _ = sources()
    for version in (
        "bookingsLoadVersion",
        "conversationLoadVersion",
        "conversationDetailVersion",
        "conversationTemplatesLoadVersion",
        "conversationAutomationLoadVersion",
        "channelOnboardingLoadVersion",
        "reviewRequestsLoadVersion",
        "messageOutboxLoadVersion",
        "rescheduleSlotsLoadVersion",
    ):
        assert js.count(version) >= 3, version
    assert "selectedConversationId !== Number(conversationId)" in js
    assert "requestedDate !== rescheduleState.date" in js


def test_dirty_state_is_delegated_and_protects_navigation_and_unload() -> None:
    _, _, js, _ = sources()
    setup = function_block(
        js, "function setupBusinessConfiguration", "function applyRoleVisibility"
    )
    for contract in (
        'addEventListener("input"',
        'addEventListener("change"',
        'addEventListener("beforeunload"',
        "updateConfigurationDirtyState",
        "configurationDirtyKeys.size",
    ):
        assert contract in setup
    navigation = function_block(
        js, "function confirmConfigurationNavigation", "function configurationState"
    )
    assert "configurationSectionHasDirty(current)" in navigation
    assert "window.confirm" in navigation
    assert "snapshotConfigurationForm" in js
    assert "configurationMutationKeys" in js


def test_drawer_and_modals_restore_focus_and_trap_keyboard_navigation() -> None:
    html, _, js, shell = sources()
    for modal_id, title_id, description_id in (
        ("reschedule-modal", "reschedule-modal-title", "reschedule-modal-description"),
        ("staff-removal-modal", "staff-removal-modal-title", "staff-removal-modal-message"),
    ):
        assert f'id="{modal_id}"' in html
        assert 'aria-modal="true"' in html.split(f'id="{modal_id}"', 1)[1].split(">", 1)[0]
        assert f'aria-labelledby="{title_id}"' in html
        assert f'aria-describedby="{description_id}"' in html
    modal_keys = function_block(
        js, "function handleRescheduleModalKeydown", "async function confirmSelectedReschedule"
    )
    assert 'event.key === "Escape"' in modal_keys
    assert "trapModalFocus" in modal_keys
    assert "rescheduleReturnFocus" in js and "staffRemovalReturnFocus" in js
    for contract in ("setInert(mainArea, true)", 'event.key === "Escape"', "returnFocus.focus()"):
        assert contract in shell


def test_staff_removal_modal_does_not_render_technical_ids_or_phone_numbers() -> None:
    _, _, js, _ = sources()
    modal = function_block(js, "function openStaffRemovalModal", "function closeStaffRemovalModal")
    assert "customer_name" in modal
    assert "service_name" in modal
    assert "formatBlockingBookingDate" in modal
    assert "customer_phone" not in modal
    assert "Reserva #" not in modal
    assert 'data-admin-action="go-to-booking"' in modal
    delegated = function_block(
        js,
        "function setupAdminDelegatedActions",
        'document.addEventListener("DOMContentLoaded"',
    )
    assert 'action === "go-to-booking"' in delegated
    assert "goToBooking(id)" in delegated  # the identifier remains internal to the action


def test_business_requests_are_authenticated_tenant_scoped_and_stale_media_is_slug_scoped() -> None:
    _, _, js, _ = sources()
    router = ADMIN_ROUTER.read_text(encoding="utf-8")
    conversation_service = CONVERSATION_SERVICE.read_text(encoding="utf-8")
    auth_wrapper = js.split("let currentBusiness", 1)[0]
    assert "AutonoGrowAuth.secureRequestOptions(options)" in auth_wrapper
    assert "response.status === 401" in auth_wrapper
    assert "response.status === 403" in auth_wrapper
    assert 'params.get("b")' in js
    assert "/api/admin/businesses/${getBusinessSlug()}" in js
    assert "/api/admin/businesses/${slug}" in js
    assert "JSON.stringify({ slug: getBusinessSlug(), kind })" in js
    assert "pending.slug !== getBusinessSlug()" in js
    assert "localStorage" not in js
    assert "Booking.business_id == business.id" in router
    assert "Conversation.business_id == business_id" in conversation_service


def test_business_context_is_authorized_from_the_url_and_loads_every_admin_area() -> None:
    _, _, js, _ = sources()
    bootstrap = function_block(
        js, "async function bootstrapAdminAuth", "async function adminLogout"
    )
    assert "adminAuthUser.businesses.find((item) => item.slug === slug)" in bootstrap
    assert "adminAuthUser.is_owner || Boolean(adminMembership)" in bootstrap
    assert 'showAdminLogin("Tu cuenta no tiene acceso a este negocio.", true)' in bootstrap
    load_panel = function_block(
        js, "async function loadAdminPanel", "function channelOnboardingStatusLabel"
    )
    for loader in (
        "loadAdminServices()",
        "loadStaffMembers()",
        "loadAvailabilitySettings()",
        "loadAvailabilityExceptions()",
        "loadBookings()",
        "loadMessageOutbox()",
        "loadAdminGallery()",
        "loadConversationTemplates()",
        "loadConversationAutomation()",
        "loadBusinessChannelOnboarding()",
        "loadConversations()",
    ):
        assert loader in load_panel
    # There is no soft business selector: changing ?b= creates a new document load.
    assert "data-business-switch" not in js


def test_errors_are_filtered_and_media_diagnostics_do_not_log_payloads_or_urls() -> None:
    _, _, js, _ = sources()
    safe_error = function_block(js, "function safeConfigurationError", "function adminMediaError")
    for forbidden in ("traceback", "exception", "payload", "sql", "token"):
        assert forbidden in safe_error.lower()
    media_error = function_block(
        js, "function adminMediaError", "async function reloadAdminBusiness"
    )
    assert 'console.error("Error de media", { action, status: response.status })' in media_error
    assert "response.url" not in media_error
    save_notes = function_block(
        js, "async function saveInternalNotes", "function rescheduleBooking"
    )
    update_status = function_block(
        js, "async function updateBookingStatus", "function setupConversationInterface"
    )
    assert "safeConfigurationError" in save_notes
    assert update_status.count("safeConfigurationError") >= 2
    conversation_error = function_block(
        js, "function conversationErrorMessage", "function conversationDisplayName"
    )
    assert "safeConfigurationError" in conversation_error
    outbox_actions = function_block(
        js, "async function openPreparedWhatsAppMessage", "function replaceOutboxMessage"
    )
    assert outbox_actions.count("safeConfigurationError") == 2
    assert "result?.detail ||" not in outbox_actions


def test_no_secret_or_owner_control_is_rendered_and_api_namespaces_are_reused() -> None:
    html, _, js, _ = sources()
    for secret in ("access_token", "app_secret", "client_secret"):
        assert secret not in html.lower()
        assert secret not in js.lower()
    for internal_meta_field in ("phone_number_id", "waba_id"):
        assert internal_meta_field not in html.lower()
    whatsapp_completion = function_block(
        js,
        "async function completeWhatsAppEmbeddedSignup",
        "async function launchWhatsAppEmbeddedSignup",
    )
    assert "phone_number_id" in whatsapp_completion
    assert "waba_id" in whatsapp_completion
    assert "/api/owner" not in js
    assert "data-owner" not in html
    assert not any(label in html for label in (">Aprobar<", ">Revocar<", ">Suspender<"))
    api_paths = re.findall(r"/api/[A-Za-z0-9_/$?={}.&-]+", js)
    assert api_paths
    assert all(
        path.startswith(("/api/admin/", "/api/bookings/", "/api/businesses/")) for path in api_paths
    )


def test_dashboard_and_growth_metrics_are_derived_without_product_claims() -> None:
    _, _, js, _ = sources()
    dashboard = function_block(
        js, "function renderDashboardMetrics", "function renderDashboardBlockError"
    )
    growth = function_block(
        js, "function renderGrowthOverview", "function renderGrowthOpportunities"
    )
    for real_source in (
        "getDashboardTodayBookings()",
        "getDashboardPendingBookings()",
        "getDashboardPendingConversations()",
    ):
        assert real_source in dashboard
    for real_source in (
        "getReviewCandidates()",
        "reviewRequestsByBooking.values()",
        "getFailedReviewMessages()",
    ):
        assert real_source in growth
    for forbidden in ("conversion", "revenue", "roi", "rating", "review_received"):
        assert forbidden not in (dashboard + growth).lower()


def test_cross_section_mutations_reuse_shared_refresh_and_canonical_review_state() -> None:
    _, _, js, _ = sources()
    assert "async function refreshOperationalData" in js
    booking_review = function_block(
        js, "function renderReviewRequest", "function showGrowthReviewFeedback"
    )
    assert 'data-review-create="${booking.id}"' in booking_review
    assert "Gestionar en Crecimiento" in booking_review
    review_creation = function_block(
        js, "async function createReviewRequest", "async function copyReviewMessage"
    )
    assert "reviewRequestsByBooking.set" in review_creation
    assert "replaceOutboxMessage" in review_creation
    assert "requestAdminRefresh" in review_creation
    assert "renderGrowth" in review_creation
    review_loader = function_block(
        js, "async function loadReviewRequests", "function conversationErrorMessage"
    )
    assert "renderGrowth()" in review_loader
    assert "renderDashboard()" in review_loader


def test_responsive_contracts_cover_phone_tablet_desktop_zoom_and_safe_areas() -> None:
    _, css, _, _ = sources()
    shared = SHARED_RESPONSIVE_CSS.read_text(encoding="utf-8")
    for breakpoint in ("@media (max-width: 1023px)", "@media (max-width: 639px)"):
        assert breakpoint in shared
        assert breakpoint in css
    for contract in (
        "env(safe-area-inset-bottom)",
        "max-height: calc(100dvh",
        "overflow-wrap: anywhere",
        "min-width: 0",
    ):
        assert contract in shared
    assert "overflow-x: auto" in css
    assert "grid-template-columns: minmax" in css
    assert "prefers-reduced-motion: reduce" in css


def test_admin_javascript_cachebuster_matches_this_cross_section_pass() -> None:
    html, _, _, _ = sources()
    assert '<script src="admin.js?v=20260829-p14a-a"></script>' in html
