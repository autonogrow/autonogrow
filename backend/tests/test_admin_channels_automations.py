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


def sources() -> tuple[str, str, str]:
    return (
        ADMIN_HTML.read_text(encoding="utf-8"),
        ADMIN_CSS.read_text(encoding="utf-8"),
        ADMIN_JS.read_text(encoding="utf-8"),
    )


def function_block(js: str, start: str, end: str) -> str:
    return js.split(start, 1)[1].split(end, 1)[0]


def test_channels_and_automations_have_four_categories_and_legacy_contracts() -> None:
    html, _, js = sources()
    for section in ("channels", "channel-instagram", "channel-whatsapp", "messages"):
        assert html.count(f'data-admin-section="{section}"') == 1
        assert f'{{ id: "{section}"' in js
    for element_id in (
        "channel-onboarding-list",
        "channel-onboarding-feedback",
        "conversation-automation-panel",
        "conversation-automation-content",
        "conversation-templates-panel",
        "conversation-template-list",
        "message-outbox-list",
    ):
        assert html.count(f'id="{element_id}"') == 1
    inventory = IdInventory()
    inventory.feed(html)
    assert sorted({item for item in inventory.ids if inventory.ids.count(item) > 1}) == []


def test_overview_separates_all_six_real_state_dimensions() -> None:
    _, _, js = sources()
    block = function_block(js, "function channelStateRows", "function channelActionMarkup")
    for label in (
        "Disponibilidad",
        "Conexión",
        "Aprobación",
        "Envío desde AutonoGrow",
        "Respuestas automáticas",
        "Salud",
    ):
        assert label in block
    assert "Todo funciona" not in block
    for status in ("available", "pending_approval", "approved", "suspended", "revoked"):
        assert status in js


def test_health_is_friendly_partial_and_does_not_expose_diagnostics() -> None:
    _, _, js = sources()
    mapping = function_block(js, "function channelHealthStatus", "function channelHubNavigationMarkup")
    for label in (
        "Aún no comprobado",
        "Funciona correctamente",
        "Puede necesitar atención",
        "Funciona con problemas",
        "Necesita tu atención",
        "Debes volver a conectar",
        "Canal suspendido",
        "No se ha podido comprobar",
    ):
        assert label in mapping
    render = function_block(js, "function renderChannelDetail", "function renderBusinessChannelOnboarding")
    for forbidden in (
        "consecutive_health_failures",
        "health_error_code",
        "metadata",
        "scopes",
        "safe_error_message",
        "token_expires_at",
    ):
        assert forbidden not in render
    loader = function_block(js, "async function loadBusinessChannelOnboarding", "let metaSdkPromise")
    assert "Promise.allSettled" in loader
    assert 'channelHubLoadState.onboarding = nextOnboarding ? "ready" : "error"' in loader
    assert 'channelHubLoadState.health = Array.isArray(nextHealth?.channels) ? "ready" : "error"' in loader


def test_admin_actions_use_existing_official_flows_without_owner_controls() -> None:
    _, _, js = sources()
    actions = function_block(js, "async function requestBusinessChannelConnection", "const WEEKDAYS")
    for route in (
        "/integrations/instagram/oauth/start",
        "/integrations/whatsapp/embedded-signup/start",
        "/integrations/whatsapp/embedded-signup/complete",
        "/channels/instagram/reconnect",
        "/health-check",
    ):
        assert route in js
    for forbidden in ("/approve", "/suspend", "/revoke", "integrated-delivery/enable"):
        assert forbidden not in actions
    assert "channelActionKeys.has(actionKey)" in actions
    assert "Confirmo que soy administrador autorizado" in actions


def test_instagram_redirect_and_meta_messages_are_strictly_validated() -> None:
    _, _, js = sources()
    validator = function_block(
        js,
        "function isSafeInstagramAuthorizationUrl",
        "function channelFeedbackElement",
    )
    assert 'url.protocol === "https:"' in validator
    assert 'url.hostname === "www.instagram.com"' in validator
    assert 'url.pathname === "/oauth/authorize"' in validator
    assert "!url.username" in validator and "!url.password" in validator
    meta_origin = function_block(js, "function isTrustedMetaEventOrigin", "function isSafeInstagramAuthorizationUrl")
    assert 'url.protocol === "https:"' in meta_origin
    assert 'url.hostname.endsWith(".facebook.com")' in meta_origin
    assert 'configuration.sdk_url !== "https://connect.facebook.net/en_US/sdk.js"' in js


def test_reconnection_preserves_previous_integration_and_pending_review_copy() -> None:
    _, _, js = sources()
    detail = function_block(js, "function renderChannelDetail", "function renderBusinessChannelOnboarding")
    assert "La conexión actual seguirá funcionando" in detail
    assert "hasta que la nueva conexión sea revisada y aprobada" in detail
    actions = function_block(js, "async function handleChannelHealthAction", "const WEEKDAYS")
    assert "La anterior no se sustituirá todavía" in actions
    assert "pendiente de revisión por AutonoGrow" in actions


def test_whatsapp_distinguishes_integrated_and_assisted_delivery() -> None:
    _, _, js = sources()
    detail = function_block(js, "function renderChannelDetail", "function renderBusinessChannelOnboarding")
    assert "Envío desde AutonoGrow" in detail
    assert "Modo asistido" in detail
    assert "la persona completa el envío fuera de AutonoGrow" in detail
    assert "24 horas desde el último mensaje del cliente" in detail
    assert "PIN" in detail
    assert "WABA" not in detail and "phone_number_id" not in detail


def test_automation_respects_owner_period_channel_health_and_credits() -> None:
    _, _, js = sources()
    authorization = function_block(js, "function automationAuthorizedChannels", "function renderConversationAutomation")
    assert 'channel?.status === "approved"' in authorization
    assert "channel.automation_enabled" in authorization
    assert "!health?.reconnection_required" in authorization
    render = function_block(js, "function renderConversationAutomation", "async function saveConversationAutomationSettings")
    assert "settings.automation_feature_enabled" in render
    assert 'usage.period_status === "active"' in render
    assert "Bloqueada por el canal" in render
    assert "Créditos de automatización" in render
    assert "La salud del canal se comprueba por separado" in render
    assert "El límite de mensajes forma parte de tu plan" in render


def test_templates_use_only_real_variables_safe_preview_and_real_limits() -> None:
    html, _, js = sources()
    variables = (
        "business_name",
        "business_slug",
        "public_booking_url",
        "business_phone",
        "business_address",
    )
    for variable in variables:
        assert f"{{{variable}}}" in html
        assert f'"{variable}"' in js
    assert 'maxlength="160"' in html
    assert 'maxlength="10000"' in html
    validation = function_block(js, "function templateValidation", "function templatePreviewText")
    assert "CONVERSATION_TEMPLATE_VARIABLES.has" in validation
    assert "/[{}]/" in validation
    preview = function_block(js, "function renderNewTemplatePreview", "function canSaveChannelConfiguration")
    assert ".textContent" in preview
    assert ".innerHTML" not in preview


def test_dirty_state_is_independent_and_background_refresh_preserves_forms() -> None:
    html, _, js = sources()
    assert 'data-config-dirty-key="template-new"' in html
    assert 'data-config-dirty-key="automation-settings"' in js
    assert 'data-config-dirty-key="automation-rule-' in js
    assert 'data-config-dirty-key="template-${template.id}"' in js
    assert "canSaveChannelConfiguration" in js
    assert "configurationMutationKeys.has" in js
    assert '!background || !configurationSectionHasDirty("messages")' in js
    setup = function_block(js, "function setupChannelHub", "function setupBusinessConfiguration")
    assert setup.count('addEventListener("click"') == 1
    assert setup.count('addEventListener("input"') == 1
    assert "setInterval(" not in setup


def test_accessibility_and_responsive_structure_are_explicit() -> None:
    html, css, js = sources()
    assert html.count("data-channel-hub-navigation") == 4
    assert 'aria-label="Canales y automatizaciones"' in js
    assert 'aria-current="page"' in js
    assert 'aria-busy="true"' in html
    assert 'role="status" aria-live="polite"' in html
    sprint_css = css.split("/* Sprint 5B.5", 1)[1].split("/* Sprint 5B.2", 1)[0]
    assert "@media (max-width: 1023px)" in sprint_css
    assert "@media (max-width: 639px)" in sprint_css
    assert "env(safe-area-inset-bottom)" in sprint_css
    assert "@media (prefers-reduced-motion: reduce)" in sprint_css
    assert "overflow-x" not in sprint_css


def test_refresh_reuses_polling_and_updates_channels_conversations_dashboard() -> None:
    _, _, js = sources()
    refresh = function_block(js, "async function refreshOperationalData", "async function enrichBookingsWithAttachments")
    assert 'requestAdminRefresh(["conversationList", "conversationThread", "operations"])' in refresh
    assert "loadBusinessChannelOnboarding({ background: true })" in refresh
    assert "loadConversationAutomation({ background: true })" in refresh
    assert "loadConversationTemplates({ background: true })" in refresh
    assert "setInterval(" not in refresh
    assert "channelOnboardingLoadVersion" in js
    assert "conversationAutomationLoadVersion" in js
    assert "conversationTemplatesLoadVersion" in js
