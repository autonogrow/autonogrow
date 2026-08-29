from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
CUSTOMER_HTML = (ROOT / "autonogrow-customer" / "index.html").read_text(encoding="utf-8")
CUSTOMER_JS = (ROOT / "autonogrow-customer" / "customer.js").read_text(encoding="utf-8")
CUSTOMER_CSS = (ROOT / "autonogrow-customer" / "styles.css").read_text(encoding="utf-8")
LANDING_HTML = (ROOT / "autonogrow-landing" / "index.html").read_text(encoding="utf-8")
LANDING_JS = (ROOT / "autonogrow-landing" / "script.js").read_text(encoding="utf-8")
AUTH_ROUTER = (ROOT / "backend" / "app" / "routers" / "auth.py").read_text(encoding="utf-8")
BOOKING_ROUTER = (ROOT / "backend" / "app" / "routers" / "bookings.py").read_text(encoding="utf-8")


def test_identified_home_prioritizes_greeting_next_repeat_calendar_and_profile() -> None:
    positions = [
        CUSTOMER_HTML.index('id="customer-greeting"'),
        CUSTOMER_HTML.index('id="next-booking"'),
        CUSTOMER_HTML.index('id="recent-services"'),
        CUSTOMER_HTML.index('id="customer-calendar"'),
        CUSTOMER_HTML.index('class="profile-section"'),
    ]
    assert positions == sorted(positions)
    assert 'id="today-summary"' in CUSTOMER_HTML
    assert 'data-calendar-view="today"' in CUSTOMER_HTML
    assert 'data-calendar-view="month"' in CUSTOMER_HTML
    assert 'id="customer-day-agenda"' in CUSTOMER_HTML


def test_repeat_journey_keeps_optimizations_but_always_shows_booking_details() -> None:
    assert 'new URLSearchParams({ b: item.business_slug, repeat: "1" })' in CUSTOMER_JS
    assert 'params.set("service_id", String(item.service_id))' in CUSTOMER_JS
    assert 'new URLSearchParams(window.location.search).get("repeat") === "1"' in LANDING_JS
    assert 'showBookingStep("datetime")' in LANDING_JS
    next_step = LANDING_JS.split("function nextBookingStep", 1)[1].split(
        "async function submitBooking", 1
    )[0]
    assert "const next = BOOKING_STEPS[index + 1]" in next_step
    assert 'landingState.step === "datetime" && landingState.customerProfile' not in next_step
    assert 'next = "review"' not in next_step
    assert 'data-booking-step="customer"' in LANDING_HTML
    assert 'id="notes"' in LANDING_HTML
    assert 'id="booking-photos"' in LANDING_HTML


def test_known_customer_only_prefills_contact_data_for_the_current_booking() -> None:
    profile = LANDING_JS.split("function applyKnownCustomerProfile", 1)[1].split(
        "async function claimPendingBooking", 1
    )[0]
    assert 'byId("client-name").value = name' in profile
    assert 'byId("client-phone").value = phone' in profile
    for historical_value in ("profile.notes", "profile.files", "profile.attachments"):
        assert historical_value not in profile
    assert 'customer: { name: "", phone: "", notes: "", files: [] }' in LANDING_JS


def test_guest_booking_remains_available_and_login_is_post_value_optional() -> None:
    assert "get_optional_current_user" in BOOKING_ROUTER
    assert 'current_user: User | None = Depends(get_optional_current_user)' in BOOKING_ROUTER
    assert 'id="booking-form"' in LANDING_HTML
    assert "La próxima vez, aún más rápido" in LANDING_JS
    assert "Guarda tus citas y reserva sin volver a rellenar tus datos" in LANDING_JS
    assert "/api/customer/claim-booking" in LANDING_JS
    assert "Crea una cuenta para continuar" not in f"{LANDING_HTML}\n{LANDING_JS}"


def test_google_bootstraps_but_does_not_overwrite_a_custom_name() -> None:
    assert "google_sub = str(claims.get(\"sub\")" in AUTH_ROUTER
    assert "if not user.preferred_name:" in AUTH_ROUTER
    assert 'user.name = claims.get("name") or user.name' in AUTH_ROUTER
    assert 'requestJson("/api/customer/profile"' in LANDING_JS
    assert "applyKnownCustomerProfile(profile)" in LANDING_JS
    assert 'byId("client-name").value = name' in LANDING_JS


def test_profile_is_minimal_instagram_optional_and_email_read_only() -> None:
    for element_id in (
        "customer-preferred-name",
        "customer-phone",
        "customer-email",
        "customer-instagram",
    ):
        assert f'id="{element_id}"' in CUSTOMER_HTML
    assert 'id="customer-email" type="email" readonly' in CUSTOMER_HTML
    assert "Instagram <span>opcional</span>" in CUSTOMER_HTML
    for forbidden in ("Fecha de nacimiento", "Género", "Intereses", "TikTok"):
        assert forbidden not in CUSTOMER_HTML


def test_calendar_is_personal_compact_accessible_and_mobile_first() -> None:
    assert 'role="tablist" aria-label="Vista del calendario"' in CUSTOMER_HTML
    assert 'aria-live="polite"' in CUSTOMER_HTML
    assert "button.setAttribute(\"aria-label\"" in CUSTOMER_JS
    assert "items.length > 1 ? String(items.length)" in CUSTOMER_JS
    assert "renderDay(key)" in CUSTOMER_JS
    assert "@media (max-width: 390px)" in CUSTOMER_CSS
    assert "overflow-x: hidden" in CUSTOMER_CSS
    assert "font-size: 16px" in CUSTOMER_CSS
    assert "grid-template-columns: repeat(7, minmax(0, 1fr))" in CUSTOMER_CSS


def test_customer_home_uses_one_aggregate_range_request_and_human_errors() -> None:
    assert "/api/customer/home?from=${range.from}&to=${range.to}" in CUSTOMER_JS
    assert "/api/customer/bookings/" not in CUSTOMER_JS
    for text in (
        "Tu sesión ha caducado",
        "No tienes próximas citas",
        "Aún no tienes servicios anteriores",
        "Hoy no tienes citas",
        "No se pudo conectar",
    ):
        assert text in CUSTOMER_JS


def test_logout_profile_and_dynamic_content_keep_security_contracts() -> None:
    assert "AutonoGrowAuth.logout()" in CUSTOMER_JS
    assert "AutonoGrowAuth.secureRequestOptions" in CUSTOMER_JS
    assert 'method: "PATCH"' in CUSTOMER_JS
    assert 'event.key === "Escape"' in CUSTOMER_JS
    assert 'event.key !== "Tab"' in CUSTOMER_JS
    for forbidden in ("innerHTML", "localStorage", "sessionStorage", "access_token"):
        assert forbidden not in f"{CUSTOMER_JS}\n{LANDING_JS}"
