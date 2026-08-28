from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
OWNER_HTML = (ROOT / "autonogrow-owner" / "index.html").read_text(encoding="utf-8")
OWNER_JS = (ROOT / "autonogrow-owner" / "owner.js").read_text(encoding="utf-8")
OWNER_CSS = (ROOT / "autonogrow-owner" / "styles.css").read_text(encoding="utf-8")
ADMIN_HTML = (ROOT / "autonogrow-admin" / "index.html").read_text(encoding="utf-8")
ADMIN_JS = (ROOT / "autonogrow-admin" / "admin.js").read_text(encoding="utf-8")
ADMIN_CSS = (ROOT / "autonogrow-admin" / "styles.css").read_text(encoding="utf-8")


def test_owner_editorial_calendar_has_periods_filters_attention_and_composer() -> None:
    for view in ("today", "week", "month"):
        assert f'data-owner-instagram-view="{view}"' in OWNER_HTML
    assert 'id="owner-instagram-state-filter"' in OWNER_HTML
    assert 'id="owner-instagram-format-filter"' in OWNER_HTML
    assert 'id="owner-instagram-attention"' in OWNER_HTML
    assert 'id="owner-instagram-unscheduled"' in OWNER_HTML
    assert 'id="owner-instagram-composer"' in OWNER_HTML
    assert 'id="owner-instagram-create"' in OWNER_HTML
    assert "function renderOwnerInstagramCalendar" in OWNER_JS
    assert "function openOwnerInstagramContentDetail" in OWNER_JS
    assert "function openOwnerInstagramComposer" in OWNER_JS
    assert 'data-owner-instagram-create-date="${key}"' in OWNER_JS
    assert "ownerInstagramComposerPatchDate" in OWNER_JS
    assert "contents/${content.id}/schedule" in OWNER_JS
    assert 'multiple = state.format === "carousel"' in OWNER_JS
    assert 'data-owner-composer-move="-1"' in OWNER_JS
    assert 'data-owner-composer-preview="previous"' in OWNER_HTML
    assert "Necesita tu atención" not in OWNER_HTML
    assert "Todo preparado para esta semana" in OWNER_JS


def test_business_admin_calendar_keeps_editorial_permissions_narrow() -> None:
    for view in ("today", "week", "month"):
        assert f'data-admin-instagram-view="{view}"' in ADMIN_HTML
    assert 'id="admin-instagram-state-filter"' in ADMIN_HTML
    assert 'id="admin-instagram-format-filter"' in ADMIN_HTML
    assert "function renderAdminInstagramCalendar" in ADMIN_JS
    assert "function adminInstagramCalendarBlock" in ADMIN_JS
    block = ADMIN_JS.split("function adminInstagramCalendarBlock", 1)[1].split(
        "function renderAdminInstagramCalendar", 1
    )[0]
    assert "Revisar" in block
    assert "data-owner-instagram-action" not in block
    assert "Dar visto bueno" in ADMIN_JS
    assert "Visto bueno del negocio" in ADMIN_JS
    assert "/editorial-review" in ADMIN_JS
    assert "data-admin-instagram-publication" not in ADMIN_JS
    assert ADMIN_HTML.index('id="admin-instagram-planning-title"') < ADMIN_HTML.index(
        'id="social-content-ideas-title"'
    )


def test_business_admin_review_reveals_only_action_specific_inputs() -> None:
    for marker in (
        "Añadir comentario",
        "¿Qué quieres que cambiemos?",
        "Cuéntanos brevemente por qué",
        "Confirmar solicitud",
        "Confirmar rechazo",
        "Confirmar detención",
        "data-admin-instagram-comment-panel hidden",
        'data-admin-instagram-review-panel="changes_requested" hidden',
        'data-admin-instagram-review-panel="reject" hidden',
        "data-admin-instagram-hold-panel hidden",
    ):
        assert marker in ADMIN_JS
    assert "Nota para AutonoGrow" not in ADMIN_JS
    assert 'name="decision" value="approve"' in ADMIN_JS


def test_owner_raw_dependency_modal_exposes_lifecycle_actions_and_meaning() -> None:
    for marker in (
        'id="owner-instagram-associations-retire"',
        'id="owner-instagram-associations-delete"',
        "Retirar de biblioteca",
        "Eliminar definitivamente",
        "USO ACTUAL",
        "HISTÓRICO",
        "current_physical_dependency",
        "can_disassociate",
    ):
        assert marker in OWNER_HTML or marker in OWNER_JS


def test_editorial_calendars_use_bounded_ranges_without_detail_request_fanout() -> None:
    assert 'include_unscheduled: "true"' in OWNER_JS
    assert 'include_unscheduled: "true"' in ADMIN_JS
    assert "contents?${range.toString()}" in OWNER_JS
    assert "contents?${adminInstagramCalendarQuery().toString()}" in ADMIN_JS
    assert "Promise.all(contentList.contents.map" not in ADMIN_JS


def test_editorial_states_are_not_expressed_by_color_alone() -> None:
    for js in (OWNER_JS, ADMIN_JS):
        assert "instagram-calendar-item__state" in js
        assert "instagram-calendar-item__action" in js
        assert "aria-label" in js
    for css in (OWNER_CSS, ADMIN_CSS):
        assert ".instagram-calendar-item--attention" in css
        assert ".instagram-calendar-item:focus-visible" in css


def test_editorial_calendars_collapse_week_and_month_density_on_mobile() -> None:
    for css in (OWNER_CSS, ADMIN_CSS):
        assert "@media (max-width: 760px)" in css
        assert ".instagram-calendar--week { grid-template-columns: 1fr; }" in css
        assert ".instagram-month-day .instagram-calendar-item__body { display: none; }" in css
        assert ".instagram-unscheduled > div:last-child { grid-template-columns: 1fr; }" in css
