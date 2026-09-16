from __future__ import annotations

import json
import re

import pytest
from playwright.sync_api import expect

pytestmark = pytest.mark.e2e


def _open_admin(journey, email="admin-a@e2e.test"):
    session = journey(email=email)
    page = session.goto("/autonogrow-admin/?b=salon-e2e#bookings")
    expect(page.locator("#admin-app")).to_be_visible()
    expect(page.locator("#business-name")).to_have_text("Salón E2E")
    return page


@pytest.mark.parametrize(
    "email",
    (
        pytest.param("admin-a@e2e.test", id="admin"),
        pytest.param("pro-1@e2e.test", id="staff"),
    ),
)
@pytest.mark.parametrize(
    "viewport",
    (
        pytest.param({"width": 430, "height": 932}, id="430x932"),
        pytest.param({"width": 390, "height": 844}, id="390x844"),
        pytest.param({"width": 375, "height": 667}, id="375x667"),
        pytest.param({"width": 768, "height": 1024}, id="768x1024"),
        pytest.param({"width": 1440, "height": 900}, id="1440x900"),
    ),
)
def test_growth_modal_opens_at_context_and_contains_focus(journey, viewport, email) -> None:
    page = _open_admin(journey, email)
    page.set_viewport_size(viewport)
    page.evaluate("showAdminSection('growth-opportunities', 'replace')")
    expect(page.locator("#growth-tasks-list")).not_to_have_attribute("aria-busy", "true")
    opportunity = page.locator("[data-customer-opportunity]").first
    trigger = opportunity.get_by_role(
        "button", name=re.compile("Preparar mensaje|Continuar borrador")
    )
    trigger.click()

    modal = page.locator("#growth-action-modal.open")
    expect(modal).to_be_visible()
    expect(page.locator("#growth-action-modal-title")).to_be_focused()
    state = modal.evaluate(
        """element => {
          const body = element.querySelector('.growth-action-modal__body');
          const title = element.querySelector('#growth-action-modal-title').getBoundingClientRect();
          const explanation = element.querySelector('#growth-action-modal-description').getBoundingClientRect();
          const context = element.querySelector('.growth-action-context').getBoundingClientRect();
          const card = element.querySelector('.growth-action-modal-card');
          return {
            scrollTop: body.scrollTop,
            title: { top: title.top, bottom: title.bottom },
            explanation: { top: explanation.top, bottom: explanation.bottom },
            context: { top: context.top, bottom: context.bottom },
            body: body.getBoundingClientRect().toJSON(),
            card: card.getBoundingClientRect().toJSON(),
            gridRows: getComputedStyle(card).gridTemplateRows,
            children: [...card.children].map(child => ({
              tag: child.tagName,
              className: child.className,
              rect: child.getBoundingClientRect().toJSON(),
            })),
            activeElement: document.activeElement.id,
            viewportHeight: innerHeight,
          };
        }"""
    )
    assert state["scrollTop"] == 0, json.dumps(state, ensure_ascii=False, indent=2)
    assert state["activeElement"] == "growth-action-modal-title", state
    assert 0 <= state["title"]["top"] < state["title"]["bottom"] <= state["viewportHeight"]
    assert 0 <= state["explanation"]["top"] < state["explanation"]["bottom"] <= state["viewportHeight"]
    assert state["body"]["top"] >= state["explanation"]["bottom"], json.dumps(
        state, ensure_ascii=False, indent=2
    )
    assert state["context"]["top"] >= state["body"]["top"] - 1
    assert state["context"]["top"] < state["body"]["bottom"]

    page.keyboard.press("Tab")
    expect(page.locator("#growth-action-text")).to_be_focused()
    for _ in range(11):
        page.keyboard.press("Tab")
        assert modal.evaluate("element => element.contains(document.activeElement)")
    page.keyboard.press("Escape")
    expect(modal).to_be_hidden()
    assert trigger.evaluate("element => document.activeElement === element")


@pytest.mark.parametrize(
    "viewport",
    (
        pytest.param({"width": 1440, "height": 900}, id="1440x900"),
        pytest.param({"width": 1024, "height": 768}, id="1024x768"),
        pytest.param({"width": 390, "height": 844}, id="390x844"),
    ),
)
def test_automation_rule_selects_have_20_unique_contextual_names(
    journey, viewport
) -> None:
    page = _open_admin(journey)
    page.set_viewport_size(viewport)
    page.evaluate("showAdminSection('messages', 'replace')")
    panel = page.locator("#conversation-automation-content")
    expect(panel).to_be_visible()
    expect(panel).not_to_have_attribute("aria-busy", "true")

    controls = panel.locator(
        ".conversation-automation-rule-mode, .conversation-automation-rule-template"
    )
    expect(controls).to_have_count(20)
    inventory = controls.evaluate_all(
        r"""elements => elements.map(element => ({
          id: element.id,
          name: element.getAttribute('aria-labelledby')
            .split(/\s+/)
            .map(id => document.getElementById(id)?.textContent.trim() || '')
            .filter(Boolean)
            .join(' '),
        }))"""
    )
    ids = [item["id"] for item in inventory]
    names = [item["name"] for item in inventory]
    assert all(ids) and len(set(ids)) == 20, inventory
    assert all(names) and len(set(names)) == 20, inventory


def test_automation_rule_changes_survive_save_and_rerender(journey) -> None:
    page = _open_admin(journey)
    page.evaluate("showAdminSection('messages', 'replace')")
    panel = page.locator("#conversation-automation-content")
    expect(panel).not_to_have_attribute("aria-busy", "true")
    row = panel.locator("[data-automation-intent]").first
    intent = row.get_attribute("data-automation-intent")
    assert intent
    mode = row.locator(".conversation-automation-rule-mode")
    template = row.locator(".conversation-automation-rule-template")
    target_mode = "semi_automatic" if mode.input_value() != "semi_automatic" else "disabled"
    template_values = template.locator("option").evaluate_all(
        "options => options.map(option => option.value)"
    )
    target_template = next(
        (value for value in template_values if value != template.input_value()),
        template.input_value(),
    )
    active = row.locator(".conversation-automation-rule-active")
    if active.is_checked():
        active.uncheck()
    mode.select_option(target_mode)
    template.select_option(target_template)

    with page.expect_response(
        lambda response: response.request.method == "PATCH"
        and f"/conversation-automation/rules/{intent}" in response.url
    ) as saved:
        row.get_by_role("button", name="Guardar").click()
    assert saved.value.status == 200
    expect(page.locator("#channel-automations-errors")).to_contain_text("actualizada")
    rerendered = panel.locator(f'[data-automation-intent="{intent}"]')
    expect(rerendered.locator(".conversation-automation-rule-mode")).to_have_value(target_mode)
    expect(rerendered.locator(".conversation-automation-rule-template")).to_have_value(
        target_template
    )


def test_owner_readiness_mixed_states_follow_the_semantic_contract(journey) -> None:
    session = journey(email="owner@e2e.test")
    page = session.goto("/autonogrow-owner/")
    expect(page.locator("#owner-app")).to_be_visible()
    page.evaluate("setActiveTab('businesses')")
    page.evaluate(
        "openBusinessDetail(businesses.find(item => item.name === 'Salón E2E').id, 'activation')"
    )
    content = page.locator("[data-owner-readiness-content]")
    expect(content.locator(".readiness-item").first).to_be_visible()
    page.evaluate(
        """() => {
          const checks = [
            { key: 'ok', label: 'Identidad', status: 'passed', blocking: false,
              message: 'Todo está bien', remediation: 'No debe mostrarse', related_step: 'business_identity' },
            { key: 'recommended', label: 'Contacto', status: 'warning', blocking: false,
              message: 'Falta un canal público', remediation: 'Añade un teléfono', related_step: 'contact_and_location' },
            { key: 'blocking', label: 'Servicios', status: 'failed', blocking: true,
              message: 'No hay servicios', remediation: 'Crea un servicio', related_step: 'services' },
            { key: 'optional', label: 'Automatizaciones', status: 'not_applicable', blocking: false,
              message: 'Automatizaciones desactivadas', remediation: 'No debe mostrarse', related_step: 'automations' },
          ];
          document.querySelector('[data-owner-readiness-content]').innerHTML =
            checks.map(ownerReadinessCheckMarkup).join('');
        }"""
    )

    passed = content.locator(".readiness-item.passed")
    expect(passed).to_contain_text("Correcto")
    expect(passed.locator("p, small, button")).to_have_count(0)
    warning = content.locator(".readiness-item.warning")
    expect(warning).to_contain_text("Recomendado")
    expect(warning.locator("p, [data-owner-readiness-step]")).to_have_count(2)
    failed = content.locator(".readiness-item.failed")
    expect(failed).to_contain_text("Bloqueante")
    expect(failed.locator("p, small, [data-owner-readiness-step]")).to_have_count(3)
    optional = content.locator(".readiness-item.not_applicable")
    expect(optional).to_contain_text("No aplica")
    expect(optional.locator("small, button")).to_have_count(0)
