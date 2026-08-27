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
    assert 'item.status === "pending"' in block
    assert "Number(left.item.unread_count) > 0" in block
    assert "leftPriority - rightPriority || left.index - right.index" in block


def test_conversation_filters_are_remote_debounced_and_resettable() -> None:
    html, _, js = read_sources()
    for value in ("pending", "whatsapp", "instagram"):
        assert f'data-conversation-quick-filter="{value}"' in html
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


def test_whatsapp_assisted_url_is_restricted_to_safe_wa_me_https() -> None:
    _, _, js = read_sources()
    block = function_block(js, "function isSafeWhatsAppUrl", "async function openConversationWhatsApp")
    assert 'url.protocol === "https:"' in block
    assert 'url.hostname === "wa.me"' in block
    assert "!url.username" in block
    assert "!url.password" in block


def test_customer_context_reuses_loaded_bookings_without_n_plus_one() -> None:
    _, _, js = read_sources()
    block = function_block(js, "function customerBookingsForConversation", "function openConversationCustomerPanel")
    assert "allBookings" in block
    assert "normalizedConversationPhone" in block
    assert "fetch(" not in block
    assert "Próxima reserva" in block
    assert "Última reserva" in block
    assert 'data-admin-action="go-to-booking"' in block
    delegated = function_block(
        js,
        "function setupAdminDelegatedActions",
        'document.addEventListener("DOMContentLoaded"',
    )
    assert "goToBooking(id)" in delegated
    assert "Solo se relacionan teléfonos coincidentes" in block


def test_conversation_drawer_has_focus_escape_and_responsive_modes() -> None:
    html, css, js = read_sources()
    assert 'id="conversation-customer-backdrop"' in html
    assert 'aria-controls="conversation-create-panel"' in html
    assert 'id="conversation-customer-title" tabindex="-1"' in html
    assert 'event.key === "Escape"' in js
    assert 'event.key !== "Tab"' in js
    assert "conversationCustomerReturnFocus" in js
    assert "@media (max-width: 1199px)" in css
    assert "@media (max-width: 639px)" in css
    assert ".conversation-mobile-back" in css
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
