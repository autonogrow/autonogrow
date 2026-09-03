from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
ADMIN_HTML = ROOT / "autonogrow-admin" / "index.html"
ADMIN_CSS = ROOT / "autonogrow-admin" / "styles.css"
ADMIN_JS = ROOT / "autonogrow-admin" / "admin.js"


def sources() -> tuple[str, str, str]:
    return (
        ADMIN_HTML.read_text(encoding="utf-8"),
        ADMIN_CSS.read_text(encoding="utf-8"),
        ADMIN_JS.read_text(encoding="utf-8"),
    )


def function_block(js: str, start: str, end: str) -> str:
    return js.split(start, 1)[1].split(end, 1)[0]


def test_home_prioritizes_real_growth_opportunities_and_separates_setup() -> None:
    html, _, js = sources()
    render = function_block(js, "function renderAttentionItems", "function renderMessageSummary")

    assert "Oportunidades y tareas para hoy" in html
    assert "Oportunidades para hoy" in render
    assert "growthFollowUps.slice(0, 5)" in render
    assert "compareGrowthOpportunities" in js
    assert "growthOpportunityHeadline(opportunity)" in render
    assert "growthOpportunityTiming(opportunity)" in render
    assert "Preparar mensaje" in render
    assert "Mejora la configuración" in render
    growth_markup = render.split("const growthTaskItems =", 1)[1].split("const closeTaskItems", 1)[
        0
    ]
    assert "review" not in growth_markup.lower()


def test_home_growth_opportunity_card_stacks_content_without_narrow_text_columns() -> None:
    _, css, js = sources()
    render = function_block(js, "function renderAttentionItems", "function renderMessageSummary")
    card = render.split('dashboard-growth-task dashboard-growth-opportunity">', 1)[1].split(
        "</article>", 1
    )[0]

    expected_order = (
        'class="dashboard-growth-opportunity__header"',
        'class="growth-opportunity-actions dashboard-growth-opportunity__actions"',
        'class="dashboard-growth-opportunity__description"',
        'class="dashboard-growth-opportunity__metadata"',
    )
    assert [card.index(fragment) for fragment in expected_order] == sorted(
        card.index(fragment) for fragment in expected_order
    )
    assert "ag-button--primary" in card
    assert "ag-button--secondary" in card
    assert "Preparar mensaje" in card
    assert "Ver oportunidad" in card

    layout = css.split(".dashboard-growth-opportunity {", 1)[1].split(".dashboard-next-booking", 1)[
        0
    ]
    assert "grid-template-columns: minmax(0, 1fr)" in layout
    assert "flex: 1 1 auto" in layout
    assert "width: 100%" in layout
    assert "min-width: 0" in layout
    assert "flex-wrap: wrap" in css
    assert "overflow-wrap: break-word" in layout
    assert "word-break: normal" in layout
    assert "word-break: break-all" not in layout


def test_growth_hierarchy_copy_and_results_are_honest() -> None:
    html, _, js = sources()
    positions = [
        html.index("Necesitan atención"),
        html.index('id="growth-opportunity-preview-title"'),
        html.index("Cambios que conviene revisar"),
        html.index("D · Resultados"),
    ]
    assert positions == sorted(positions)
    assert "Reservas vinculadas a acciones Growth" in html
    assert "Ingresos registrados en reservas vinculadas" in html
    assert 'viewed: "Acciones preparadas"' in js
    assert 'viewed: "Vistas"' not in js
    overview = function_block(
        js, "function renderGrowthOverview", "function renderGrowthOpportunities"
    )
    opportunities = function_block(
        js, "function renderGrowthOpportunities", "function renderGrowthActionMetrics"
    )
    assert "configurationTaskIds" in overview
    assert 'task.id.startsWith("channel-")' in overview
    assert "growth-operational-recommendations" not in opportunities
    assert "review-candidates" not in opportunities


def test_signals_distinguish_supported_actions_from_information() -> None:
    _, _, js = sources()
    render = function_block(
        js, "function renderBusinessGrowthSignals", "async function loadBusinessGrowthSignals"
    )

    assert "const related = signal.related_opportunities" in render
    assert "related ?" in render
    assert "Ver oportunidades relacionadas" in render
    assert "Información · no requiere una acción directa" in render
    assert "Tienes más huecos de lo habitual" in render
    assert "Están volviendo menos clientes" in render
    assert "Se acerca una fecha importante" in render


def test_customer_growth_is_scoped_hidden_when_empty_and_separate_from_memory() -> None:
    _, css, js = sources()
    growth = function_block(
        js, "function renderCustomerGrowthSection", "function renderConversationCustomerSearch"
    )
    panel = function_block(
        js, "function renderConversationCustomerPanel", "function openCustomerMemoryForm"
    )

    assert 'if (!customerId || !moduleAvailable("growth")) return ""' in growth
    assert 'if (!opportunities.length) return ""' in growth
    assert "Number(item.customer?.id) === Number(customerId)" in growth
    assert "Oportunidades activas" in growth
    assert "Preparar mensaje" in growth
    assert "Abrir oportunidad" in growth
    assert panel.index("renderCustomerGrowthSection") < panel.index("renderCustomerMemorySection")
    assert ".customer-growth" in css


def test_conversation_explains_follow_up_and_links_exact_opportunity() -> None:
    _, css, js = sources()
    context = function_block(
        js, "function renderConversationGrowthFollowUp", "function conversationFilterLabel"
    )
    detail = function_block(
        js, "function renderConversationDetail", "function customerMemoryCategoryLabel"
    )

    assert 'conversation.status === "closed" ? null' in context
    assert "opportunity.reason_text" in context
    assert "Este cliente requiere seguimiento porque" in context
    assert 'data-admin-action="view-growth-opportunity"' in context
    assert "renderConversationGrowthFollowUp(conversation)" in detail
    assert "focusGrowthOpportunity" in js
    assert ".conversation-growth-follow-up" in css


def test_growth_empty_states_explain_evaluation_cold_start_and_recurrence() -> None:
    _, _, js = sources()
    empty = function_block(
        js, "function growthOpportunityEmptyCopy", "function growthOpportunityPreviewMarkup"
    )

    assert "insufficient_history_or_not_evaluated" in empty
    assert "Todavía estamos aprendiendo de tu negocio" in empty
    assert "necesitan reservas anteriores" in empty
    assert "Configura cuándo suelen volver tus clientes" in empty
    assert "last_evaluated_at" in empty
    assert "Todo está al día" in empty


def test_new_growth_surfaces_keep_mobile_actions_unclipped() -> None:
    _, css, _ = sources()
    mobile = css.rsplit("@media (max-width: 639px)", 1)[1]

    assert ".conversation-growth-follow-up" in mobile
    assert ".customer-growth .ag-button" in mobile
    assert "width: 100%" in mobile
