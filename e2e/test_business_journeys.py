from __future__ import annotations

import base64
import io
import re
from datetime import datetime, timedelta, timezone

import pytest
from PIL import Image
from playwright.sync_api import expect

from e2e.seed import JPEG_BYTES

pytestmark = pytest.mark.e2e
MP4_BYTES = base64.b64decode(
    "AAAAIGZ0eXBpc29tAAACAGlzb21pc28yYXZjMW1wNDEAAAN0bW9vdgAAAGxtdmhkAAAAAAAAAAAAAAAAAAAD6AAAAMgAAQAAAQAAAAAAAAAAAAAAAAEAAAAAAAAAAAAAAAAAAAABAAAAAAAAAAAAAAAAAABAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAgAAAp90cmFrAAAAXHRraGQAAAADAAAAAAAAAAAAAAABAAAAAAAAAMgAAAAAAAAAAAAAAAAAAAAAAAEAAAAAAAAAAAAAAAAAAAABAAAAAAAAAAAAAAAAAABAAAAAABAAAAAQAAAAAAAkZWR0cwAAABxlbHN0AAAAAAAAAAEAAADIAAAEAAABAAAAAAIXbWRpYQAAACBtZGhkAAAAAAAAAAAAAAAAAAAyAAAACgBVxAAAAAAALWhkbHIAAAAAAAAAAHZpZGUAAAAAAAAAAAAAAABWaWRlb0hhbmRsZXIAAAABwm1pbmYAAAAUdm1oZAAAAAEAAAAAAAAAAAAAACRkaW5mAAAAHGRyZWYAAAAAAAAAAQAAAAx1cmwgAAAAAQAAAYJzdGJsAAAAvnN0c2QAAAAAAAAAAQAAAK5hdmMxAAAAAAAAAAEAAAAAAAAAAAAAAAAAAAAAABAAEABIAAAASAAAAAAAAAABFUxhdmM2Mi4xMS4xMDAgbGlieDI2NAAAAAAAAAAAAAAAGP//AAAANGF2Y0MBZAAK/+EAF2dkAAqs2V7ARAAAAwAEAAADAMg8SJZYAQAGaOvjyyLA/fj4AAAAABBwYXNwAAAAAQAAAAEAAAAUYnRydAAAAAAAAHZwAAAAAAAAABhzdHRzAAAAAAAAAAEAAAAFAAACAAAAABRzdHNzAAAAAAAAAAEAAAABAAAAOGN0dHMAAAAAAAAABQAAAAEAAAQAAAAAAQAACgAAAAABAAAEAAAAAAEAAAAAAAAAAQAAAgAAAAAcc3RzYwAAAAAAAAABAAAAAQAAAAUAAAABAAAAKHN0c3oAAAAAAAAAAAAAAAUAAALGAAAADAAAAAwAAAAMAAAADAAAABRzdGNvAAAAAAAAAAEAAAOkAAAAYXVkdGEAAABZbWV0YQAAAAAAAAAhaGRscgAAAAAAAAAAbWRpcmFwcGwAAAAAAAAAAAAAAAAsaWxzdAAAACSpdG9vAAAAHGRhdGEAAAABAAAAAExhdmY2Mi4zLjEwMAAAAAhmcmVlAAAC/m1kYXQAAAKvBgX//6vcRem95tlIt5Ys2CDZI+7veDI2NCAtIGNvcmUgMTY1IHIzMjIyTSBiMzU2MDVhIC0gSC4yNjQvTVBFRy00IEFWQyBjb2RlYyAtIENvcHlsZWZ0IDIwMDMtMjAyNSAtIGh0dHA6Ly93d3cudmlkZW9sYW4ub3JnL3gyNjQuaHRtbCAtIG9wdGlvbnM6IGNhYmFjPTEgcmVmPTMgZGVibG9jaz0xOjA6MCBhbmFseXNpPTB4MzoweDExMyBtZT1oZXggc3VibWU9NyBwc3k9MSBwc3lfcmQ9MS4wMDowLjAwIG1peGVkX3JlZj0xIG1lX3JhbmdlPTE2IGNocm9tYV9tZT0xIHRyZWxsaXM9MSA4eDhkY3Q9MSBjcW09MCBkZWFkem9uZT0yMSwxMSBmYXN0X3Bza2lwPTEgY2hyb21hX3FwX29mZnNldD0tMiB0aHJlYWRzPTEgbG9va2FoZWFkX3RocmVhZHM9MSBzbGljZWRfdGhyZWFkcz0wIG5yPTAgZGVjaW1hdGU9MSBpbnRlcmxhY2VkPTAgYmx1cmF5X2NvbXBhdD0wIGNvbnN0cmFpbmVkX2ludHJhPTAgYmZyYW1lcz0zIGJfcHlyYW1pZD0yIGJfYWRhcHQ9MSBiX2JpYXM9MCBkaXJlY3Q9MSB3ZWlnaHRiPTEgb3Blbl9nb3A9MCB3ZWlnaHRwPTIga2V5aW50PTI1MCBrZXlpbnRfbWluPTI1IHNjZW5lY3V0PTQwIGludHJhX3JlZnJlc2g9MCByY19sb29rYWhlYWQ9NDAgcmM9Y3JmIG1idHJlZT0xIGNyZj0yMy4wIHFjb21wPTAuNjAgcXBtaW49MCBxcG1heD02OSBxcHN0ZXA9NCBpcF9yYXRpbz0xLjQwIGFxPTE6MS4wMACAAAAAD2WIhAAz//727L4FNhTIwQAAAAhBmiRsQr/+wAAAAAhBnkJ4hf/BgQAAAAgBnmF0Qr/EgAAAAAgBnmNqQr/EgQ=="
)


def _horizontal_png() -> bytes:
    output = io.BytesIO()
    Image.new("RGB", (1200, 600), (190, 50, 25)).save(output, format="PNG")
    return output.getvalue()


def _open_admin(journey, *, mobile: bool = False):
    session = journey(email="admin-a@e2e.test", mobile=mobile)
    page = session.goto("/autonogrow-admin/?b=salon-e2e#bookings")
    expect(page.locator("#admin-app")).to_be_visible()
    expect(page.locator("#business-name")).to_have_text("Salón E2E")
    return session, page


def _open_owner_instagram(journey):
    session = journey(email="owner@e2e.test")
    page = session.goto("/autonogrow-owner/")
    expect(page.locator("#owner-app")).to_be_visible()
    page.locator('[data-tab="instagram-content"]').click()
    expect(page.locator("#owner-instagram-business")).to_be_visible()
    page.locator("#owner-instagram-business").select_option(label="Salón E2E")
    expect(page.locator("#owner-instagram-workspace")).to_be_visible()
    expect(page.locator("#owner-instagram-status")).to_contain_text("contenidos", timeout=15_000)
    return session, page


def _assert_no_horizontal_overflow(page) -> None:
    drawer = page.locator(".conversation-customer-panel.is-open")
    if drawer.count():
        expect(drawer).to_have_css(
            "transform", re.compile(r"^(none|matrix\(1, 0, 0, 1, 0, 0\))$")
        )
    offenders = page.evaluate(
        """() => {
          const openPanels = [...document.querySelectorAll('.conversation-customer-panel.is-open')];
          const roots = openPanels.length ? openPanels : [...document.querySelectorAll('.admin-section-active')];
          const elements = [...new Set(roots.flatMap((root) => [root, ...root.querySelectorAll('*')]))];
          return elements
          .filter((element) => {
            const style = getComputedStyle(element);
            if (style.display === 'none' || style.visibility === 'hidden') return false;
            const rect = element.getBoundingClientRect();
            return rect.width > 0 && (rect.left < -1 || rect.right > innerWidth + 1);
          })
          .slice(0, 20)
          .map((element) => ({
            tag: element.tagName,
            id: element.id,
            className: String(element.className || ''),
            rect: element.getBoundingClientRect().toJSON()
          }));
        }"""
    )
    assert not offenders, offenders


def test_admin_controlled_login_navigation_and_owner_separation(journey) -> None:
    session = journey()
    page = session.goto("/autonogrow-admin/?b=salon-e2e")
    page.locator("#admin-google-button button").evaluate("button => button.click()")
    expect(page.locator("#admin-app")).to_be_visible()
    expect(page.locator("#business-name")).to_have_text("Salón E2E")
    expect(page.get_by_role("navigation", name="Secciones del panel")).to_be_visible()
    assert (
        page.request.get(
            "/api/owner/businesses/1/instagram-content/raw-assets", timeout=5000
        ).status
        == 403
    )
    assert page.locator("[data-tab='operations']").count() == 0


def test_growth_disabled_hides_its_surface_and_api_fails_closed(journey) -> None:
    from app.core.database import SessionLocal
    from app.models import Business
    from app.services.capability_service import configure_business_modules

    with SessionLocal() as db:
        business = db.query(Business).filter(Business.slug == "salon-e2e").one()
        configure_business_modules(
            db,
            business_id=business.id,
            enabled_modules=["essential", "social"],
            actor_user_id=None,
        )
        db.commit()

    _session, page = _open_admin(journey)
    expect(page.locator('.admin-tab[data-section="growth"]')).to_be_hidden()
    expect(page.locator('.admin-tab[data-section="instagram-content"]')).to_be_visible()
    expect(page.locator('.admin-tab[data-section="reviews"]:visible').first).to_be_visible()
    denied = page.request.get("/api/admin/businesses/salon-e2e/opportunities")
    assert denied.status == 403
    assert denied.json()["detail"]["code"] == "module_not_available"


def test_growth_opportunity_home_customer_conversation_backlink(journey) -> None:
    _session, page = _open_admin(journey)
    page.locator('.admin-tab[data-section="summary"]').evaluate("button => button.click()")

    today = page.locator("#dashboard-attention-list")
    expect(today).to_contain_text("Oportunidades para hoy")
    expect(today).to_contain_text("María Cliente E2E está en fecha de volver")
    _assert_no_horizontal_overflow(page)
    today.get_by_role("button", name="Ver oportunidad").click()

    opportunity = page.locator("[data-customer-opportunity]").filter(has_text="María Cliente E2E")
    expect(opportunity).to_be_visible()
    _assert_no_horizontal_overflow(page)
    opportunity.get_by_role("button", name="Ver cliente").click()

    customer_growth = page.locator(".customer-growth")
    expect(customer_growth).to_be_visible()
    expect(customer_growth).to_contain_text("Oportunidades activas")
    expect(customer_growth).to_contain_text("Corte E2E")
    _assert_no_horizontal_overflow(page)
    customer_growth.get_by_role("button", name="Abrir conversación").click()

    page.locator("#conversation-customer-close").click()
    follow_up = page.locator(".conversation-growth-follow-up")
    expect(follow_up).to_contain_text("Este cliente requiere seguimiento porque")
    expect(follow_up).to_contain_text("Está en fecha de volver para Corte E2E.")
    follow_up.get_by_role("button", name="Ver oportunidad").click()
    expect(opportunity).to_be_visible()

    for size in ({"width": 768, "height": 1024}, {"width": 390, "height": 844}):
        page.set_viewport_size(size)
        page.locator('.admin-tab[data-section="summary"]').evaluate("button => button.click()")
        expect(today).to_contain_text("Oportunidades para hoy")
        _assert_no_horizontal_overflow(page)
        today.get_by_role("button", name="Ver oportunidad").click()
        expect(opportunity).to_be_visible()
        _assert_no_horizontal_overflow(page)
        opportunity.get_by_role("button", name="Ver cliente").click()
        expect(customer_growth).to_be_visible()
        _assert_no_horizontal_overflow(page)
        page.locator("#conversation-customer-close").click()


def test_admin_booking_day_week_month_and_confirm_without_reload(journey) -> None:
    _session, page = _open_admin(journey)
    capabilities = page.request.get("/api/admin/businesses/salon-e2e/capabilities")
    assert capabilities.status == 200
    assert capabilities.json()["modules"]["growth"] == {
        "module": "growth",
        "entitled": True,
        "active": True,
        "available": True,
        "configuration_source": "business_module_access",
        "module_cost": None,
    }
    expect(page.get_by_role("tab", name="Día")).to_have_attribute("aria-selected", "true")
    page.get_by_role("tab", name="Semana").click()
    expect(page.get_by_role("tab", name="Semana")).to_have_attribute("aria-selected", "true")
    page.get_by_role("tab", name="Mes").click()
    expect(page.get_by_role("tab", name="Mes")).to_have_attribute("aria-selected", "true")
    page.get_by_role("button", name="Hoy", exact=True).click()
    page.get_by_role("tab", name="Día").click()
    page.get_by_role("button", name="Periodo siguiente").click()
    page.get_by_role("button", name=re.compile("Invitado Fixture, Color E2E")).click()
    pending = page.locator(".booking-card", has_text="Invitado Fixture")
    expect(pending).to_be_visible()
    expect(pending).to_contain_text("Color E2E")
    page.once("dialog", lambda dialog: dialog.accept())
    pending.get_by_role("button", name="Confirmar").click()
    expect(pending).to_contain_text("Confirmada", timeout=15_000)
    expect(pending).to_contain_text(re.compile(r"60\s*min"))


def test_appointment_customer_memory_is_private_timed_and_append_only(journey) -> None:
    _session, page = _open_admin(journey)
    bookings_path = "/api/admin/businesses/salon-e2e/bookings"
    initial_bookings = page.request.get(bookings_path).json()["bookings"]
    customer_booking = next(
        item for item in initial_bookings if item["customer_name"] == "María Cliente E2E"
    )
    empty_booking = next(
        item for item in initial_bookings if item["customer_name"] == "Invitado Fixture"
    )
    original_booking_comment = customer_booking["notes"]
    customer_id = customer_booking["customer_id"]
    csrf = page.evaluate(
        """async () => {
            const options = await AutonoGrowAuth.secureRequestOptions({ method: "POST" });
            return options.headers.get("X-CSRF-Token");
        }"""
    )
    created = page.request.post(
        f"/api/admin/businesses/salon-e2e/customers/{customer_id}/memory",
        headers={"X-CSRF-Token": csrf},
        data={
            "category": "preference",
            "key": "preference",
            "value": "Memoria histórica visible desde la cita",
            "source_type": "manual",
        },
    )
    assert created.status == 201

    page.goto(
        f"/autonogrow-admin/?b=salon-e2e&booking={customer_booking['id']}#bookings",
        wait_until="domcontentloaded",
    )
    card = page.locator(f"#booking-{customer_booking['id']}")
    expect(card).to_be_visible()
    card.locator(".agenda-booking-details > summary").click()
    toggle = card.get_by_role("button", name="Ver notas del cliente")
    expect(toggle).to_have_attribute("aria-expanded", "false")
    expect(card.get_by_text("Memoria histórica visible desde la cita")).to_have_count(0)

    page.clock.install()
    toggle.click()
    expect(card.get_by_text("Memoria histórica visible desde la cita")).to_be_visible()
    expect(card.get_by_text("Autor: Admin Salón E2E", exact=False)).to_be_visible()
    card.get_by_role("button", name="+ Añadir nota").click()
    draft = card.locator("[data-booking-customer-memory-draft]")
    draft.fill("Nota nueva exclusiva del cliente")
    page.clock.fast_forward(61_000)
    expect(card.get_by_role("button", name="Ocultar notas del cliente")).to_be_visible()

    page.locator("#agenda-customer-search").focus()
    page.clock.fast_forward(60_001)
    expect(card.get_by_role("button", name="Ver notas del cliente")).to_be_visible()
    expect(card.locator(".booking-customer-memory-content")).to_have_count(0)

    card.get_by_role("button", name="Ver notas del cliente").click()
    expect(card.locator("[data-booking-customer-memory-draft]")).to_have_value(
        "Nota nueva exclusiva del cliente"
    )
    card.get_by_role("button", name="Guardar nota", exact=True).press("Enter")
    expect(card.get_by_text("Nota nueva exclusiva del cliente")).to_be_visible()
    expect(card.get_by_text("Nota añadida.")).to_be_visible()

    current_bookings = page.request.get(bookings_path).json()["bookings"]
    current = next(item for item in current_bookings if item["id"] == customer_booking["id"])
    assert current["notes"] == original_booking_comment

    memory_path = f"/api/admin/businesses/salon-e2e/customers/{customer_id}/memory"
    memory_before_internal_save = page.request.get(memory_path).json()["items"]
    internal_details = card.locator("[data-internal-notes-details]")
    assert internal_details.get_attribute("open") is None
    expect(internal_details.locator("summary")).to_have_text("Nota interna de esta cita")
    expect(internal_details.locator("[data-internal-notes]")).to_be_hidden()
    internal_details.locator("summary").click()
    internal_note = card.locator("[data-internal-notes]")
    expect(internal_note).to_be_visible()
    internal_note.fill("Nota exclusiva de la Booking")
    save_booking_note = card.get_by_role("button", name="Guardar nota de esta cita")
    page.once("dialog", lambda dialog: dialog.accept())
    save_booking_note.click()
    expect(save_booking_note).to_be_enabled()
    memory_after_internal_save = page.request.get(memory_path).json()["items"]
    assert len(memory_after_internal_save) == len(memory_before_internal_save)

    internal_note.fill("Nota copiada de forma explícita")
    copy_to_customer = card.get_by_role("button", name="Guardar también en notas del cliente")
    page.once("dialog", lambda dialog: dialog.accept())
    copy_to_customer.click()
    expect(copy_to_customer).to_be_enabled()
    expect(card.get_by_text("Nota copiada de forma explícita")).to_be_visible()
    memory_after_copy = page.request.get(memory_path).json()["items"]
    assert len(memory_after_copy) == len(memory_before_internal_save) + 1
    assert "Nota copiada de forma explícita" in {item["value"] for item in memory_after_copy}
    current_bookings = page.request.get(bookings_path).json()["bookings"]
    current = next(item for item in current_bookings if item["id"] == customer_booking["id"])
    assert current["internal_notes"] == "Nota copiada de forma explícita"
    assert current["notes"] == original_booking_comment

    page.evaluate("bookingId => goToBooking(bookingId)", empty_booking["id"])
    assert page.evaluate("bookingCustomerMemoryTimer === null")
    empty_card = page.locator(f"#booking-{empty_booking['id']}")
    empty_card.locator(".agenda-booking-details > summary").click()
    expect(empty_card.get_by_role("button", name="Ver notas del cliente")).to_have_count(0)
    expect(empty_card.locator(".booking-customer-memory")).to_have_count(0)
    empty_card.locator("[data-internal-notes-details] > summary").click()
    expect(
        empty_card.get_by_role("button", name="Guardar también en notas del cliente")
    ).to_have_count(0)


def test_admin_instagram_calendar_editorial_action_and_permissions(journey) -> None:
    _session, page = _open_admin(journey)
    page.locator('[data-section="instagram-content"]').click()
    expect(page.locator("#admin-instagram-workspace")).to_be_visible()
    expect(page.get_by_role("tab", name="Semana").last).to_have_attribute("aria-selected", "true")
    page.get_by_role("tab", name="Mes").last.click()
    expect(page.get_by_role("tab", name="Mes").last).to_have_attribute("aria-selected", "true")
    page.get_by_role("button", name=re.compile("SALON lanzamiento")).click()
    detail = page.locator("[data-admin-instagram-content]")
    expect(detail).to_contain_text("Caption de revisión SALON")
    expect(detail).to_contain_text("Visto bueno del negocio")
    expect(detail).to_contain_text("No es un requisito")
    reviewed = page.request.get(
        "/api/admin/businesses/salon-e2e/instagram-content/contents/1"
    ).json()
    assert reviewed["current_version"]["editorial_review"]["status"] == "approved"
    assert detail.get_by_role("button", name="Programar").count() == 0
    assert detail.get_by_role("button", name="Publicar ahora").count() == 0
    assert (
        page.request.post(
            "/api/owner/businesses/1/instagram-content/contents/1/schedule", data={}
        ).status
        == 403
    )
    assert page.locator("[data-owner-instagram-action]").count() == 0


def test_whatsapp_assisted_opens_safe_url_without_claiming_sent(journey) -> None:
    session, page = _open_admin(journey)
    page.get_by_role("button", name="Crecimiento", exact=True).click()
    page.locator('[data-growth-target="reviews"]:visible').click()
    pending = page.locator("#review-requests-pending-list")
    expect(pending).to_contain_text("Invitado Fixture")
    button = pending.get_by_role("button", name="Abrir en WhatsApp")
    expect(button).to_be_visible()
    page.once("dialog", lambda dialog: dialog.accept())
    with page.expect_popup() as popup_info:
        button.click()
    popup = popup_info.value

    for _ in range(100):
        if session.whatsapp_urls:
            break
        page.wait_for_timeout(100)

    assert any(url.startswith("https://wa.me/34611000111") for url in session.whatsapp_urls), (
        session.whatsapp_urls
    )
    popup.close()
    expect(pending).to_contain_text("Abierta en WhatsApp")
    expect(pending).to_contain_text(re.compile("no lo marc. como enviado", re.IGNORECASE))
    expect(pending).not_to_contain_text("Marcada como enviada")


def test_owner_business_switching_isolates_bookings_and_instagram(journey) -> None:
    session, page = _open_owner_instagram(journey)
    expect(page.locator("#owner-instagram-workspace")).to_contain_text("SALON")
    page.locator("#owner-instagram-business").select_option(label="Fisio E2E")
    expect(page.locator("#owner-instagram-workspace")).to_contain_text("FISIO")
    expect(page.locator("#owner-instagram-workspace")).not_to_contain_text("SALON")
    page.locator("#owner-instagram-business").select_option(label="Salón E2E")
    expect(page.locator("#owner-instagram-workspace")).to_contain_text("SALON")

    bookings_a = page.request.get("/api/admin/businesses/salon-e2e/bookings").json()
    bookings_b = page.request.get("/api/admin/businesses/fisio-e2e/bookings").json()
    assert {item["service_name"] for item in bookings_a["bookings"]} >= {
        "Corte E2E",
        "Color E2E",
    }
    assert {item["service_name"] for item in bookings_b["bookings"]} == {"Sesión Fisio E2E"}


def test_owner_instagram_calendar_views_filter_and_quick_action(journey) -> None:
    _session, page = _open_owner_instagram(journey)
    expect(page.get_by_role("tab", name="Semana").last).to_have_attribute("aria-selected", "true")
    page.get_by_role("tab", name="Mes").last.click()
    expect(page.get_by_role("tab", name="Mes").last).to_have_attribute("aria-selected", "true")
    page.locator("#owner-instagram-state-filter").select_option("ready_for_review")
    item = page.get_by_role("button", name=re.compile("SALON lanzamiento"))
    expect(item).to_be_visible()
    expect(item).to_contain_text("Revisar")
    item.click()
    composer = page.locator("#owner-instagram-composer")
    expect(composer).to_be_visible()
    expect(page.locator("#owner-instagram-composer-title")).to_have_text("Editar publicación")
    expect(page.locator("#owner-instagram-composer-caption")).to_have_value(
        "Caption de revisión SALON"
    )
    expect(composer.get_by_text("Versión", exact=True)).to_be_hidden()
    composer.locator("#owner-instagram-composer-advanced").click()
    expect(composer.get_by_text("Versión", exact=True)).to_be_visible()


def test_owner_instagram_polling_moves_processing_to_published_without_reload(journey) -> None:
    from app.core.database import SessionLocal
    from app.models import Business, InstagramContent, InstagramPublishJob

    with SessionLocal() as db:
        business = db.query(Business).filter(Business.slug == "salon-e2e").one()
        content = (
            db.query(InstagramContent)
            .filter_by(business_id=business.id, title="SALON lanzamiento")
            .one()
        )
        version = content.versions[0]
        now = datetime.now(timezone.utc)
        content.status = "scheduled"
        job = InstagramPublishJob(
            business_id=business.id,
            content_item_id=content.id,
            content_version_id=version.id,
            status="retry_wait",
            scheduled_for=now,
            attempt_count=1,
            max_attempts=3,
            next_attempt_at=now + timedelta(seconds=30),
            idempotency_key=f"e2e-poll-{content.id}-{version.id}",
            provider_status="temporary_failure",
            provider_error_code="instagram_carousel_parent_processing",
            safe_error_message="Instagram carousel is still being processed",
        )
        db.add(job)
        db.commit()
        content_id = content.id
        job_id = job.id

    _session, page = _open_owner_instagram(journey)
    item = page.get_by_role("button", name=re.compile("SALON lanzamiento"))
    expect(item).to_contain_text("Reintento programado")

    with SessionLocal() as db:
        persisted_content = db.get(InstagramContent, content_id)
        persisted_job = db.get(InstagramPublishJob, job_id)
        assert persisted_content is not None
        assert persisted_job is not None
        persisted_content.status = "published"
        persisted_job.status = "published"
        persisted_job.provider_status = "published_simulated"
        persisted_job.provider_error_code = None
        persisted_job.safe_error_message = None
        persisted_job.provider_media_id = "e2e-media-published"
        persisted_job.provider_permalink = "https://www.instagram.com/p/e2e-safe/"
        persisted_job.published_at = datetime.now(timezone.utc)
        persisted_job.next_attempt_at = None
        db.commit()

    expect(item).to_contain_text("Publicado", timeout=15_000)


def test_owner_instagram_composer_uses_day_without_fixed_hour_and_previews_formats(journey) -> None:
    _session, page = _open_owner_instagram(journey)
    day = page.locator("[data-owner-instagram-create-date]").first
    selected_date = day.get_attribute("data-owner-instagram-create-date")
    day.click()
    composer = page.locator("#owner-instagram-composer")
    expect(composer).to_be_visible()
    expect(page.locator("#owner-instagram-composer-date")).to_have_value(selected_date)
    expect(page.locator("#owner-instagram-composer-time")).to_have_value("")

    composer.locator(".instagram-composer__formats").get_by_text("Carrusel", exact=True).click()
    composer.locator("#owner-instagram-composer-file").set_input_files(
        [
            {"name": "uno.jpg", "mimeType": "image/jpeg", "buffer": JPEG_BYTES},
            {"name": "dos.jpg", "mimeType": "image/jpeg", "buffer": JPEG_BYTES},
        ]
    )
    expect(composer.locator("#owner-instagram-media-count")).to_have_text("2/10")
    expect(composer.locator("[data-owner-composer-move='1']").first).to_be_enabled()
    expect(composer.locator("#owner-instagram-preview-carousel")).to_be_visible()
    composer.locator('[data-owner-composer-preview="next"]').click()
    expect(composer.locator("#owner-instagram-preview-position")).to_have_text("2/2")

    composer.locator(".instagram-composer__formats").get_by_text("Reel", exact=True).click()
    expect(composer.locator("#owner-instagram-composer-error")).to_have_text(
        re.compile("no es compatible con Reel")
    )
    expect(composer.locator("#owner-instagram-media-count")).to_have_text("2/10")
    composer.locator(".instagram-composer-media__remove").first.click()
    expect(composer.locator("#owner-instagram-media-count")).to_have_text("1/10")
    composer.locator(".instagram-composer-media__remove").click()
    expect(composer.locator("#owner-instagram-media-count")).to_have_text("0/10")
    composer.locator(".instagram-composer__formats").get_by_text("Reel", exact=True).click()
    composer.locator("#owner-instagram-composer-file").set_input_files(
        {"name": "reel.mp4", "mimeType": "video/mp4", "buffer": MP4_BYTES}
    )
    expect(composer.locator("#owner-instagram-phone")).to_have_class(
        re.compile("instagram-phone--vertical")
    )
    expect(composer.locator("#owner-instagram-preview-stage video")).to_have_count(1)

    composer.locator(".instagram-composer__formats").get_by_text("Historia", exact=True).click()
    expect(composer.locator("#owner-instagram-composer-reuse")).to_be_visible()
    expect(composer.locator("#owner-instagram-composer-reuse")).to_be_enabled()
    expect(composer.locator("#owner-instagram-caption-field")).to_be_hidden()


def test_owner_instagram_composer_saves_ordered_carousel_without_exposing_assets(journey) -> None:
    _session, page = _open_owner_instagram(journey)
    page.locator("#owner-instagram-create").click()
    composer = page.locator("#owner-instagram-composer")
    composer.locator(".instagram-composer__formats").get_by_text("Carrusel", exact=True).click()
    composer.locator("#owner-instagram-composer-file").set_input_files(
        [
            {"name": "primera.jpg", "mimeType": "image/jpeg", "buffer": JPEG_BYTES},
            {"name": "segunda.jpg", "mimeType": "image/jpeg", "buffer": JPEG_BYTES},
        ]
    )
    composer.locator("#owner-instagram-composer-caption").fill("Carrusel creado desde el Composer")
    original_order = composer.locator(".instagram-composer-media__meta strong").all_text_contents()
    composer.locator("[data-owner-composer-move='1']").first.dispatch_event("click")
    expect(composer.locator(".instagram-composer-media__meta strong").first).to_have_text(
        original_order[1]
    )
    reordered = composer.locator(".instagram-composer-media__meta strong").all_text_contents()
    assert reordered == list(reversed(original_order))
    with page.expect_response(
        lambda response: response.request.method == "PUT" and response.url.endswith("/material")
    ) as saved:
        composer.locator("#owner-instagram-composer-save").click()
    payload = saved.value.json()
    expect(composer).to_be_hidden()
    expect(page.locator("#owner-instagram-status")).to_have_text("Borrador guardado.")
    assert payload["status"] == "draft"
    assert payload["current_version"]["format"] == "carousel"
    assert [item["original_filename"] for item in payload["current_version"]["assets"]] == reordered
    assert page.locator("#owner-instagram-enabled-area").get_by_text("Assets finales").count() == 0


def test_owner_story_editor_renders_horizontal_upload_with_saved_contract(journey) -> None:
    _session, page = _open_owner_instagram(journey)
    page.locator("#owner-instagram-create").click()
    composer = page.locator("#owner-instagram-composer")
    composer.locator(".instagram-composer__formats").get_by_text("Historia", exact=True).click()
    composer.locator("#owner-instagram-composer-file").set_input_files(
        {"name": "horizontal.png", "mimeType": "image/png", "buffer": _horizontal_png()}
    )
    expect(composer.locator("#owner-instagram-story-editor")).to_be_visible()
    expect(composer.locator("#owner-instagram-preview-stage [data-story-preview]")).to_be_visible()
    ratio = composer.locator("#owner-instagram-preview-stage").evaluate(
        "element => element.clientWidth / element.clientHeight"
    )
    assert ratio == pytest.approx(9 / 16, rel=0.02)
    composer.get_by_text("Encajar", exact=True).click()
    composer.locator("#owner-instagram-story-zoom").fill("1.2")
    composer.get_by_text("Claro", exact=False).click()
    with page.expect_response(
        lambda response: response.request.method == "POST" and response.url.endswith("/story-image")
    ) as rendered:
        composer.locator("#owner-instagram-composer-save").click()
    payload = rendered.value.json()
    assert payload["asset"]["media_type"] == "image/jpeg"
    assert payload["asset"]["source_raw_asset_id"] is not None
    assert payload["content"]["current_version"]["story_transform"]["mode"] == "fit"
    assert payload["content"]["current_version"]["story_transform"]["background"] == "light"
    expect(composer).to_be_hidden()


def test_owner_instagram_library_selects_explicit_carousel_child(journey) -> None:
    from app.core.database import SessionLocal
    from app.models import Business, BusinessChannelIntegration, InstagramRemoteMedia

    with SessionLocal() as db:
        business = db.query(Business).filter(Business.slug == "salon-e2e").one()
        integration = BusinessChannelIntegration(
            business_id=business.id,
            channel="instagram",
            provider="instagram",
            external_account_id="e2e-library-account",
            integration_status="connected",
        )
        db.add(integration)
        db.flush()
        parent = InstagramRemoteMedia(
            business_id=business.id,
            integration_id=integration.id,
            provider_media_id="e2e-carousel",
            media_type="CAROUSEL_ALBUM",
            origin="instagram",
            remote_status="available",
        )
        db.add(parent)
        db.flush()
        db.add_all(
            [
                InstagramRemoteMedia(
                    business_id=business.id,
                    integration_id=integration.id,
                    provider_media_id=f"e2e-child-{position}",
                    parent_id=parent.id,
                    position=position,
                    media_type="IMAGE",
                    origin="instagram",
                    remote_status="available",
                )
                for position in range(2)
            ]
        )
        db.commit()

    _session, page = _open_owner_instagram(journey)
    page.route(
        "**/instagram-media/*/preview",
        lambda route: route.fulfill(status=200, content_type="image/png", body=_horizontal_png()),
    )
    page.locator("#owner-instagram-create").click()
    composer = page.locator("#owner-instagram-composer")
    composer.locator(".instagram-composer__formats").get_by_text("Historia", exact=True).click()
    composer.locator("#owner-instagram-composer-reuse").click()
    library = page.locator("#owner-instagram-library-dialog")
    expect(library).to_be_visible()
    expect(library.get_by_role("tab", name="Instagram")).to_have_attribute("aria-selected", "true")
    expect(library.get_by_role("tab", name="Material del negocio")).to_be_enabled()
    library.get_by_role("button", name="Elegir imagen").click()
    expect(library.get_by_text("¿Qué imagen quieres usar?")).to_be_visible()
    library.get_by_role("button", name="Usar en Story").first.click()
    expect(library).to_be_hidden()
    expect(composer.locator("#owner-instagram-story-editor")).to_be_visible()


def test_owner_create_from_raw_opens_lazy_composer_and_close_leaves_no_garbage(journey) -> None:
    from app.core.database import SessionLocal
    from app.models import (
        InstagramContent,
        InstagramContentRawAsset,
        InstagramContentVersion,
        InstagramFinalAsset,
    )

    def persisted_counts() -> tuple[int, int, int, int]:
        with SessionLocal() as db:
            return (
                db.query(InstagramContent).count(),
                db.query(InstagramContentVersion).count(),
                db.query(InstagramContentRawAsset).count(),
                db.query(InstagramFinalAsset).count(),
            )

    before = persisted_counts()
    _session, page = _open_owner_instagram(journey)
    page.locator("summary", has_text="Herramientas avanzadas de material").click()
    raw = page.locator("[data-owner-instagram-raw]", has_text="Material compartido SALON")
    raw.get_by_role("button", name="Crear contenido con este material").click()

    composer = page.locator("#owner-instagram-composer")
    expect(composer).to_be_visible()
    expect(page.locator("#owner-instagram-composer-title")).to_have_text(
        re.compile("Crear publicaci")
    )
    expect(composer.locator('[name="composer_format"][value="single_image"]')).to_be_checked()
    expect(page.locator("#owner-instagram-media-count")).to_have_text("1")
    expect(composer.locator(".instagram-composer-media__meta strong")).to_have_text(
        "Material compartido SALON"
    )
    expect(page.locator("#owner-instagram-preview-stage img")).to_be_visible()
    assert persisted_counts() == before

    page.locator("#owner-instagram-composer-close").click()
    expect(composer).to_be_hidden()
    assert persisted_counts() == before


def test_owner_create_from_raw_saves_reopens_retries_and_keeps_carousel_provenance(
    journey,
) -> None:
    from app.core.database import SessionLocal
    from app.models import (
        InstagramContent,
        InstagramContentRawAsset,
        InstagramFinalAsset,
        InstagramRawAsset,
    )

    caption = "P1.2.3 lazy SALON"
    _session, page = _open_owner_instagram(journey)
    page.locator("summary", has_text="Herramientas avanzadas de material").click()
    raw_card = page.locator("[data-owner-instagram-raw]", has_text="Material compartido SALON")
    raw_card.get_by_role("button", name="Crear contenido con este material").click()
    composer = page.locator("#owner-instagram-composer")
    expect(page.locator("#owner-instagram-preview-stage img")).to_be_visible()
    composer.locator("#owner-instagram-composer-caption").fill(caption)
    composer.locator("#owner-instagram-composer-save").click()
    expect(composer).to_be_hidden()

    with SessionLocal() as db:
        content = db.query(InstagramContent).filter(InstagramContent.title == caption).one()
        raw = db.query(InstagramRawAsset).filter_by(label="Material compartido SALON").one()
        content_id = content.id
        raw_id = raw.id
        assert content.status == "draft"
        assert content.planned_publish_at is None
        assert (
            db.query(InstagramContentRawAsset)
            .filter_by(content_id=content_id, raw_asset_id=raw_id)
            .count()
            == 1
        )
        assert (
            db.query(InstagramFinalAsset)
            .filter_by(content_id=content_id, source_raw_asset_id=raw_id)
            .count()
            == 1
        )
        current = max(content.versions, key=lambda version: version.version_number)
        assert current.format == "single_image"
        assert len(current.asset_links) == 1
        first_version_number = current.version_number

    content_button = page.get_by_role("button", name=re.compile(caption))
    content_button.click()
    expect(composer).to_be_visible()
    expect(page.locator("#owner-instagram-media-count")).to_have_text("1")
    expect(page.locator("#owner-instagram-preview-stage img")).to_be_visible()
    composer.locator("#owner-instagram-composer-save").click()
    expect(composer).to_be_hidden()

    with SessionLocal() as db:
        persisted_content = db.get(InstagramContent, content_id)
        assert persisted_content is not None
        assert (
            db.query(InstagramContentRawAsset)
            .filter_by(content_id=content_id, raw_asset_id=raw_id)
            .count()
            == 1
        )
        assert (
            db.query(InstagramFinalAsset)
            .filter_by(content_id=content_id, source_raw_asset_id=raw_id)
            .count()
            == 1
        )
        assert (
            max(
                persisted_content.versions,
                key=lambda version: version.version_number,
            ).version_number
            == first_version_number
        )

    page.get_by_role("button", name=re.compile(caption)).click()
    expect(page.locator("#owner-instagram-media-count")).to_have_text("1")
    composer.locator(".instagram-composer__formats").get_by_text("Carrusel", exact=True).click()
    expect(page.locator("#owner-instagram-media-count")).to_have_text("1/10")
    composer.locator("#owner-instagram-composer-file").set_input_files(
        {"name": "segunda.jpg", "mimeType": "image/jpeg", "buffer": JPEG_BYTES}
    )
    expect(page.locator("#owner-instagram-media-count")).to_have_text("2/10")
    expect(composer.locator(".instagram-composer-media__meta strong").first).to_have_text(
        "salon-shared.jpg"
    )
    composer.locator("#owner-instagram-composer-save").click()
    expect(composer).to_be_hidden()

    with SessionLocal() as db:
        persisted_content = db.get(InstagramContent, content_id)
        assert persisted_content is not None
        current = max(
            persisted_content.versions,
            key=lambda version: version.version_number,
        )
        assert current.format == "carousel"
        assert len(current.asset_links) == 2
        assert (
            db.query(InstagramContentRawAsset)
            .filter_by(content_id=content_id, raw_asset_id=raw_id)
            .count()
            == 1
        )
        assert (
            db.query(InstagramFinalAsset)
            .filter_by(content_id=content_id, source_raw_asset_id=raw_id)
            .count()
            == 1
        )


def test_owner_create_from_mp4_raw_preselects_reel_without_browser_reupload(journey) -> None:
    from app.core.database import SessionLocal
    from app.models import InstagramContent, InstagramFinalAsset, InstagramRawAsset

    _session, page = _open_owner_instagram(journey)
    csrf = page.evaluate(
        """async () => {
            const options = await AutonoGrowAuth.secureRequestOptions({ method: "POST" });
            return options.headers.get("X-CSRF-Token");
        }"""
    )
    uploaded = page.request.post(
        "/api/owner/businesses/1/instagram-content/raw-assets",
        headers={"X-CSRF-Token": csrf},
        multipart={
            "file": {"name": "p123-reel.mp4", "mimeType": "video/mp4", "buffer": MP4_BYTES},
            "label": "VÃ­deo P1.2.3 SALON",
        },
    )
    assert uploaded.status == 201
    raw_id = uploaded.json()["id"]
    page.locator("#owner-instagram-refresh").click()
    page.locator("summary", has_text="Herramientas avanzadas de material").click()
    raw = page.locator("[data-owner-instagram-raw]", has_text="VÃ­deo P1.2.3 SALON")
    expect(raw).to_be_visible()
    raw.get_by_role("button", name="Crear contenido con este material").click()

    composer = page.locator("#owner-instagram-composer")
    expect(composer).to_be_visible()
    expect(composer.locator('[name="composer_format"][value="reel"]')).to_be_checked()
    expect(page.locator("#owner-instagram-media-count")).to_have_text("1")
    expect(page.locator("#owner-instagram-preview-stage video")).to_be_visible()
    composer.locator("#owner-instagram-composer-caption").fill("Reel lazy P1.2.3 SALON")
    composer.locator("#owner-instagram-composer-save").click()
    expect(composer).to_be_hidden()

    with SessionLocal() as db:
        content = db.query(InstagramContent).filter_by(title="Reel lazy P1.2.3 SALON").one()
        current = max(content.versions, key=lambda version: version.version_number)
        assert current.format == "reel"
        assert len(current.asset_links) == 1
        assert db.query(InstagramRawAsset).filter_by(id=raw_id).count() == 1
        assert (
            db.query(InstagramFinalAsset)
            .filter_by(content_id=content.id, source_raw_asset_id=raw_id, media_type="video/mp4")
            .count()
            == 1
        )


def test_owner_create_from_raw_rejects_concurrent_retirement_without_invalid_final(journey) -> None:
    from app.core.database import SessionLocal
    from app.models import InstagramContent, InstagramContentRawAsset, InstagramFinalAsset

    session, page = _open_owner_instagram(journey)
    page.locator("summary", has_text="Herramientas avanzadas de material").click()
    raw = page.locator("[data-owner-instagram-raw]", has_text="Material liberable SALON")
    raw_id = int(raw.get_attribute("data-owner-instagram-raw"))
    raw.get_by_role("button", name="Crear contenido con este material").click()
    composer = page.locator("#owner-instagram-composer")
    expect(page.locator("#owner-instagram-preview-stage img")).to_be_visible()

    retired = page.evaluate(
        """async (assetId) => ownerInstagramJson(
            `${ownerInstagramApi()}/raw-assets/${assetId}/retire`,
            { method: "POST" }
        )""",
        raw_id,
    )
    assert retired["disposition"] == "retired"
    session.expect_response_error(404, "POST", f"/raw-assets/{raw_id}/use-as-final")
    composer.locator("#owner-instagram-composer-caption").fill("Retirada concurrente P1.2.3")
    composer.locator("#owner-instagram-composer-save").click()
    expect(page.locator("#owner-instagram-composer-error")).to_have_text(
        re.compile("El material ya no est.*disponible en la biblioteca")
    )
    expect(composer).to_be_visible()

    with SessionLocal() as db:
        content = db.query(InstagramContent).filter_by(title="Retirada concurrente P1.2.3").one()
        assert (
            db.query(InstagramContentRawAsset)
            .filter_by(content_id=content.id, raw_asset_id=raw_id)
            .count()
            == 0
        )
        assert (
            db.query(InstagramFinalAsset)
            .filter_by(content_id=content.id, source_raw_asset_id=raw_id)
            .count()
            == 0
        )


@pytest.mark.parametrize("publication", ["schedule", "now"])
def test_owner_create_from_raw_uses_normal_schedule_and_simulated_publish_flow(
    journey, publication
) -> None:
    from app.core.database import SessionLocal
    from app.models import (
        Business,
        BusinessChannelControl,
        BusinessChannelIntegration,
        InstagramContent,
        InstagramContentRawAsset,
        InstagramFinalAsset,
    )

    with SessionLocal() as db:
        business = db.query(Business).filter(Business.slug == "salon-e2e").one()
        control = (
            db.query(BusinessChannelControl)
            .filter_by(business_id=business.id, channel="instagram")
            .one_or_none()
        )
        if control is None:
            control = BusinessChannelControl(
                business_id=business.id,
                channel="instagram",
                status="approved",
                connector_policy="owner_only",
                connection_mode="simulated",
                integrated_delivery_enabled=True,
            )
            db.add(control)
        else:
            control.status = "approved"
            control.integrated_delivery_enabled = True
        integration = (
            db.query(BusinessChannelIntegration)
            .filter_by(business_id=business.id, provider="instagram")
            .one_or_none()
        )
        if integration is None:
            db.add(
                BusinessChannelIntegration(
                    business_id=business.id,
                    channel="instagram",
                    provider="instagram",
                    external_account_id=f"e2e-p123-{publication}",
                    integration_status="connected",
                    health_status="healthy",
                )
            )
        else:
            integration.integration_status = "connected"
            integration.health_status = "healthy"
        db.commit()

    caption = f"P1.2.3 {publication} SALON"
    _session, page = _open_owner_instagram(journey)
    page.locator("summary", has_text="Herramientas avanzadas de material").click()
    raw = page.locator("[data-owner-instagram-raw]", has_text="Material liberable SALON")
    raw.get_by_role("button", name="Crear contenido con este material").click()
    composer = page.locator("#owner-instagram-composer")
    expect(page.locator("#owner-instagram-preview-stage img")).to_be_visible()
    composer.locator("#owner-instagram-composer-caption").fill(caption)
    if publication == "schedule":
        planned = datetime.now(timezone.utc) + timedelta(days=3)
        composer.locator("#owner-instagram-composer-date").fill(planned.date().isoformat())
        composer.locator("#owner-instagram-composer-time").fill("12:30")
        composer.locator("#owner-instagram-composer-primary").click()
    else:
        composer.get_by_text(re.compile("Publicar ahora")).click()
        composer.locator("#owner-instagram-composer-primary").click()
    expect(composer).to_be_hidden(timeout=15_000)

    with SessionLocal() as db:
        content = db.query(InstagramContent).filter(InstagramContent.title == caption).one()
        current = max(content.versions, key=lambda version: version.version_number)
        assert len(current.asset_links) == 1
        assert db.query(InstagramContentRawAsset).filter_by(content_id=content.id).count() == 1
        assert db.query(InstagramFinalAsset).filter_by(content_id=content.id).count() == 1
        assert len(content.publish_jobs) == 1
        if publication == "schedule":
            assert content.planned_publish_at is not None
        else:
            assert content.planned_publish_at is None


def test_owner_raw_association_manager_classifies_and_updates_without_reload(journey) -> None:
    session, page = _open_owner_instagram(journey)
    page.locator("summary", has_text="Herramientas avanzadas de material").click()
    shared = page.locator("[data-owner-instagram-raw]", has_text="Material compartido SALON")
    session.expect_response_error(409, "DELETE", "/instagram-content/raw-assets/")
    page.once("dialog", lambda confirmation: confirmation.accept())
    shared.get_by_role("button", name="Eliminar").click()
    dialog = page.locator("#owner-instagram-associations-dialog")
    expect(dialog).to_be_visible()
    expect(page.locator("#owner-instagram-associations-count")).to_have_text("2")
    published = page.locator("[data-owner-instagram-association]", has_text="histórico protegido")
    expect(published).to_contain_text("Afecta a versión actualNo")
    expect(published.get_by_role("button", name="Desasociar")).to_be_visible()
    modifiable = page.locator(
        "[data-owner-instagram-association]", has_text="SALON borrador eliminable"
    )
    modifiable.get_by_role("button", name="Desasociar").click()
    expect(page.locator("#owner-instagram-associations-count")).to_have_text("1")
    published.get_by_role("button", name="Abrir contenido").click()
    expect(page.locator("#owner-instagram-composer")).to_be_visible()
    expect(page.locator("#owner-instagram-composer-title")).to_have_text("Consultar publicación")
    expect(page.locator("#owner-instagram-composer-caption")).to_have_value(
        "Caption publicada SALON"
    )
    page.locator("#owner-instagram-composer-close").click()
    shared.get_by_role("button", name="Asociaciones").click()
    expect(dialog).to_be_visible()
    page.locator("[data-owner-instagram-association]", has_text="histórico protegido").get_by_role(
        "button", name="Desasociar"
    ).click()
    expect(page.locator("#owner-instagram-associations-count")).to_have_text("0")
    expect(page.locator("#owner-instagram-associations-delete")).to_be_visible()
    page.locator("#owner-instagram-associations-done").click()

    freeable = page.locator("[data-owner-instagram-raw]", has_text="Material liberable SALON")
    freeable.get_by_role("button", name="Asociaciones").click()
    expect(dialog).to_be_visible()
    dialog.get_by_role("button", name="Desasociar", exact=True).click()
    expect(page.locator("#owner-instagram-associations-count")).to_have_text("0")
    expect(page.locator("#owner-instagram-associations-delete")).to_be_visible()
    page.once("dialog", lambda confirmation: confirmation.accept())
    page.locator("#owner-instagram-associations-delete").click()
    expect(dialog).to_be_hidden()
    expect(freeable).to_have_count(0)


def test_owner_sees_technical_controls_admin_cannot_use(journey) -> None:
    _session, owner = _open_owner_instagram(journey)
    owner.get_by_role("button", name=re.compile("SALON lanzamiento")).click()
    expect(owner.locator("#owner-instagram-composer")).to_be_visible()
    expect(owner.locator("#owner-instagram-composer-advanced")).to_be_visible()
    expect(owner.locator("[data-owner-instagram-action='validate']")).to_have_count(0)
    assert owner.request.get("/api/owner/businesses/1/instagram-content/raw-assets").status == 200

    _admin_session, admin = _open_admin(journey)
    assert admin.request.get("/api/owner/businesses/1/instagram-content/raw-assets").status == 403


def test_mobile_admin_confirms_booking_and_opens_instagram(journey) -> None:
    _session, page = _open_admin(journey, mobile=True)
    page.get_by_role("button", name="Periodo siguiente").click()
    page.get_by_role("button", name=re.compile("Invitado Fixture, Color E2E")).click()
    pending = page.locator(".booking-card", has_text="Invitado Fixture")
    page.once("dialog", lambda dialog: dialog.accept())
    pending.get_by_role("button", name="Confirmar").click()
    expect(pending).to_contain_text("Confirmada", timeout=15_000)
    page.locator("[data-ag-shell-open]:not([data-ag-shell-more])").click()
    page.locator('[data-section="instagram-content"]').click()
    expect(page.locator("#admin-instagram-workspace")).to_be_visible()
    expect(page.get_by_role("button", name=re.compile("SALON lanzamiento"))).to_be_visible()
    assert page.evaluate("document.documentElement.scrollWidth <= window.innerWidth + 1")
