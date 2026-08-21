from __future__ import annotations

import re
from html.parser import HTMLParser
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
LANDING = ROOT / "autonogrow-landing"
CUSTOMER = ROOT / "autonogrow-customer"
LANDING_HTML = LANDING / "index.html"
LANDING_JS = LANDING / "script.js"
LANDING_CSS = LANDING / "styles.css"
CUSTOMER_HTML = CUSTOMER / "index.html"
CUSTOMER_JS = CUSTOMER / "customer.js"
CUSTOMER_CSS = CUSTOMER / "styles.css"
BUSINESS_ROUTER = ROOT / "backend" / "app" / "routers" / "businesses.py"
SERVICE_ROUTER = ROOT / "backend" / "app" / "routers" / "services.py"
SERVICE_SCHEMA = ROOT / "backend" / "app" / "schemas" / "service.py"
STAFF_ROUTER = ROOT / "backend" / "app" / "routers" / "staff.py"
BOOKING_ROUTER = ROOT / "backend" / "app" / "routers" / "bookings.py"
CUSTOMER_ROUTER = ROOT / "backend" / "app" / "routers" / "customer.py"
BOOKING_SERVICE = ROOT / "backend" / "app" / "services" / "booking_service.py"
DOC = ROOT / "docs" / "ux" / "26_public_landing_booking.md"


class Inventory(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.ids: list[str] = []
        self.links: list[dict[str, str | None]] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        values = dict(attrs)
        if values.get("id"):
            self.ids.append(str(values["id"]))
        if tag == "a":
            self.links.append(values)


def sources() -> tuple[str, str, str, str, str, str]:
    return (
        LANDING_HTML.read_text(encoding="utf-8"),
        LANDING_JS.read_text(encoding="utf-8"),
        LANDING_CSS.read_text(encoding="utf-8"),
        CUSTOMER_HTML.read_text(encoding="utf-8"),
        CUSTOMER_JS.read_text(encoding="utf-8"),
        CUSTOMER_CSS.read_text(encoding="utf-8"),
    )


def block(source: str, start: str, end: str) -> str:
    return source.split(start, 1)[1].split(end, 1)[0]


def test_public_architecture_has_identity_and_only_one_guided_booking_flow() -> None:
    html, js, _, _, _, _ = sources()
    for section in (
        "information",
        "services",
        "team",
        "gallery-section",
        "location",
        "reviews",
        "booking",
        "contact",
    ):
        assert html.count(f'id="{section}"') == 1
    for step in ("service", "staff", "datetime", "customer", "review"):
        assert html.count(f'data-booking-step="{step}"') == 1
    assert html.count('id="booking-form"') == 1
    assert js.count('addEventListener("submit", submitBooking)') == 1
    assert "const bookingState = {" in js
    for key in ("business", "service", "staff", "date", "slot", "customer", "booking"):
        assert re.search(rf"^  {key}:", js, re.MULTILINE)
    for legacy in ("let selectedService", "let selectedDate", "let selectedSlot"):
        assert legacy not in js


def test_business_load_uses_active_public_contract_and_safe_unavailable_state() -> None:
    _, js, _, _, _, _ = sources()
    router = BUSINESS_ROUTER.read_text(encoding="utf-8")
    assert 'Business.status == "active"' in router
    assert 'requestJson(`/api/businesses/${encodeURIComponent(slug)}`' in js
    assert "Este negocio no está disponible para reservas en este momento." in js
    unavailable = block(js, "function showUnavailable", "async function loadPublicBusiness")
    for forbidden in ("business_id", "traceback", "SQL", "endpoint"):
        assert forbidden not in unavailable


def test_public_tenant_requires_an_explicit_valid_slug_without_demo_fallback() -> None:
    _, js, _, _, _, _ = sources()
    resolver = block(js, "function getBusinessSlug", "function safeExternalUrl")
    loader = block(js, "async function loadPublicBusiness", "async function loadSecondarySources")
    assert '.get("b");' in resolver
    assert 'if (!value) return "";' in resolver
    assert '|| "demo-manicura"' not in resolver
    assert "? value : \"\"" in resolver
    assert loader.index("if (!slug)") < loader.index("requestJson(")
    assert loader.index('showUnavailable("not-found")') < loader.index("requestJson(")


def test_preview_and_inactive_pages_are_not_simulated() -> None:
    html, js, _, _, _, _ = sources()
    assert '<meta name="robots" content="noindex, nofollow"' in html
    assert 'business.status !== "active"' in js
    assert 'content = "noindex, nofollow"' in js
    assert "/preview" not in js
    assert "preview=" not in js


def test_identity_metadata_colors_and_images_are_safely_applied() -> None:
    html, js, _, _, _, _ = sources()
    for element_id in (
        "business-logo",
        "business-name",
        "business-category",
        "business-headline",
        "business-description",
        "business-city-hero",
    ):
        assert f'id="{element_id}"' in html
    assert "function safeColor" in js and "/^#[0-9a-f]{6}$/i" in js
    assert "function colorText" in js
    assert "function safeMediaUrl" in js and 'value.startsWith("/uploads/")' in js
    assert 'image.addEventListener("error"' in js
    assert 'image.loading = "lazy"' in js
    assert "textContent" in block(js, "function setText", "function applyBranding")


def test_services_show_real_duration_and_do_not_turn_missing_price_into_zero() -> None:
    _, js, _, _, _, _ = sources()
    services = block(js, "function servicePrice", "function renderStaff")
    assert 'return service.price_text ? String(service.price_text) : "Precio no indicado"' in services
    assert "service.duration_minutes" in services
    assert "0 €" not in services
    assert "No hay servicios disponibles para reserva online." in js
    assert ".filter(isValidPublicService)" in js


def test_public_services_contract_requires_staff_verification_for_reservability() -> None:
    _, js, _, _, _, _ = sources()
    service_router = SERVICE_ROUTER.read_text(encoding="utf-8")
    service_schema = SERVICE_SCHEMA.read_text(encoding="utf-8")
    staff_router = STAFF_ROUTER.read_text(encoding="utf-8")

    assert "BusinessService.active == True" in service_router
    service_out = block(service_schema, "class ServiceOut", "class AdminServiceCreate")
    for absent_field in ("visible", "bookable", "archived_at"):
        assert absent_field not in service_out

    basic_validation = block(js, "function isValidPublicService", "function setSafeLink")
    for condition in (
        "service.active !== false",
        "Number.isInteger(serviceId)",
        "serviceId > 0",
        'typeof service.name === "string"',
    ):
        assert condition in basic_validation
    for unavailable_signal in ("visible", "bookable", "archived_at"):
        assert unavailable_signal not in basic_validation

    verification = block(js, "async function verifyReservableServices", "function setVerifiedServices")
    assert ".filter(isValidPublicService)" in verification
    assert "await loadCompatibleStaffCached(slug, service.id)" in verification
    assert "if (staff.length > 0) verified[index] = service" in verification
    assert "services: verified.filter(Boolean)" in verification
    assert "for item in get_public_bookable_staff(db, business.id, service_id)" in staff_router


def test_verified_service_outcomes_exclude_empty_and_failed_staff_checks() -> None:
    _, js, _, _, _, _ = sources()
    verification = block(js, "async function verifyReservableServices", "function setVerifiedServices")
    loader = block(js, "async function loadVerifiedReservableServices", "async function loadPublicBusiness")

    def verified_services(outcomes: list[tuple[str, list[object] | Exception]]) -> list[str]:
        return [name for name, staff in outcomes if isinstance(staff, list) and len(staff) > 0]

    public_staff = [{"id": 10, "public_name": "Ana"}]
    assert verified_services([("Manicura", public_staff)]) == ["Manicura"]
    assert verified_services([("Manicura", [])]) == []
    assert verified_services([("Manicura", RuntimeError("source unavailable"))]) == []
    assert verified_services(
        [
            ("Manicura", public_staff),
            ("Pedicura", []),
            ("Decoración", RuntimeError("source unavailable")),
        ]
    ) == ["Manicura"]

    assert "failedCount += 1" in verification
    assert "result.failedCount === result.candidatesCount" in loader
    assert "No se pudieron comprobar los servicios reservables. Vuelve a intentarlo." in loader
    assert "No hay servicios disponibles para reserva online." in loader
    assert "Algunos servicios no se pudieron comprobar. Solo mostramos los verificados." in loader


def test_cta_stays_hidden_until_at_least_one_service_is_verified() -> None:
    html, js, _, _, _, _ = sources()
    availability = block(js, "function updateBookingAvailability", "function showBookingMessage")
    assert 'const verificationComplete = ["ready", "partial"].includes' in availability
    assert "const available = verificationComplete" in availability
    assert 'landingState.serviceVerificationStatus === "checking"' in availability
    assert "Comprobando servicios disponibles…" in availability
    assert 'byId("booking-form").hidden = !available' in availability
    assert 'byId("nav-booking-button").hidden = !available' in availability
    assert 'byId("hero-booking-button").hidden = !available' in availability
    assert 'byId("mobile-booking-cta").hidden = !available' in availability
    assert 'document.querySelectorAll(".staff-booking-action")' in availability
    for element_id in (
        "nav-booking-button",
        "hero-booking-button",
        "booking-form",
        "mobile-booking-cta",
    ):
        assert re.search(rf'id="{element_id}"[^>]*\bhidden\b', html)


def test_service_staff_verification_is_cached_limited_and_versioned() -> None:
    _, js, _, _, _, _ = sources()
    cache = block(js, "function compatibleStaffCacheKey", "async function verifyReservableServices")
    verification = block(js, "async function verifyReservableServices", "function setVerifiedServices")
    selection = block(js, "async function loadStaffForService", "function renderBookingStaffOptions")
    assert "serviceStaffCache: new Map()" in js
    assert "serviceStaffCache.has(key)" in cache
    assert "serviceStaffCache.get(key)" in cache
    assert "serviceStaffCache.set(key, pending)" in cache
    assert "serviceStaffCache.delete(key)" in cache
    assert js.count("/staff?service_id=") == 1
    assert "await loadCompatibleStaffCached(getBusinessSlug(), serviceId)" in selection
    assert "requestJson(" not in selection
    assert "SERVICE_VERIFICATION_CONCURRENCY = 3" in js
    assert "Math.min(SERVICE_VERIFICATION_CONCURRENCY, candidates.length)" in verification
    assert "isCurrentBusinessLoad(slug, businessLoadVersion)" in verification
    assert "landingState.serviceVerificationVersion !== verificationVersion" in verification


def test_selected_service_that_stops_being_reservable_is_never_submitted() -> None:
    _, js, _, _, _, _ = sources()
    submit = block(js, "async function submitBooking", "async function uploadBookingPhotos")
    validation = submit.split("landingState.submitting = true", 1)[0]
    assert '["ready", "partial"].includes(landingState.serviceVerificationStatus)' in validation
    assert "(bookingState.business.services || []).some" in validation
    assert "String(service.id) === String(bookingState.service.id)" in validation
    assert validation.index("const validService") < validation.index("if (!validService")
    assert submit.index("if (!validService") < submit.index("landingState.submitting = true")
    assert submit.index("landingState.submitting = true") < submit.index("await requestJson")


def test_public_staff_is_compatible_and_neutral_assignment_is_backend_owned() -> None:
    html, js, _, _, _, _ = sources()
    assert 'id="team"' in html and 'id="booking-staff-options"' in html
    assert "/staff?service_id=" in js
    assert "landingState.compatibleStaff = []" in js
    assert "Cualquier profesional disponible" in js
    assert "El backend asignará una persona compatible" in js
    staff_render = block(js, "function renderStaff", "function renderGallery")
    for forbidden in ("email", "user_id", "business_id", "role"):
        assert forbidden not in staff_render


def test_gallery_is_lazy_resilient_and_has_accessible_focus_managed_viewer() -> None:
    html, js, css, _, _, _ = sources()
    assert 'role="dialog" aria-modal="true" aria-labelledby="gallery-dialog-title"' in html
    assert "loading = \"lazy\"" in js
    assert 'event.key === "Escape"' in js
    assert 'event.key !== "Tab"' in js
    assert "galleryReturnFocus" in js
    assert 'image.addEventListener("error", () => button.remove()' in js
    assert "max-height: calc(100dvh - 40px)" in css


def test_location_reviews_and_contact_only_use_valid_public_urls() -> None:
    html, js, _, _, _, _ = sources()
    for element_id in ("maps-link", "reviews-link", "phone-link", "whatsapp-direct-link", "instagram-link"):
        assert f'id="{element_id}"' in html
    assert 'return ["http:", "https:"].includes(url.protocol)' in js
    assert "function phoneDigits" in js
    assert 'link.target = "_blank"' not in js
    inventory = Inventory()
    inventory.feed(html)
    for link in inventory.links:
        if link.get("target") == "_blank":
            assert "noopener" in str(link.get("rel"))


def test_service_and_staff_changes_invalidate_downstream_selection() -> None:
    _, js, _, _, _, _ = sources()
    service = block(js, "async function selectBookingService", "function syncServiceSelection")
    staff = block(js, "function selectBookingStaff", "function renderBookingTimezone")
    for source in (service, staff):
        assert "bookingState.date = null" in source
        assert "bookingState.slot = null" in source
        assert "landingState.slotCache.clear()" in source


def test_calendar_and_slots_are_real_lazy_versioned_and_deduplicated() -> None:
    _, js, _, _, _, _ = sources()
    assert "/calendar-days?${params.toString()}" in js
    assert "/available-slots?${params.toString()}" in js
    assert "calendarLoadVersion" in js and "slotLoadVersion" in js and "staffLoadVersion" in js
    assert "version !== landingState.calendarLoadVersion" in js
    assert "version !== landingState.slotLoadVersion" in js
    assert "landingState.calendarCache.get(key)" in js
    assert "landingState.slotCache.get(key)" in js
    assert 'if (step === "datetime") loadBookingDates()' in js
    assert 'aria-busy="false"' in LANDING_HTML.read_text(encoding="utf-8")


def test_availability_empty_error_and_slot_conflict_are_distinct() -> None:
    _, js, _, _, _, _ = sources()
    assert "No hay horarios disponibles para esta fecha. Prueba otro día o profesional." in js
    assert "No se pudieron comprobar los horarios. Vuelve a intentarlo." in js
    assert "Ese horario ya no está disponible. Elige otro hueco." in js
    conflict = block(js, "async function submitBooking", "async function uploadBookingPhotos")
    assert "bookingState.slot = null" in conflict
    assert "await loadBookingSlots(true)" in conflict
    assert "bookingState.customer =" not in conflict


def test_customer_data_privacy_review_and_requested_result_are_truthful() -> None:
    html, js, _, _, _, _ = sources()
    assert 'autocomplete="name"' in html and 'autocomplete="tel"' in html
    assert "Hasta 5 imágenes" in html
    assert '../privacy/' in html and '../data-deletion/' in html
    for label in ("Negocio", "Servicio", "Profesional", "Fecha y hora", "Tus datos"):
        assert f'["{label}"' in js
    assert "La cita se enviará como solicitud. El negocio tendrá que confirmarla." in html
    booking_service = BOOKING_SERVICE.read_text(encoding="utf-8")
    assert 'status="requested"' in booking_service
    assert 'requested: { label: "Solicitud enviada"' in js


def test_creation_blocks_double_submit_waits_and_clears_personal_data_only_after_success() -> None:
    _, js, _, _, _, _ = sources()
    submit = block(js, "async function submitBooking", "async function uploadBookingPhotos")
    assert "if (landingState.submitting" in submit
    assert "landingState.submitting = true" in submit
    assert "await requestJson" in submit
    assert "bookingState.booking = result.booking" in submit
    assert submit.index("renderBookingResult") < submit.index("clearPersonalBookingData")
    assert "bookingState.booking =" not in submit.split("catch (error)", 1)[1]
    assert "booking.status =" not in submit


def test_customer_portal_lists_only_server_scoped_bookings_and_safe_detail() -> None:
    html, _, _, customer_html, customer_js, _ = sources()
    assert html  # keep source tuple order explicit
    assert 'id="next-booking"' in customer_html
    assert 'id="recent-services"' in customer_html
    assert 'id="customer-calendar"' in customer_html
    assert 'id="booking-detail-dialog"' in customer_html
    assert 'role="dialog" aria-modal="true"' in customer_html
    assert "/api/customer/home?from=" in customer_js
    assert "openBookingDetail(item" in customer_js
    assert "data-booking-id" not in customer_js
    router = CUSTOMER_ROUTER.read_text(encoding="utf-8")
    assert "Booking.customer_user_id == user.id" in router
    assert "Booking.customer_email == user.email" in router
    assert "Booking.customer_id.in_(linked_customer_ids)" in router
    assert "get_current_user" in router


def test_customer_states_expiry_empty_content_and_detail_are_friendly() -> None:
    _, _, _, _, customer_js, _ = sources()
    for internal, label in (
        ("requested", "Solicitud enviada"),
        ("pending", "Pendiente de confirmación"),
        ("confirmed", "Confirmada"),
        ("completed", "Completada"),
        ("cancelled", "Cancelada"),
        ("rejected", "Rechazada"),
        ("no_show", "No realizada"),
    ):
        assert f'{internal}: {{ label: "{label}"' in customer_js
    assert "Tu sesión ha caducado" in customer_js
    assert "No tienes próximas citas" in customer_js
    assert "Aún no tienes servicios anteriores" in customer_js
    assert "Información de tu reserva" in CUSTOMER_HTML.read_text(encoding="utf-8")


def test_customer_reschedule_and_cancellation_are_not_faked() -> None:
    _, _, _, _, customer_js, _ = sources()
    router = CUSTOMER_ROUTER.read_text(encoding="utf-8")
    assert '"can_manage": False' in router
    assert "/reschedule" not in customer_js
    assert "/cancel" not in customer_js
    assert "Solo mostramos acciones que realmente están disponibles" in customer_js
    booking_router = BOOKING_ROUTER.read_text(encoding="utf-8")
    assert "require_booking_business_access" in booking_router


def test_contextual_navigation_and_noindex_are_preserved() -> None:
    html, js, _, customer_html, customer_js, _ = sources()
    assert 'href="#booking"' in html
    assert 'href="#contact"' in html
    assert 'customerLink.href = "../autonogrow-customer/index.html"' in js
    assert 'href="../privacy/"' in html
    assert '<meta name="robots" content="noindex, nofollow"' in customer_html
    assert "new URLSearchParams({ b: item.business_slug" in customer_js


def test_responsive_and_accessible_structure_covers_required_controls() -> None:
    html, _, css, customer_html, customer_js, customer_css = sources()
    assert 'href="#main-content"' in html
    assert 'href="#customer-main"' in customer_html
    assert 'aria-label="Navegación del negocio"' in html
    assert 'role="group" aria-label="Horarios disponibles"' in html
    assert 'id="booking-error-summary" class="error-summary" role="alert"' in html
    assert "booking-error-${field.id}-${index}" in LANDING_JS.read_text(encoding="utf-8")
    assert 'event.key === "Escape"' in customer_js and 'event.key !== "Tab"' in customer_js
    for source in (css, customer_css):
        assert "@media (max-width: 640px)" in source or "@media (max-width: 680px)" in source
        assert "100dvh" in source
        assert "env(safe-area-inset-bottom)" in source
        assert "font-size: 16px" in source
        assert "prefers-reduced-motion" in source


def test_dynamic_content_is_text_only_and_personal_data_is_not_persisted() -> None:
    _, js, _, _, customer_js, _ = sources()
    combined = f"{js}\n{customer_js}"
    for forbidden in (
        "innerHTML",
        "outerHTML",
        "insertAdjacentHTML",
        "localStorage",
        "sessionStorage",
        "console.log",
        "console.error",
        "debugger",
    ):
        assert forbidden not in combined
    assert "textContent" in js and "textContent" in customer_js
    assert "window.location.search" not in customer_js
    assert "window.location.hash" not in combined


def test_frontends_use_only_existing_endpoints_and_expose_no_secrets() -> None:
    _, js, _, _, customer_js, _ = sources()
    combined = f"{js}\n{customer_js}".lower()
    for secret in (
        "access_token",
        "refresh_token",
        "app_secret",
        "verify_token",
        "phone_number_id",
        "waba_id",
        "provider_message_id",
    ):
        assert secret not in combined
    expected = (
        "/api/businesses/",
        "/services",
        "/staff",
        "/media/gallery",
        "/availability-settings",
        "/calendar-days",
        "/available-slots",
        "/bookings",
        "/attachments",
        "/api/customer/profile",
        "/api/customer/home",
        "/api/customer/claim-booking",
    )
    assert all(value in f"{js}\n{customer_js}" for value in expected)
    for forbidden in ("/api/customer/bookings/", "/api/customer/reschedule", "/api/customer/cancel"):
        assert forbidden not in combined


def test_static_ids_are_unique_and_documentation_exists() -> None:
    for path in (LANDING_HTML, CUSTOMER_HTML):
        inventory = Inventory()
        inventory.feed(path.read_text(encoding="utf-8"))
        assert len(inventory.ids) == len(set(inventory.ids))
    assert DOC.is_file()
