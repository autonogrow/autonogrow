from __future__ import annotations

import json
import re

import pytest
from playwright.sync_api import expect

pytestmark = pytest.mark.e2e


def _document_geometry(page) -> dict:
    return page.evaluate(
        """() => {
          const root = document.documentElement;
          const candidates = [...document.querySelectorAll('body *')]
            .filter((element) => {
              const style = getComputedStyle(element);
              const rect = element.getBoundingClientRect();
              return style.display !== 'none'
                && style.visibility !== 'hidden'
                && rect.width > 0
                && (rect.left < -1 || rect.right > root.clientWidth + 1);
            })
            .map((element) => {
              const style = getComputedStyle(element);
              const rect = element.getBoundingClientRect();
              return {
                tag: element.tagName,
                id: element.id,
                className: String(element.className || ''),
                left: rect.left,
                right: rect.right,
                width: rect.width,
                minWidth: style.minWidth,
                computedWidth: style.width,
                gridTemplateColumns: style.gridTemplateColumns,
                overflowX: style.overflowX,
                parent: element.parentElement ? {
                  tag: element.parentElement.tagName,
                  id: element.parentElement.id,
                  className: String(element.parentElement.className || ''),
                  rect: element.parentElement.getBoundingClientRect().toJSON(),
                  minWidth: getComputedStyle(element.parentElement).minWidth,
                  computedWidth: getComputedStyle(element.parentElement).width,
                  gridTemplateColumns: getComputedStyle(element.parentElement).gridTemplateColumns,
                } : null,
              };
            })
            .sort((left, right) => right.right - left.right)
            .slice(0, 12);
          return {
            viewportWidth: innerWidth,
            clientWidth: root.clientWidth,
            scrollWidth: root.scrollWidth,
            overflow: root.scrollWidth - root.clientWidth,
            candidates,
          };
        }"""
    )


def _assert_document_fits(page) -> None:
    geometry = _document_geometry(page)
    assert geometry["scrollWidth"] <= geometry["clientWidth"] + 1, json.dumps(
        geometry, ensure_ascii=False, indent=2
    )


def _open_admin(journey, email: str = "admin-a@e2e.test"):
    session = journey(email=email)
    page = session.goto("/autonogrow-admin/?b=salon-e2e#bookings")
    expect(page.locator("#admin-app")).to_be_visible()
    expect(page.locator("#business-name")).to_have_text("Salón E2E")
    return page


@pytest.mark.parametrize(
    ("section", "ready_selector"),
    (
        ("bookings", "#bookings-list"),
        ("schedule", "#weekly-schedule-editor"),
        ("channels", "#channel-onboarding-list"),
        ("messages", "#conversation-automation-content"),
    ),
)
def test_admin_critical_sections_fit_responsive_matrix(
    journey, section: str, ready_selector: str
) -> None:
    page = _open_admin(journey)
    page.evaluate("section => showAdminSection(section, 'replace')", section)
    active = page.locator(f'[data-admin-section="{section}"]')
    expect(active).to_have_class(re.compile(r"\badmin-section-active\b"))
    expect(page.locator(ready_selector)).to_be_visible()
    for viewport in (
        {"width": 1920, "height": 1080},
        {"width": 1440, "height": 900},
        {"width": 1280, "height": 800},
        {"width": 1024, "height": 768},
        {"width": 768, "height": 1024},
        {"width": 430, "height": 932},
        {"width": 390, "height": 844},
        {"width": 375, "height": 667},
    ):
        page.set_viewport_size(viewport)
        expect(active).to_be_visible()
        _assert_document_fits(page)


@pytest.mark.parametrize(
    "viewport",
    (
        pytest.param({"width": 1920, "height": 1080}, id="1920x1080"),
        pytest.param({"width": 1440, "height": 900}, id="1440x900"),
        pytest.param({"width": 1280, "height": 800}, id="1280x800"),
        pytest.param({"width": 1024, "height": 768}, id="1024x768"),
        pytest.param({"width": 768, "height": 1024}, id="768x1024"),
        pytest.param({"width": 430, "height": 932}, id="430x932"),
        pytest.param({"width": 390, "height": 844}, id="390x844"),
        pytest.param({"width": 375, "height": 667}, id="375x667"),
    ),
)
def test_owner_activation_fits_supported_viewports(journey, viewport: dict[str, int]) -> None:
    session = journey(email="owner@e2e.test")
    page = session.goto("/autonogrow-owner/")
    page.set_viewport_size(viewport)
    expect(page.locator("#owner-app")).to_be_visible()
    page.evaluate("setActiveTab('businesses')")
    page.evaluate(
        "openBusinessDetail(businesses.find(item => item.name === 'Salón E2E').id, 'activation')"
    )
    activation = page.locator('[data-owner-detail-panel="activation"]')
    expect(activation).to_be_visible()
    expect(activation.locator(".readiness-item").first).to_be_visible()
    _assert_document_fits(page)


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
        pytest.param({"width": 1280, "height": 800}, id="1280x800"),
        pytest.param({"width": 390, "height": 844}, id="390x844"),
        pytest.param({"width": 375, "height": 667}, id="375x667"),
    ),
)
def test_mobile_reschedule_calendar_has_usable_day_targets(
    journey, email: str, viewport: dict[str, int]
) -> None:
    page = _open_admin(journey, email=email)
    page.set_viewport_size(viewport)
    page.locator('[data-agenda-nav="1"]').click()
    booking = page.locator("[data-agenda-booking-open]:visible").first
    expect(booking).to_be_visible()
    booking.click()
    reschedule = page.locator('[data-booking-action="reschedule"]:visible').first
    expect(reschedule).to_be_visible()
    reschedule.click()

    modal = page.locator("#reschedule-modal.open")
    days = modal.locator(".calendar-day")
    expect(modal).to_be_visible()
    expect(days.first).to_be_visible()
    sizes = days.evaluate_all(
        "items => items.map(item => { const rect = item.getBoundingClientRect(); "
        "return { width: rect.width, height: rect.height }; })"
    )
    assert len(sizes) >= 7
    assert min(item["width"] for item in sizes) >= 44, sizes
    assert min(item["height"] for item in sizes) >= 44, sizes
    _assert_document_fits(page)

    expect(days.first).to_have_attribute("aria-current", "date")
    unavailable = days.nth(2)
    unavailable.evaluate("element => { element.disabled = true; }")
    expect(unavailable).to_have_css("cursor", "not-allowed")

    days.nth(1).click()
    expect(days.nth(1)).to_have_attribute("aria-pressed", "true")
    expect(page.locator("#reschedule-slots")).not_to_have_attribute("aria-busy", "true")
    slot = page.locator("#reschedule-slots .time-slot").first
    expect(slot).to_be_visible()
    slot.click()
    expect(page.locator("#reschedule-selection-summary")).to_be_visible()
    confirm = page.locator("#confirm-reschedule-button")
    expect(confirm).to_be_enabled()
    confirm.scroll_into_view_if_needed()
    confirm_geometry = confirm.evaluate(
        "element => { const rect = element.getBoundingClientRect(); "
        "return { top: rect.top, bottom: rect.bottom, viewportHeight: innerHeight }; }"
    )
    assert confirm_geometry["top"] >= 0, confirm_geometry
    assert confirm_geometry["bottom"] <= confirm_geometry["viewportHeight"] + 1, confirm_geometry
    expect(page.locator("#reschedule-modal .ag-modal__close")).to_be_visible()
    if email == "pro-1@e2e.test":
        page.locator("#reschedule-modal .ag-modal__close").click()
        expect(modal).to_be_hidden()
        return

    page.once("dialog", lambda dialog: dialog.accept())
    with page.expect_response(
        lambda response: response.request.method == "PATCH" and "/reschedule" in response.url
    ) as rescheduled:
        confirm.click()
    assert rescheduled.value.status == 200
    expect(modal).to_be_hidden()
