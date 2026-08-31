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


def test_conversations_has_three_panel_architecture_and_preserves_contracts() -> None:
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
    assert "conversation-date-separator" in block
    assert "escapeHtml(message.body)" in block
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


def test_conversation_composer_precedes_collapsed_secondary_controls() -> None:
    _, css, js = read_sources()
    render = function_block(js, "function renderConversationDetail", "function customerMemoryCategoryLabel")
    header = render.split('<header class="conversation-detail-header">', 1)[1].split("</header>", 1)[0]

    assert render.index('id="conversation-thread"') < render.index('class="conversation-footer"')
    assert render.index("renderConversationComposer(conversation)") < render.index("conversation-secondary-controls")
    assert render.index('id="conversation-templates-control"') < render.index('id="conversation-automation-control"')
    assert "conversation-automation-controls" not in header
    assert '${uiState?.templatesOpen ? " open" : ""}' in render
    assert '${uiState?.automationOpen ? " open" : ""}' in render
    assert "grid-template-rows: auto minmax(0, 1fr) auto" in css
    assert ".conversation-secondary-controls" in css


def test_conversation_header_is_compact_without_redundant_breadcrumb() -> None:
    _, css, js = read_sources()
    render = function_block(js, "function renderConversationDetail", "function customerMemoryCategoryLabel")
    header = render.split('<header class="conversation-detail-header">', 1)[1].split("</header>", 1)[0]
    open_panel = function_block(js, "function openConversationCustomerPanel", "function closeConversationCustomerPanel")
    open_search = function_block(js, "function openConversationCustomerSearch", "async function updateConversationCustomer")

    assert "conversation.customer_id" in render
    assert "Ver cliente" not in render
    assert "Asociar cliente" in render
    assert "conversation-association-trigger" in render
    assert "open-conversation-customer-panel" in render
    assert "!isBusinessStaff()" in render
    assert "Conversaciones" not in header
    assert "conversation-mobile-back" not in header
    assert header.index("conversationAttentionBadges(conversation)") < header.index("${customerHeaderAction}")
    assert 'class="conversation-detail-meta"' in header
    assert 'class="conversation-detail-header-lower"' in header
    assert 'class="conversation-operational-actions"' in header
    assert header.index("Marcar pendiente") < header.index("Cerrar")
    assert "scrollIntoView" in open_panel
    assert "title?.focus" in open_panel
    assert "openConversationCustomerPanel(document.activeElement)" in open_search
    assert ".conversation-customer-open { display: inline-flex; }" in css
    assert ".conversations-section .conversation-detail-header { display: grid;" in css
    assert ".conversation-operational-actions { display: flex;" in css
    assert "flex-wrap: nowrap" in css


def test_conversation_badges_wrap_without_clipping_and_history_keeps_flexible_height() -> None:
    _, css, _ = read_sources()

    assert ".conversation-detail-badges { display: flex; min-width: 0;" in css
    assert ".conversation-attention-states { display: inline-flex; min-width: 0;" in css
    assert "min-height: 1.5rem; white-space: normal; overflow-wrap: anywhere;" in css
    assert ".conversation-detail-header-copy { min-width: 0;" in css
    assert "grid-template-columns: minmax(15rem, 19rem) minmax(0, 1fr)" in css
    assert "grid-template-rows: auto minmax(0, 1fr) auto" in css
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
    assert 'getElementById("conversation-templates-control")?.removeAttribute("open")' in fill
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
    assert "Usuario de Instagram no disponible" in display
    assert "external_user_id" not in display
    assert "@${identity.username}" in display
    assert "+34 ${spanish[1]} ${spanish[2]} ${spanish[3]}" in display
    assert 'if (isBusinessStaff()) return;' in js
    assert 'isBusinessStaff() ? ""' in panel


def test_conversation_drawer_has_focus_escape_and_responsive_modes() -> None:
    html, css, js = read_sources()
    assert 'id="conversation-customer-backdrop"' in html
    assert 'aria-controls="conversation-create-panel"' in html
    assert 'id="conversation-customer-title" tabindex="-1"' in html
    assert 'event.key === "Escape"' in js
    assert 'event.key !== "Tab"' in js
    assert "conversationCustomerReturnFocus" in js
    assert "@media (max-width: 1599px)" in css
    assert "@media (max-width: 639px)" in css
    assert ".conversation-mobile-back" not in css
    navigation = function_block(js, "function showAdminSection", "function setupAdminNavigation")
    assert 'targetSection === "conversations"' in navigation
    assert 'window.matchMedia("(max-width: 639px)").matches' in navigation
    assert "closeConversationMobileDetail()" in navigation
    assert "env(safe-area-inset-bottom)" in css


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
