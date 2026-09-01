from __future__ import annotations

import re
from datetime import date, timedelta

import pytest
from playwright.sync_api import Page, expect

pytestmark = pytest.mark.e2e


def _select_slot(page: Page) -> None:
    page.locator("#calendar-days button:enabled").first.click()
    expect(page.locator("#time-slots button").first).to_be_visible()
    page.locator("#time-slots button").first.click()


def complete_booking(page: Page, *, guest: bool, service: str = "Corte E2E") -> dict:
    expect(page.locator("#booking-form")).to_be_visible()
    page.locator("#booking-service-options .choice-button", has_text=service).click()
    any_staff = page.locator("#booking-staff-options .choice-button", has_text="Cualquier")
    expect(any_staff).to_be_visible()
    any_staff.click()
    page.locator("#booking-next").click()
    _select_slot(page)
    page.locator("#booking-next").click()
    if guest:
        expect(page.locator("#booking-step-customer")).to_be_visible()
        page.locator("#client-name").fill("Cliente Journey")
        page.locator("#client-phone").fill("612 345 679")
        page.locator("#booking-next").click()
    else:
        expect(page.locator("#booking-step-customer")).to_be_hidden()
    expect(page.locator("#booking-step-review")).to_be_visible()
    with page.expect_response(
        lambda response: response.request.method == "POST" and response.url.endswith("/bookings")
    ) as created:
        page.locator("#booking-submit").click()
    expect(page.locator("#booking-confirmation")).to_be_visible()
    return created.value.json()


def test_guest_booking_is_real_optional_auth_and_persists(journey) -> None:
    session = journey()
    page = session.goto("/autonogrow-landing/?b=salon-e2e&claim=1")
    expect(page.locator("#business-name")).to_have_text("Salón E2E")
    expect(page.get_by_text("Europe/Madrid", exact=False)).to_be_visible()
    result = complete_booking(page, guest=True)
    expect(page.get_by_text("Resultado de la reserva")).to_be_visible()
    expect(page.get_by_text("La próxima vez, aún más rápido")).to_be_visible()
    expect(page.get_by_text("Guarda tus citas y reserva sin volver", exact=False)).to_be_visible()
    expect(
        page.locator("#post-booking-google-button").get_by_role(
            "button", name="Continuar con Google"
        )
    ).to_be_visible()
    assert result["booking"]["id"] > 0
    assert result["booking_manage_token"]
    assert result["booking_manage_token_expires_at"]
    guest_attachments = page.request.get(
        f"/api/businesses/salon-e2e/bookings/{result['booking']['id']}/attachments",
        headers={"X-Booking-Token": result["booking_manage_token"]},
    )
    assert guest_attachments.status == 200
    response = page.request.get("/api/admin/businesses/salon-e2e/bookings")
    assert response.status == 401

    page.locator("#post-booking-google-button button").evaluate("button => button.click()")
    expect(page.locator("#post-booking-login-status")).to_contain_text("Cita guardada")
    home = page.request.get("/api/customer/home")
    assert home.status == 200
    assert result["booking"]["id"] in {item["id"] for item in home.json()["bookings"]}
    assert (
        page.request.get(
            f"/api/businesses/salon-e2e/bookings/{result['booking']['id']}/attachments"
        ).status
        == 200
    )

    replay = journey()
    replay_response = replay.page.request.get(
        f"/api/businesses/salon-e2e/bookings/{result['booking']['id']}/attachments",
        headers={"X-Booking-Token": result["booking_manage_token"]},
    )
    assert replay_response.status == 404
    assert replay_response.json()["detail"] == "El enlace ya no es válido."
    assert page.locator("#client-name").count() == 1


def test_controlled_google_login_uses_real_auth_endpoint(journey) -> None:
    session = journey()
    page = session.goto("/autonogrow-customer/")
    login = page.get_by_role("button", name="Continuar con Google")
    expect(login).to_be_visible()
    page.locator("#customer-google-button button").evaluate("button => button.click()")
    expect(page.locator("#customer-greeting")).to_have_text("Hola, María")
    assert page.request.get("/api/auth/me").status == 200
    expect(page.locator("#customer-auth-gate")).to_be_hidden()
    assert any(cookie["name"] == "autonogrow_session" for cookie in session.context.cookies())


def test_revocable_session_replay_multi_device_and_relogin(journey) -> None:
    first = journey()
    first_page = first.goto("/autonogrow-customer/")
    first_page.locator("#customer-google-button button").evaluate("button => button.click()")
    expect(first_page.locator("#customer-app")).to_be_visible()
    copied = next(
        cookie for cookie in first.context.cookies() if cookie["name"] == "autonogrow_session"
    )

    second = journey()
    second_page = second.goto("/autonogrow-customer/")
    second_page.locator("#customer-google-button button").evaluate("button => button.click()")
    expect(second_page.locator("#customer-app")).to_be_visible()

    first_page.locator("#customer-logout").click()
    expect(first_page.locator("#customer-auth-gate")).to_be_visible()
    first.context.add_cookies([copied])
    assert first_page.request.get("/api/auth/me").status == 401
    assert second_page.request.get("/api/auth/me").status == 200

    first_page.reload(wait_until="domcontentloaded")
    first_page.locator("#customer-google-button button").evaluate("button => button.click()")
    expect(first_page.locator("#customer-app")).to_be_visible()
    csrf = first_page.request.get("/api/auth/csrf").json()["csrf_token"]
    revoked = first_page.request.post("/api/auth/logout-all", headers={"X-CSRF-Token": csrf})
    assert revoked.status == 200
    assert first_page.request.get("/api/auth/me").status == 401
    assert second_page.request.get("/api/auth/me").status == 401

    second_page.reload(wait_until="domcontentloaded")
    second_page.locator("#customer-google-button button").evaluate("button => button.click()")
    expect(second_page.locator("#customer-app")).to_be_visible()
    assert second_page.request.get("/api/auth/me").status == 200


def test_authenticated_home_links_equivalent_phone_and_cross_business_data(journey) -> None:
    session = journey(email="customer@e2e.test")
    page = session.goto("/autonogrow-customer/")
    expect(page.locator("#customer-greeting")).to_have_text("Hola, María")
    expect(page.locator("#next-booking")).to_contain_text("Salón E2E")
    expect(page.locator("#recent-services")).to_contain_text("Corte E2E")
    expect(page.locator("#customer-calendar")).to_be_visible()
    start = date.today() - timedelta(days=10)
    end = date.today() + timedelta(days=45)
    home = page.request.get(f"/api/customer/home?from={start.isoformat()}&to={end.isoformat()}")
    assert home.ok
    assert {item["business_name"] for item in home.json()["bookings"]} == {
        "Salón E2E",
        "Fisio E2E",
    }
    profile = page.request.get("/api/customer/profile")
    assert profile.ok
    assert profile.json()["phone_normalized"] == "+34612345678"


def test_repeat_booking_shows_prefilled_details_and_updates_home(journey) -> None:
    session = journey(email="customer@e2e.test")
    page = session.goto("/autonogrow-customer/")
    page.locator("#recent-services").get_by_role("link", name="Repetir").first.click()
    expect(page).to_have_url(re.compile(r"service_id=\d+.*repeat=1|repeat=1.*service_id=\d+"))
    expect(page.locator("#business-name")).to_have_text("Salón E2E")
    expect(page.locator("#booking-step-datetime")).to_be_visible()
    _select_slot(page)
    page.locator("#booking-next").click()
    expect(page.locator("#booking-step-customer")).to_be_visible()
    expect(page.locator("#client-name")).to_have_value("María")
    expect(page.locator("#client-phone")).to_have_value("+34612345678")
    expect(page.locator("#notes")).to_be_visible()
    expect(page.locator("#notes")).to_have_value("")
    expect(page.locator("#booking-photos")).to_be_visible()
    assert page.locator("#booking-photos").evaluate("input => input.files.length") == 0
    page.locator("#notes").fill("Comentario exclusivo de esta nueva reserva")
    page.locator("#booking-next").click()
    expect(page.locator("#booking-step-review")).to_be_visible()
    expect(page.locator("#booking-review")).to_contain_text(
        "Comentario exclusivo de esta nueva reserva"
    )
    page.locator("#booking-submit").click()
    expect(page.locator("#booking-confirmation")).to_be_visible()
    page.get_by_role("link", name="Ir a Mis citas").click()
    expect(page.locator("#customer-greeting")).to_have_text("Hola, María")
    expect(page.locator("#next-booking")).to_contain_text("Corte E2E")


def test_customer_calendar_today_month_day_and_navigation(journey) -> None:
    session = journey(email="customer@e2e.test")
    page = session.goto("/autonogrow-customer/")
    month = page.get_by_role("tab", name="Mes")
    today = page.get_by_role("tab", name="Hoy")
    expect(month).to_have_attribute("aria-selected", "true")
    booking_day = page.locator('#customer-calendar button[aria-label*="1 citas"]').first
    expect(booking_day).to_be_visible()
    booking_day.click()
    expect(page.locator("#day-bookings")).to_contain_text(re.compile("Salón E2E|Fisio E2E"))
    period = page.locator("#calendar-period").inner_text()
    page.get_by_role("button", name="Mes siguiente").click()
    expect(page.locator("#calendar-period")).not_to_have_text(period)
    page.get_by_role("button", name="Mes anterior").click()
    expect(page.locator("#calendar-period")).to_have_text(
        re.compile(re.escape(period), re.IGNORECASE)
    )
    today.click()
    expect(today).to_have_attribute("aria-selected", "true")


def test_profile_session_persistence_and_logout(journey) -> None:
    session = journey(email="customer@e2e.test")
    page = session.goto("/autonogrow-customer/")
    page.get_by_text("Perfil y canales de contacto", exact=True).click()
    page.locator("#customer-preferred-name").fill("Mari E2E")
    page.locator("#customer-instagram").fill("@mari.e2e")
    page.locator("#save-customer-profile").click()
    expect(page.locator("#customer-profile-status")).to_contain_text("guard", ignore_case=True)
    page.reload(wait_until="domcontentloaded")
    expect(page.locator("#customer-greeting")).to_have_text("Hola, Mari")
    page.get_by_text("Perfil y canales de contacto", exact=True).click()
    expect(page.locator("#customer-instagram")).to_have_value("@mari.e2e")
    expect(page.locator("#customer-email")).to_have_attribute("readonly", "")
    page.locator("#customer-logout").click()
    expect(page.locator("#customer-auth-gate")).to_be_visible()
    expect(page.get_by_text("Vuelve sin empezar de cero")).to_be_visible()


def test_mobile_customer_critical_path_has_no_horizontal_overflow(journey) -> None:
    session = journey(mobile=True)
    page = session.goto("/autonogrow-landing/?b=salon-e2e")
    complete_booking(page, guest=True)
    assert page.evaluate("document.documentElement.scrollWidth <= window.innerWidth + 1")
    authenticated = journey(email="customer@e2e.test", mobile=True)
    portal = authenticated.goto("/autonogrow-customer/")
    expect(portal.locator("#customer-greeting")).to_be_visible()
    expect(portal.get_by_role("tab", name="Mes")).to_be_visible()
    assert portal.evaluate("document.documentElement.scrollWidth <= window.innerWidth + 1")
