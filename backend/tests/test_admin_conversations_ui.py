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


def test_templates_are_initialized_before_parallel_automation_load() -> None:
    _, _, js = read_sources()
    panel = function_block(js, "async function loadAdminPanel()", "function channelOnboardingStatusLabel")
    templates = panel.index("await loadConversationTemplates();")
    parallel_loads = panel.index("await Promise.all([", templates)
    automation = panel.index("loadConversationAutomation()", parallel_loads)

    assert templates < parallel_loads < automation


def test_delegated_instagram_forms_use_the_submitted_form() -> None:
    _, _, js = read_sources()
    comment = function_block(
        js,
        "async function submitAdminInstagramComment",
        "async function submitAdminInstagramBusinessReview",
    )
    review = function_block(
        js, "async function submitAdminInstagramBusinessReview", "async function submitAdminInstagramHold"
    )

    assert "const form = event.target;" in comment
    assert "const form = event.target;" in review
    assert "event.currentTarget" not in comment
    assert "event.currentTarget" not in review


def test_conversations_preserve_dom_contracts_for_inbox_and_focus_workspace() -> None:
    html, _, _ = read_sources()
    inventory = IdInventory()
    inventory.feed(html)
    duplicates = sorted({item for item in inventory.ids if inventory.ids.count(item) > 1})
    assert duplicates == []
    for element_id in (
        "conversation-list",
        "conversation-detail",
        "conversation-customer-panel",
        "conversation-feedback",
        "conversation-status-filter",
        "conversation-channel-filter",
        "conversation-search",
        "conversation-templates-panel",
        "conversation-automation-panel",
    ):
        assert html.count(f'id="{element_id}"') == 1
    assert "Clientes y mensajes" in html
    assert 'role="listbox"' in html
    detail_tag = html.split('<article id="conversation-detail"', 1)[1].split(">", 1)[0]
    assert "aria-live" not in detail_tag


def test_conversations_prioritize_attention_without_reordering_each_group() -> None:
    _, _, js = read_sources()
    block = function_block(js, "function prioritizeConversations", "function updateConversationFilterSummary")
    assert "conversationNeedsReply(left.item)" in block
    assert "conversationNeedsGrowthFollowUp(left.item)" in block
    assert "conversationIsManualPending(left.item)" in block
    assert "leftPriority - rightPriority || left.index - right.index" in block


def test_conversation_filters_are_remote_debounced_and_resettable() -> None:
    html, _, js = read_sources()
    for value in ("needs_reply", "whatsapp", "instagram"):
        assert f'data-conversation-quick-filter="{value}"' in html
    assert '<option value="pending">Pendientes</option>' in html
    assert 'params.set("attention", status)' in js
    assert "function resetConversationFilters" in js
    assert "function applyConversationQuickFilter" in js
    assert "clearTimeout(conversationSearchTimer)" in js
    assert "350" in js
    assert 'params.set("q", query)' in js


def test_conversation_messages_are_grouped_and_translated_for_people() -> None:
    _, _, js = read_sources()
    for label in (
        "Entrante · Cliente",
        "Saliente manual",
        "Saliente automático",
        "Sistema",
        "Error de entrega",
        "Preparando",
        "Enviando",
        "Reintentando",
        "No entregado",
    ):
        assert label in js
    block = function_block(js, "function renderConversationMessages", "function conversationComposerModel")
    content = function_block(
        js, "function renderConversationMessageContent", "function renderConversationMessages"
    )
    assert "conversation-date-separator" in block
    assert "escapeHtml(message.body)" in content
    assert ".sort(" in block


def test_composer_uses_canonical_capabilities_and_never_legacy_instagram_flag() -> None:
    _, _, js = read_sources()
    provider = function_block(js, "function conversationProviderBadge", "function formatConversationDate")
    composer = function_block(js, "function conversationComposerModel", "function renderConversationComposer")
    assert "instagram_provider_configured" not in provider
    assert "instagram_provider_configured" not in composer
    assert "provider_configured" in provider
    assert "delivery_supported" in provider
    assert "delivery_mode" in composer
    assert "assisted_delivery_available" in composer
    assert 'conversation.channel === "manual"' in composer
    assert "ventana de atención de 24 horas" in composer
    assert "Enviar por WhatsApp" in composer
    assert "Abrir en WhatsApp" in composer


def test_unavailable_channel_is_history_only_and_whatsapp_is_explicitly_assisted() -> None:
    _, _, js = read_sources()
    composer = function_block(js, "function renderConversationComposer", "function renderConversationDetail")
    assert 'if (!model.canCompose)' in composer
    assert "Respuesta no disponible" in composer
    assert "Revisar canal" in composer
    assert "conversation-whatsapp-button" in composer
    assert "AutonoGrow no marcará el mensaje como enviado" in js


def test_send_actions_block_double_submission_and_keep_assisted_draft() -> None:
    _, _, js = read_sources()
    reply = function_block(js, "async function sendConversationReply", "function isSafeWhatsAppUrl")
    assisted = function_block(js, "async function openConversationWhatsApp", "async function sendConversationSuggestion")
    assert "conversationReplySending" in reply
    assert 'button.setAttribute("aria-busy", "true")' in reply
    assert 'textarea.value = ""' in reply
    assert "conversationAssistedOpening" in assisted
    assert "isSafeWhatsAppUrl(body.whatsapp_url)" in assisted
    assert 'textarea.value = ""' not in assisted


def test_integrated_whatsapp_keeps_assisted_as_a_permanent_alternative() -> None:
    _, _, js = read_sources()
    composer = function_block(js, "function conversationComposerModel", "function renderConversationComposer")
    render = function_block(js, "function renderConversationComposer", "function renderConversationDetail")
    assert "conversation.delivery_mode" in composer
    assert 'deliveryMode === "integrated"' in composer
    assert "whatsapp && conversation.assisted_delivery_available" in composer
    assert "assistedAction" in composer
    assert "conversation-send-button" in render
    assert "conversation-whatsapp-button" in render


def test_conversation_composer_precedes_on_demand_tool_launchers() -> None:
    _, css, js = read_sources()
    render = function_block(js, "function renderConversationDetail", "function customerMemoryCategoryLabel")
    header = render.split('<header class="conversation-detail-header">', 1)[1].split("</header>", 1)[0]

    assert render.index('id="conversation-thread"') < render.index('class="conversation-footer"')
    assert render.index("renderConversationComposer(conversation)") < render.index("conversation-tool-launchers")
    assert render.index('id="conversation-templates-control"') < render.index('id="conversation-automation-control"')
    assert "conversation-automation-controls" not in header
    assert "<details" not in render
    assert "conversation-secondary-panel" not in render
    assert "grid-template-rows: auto auto minmax(0, 1fr) auto" in css
    assert ".conversation-tool-overlay { position: absolute;" in css
    assert ".conversation-tool-sheet { display: grid;" in css


def test_conversation_header_is_compact_without_redundant_breadcrumb() -> None:
    _, css, js = read_sources()
    render = function_block(js, "function renderConversationDetail", "function customerMemoryCategoryLabel")
    header = render.split('<header class="conversation-detail-header">', 1)[1].split("</header>", 1)[0]
    open_panel = function_block(js, "function openConversationCustomerPanel", "function closeConversationCustomerPanel")
    open_search = function_block(js, "function openConversationCustomerSearch", "async function updateConversationCustomer")

    assert "conversation.customer_id" in render
    assert "Información del cliente" in render
    assert "${customerHeaderAction}" not in header
    assert "open-conversation-customer-panel" in render
    assert "conversation-detail-breadcrumb" not in header
    assert 'data-admin-action="show-conversation-list"' in header
    assert 'aria-label="Volver a conversaciones"' in header
    assert "conversation-mobile-back" not in header
    assert 'class="conversation-detail-meta"' in header
    assert 'class="conversation-detail-heading-row"' in header
    assert 'class="conversation-detail-title-group"' in header
    assert 'class="conversation-operational-actions"' in header
    heading = header.split('<div class="conversation-detail-heading-row">', 1)[1].split("</div>\n      <div class=\"conversation-detail-meta\"", 1)[0]
    assert "conversation-detail-title" in heading
    assert "Marcar pendiente" in heading
    assert "Cerrar" in heading
    assert header.index("Marcar pendiente") < header.index("Cerrar")
    assert "conversationProviderBadge" not in header
    assert "conversationIntentBadge" not in header
    assert "conversationAttentionBadges" not in header
    assert "scrollIntoView" in open_panel
    assert "title?.focus" in open_panel
    assert "openConversationCustomerPanel(document.activeElement)" in open_search
    assert ".conversation-customer-open { display: inline-flex; }" in css
    assert ".conversations-section .conversation-detail-header { display: grid;" in css
    assert ".conversation-operational-actions { display: flex;" in css
    assert "flex-wrap: nowrap" in css


def test_conversation_metadata_moves_to_customer_drawer_and_history_stays_flexible() -> None:
    _, css, js = read_sources()
    customer = function_block(js, "function renderConversationCustomerPanel", "function renderStandaloneCustomerPanel")

    assert 'class="conversation-customer-context"' in customer
    assert "conversationChannelLabel(conversation.channel)" in customer
    assert "conversationProviderBadge(conversation)" in customer
    assert "conversationIntentBadge(conversation)" in customer
    assert "conversationAttentionBadges(conversation)" in customer
    assert ".conversation-customer-badges { display: flex; min-width: 0;" in css
    assert ".conversation-attention-states { display: inline-flex; min-width: 0;" in css
    assert "min-height: 1.5rem; white-space: normal; overflow-wrap: anywhere;" in css
    assert ".conversation-center.conversation-focus-open .conversation-list-panel { display: none; }" in css
    assert ".conversation-center.conversation-focus-open .conversation-detail { display: grid; }" in css
    assert "grid-template-rows: auto auto minmax(0, 1fr) auto" in css
    assert ".conversations-section .conversation-thread { min-height: 0; max-height: none;" in css


def test_conversation_attention_copy_uses_derived_reply_and_follow_up_states() -> None:
    _, _, js = read_sources()
    attention = function_block(js, "function conversationNeedsReply", "function conversationFilterLabel")
    inbox = function_block(js, "function updateConversationInboxSummary", "async function loadConversations")

    assert "item.needs_reply === true" in attention
    assert "item.growth_follow_up === true" in attention
    assert "item.manual_pending === true" in attention
    assert "Necesita respuesta" in attention
    assert "Requiere seguimiento" in attention
    assert "Pendiente" in attention
    assert "dashboardConversations.filter(conversationNeedsReply)" in inbox


def test_conversation_composer_integrates_send_and_autogrows_accessibly() -> None:
    _, css, js = read_sources()
    composer = function_block(js, "function renderConversationComposer", "function renderConversationDetail")
    resize = function_block(js, "function resizeConversationReplyTextarea", "function renderConversationComposer")
    setup = function_block(js, "function setupConversationInterface", "function setupAdminDelegatedActions")

    assert composer.index('id="conversation-reply-body"') < composer.index('id="conversation-send-button"')
    assert 'class="conversation-composer-shell"' in composer
    assert 'rows="1"' in composer
    assert 'aria-describedby="conversation-reply-notice"' in composer
    assert 'aria-label="${escapeHtml(model.action)}"' in composer
    assert '<span aria-hidden="true">➤</span>' in composer
    assert "textarea.style.height = \"auto\"" in resize
    assert "Math.min(textarea.scrollHeight, maximumHeight)" in resize
    assert 'event.target.id === "conversation-reply-body"' in setup
    assert "resize: none" in css
    assert "max-height: 9rem" in css


def test_template_selection_only_fills_and_resizes_composer() -> None:
    _, _, js = read_sources()
    fill = function_block(js, "function fillConversationReply", "async function sendConversationReply")

    assert "textarea.value = template.rendered_body || template.body" in fill
    assert "resizeConversationReplyTextarea(textarea)" in fill
    assert "closeConversationToolPanel({ restoreFocus: false })" in fill
    assert "sendConversationReply" not in fill


def test_whatsapp_assisted_url_is_restricted_to_safe_wa_me_https() -> None:
    _, _, js = read_sources()
    block = function_block(js, "function isSafeWhatsAppUrl", "async function openConversationWhatsApp")
    assert 'url.protocol === "https:"' in block
    assert 'url.hostname === "wa.me"' in block
    assert "!url.username" in block
    assert "!url.password" in block


def test_customer_context_uses_persisted_backend_association() -> None:
    _, _, js = read_sources()
    block = function_block(js, "function renderConversationCustomerPanel", "function openCustomerMemoryForm")
    assert "conversation.customer_id" in block
    assert "conversation.customer" in block
    assert "conversation.customer_memory_eligible" in block
    assert "allBookings" not in block
    assert "customerBookingsForConversation" not in js
    assert "customerIdForConversation" not in js
    assert "Asociar cliente" in block
    assert "Cambiar cliente" in block
    assert "Desasociar" in block


def test_selecting_conversation_loads_customer_panel_directly() -> None:
    _, _, js = read_sources()
    block = function_block(js, "async function selectConversation", "function conversationMessageKind")

    assert "selectedConversation = body.conversation" in block
    assert "renderConversationDetail(body.conversation, uiState)" in block
    assert "renderConversationCustomerPanel(body.conversation)" in block


def test_conversation_identity_is_honest_and_staff_controls_remain_hidden() -> None:
    _, _, js = read_sources()
    display = function_block(js, "function conversationDisplayName", "function conversationStatusLabel")
    panel = function_block(js, "function renderConversationCustomerPanel", "function openCustomerMemoryForm")
    assert "item.customer?.name" in display
    assert "item.customer?.instagram_username" in display
    assert "Instagram no asociado" in display
    assert "external_user_id" not in display
    assert "@${identity.username}" in display
    assert "Instagram del cliente" in panel
    assert "+34 ${spanish[1]} ${spanish[2]} ${spanish[3]}" in display
    assert 'if (isBusinessStaff()) return;' in js
    assert 'isBusinessStaff() ? ""' in panel


def test_growth_customer_navigation_does_not_reuse_conversation_navigation() -> None:
    _, _, js = read_sources()
    growth = function_block(js, "function setupGrowthHub", "function setupChannelHub")
    customer = function_block(js, "function openOpportunityCustomer", "async function openOpportunityConversation")
    conversation = function_block(js, "async function openOpportunityConversation", "async function updateCustomerOpportunity")

    assert "openOpportunityCustomer(opportunityId, opportunity)" in growth
    assert "customer_id" in customer
    assert "renderStandaloneCustomerPanel" in customer
    assert "/open-conversation" not in customer
    assert "/open-conversation" in conversation


def test_growth_and_conversation_channel_copy_reflects_real_capabilities() -> None:
    _, _, js = read_sources()
    channel = function_block(js, "function growthOpportunityChannelLabel", "function dashboardBookingSortKey")
    identity = function_block(js, "function conversationChannelIdentity", "function conversationAssociationLabel")

    assert "WhatsApp asistido" in channel
    assert "Sin canal integrado" in channel
    assert "Sin canal/contacto utilizable" in channel
    assert "item.customer?.instagram_username" in identity
    assert "Instagram no asociado" in identity


def test_conversation_drawer_has_focus_escape_and_responsive_modes() -> None:
    html, css, js = read_sources()
    assert 'id="conversation-customer-backdrop"' in html
    assert 'aria-controls="conversation-create-panel"' in html
    assert 'id="conversation-customer-title" tabindex="-1"' in html
    assert 'event.key === "Escape"' in js
    assert 'event.key !== "Tab"' in js
    assert "conversationCustomerReturnFocus" in js
    assert "@media (max-width: 639px)" in css
    assert ".conversation-mobile-back" not in css
    assert ".conversation-customer-panel { box-sizing: border-box; position: fixed;" in css
    assert 'panel.setAttribute("aria-hidden", String(!conversationCustomerPanelOpen))' in js
    navigation = function_block(js, "function showAdminSection", "function setupAdminNavigation")
    assert 'targetSection === "conversations"' in navigation
    assert "closeConversationWorkspace" in navigation
    assert "env(safe-area-inset-bottom)" in css
    assert ".conversation-customer-content { overflow-x: hidden; }" in css
    assert ".customer-memory-item > * { overflow-wrap: anywhere;" in css


def test_conversation_polling_keeps_versions_drafts_scroll_and_single_pipeline() -> None:
    _, _, js = read_sources()
    assert "conversationLoadVersion" in js
    assert "conversationDetailVersion" in js
    assert "conversationListFingerprint" in js
    assert "conversationDetailFingerprint" in js
    assert "captureConversationUiState" in js
    assert "threadNearBottom" in js
    assert "newMessagesVisible" in js
    assert 'adminPollingTasks.set("conversationThread"' in js
    assert 'adminPollingTasks.set("conversationList"' in js
    conversation_area = function_block(js, "function conversationErrorMessage", "function renderConversationTemplates")
    assert "setInterval(" not in conversation_area


def test_errors_are_safe_and_suggestion_failure_does_not_hide_thread() -> None:
    _, _, js = read_sources()
    errors = function_block(js, "function conversationErrorMessage", "function showConversationFeedback")
    select = function_block(js, "async function selectConversation", "function conversationMessageKind")
    assert "JSON.stringify" not in errors
    assert "suggestionsResponse.ok ?" in select
    assert "Puedes seguir revisando la conversación" in select
    assert "No pudimos abrir esta conversación" in select


def test_conversation_focus_route_uses_history_without_auto_selecting_inbox() -> None:
    _, css, js = read_sources()
    load = function_block(js, "async function loadConversations", "function renderConversationList")
    navigation = function_block(js, "const CONVERSATION_ROUTE_PARAM", "function showAdminSection")
    selection = function_block(js, "async function selectConversation", "function conversationMessageKind")

    assert '= "conversation"' in navigation
    assert "window.history[`${historyMode}State`]" in navigation
    assert "conversationIdFromRoute()" in load
    assert "conversations[0].id" not in load
    assert 'historyMode: "none"' in load
    assert "routeFallback: true" in load
    assert 'historyMode = "none"' in selection
    assert "writeConversationRoute(Number(conversationId), historyMode)" in selection
    assert "conversationDetailVersion += 1" in js
    assert ".conversations-section.conversation-focus-mode" in css


def test_secondary_conversation_tools_are_accessible_workspace_overlays() -> None:
    html, _, js = read_sources()
    render = function_block(js, "function renderConversationDetail", "function customerMemoryCategoryLabel")
    setup = function_block(js, "function setupConversationInterface", "function setupAdminDelegatedActions")
    opener = function_block(js, "function openConversationToolPanel", "function closeConversationToolPanel")
    closer = function_block(js, "function closeConversationToolPanel", "function resetConversationFilters")

    assert 'id="conversation-tool-overlay"' in html
    assert 'role="dialog"' in html
    assert 'aria-modal="true"' in html
    assert render.count('aria-controls="conversation-tool-overlay"') == 2
    assert 'data-admin-action="open-conversation-tool"' in render
    assert 'data-tool="templates"' in render
    assert 'data-tool="automation"' in render
    assert 'document.getElementById("conversation-tool-close").addEventListener' in setup
    assert 'event.key === "Escape" && conversationToolPanelOpen' in setup
    assert 'event.key !== "Tab"' in setup
    assert 'setAttribute("inert", "")' in opener
    assert 'removeAttribute("inert")' in closer
    assert 'focus({ preventScroll: true })' in opener
    assert 'focus?.({ preventScroll: true })' in closer


def test_conversation_media_renderer_supports_all_v1_kinds_and_safe_fallbacks() -> None:
    _, css, js = read_sources()
    renderer = function_block(
        js, "function conversationMediaUrl", "function renderConversationMessages"
    )
    messages = function_block(
        js, "function renderConversationMessages", "function conversationComposerModel"
    )

    assert 'value.startsWith("/api/admin/businesses/")' in renderer
    assert 'attachment.kind === "image"' in renderer
    assert 'attachment.kind === "video"' in renderer
    assert 'attachment.kind === "audio"' in renderer
    assert 'conversation-media-file' in renderer
    assert "no disponible" in renderer
    assert 'loading="lazy"' in renderer
    assert '<video controls preload="metadata"' in renderer
    assert '<audio controls preload="none"' in renderer
    assert 'target="_blank" rel="noopener"' in renderer
    assert "body_is_attachment_fallback" in renderer
    assert "renderConversationMessageContent(message)" in messages
    assert ".conversation-media-image { position: relative; display: grid;" in css
    assert ".conversation-media-card--player audio" in css
    assert "max-width: 100%" in css


def test_conversation_image_viewer_has_modal_focus_and_error_semantics() -> None:
    html, _, js = read_sources()
    opener = function_block(
        js, "function openConversationMediaViewer", "function closeConversationMediaViewer"
    )
    closer = function_block(
        js, "function closeConversationMediaViewer", "function markConversationMediaUnavailable"
    )
    setup = function_block(js, "function setupConversationInterface", "function setupAdminDelegatedActions")

    assert 'id="conversation-media-viewer"' in html
    assert 'role="dialog"' in html
    assert 'aria-modal="true"' in html
    assert 'aria-labelledby="conversation-media-viewer-title"' in html
    assert 'aria-label="Cerrar imagen"' in html
    assert 'setAttribute("inert", "")' in opener
    assert "conversation-media-viewer-title" in opener
    assert 'removeAttribute("inert")' in closer
    assert 'event.key === "Escape" && conversationMediaViewerOpen' in setup
    assert "markConversationMediaUnavailable" in setup
    assert "conversationMediaReturnFocus" in closer
