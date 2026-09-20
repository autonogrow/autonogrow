from __future__ import annotations

import base64
import io
import json
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


def _switch_admin_identity(page, token: str) -> None:
    page.locator("#admin-logout").click()
    expect(page.locator("#admin-auth-gate")).to_be_visible()
    page.evaluate("token => { window.__AUTONOGROW_E2E_GOOGLE_TOKEN = token; }", token)
    expect(page.locator("#admin-google-button button")).to_be_visible()
    page.locator("#admin-google-button button").click()


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
        expect(drawer).to_have_css("transform", re.compile(r"^(none|matrix\(1, 0, 0, 1, 0, 0\))$"))
    offenders = page.evaluate(
        """() => {
          const openPanels = [...document.querySelectorAll('.conversation-customer-panel.is-open')];
          const activeAdminSections = [...document.querySelectorAll('.admin-section-active')];
          const activeOwnerPanels = [...document.querySelectorAll('.panel.active')];
          const roots = openPanels.length ? openPanels : activeAdminSections.length ? activeAdminSections : activeOwnerPanels;
          const elements = [...new Set(roots.flatMap((root) => [root, ...root.querySelectorAll('*')]))];
          return elements
          .filter((element) => {
            const style = getComputedStyle(element);
            if (style.display === 'none' || style.visibility === 'hidden') return false;
            const rect = element.getBoundingClientRect();
            if (!(rect.width > 0 && (rect.left < -1 || rect.right > innerWidth + 1))) return false;
            let ancestor = element.parentElement;
            while (ancestor && !roots.includes(ancestor)) {
              const ancestorStyle = getComputedStyle(ancestor);
              if (['auto', 'scroll'].includes(ancestorStyle.overflowX)) {
                const ancestorRect = ancestor.getBoundingClientRect();
                if (ancestorRect.left >= -1 && ancestorRect.right <= innerWidth + 1) return false;
              }
              ancestor = ancestor.parentElement;
            }
            return true;
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
    assert page.evaluate(
        "document.documentElement.scrollWidth <= document.documentElement.clientWidth + 1"
    )


def _customer_drawer_geometry(page) -> dict:
    return page.evaluate(
        """() => {
          const panel = document.querySelector('.conversation-customer-panel.is-open');
          const header = panel.querySelector('.conversation-customer-panel__header');
          const content = panel.querySelector('.conversation-customer-content');
          const last = content.lastElementChild;
          const nav = document.querySelector('[data-ag-mobile-nav]');
          const navStyle = getComputedStyle(nav);
          const navVisible = navStyle.display !== 'none' && nav.getBoundingClientRect().height > 0;
          const panelRect = panel.getBoundingClientRect();
          const headerRect = header.getBoundingClientRect();
          const contentRect = content.getBoundingClientRect();
          const lastRect = last.getBoundingClientRect();
          const navRect = nav.getBoundingClientRect();
          return {
            viewportHeight: innerHeight,
            panelTop: panelRect.top,
            panelBottom: panelRect.bottom,
            panelWidth: panelRect.width,
            headerTop: headerRect.top,
            headerBottom: headerRect.bottom,
            contentTop: contentRect.top,
            contentBottom: contentRect.bottom,
            contentScrollHeight: content.scrollHeight,
            contentClientHeight: content.clientHeight,
            contentScrollTop: content.scrollTop,
            lastBottom: lastRect.bottom,
            navVisible,
            navTop: navVisible ? navRect.top : innerHeight,
            navHeight: navVisible ? navRect.height : 0,
            mobileNavToken: parseFloat(navStyle.minHeight),
            horizontalOverflow:
              document.documentElement.scrollWidth - document.documentElement.clientWidth
          };
        }"""
    )


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


@pytest.mark.parametrize("delay_old_response", [False, True], ids=["normal", "delayed-old-response"])
def test_admin_staff_admin_switch_never_reuses_privileged_appointments(
    journey, delay_old_response: bool
) -> None:
    from zoneinfo import ZoneInfo

    from app.core.database import SessionLocal
    from app.models import Booking, Business, BusinessUser, User

    session = journey(email="admin-a@e2e.test")
    with SessionLocal() as db:
        business = db.query(Business).filter(Business.slug == "salon-e2e").one()
        staff_membership = (
            db.query(BusinessUser)
            .join(User, User.id == BusinessUser.user_id)
            .filter(BusinessUser.business_id == business.id, User.email == "pro-1@e2e.test")
            .one()
        )
        admin_membership = (
            db.query(BusinessUser)
            .join(User, User.id == BusinessUser.user_id)
            .filter(BusinessUser.business_id == business.id, User.email == "admin-a@e2e.test")
            .one()
        )
        staff_booking = (
            db.query(Booking)
            .filter(
                Booking.business_id == business.id,
                Booking.staff_business_user_id == staff_membership.id,
                Booking.status == "confirmed",
            )
            .order_by(Booking.id)
            .first()
        )
        restricted_booking = (
            db.query(Booking)
            .filter(
                Booking.business_id == business.id,
                Booking.staff_business_user_id != staff_membership.id,
                Booking.start_datetime.is_not(None),
            )
            .order_by(Booking.id)
            .first()
        )
        assert staff_booking is not None
        assert restricted_booking is not None
        today = datetime.now(ZoneInfo("Europe/Madrid")).replace(
            hour=9, minute=0, second=0, microsecond=0, tzinfo=None
        )
        for booking, start, customer_name in (
            (staff_booking, today, "Mihai"),
            (restricted_booking, today.replace(hour=11), "Conflict QA A"),
        ):
            booking.start_datetime = start
            booking.end_datetime = start + timedelta(minutes=booking.duration_minutes or 45)
            booking.preferred_date = start.date().isoformat()
            booking.preferred_day_label = start.date().isoformat()
            booking.preferred_time = start.strftime("%H:%M")
            booking.customer.name = customer_name
        restricted_booking.staff_business_user_id = admin_membership.id
        staff_id = staff_membership.id
        staff_booking_id = staff_booking.id
        restricted_booking_id = restricted_booking.id
        db.commit()

    session.context.add_init_script(
        """
        (() => {
          const realFetch = window.fetch.bind(window);
          window.fetch = async (input, options) => {
            const shouldDelay = window.__DELAY_ADMIN_BOOKINGS === true;
            const response = await realFetch(input, options);
            if (shouldDelay
                && String(input).includes('/api/admin/businesses/salon-e2e/bookings?')) {
              await new Promise((resolve) => setTimeout(resolve, 800));
            }
            return response;
          };
        })();
        """
    )
    page = session.goto("/autonogrow-admin/?b=salon-e2e#bookings")
    expect(page.locator("#admin-app")).to_be_visible()
    expect(page.locator(f'[data-agenda-booking-open="{restricted_booking_id}"]')).to_be_visible()
    expect(page.locator(f'[data-agenda-booking-open="{staff_booking_id}"]')).to_be_visible()
    expect(page.locator("#bookings-list")).to_contain_text("Conflict QA A")
    expect(page.locator("#bookings-list")).to_contain_text("Mihai")
    assert "Admin" in page.locator(".agenda-staff-headings").inner_text()

    if delay_old_response:
        with page.expect_response(
            lambda response: response.request.method == "GET" and "/bookings?" in response.url
        ):
            page.evaluate(
                """() => {
                  window.__DELAY_ADMIN_BOOKINGS = true;
                  window.__OLD_ADMIN_BOOKINGS_PROMISE = loadBookings({ background: true });
                  window.__DELAY_ADMIN_BOOKINGS = false;
                }"""
            )

    page.locator("#admin-logout").click()
    expect(page.locator("#admin-auth-gate")).to_be_visible()
    page.evaluate(
        """bookingId => {
          window.__AUTONOGROW_E2E_GOOGLE_TOKEN = 'e2e-staff-a';
          window.__STALE_PRIVILEGED_BOOKING_SEEN = false;
          const check = () => {
            const app = document.getElementById('admin-app');
            const restricted = document.querySelector(
              `[data-agenda-booking-open="${bookingId}"], #booking-${bookingId}`
            );
            const adminLane = Array.from(document.querySelectorAll('.agenda-staff-headings strong'))
              .some((heading) => heading.textContent.includes('Admin'));
            if (app && !app.hidden && ((restricted && getComputedStyle(restricted).display !== 'none') || adminLane)) {
              window.__STALE_PRIVILEGED_BOOKING_SEEN = true;
            }
          };
          window.__STALE_OBSERVER = new MutationObserver(check);
          window.__STALE_OBSERVER.observe(document.body, {
            childList: true, subtree: true, attributes: true, attributeFilter: ['hidden', 'class']
          });
          check();
        }""",
        restricted_booking_id,
    )
    with page.expect_response(
        lambda response: response.request.method == "GET" and "/bookings?" in response.url
    ) as staff_bookings_response:
        page.locator("#admin-google-button button").click()
    expect(page.locator("#admin-app")).to_be_visible(timeout=15_000)
    expect(page.locator("#admin-auth-user")).to_have_text("staff")
    expect(page.locator("#business-subtitle")).to_have_text("Mi agenda y reservas asignadas")
    expect(page.locator("#bookings-list")).to_contain_text("Mihai")
    expect(page.locator("#bookings-list")).not_to_contain_text("Conflict QA A")
    expect(page.locator(f'[data-agenda-booking-open="{staff_booking_id}"]')).to_be_visible()
    expect(page.locator(f'[data-agenda-booking-open="{restricted_booking_id}"]')).to_have_count(0)
    expect(page.locator(f"#booking-{restricted_booking_id}")).to_have_count(0)
    expect(page.locator(".agenda-staff-headings strong")).to_have_count(1)
    expect(page.locator(".agenda-staff-headings strong")).to_have_text("Lucía")
    if delay_old_response:
        page.wait_for_timeout(900)
    assert page.evaluate("window.__STALE_PRIVILEGED_BOOKING_SEEN") is False
    staff_payload = staff_bookings_response.value.json()["bookings"]
    assert staff_payload
    assert {item["staff_business_user_id"] for item in staff_payload} == {staff_id}
    assert restricted_booking_id not in {item["id"] for item in staff_payload}
    staff_state = page.evaluate(
        """() => ({
          generation: adminSessionGeneration,
          userId: adminAuthUser.id,
          role: adminMembership.role,
          business: currentBusiness.slug,
          bookingIds: allBookings.map((booking) => booking.id),
          professionalIds: [...new Set(allBookings.map((booking) => booking.staff_business_user_id))]
        })"""
    )
    assert staff_state["generation"] > 0
    assert staff_state["role"] == "business_staff"
    assert staff_state["business"] == "salon-e2e"
    assert set(staff_state["bookingIds"]) == {item["id"] for item in staff_payload}
    assert staff_state["professionalIds"] == [staff_id]
    page.evaluate("window.__STALE_OBSERVER.disconnect()")

    _switch_admin_identity(page, "e2e-admin-a")
    expect(page.locator("#admin-app")).to_be_visible(timeout=15_000)
    expect(page.locator("#admin-auth-user")).to_contain_text("Admin")
    expect(page.locator("#bookings-list")).to_contain_text("Conflict QA A")
    expect(page.locator(f'[data-agenda-booking-open="{restricted_booking_id}"]')).to_be_visible()


def test_admin_switch_to_other_tenant_leaves_no_previous_business_dom(journey) -> None:
    session, page = _open_admin(journey)
    previous_booking = page.request.get(
        "/api/admin/businesses/salon-e2e/bookings"
    ).json()["bookings"][0]
    page.evaluate("bookingId => goToBooking(bookingId, false)", previous_booking["id"])
    expect(page.locator(f"#booking-{previous_booking['id']}")).to_be_visible()

    _switch_admin_identity(page, "e2e-admin-b")
    expect(page.locator("#admin-auth-gate")).to_be_visible(timeout=15_000)
    expect(page.locator("#admin-app")).to_be_hidden()
    expect(page.locator("#admin-auth-message")).to_contain_text("no tiene acceso")
    assert page.request.get("/api/auth/me").json()["email"] == "admin-b@e2e.test"
    assert page.locator("#bookings-list").text_content().strip() == ""
    assert "Salón E2E" not in page.locator("#admin-app").text_content()


def test_delayed_admin_response_cannot_repopulate_dom_after_staff_login(journey) -> None:
    session = journey(email="admin-a@e2e.test")
    session.context.add_init_script(
        """
        (() => {
          const realFetch = window.fetch.bind(window);
          window.fetch = async (input, options) => {
            const response = await realFetch(input, options);
            if (window.__DELAY_ADMIN_SERVICES
                && String(input).endsWith('/api/admin/businesses/salon-e2e/services')) {
              await new Promise((resolve) => setTimeout(resolve, 1000));
            }
            return response;
          };
        })();
        """
    )
    page = session.goto("/autonogrow-admin/?b=salon-e2e#services")
    expect(page.locator("#admin-app")).to_be_visible()
    expect(page.locator("#admin-services-list")).to_contain_text("Corte E2E")
    page.evaluate(
        """() => {
          window.__DELAY_ADMIN_SERVICES = true;
          window.__OLD_ADMIN_SERVICES_PROMISE = loadAdminServices();
          window.__DELAY_ADMIN_SERVICES = false;
        }"""
    )

    _switch_admin_identity(page, "e2e-staff-a")
    expect(page.locator("#admin-app")).to_be_visible(timeout=15_000)
    page.wait_for_timeout(1200)
    assert "Corte E2E" not in page.locator("#admin-services-list").text_content()
    assert page.request.get("/api/auth/me").json()["email"] == "pro-1@e2e.test"


def test_admin_business_status_controls_banner_and_submit_state(journey) -> None:
    from app.core.database import SessionLocal
    from app.models import Business

    session, page = _open_admin(journey)
    settings = page.request.get("/api/admin/businesses/salon-e2e/settings").json()
    assert settings["status"] == "active"
    assert settings["active"] is True
    expect(page.locator("body")).not_to_have_class(re.compile("business-non-operational"))
    expect(page.locator("#business-operational-banner")).to_be_hidden()
    expect(page.locator("#admin-instagram-raw-form button[type='submit']")).to_be_enabled()

    with SessionLocal() as db:
        business = db.query(Business).filter(Business.slug == "salon-e2e").one()
        business.status = "suspended"
        db.commit()

    session.expect_response_error(404, "GET", "/bookings")
    page.reload(wait_until="domcontentloaded")
    expect(page.locator("#admin-app")).to_be_visible()
    expect(page.locator("body")).to_have_class(re.compile("business-non-operational"))
    expect(page.locator("#business-operational-banner")).to_be_visible()
    expect(page.locator("#business-operational-banner-title")).to_have_text(
        "Este negocio está suspendido"
    )
    expect(page.locator("#admin-instagram-raw-form button[type='submit']")).to_be_disabled()


def test_public_page_publication_is_owner_only_and_persists_both_states(journey) -> None:
    _admin_session, admin = _open_admin(journey)
    admin.evaluate("showAdminSection('public-page')")
    expect(admin.locator("#public-page-publication-status")).to_have_text(
        "Publicada"
    )
    assert admin.locator("#business-setting-active").count() == 0

    _admin_session.expect_response_error(403, "PATCH", "/settings")
    denied = admin.evaluate(
        """async () => {
          const response = await fetch('/api/admin/businesses/salon-e2e/settings', {
            method: 'PATCH',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ name: 'Salón E2E', active: false })
          });
          return { status: response.status, body: await response.json() };
        }"""
    )
    assert denied["status"] == 403
    assert denied["body"]["detail"]["code"] == "owner_only_publication"
    assert admin.request.get("/api/businesses/salon-e2e").status == 200

    admin.locator("#business-setting-logo-alt").fill("Logo gobernado por Owner")
    with admin.expect_response(
        lambda response: response.request.method == "PATCH"
        and response.url.endswith("/api/admin/businesses/salon-e2e/settings")
    ) as normal_settings:
        admin.locator("#save-public-page-settings").click()
    assert normal_settings.value.status == 200
    expect(admin.locator("#admin-brand-feedback")).to_have_text("Guardado correctamente.")

    owner_session = journey(email="owner@e2e.test")
    owner = owner_session.goto("/autonogrow-owner/")
    expect(owner.locator("#owner-app")).to_be_visible()
    owner.locator('[data-tab="businesses"]').click()
    row = owner.locator('[data-business-row-id]').filter(has_text="Salón E2E")
    expect(row).to_be_visible()
    row.get_by_role("button", name="Abrir negocio").click()
    owner.locator('[data-owner-detail-tab="activation"]').click()
    activation = owner.locator('[data-owner-detail-panel="activation"]')
    expect(activation).to_contain_text(
        "Para vacaciones o cierres temporales usa las excepciones de disponibilidad."
    )
    expect(activation.locator('[data-owner-publication-controls]')).to_be_visible()
    expect(activation.locator('[data-owner-publication-status]')).to_have_text("Publicada")
    expect(activation.get_by_role("button", name="Despublicar página")).to_be_visible()

    owner.locator('[data-owner-publication]').click()
    owner.locator("#owner-dialog-reason").fill("Prueba E2E de gobernanza")
    with owner.expect_response(
        lambda response: response.request.method == "PATCH"
        and response.url.endswith("/publication")
    ) as unpublished:
        owner.locator("#owner-dialog-confirm").click()
    assert unpublished.value.status == 200
    expect(owner.locator('[data-owner-publication-status]')).to_have_text("Despublicada")
    expect(owner.locator('[data-owner-publication]')).to_have_text("Publicar página")
    assert owner.request.get("/api/businesses/salon-e2e").status == 404
    assert owner.request.get("/api/businesses/fisio-e2e").status == 200

    public_session = journey()
    public_session.expect_response_error(404, "GET", "/api/businesses/salon-e2e")
    landing = public_session.goto("/autonogrow-landing/?b=salon-e2e")
    expect(landing.locator("#landing-unavailable")).to_be_visible()
    expect(landing.locator("#landing-app")).to_be_hidden()

    owner.locator('[data-owner-publication]').click()
    owner.locator("#owner-dialog-reason").fill("Restaurar tras prueba E2E")
    with owner.expect_response(
        lambda response: response.request.method == "PATCH"
        and response.url.endswith("/publication")
    ) as published:
        owner.locator("#owner-dialog-confirm").click()
    assert published.value.status == 200
    expect(owner.locator('[data-owner-publication-status]')).to_have_text("Publicada")
    expect(owner.locator('[data-owner-publication]')).to_have_text("Despublicar página")
    assert owner.request.get("/api/businesses/salon-e2e").status == 200


def test_simplify_one_removes_noise_without_removing_operational_access(journey) -> None:
    _session, admin = _open_admin(journey)

    admin.evaluate("showAdminSection('conversations', 'replace')")
    expect(admin.locator("#conversation-list")).to_be_visible()
    expect(admin.locator("#conversation-detail")).to_be_hidden()
    admin.locator('#conversation-list [data-admin-action="select-conversation"]').last.click()
    expect(admin.locator("#conversation-detail")).to_be_visible()
    expect(admin.locator("#conversation-detail")).to_contain_text("WhatsApp")
    assert admin.locator(".conversation-automation-shortcut").count() == 0

    admin.set_viewport_size({"width": 390, "height": 844})
    admin.get_by_role("button", name="Volver a conversaciones").click()
    expect(admin.locator("#conversation-list")).to_be_visible()
    assert admin.locator(".conversation-automation-shortcut").count() == 0
    _assert_no_horizontal_overflow(admin)

    admin.set_viewport_size({"width": 1440, "height": 900})
    admin.evaluate("showAdminSection('configuration', 'replace')")
    expect(admin.locator("#pilot-readiness-summary")).to_contain_text(
        "Listo para recibir reservas"
    )
    expect(admin.locator("#configuration-tasks")).to_be_hidden()
    assert admin.locator("#configuration-overview-list").count() == 0

    admin.evaluate("showAdminSection('messages', 'replace')")
    automations = admin.locator('[data-admin-section="messages"]')
    expect(automations).not_to_contain_text("Sin cambios")
    expect(automations).not_to_contain_text(
        "Se evalúa cuando el sistema reconoce esta intención"
    )
    expect(automations.get_by_role("button", name="Guardar configuración")).to_be_visible()

    admin.evaluate("showAdminSection('growth', 'replace')")
    attention_ids = set(
        admin.locator("#growth-attention-list [data-customer-opportunity-preview]")
        .evaluate_all("items => items.map(item => item.dataset.customerOpportunityPreview)")
    )
    preview_ids = set(
        admin.locator("#growth-opportunities-preview [data-customer-opportunity-preview]")
        .evaluate_all("items => items.map(item => item.dataset.customerOpportunityPreview)")
    )
    assert attention_ids.isdisjoint(preview_ids)

    admin.evaluate("showAdminSection('summary', 'replace')")
    expect(admin.locator("#dashboard-stat-today").locator("xpath=ancestor::article")).to_be_hidden()
    expect(admin.locator("#dashboard-stat-pending").locator("xpath=ancestor::article")).to_be_visible()
    expect(admin.locator("#dashboard-stat-messages").locator("xpath=ancestor::article")).to_be_hidden()
    expect(admin.locator("#dashboard-weekly-activity")).not_to_contain_text(
        "Canceladas o rechazadas"
    )
    expect(admin.locator("#pilot-value-summary")).not_to_contain_text(
        "Growth · reservas atribuidas"
    )

    staff_session = journey(email="pro-1@e2e.test")
    staff = staff_session.goto("/autonogrow-admin/?b=salon-e2e#instagram-content")
    expect(staff.locator("#admin-app")).to_be_visible()
    expect(staff).to_have_url(re.compile(r"#bookings$"))
    expect(staff.locator('.admin-tab[data-section="instagram-content"]')).to_be_hidden()
    expect(staff.locator('[data-admin-section="bookings"]')).to_have_class(
        re.compile(r"\badmin-section-active\b")
    )


def test_owner_simplify_one_hides_healthy_noise_and_keeps_exceptions(journey) -> None:
    owner_session = journey(email="owner@e2e.test")
    owner = owner_session.goto("/autonogrow-owner/")
    expect(owner.locator("#owner-app")).to_be_visible()
    expect(owner.locator("#owner-sync-status")).to_contain_text("Actualizado", timeout=20_000)

    expect(owner.locator("#owner-metric-active").locator("xpath=ancestor::article")).to_be_visible()
    for metric_id in (
        "owner-metric-pending-businesses",
        "owner-metric-decisions",
        "owner-metric-integrations",
        "owner-metric-incidents",
        "owner-metric-messages",
    ):
        expect(owner.locator(f"#{metric_id}").locator("xpath=ancestor::article")).to_be_hidden()
    for block_id in (
        "owner-dashboard-decisions",
        "owner-dashboard-integrations",
        "owner-dashboard-incidents",
        "owner-dashboard-businesses",
    ):
        expect(owner.locator(f"#{block_id}")).to_be_hidden()
    expect(owner.locator("#owner-dashboard-operations")).to_be_visible()

    owner.evaluate("setActiveTab('businesses')")
    owner.evaluate(
        "openBusinessDetail(businesses.find(item => item.name === 'Salón E2E').id, 'activation')"
    )
    activation = owner.locator('[data-owner-detail-panel="activation"]')
    expect(activation).to_be_visible()
    expect(activation.locator("[data-owner-readiness-summary]")).not_to_have_text(
        "Sin comprobar en esta vista"
    )
    passed = activation.locator(".readiness-item.passed").first
    expect(passed).to_contain_text("Correcto")
    expect(passed.locator("p, small, button")).to_have_count(0)
    expect(activation.locator(".readiness-item:not(.passed) [data-owner-readiness-step]").first).to_be_visible()

    owner.evaluate("setActiveTab('audit')")
    audit = owner.locator('[data-panel="audit"]')
    expect(audit).not_to_contain_text("endpoint Owner")
    expect(audit).not_to_contain_text("no inventa actores")


def test_legitimate_admin_forbidden_responses_keep_valid_sessions_visible(journey) -> None:
    from app.core.database import SessionLocal
    from app.models import Business
    from app.services.capability_service import configure_business_modules

    staff_session = journey(email="pro-1@e2e.test")
    staff = staff_session.goto("/autonogrow-admin/?b=salon-e2e#bookings")
    expect(staff.locator("#admin-app")).to_be_visible()
    staff_session.expect_response_error(403, "GET", "/staff")
    staff.evaluate("loadStaffMembers()")
    expect(staff.locator("#admin-permission-feedback")).to_be_visible()
    expect(staff.locator("#admin-app")).to_be_visible()
    expect(staff.locator("#admin-auth-gate")).to_be_hidden()
    assert staff.request.get("/api/auth/me").status == 200

    admin_session, admin = _open_admin(journey)
    admin_session.expect_response_error(403, "GET", "/salon-e2e/services")
    admin.route(
        "**/api/admin/businesses/salon-e2e/services",
        lambda route: route.fulfill(
            status=403,
            content_type="application/json",
            body=json.dumps({"detail": "Configuración no permitida para esta cuenta."}),
        ),
    )
    admin.evaluate("loadAdminServices()")
    expect(admin.locator("#admin-permission-feedback")).to_be_visible()
    expect(admin.locator("#admin-app")).to_be_visible()
    assert admin.request.get("/api/auth/me").status == 200
    admin.unroute("**/api/admin/businesses/salon-e2e/services")
    admin.evaluate("stopAdminPolling()")

    with SessionLocal() as db:
        business = db.query(Business).filter(Business.slug == "salon-e2e").one()
        configure_business_modules(
            db,
            business_id=business.id,
            enabled_modules=("essential", "social"),
            actor_user_id=None,
        )
        db.commit()
    admin_session.expect_response_error(403, "GET", "/growth-metrics")
    admin.evaluate("loadGrowthActionMetrics()")
    expect(admin.locator("#admin-permission-feedback")).to_contain_text(
        "Este módulo no está disponible"
    )
    expect(admin.locator("#admin-app")).to_be_visible()
    expect(admin.locator("#admin-auth-gate")).to_be_hidden()
    assert admin.request.get("/api/auth/me").status == 200


def test_reviews_url_backend_rejects_unsafe_value_without_overwriting(journey) -> None:
    _session, page = _open_admin(journey)
    settings_path = "/api/admin/businesses/salon-e2e/settings"
    original = page.request.get(settings_path).json()
    csrf = page.evaluate(
        """async () => {
            const options = await AutonoGrowAuth.secureRequestOptions({ method: "PATCH" });
            return options.headers.get("X-CSRF-Token");
        }"""
    )
    safe_url = "https://reviews.example.test/e2e-safe"
    accepted = page.request.patch(
        settings_path,
        headers={"X-CSRF-Token": csrf},
        data={"name": original["name"], "reviews_url": safe_url},
    )
    assert accepted.status == 200

    rejected = page.request.patch(
        settings_path,
        headers={"X-CSRF-Token": csrf},
        data={
            "name": original["name"],
            "reviews_url": "javascript:alert(1)",
        },
    )
    assert rejected.status == 422
    assert page.request.get(settings_path).json()["reviews_url"] == safe_url

    restored = page.request.patch(
        settings_path,
        headers={"X-CSRF-Token": csrf},
        data={
            "name": original["name"],
            "reviews_url": original["reviews_url"],
        },
    )
    assert restored.status == 200


def test_growth_results_render_summary_values_and_refresh(journey) -> None:
    from app.core.database import SessionLocal
    from app.models import CustomerOpportunity, OpportunityAction

    _session, page = _open_admin(journey)
    page.evaluate("showAdminSection('growth')")
    expect(page.locator("#growth-result-prepared")).to_have_text("0")
    expect(page.locator("#growth-result-sent")).to_have_text("0")
    with SessionLocal() as db:
        opportunity = (
            db.query(CustomerOpportunity)
            .filter(CustomerOpportunity.reason_code == "service_due_e2e")
            .one()
        )
        db.add(
            OpportunityAction(
                business_id=opportunity.business_id,
                opportunity_id=opportunity.id,
                customer_id=opportunity.customer_id,
                action_type="contact_customer",
                status="sent",
                channel="whatsapp",
                suggested_text="Mensaje E2E",
                final_text="Mensaje E2E",
                sent_at=datetime.now(timezone.utc),
            )
        )
        db.commit()

    metrics_path = "/api/admin/businesses/salon-e2e/growth-metrics?period=30d"
    metrics = page.request.get(metrics_path).json()["summary"]
    assert metrics["actions_prepared"] == 1
    assert metrics["messages_sent"] == 1
    page.evaluate("loadGrowthActionMetrics()")
    page.evaluate("showAdminSection('growth')")
    expect(page.locator("#growth-result-detected")).to_have_text(
        str(metrics["opportunities_detected"])
    )
    expect(page.locator("#growth-result-prepared")).to_have_text("1")
    expect(page.locator("#growth-result-sent")).to_have_text("1")
    expect(page.locator("#growth-result-booked")).to_have_text(
        str(metrics["bookings_attributed"])
    )
    expect(page.locator("#growth-result-completed")).to_have_text(
        str(metrics["attributed_bookings_completed"])
    )
    for viewport in ({"width": 1024, "height": 768}, {"width": 390, "height": 844}):
        page.set_viewport_size(viewport)
        _assert_no_horizontal_overflow(page)
    page.reload(wait_until="domcontentloaded")
    expect(page.locator("#growth-result-prepared")).to_have_text("1")
    expect(page.locator("#growth-result-sent")).to_have_text("1")


def test_service_professional_count_handles_zero_one_two_after_refresh(journey) -> None:
    from app.core.database import SessionLocal
    from app.models import Business, BusinessService, BusinessUserService

    _session, page = _open_admin(journey)
    with SessionLocal() as db:
        service = (
            db.query(BusinessService)
            .join(Business, Business.id == BusinessService.business_id)
            .filter(Business.slug == "salon-e2e", BusinessService.name == "Corte E2E")
            .one()
        )
        service_id = service.id
        assignments = (
            db.query(BusinessUserService)
            .filter(BusinessUserService.service_id == service_id)
            .order_by(BusinessUserService.business_user_id)
            .all()
        )
        assert len(assignments) == 2
        assignment_ids = [item.business_user_id for item in assignments]
        other_count = (
            db.query(BusinessUserService)
            .join(BusinessService, BusinessService.id == BusinessUserService.service_id)
            .join(Business, Business.id == BusinessService.business_id)
            .filter(Business.slug == "fisio-e2e")
            .count()
        )

    def expect_count(expected: int) -> None:
        page.reload(wait_until="domcontentloaded")
        expect(page.locator("#admin-app")).to_be_visible()
        page.evaluate("showAdminSection('services')")
        label = "profesional" if expected == 1 else "profesionales"
        expect(
            page.locator(f".admin-service-item[data-service-id='{service_id}'] header p")
        ).to_contain_text(f"{expected} {label}")

    expect_count(2)
    with SessionLocal() as db:
        db.query(BusinessUserService).filter(
            BusinessUserService.service_id == service_id,
            BusinessUserService.business_user_id == assignment_ids[0],
        ).delete(synchronize_session=False)
        db.commit()
    expect_count(1)
    with SessionLocal() as db:
        db.query(BusinessUserService).filter(
            BusinessUserService.service_id == service_id,
            BusinessUserService.business_user_id == assignment_ids[1],
        ).delete(synchronize_session=False)
        db.commit()
        assert (
            db.query(BusinessUserService)
            .join(BusinessService, BusinessService.id == BusinessUserService.service_id)
            .join(Business, Business.id == BusinessService.business_id)
            .filter(Business.slug == "fisio-e2e")
            .count()
            == other_count
        )
    expect_count(0)


def test_service_deactivate_reactivate_preserves_team_assignments(journey) -> None:
    from app.core.database import SessionLocal
    from app.models import Business, BusinessService, BusinessUserService

    _session, page = _open_admin(journey)
    services_path = "/api/admin/businesses/salon-e2e/services"
    staff_path = "/api/admin/businesses/salon-e2e/staff"
    service = next(
        item
        for item in page.request.get(services_path).json()["services"]
        if item["name"] == "Corte E2E"
    )
    service_id = service["id"]
    initial_staff = page.request.get(staff_path).json()["staff"]
    initial_service_ids = {
        item["id"]: item["service_ids"]
        for item in initial_staff
        if service_id in item["service_ids"]
    }
    assigned_member_ids = set(initial_service_ids)
    assert len(assigned_member_ids) == 2
    with SessionLocal() as db:
        other_business_id = db.query(Business.id).filter(Business.slug == "fisio-e2e").scalar()
        other_assignment_count = (
            db.query(BusinessUserService)
            .join(BusinessService, BusinessUserService.service_id == BusinessService.id)
            .filter(BusinessService.business_id == other_business_id)
            .count()
        )

    page.evaluate("showAdminSection('services')")
    service_card = page.locator(f".admin-service-item[data-service-id='{service_id}']")
    expect(service_card.locator("header p")).to_contain_text("2 profesionales")
    page.once("dialog", lambda dialog: dialog.accept())
    with page.expect_response(
        lambda response: (
            response.request.method == "PATCH" and response.url.endswith(f"/services/{service_id}")
        )
    ):
        service_card.locator(".service-active").uncheck()
        service_card.get_by_role("button", name="Guardar servicio").click()

    public_services = page.request.get("/api/businesses/salon-e2e/services").json()
    assert service_id not in {item["id"] for item in public_services}
    public_session = journey()
    landing = public_session.goto("/autonogrow-landing/?b=salon-e2e")
    expect(
        landing.locator("#booking-service-options .choice-button", has_text="Corte E2E")
    ).to_have_count(0)
    assert (
        page.request.get(f"/api/businesses/salon-e2e/staff?service_id={service_id}").status == 404
    )
    assert (
        page.request.get(
            f"/api/businesses/salon-e2e/available-slots?service_id={service_id}&date=2030-01-02"
        ).status
        == 404
    )
    assert "Corte E2E" in {
        item["service_name"]
        for item in page.request.get("/api/admin/businesses/salon-e2e/bookings").json()["bookings"]
    }
    inactive_staff = page.request.get(staff_path).json()["staff"]
    assert {
        item["id"]: item["service_ids"]
        for item in inactive_staff
        if item["id"] in assigned_member_ids
    } == initial_service_ids
    assert assigned_member_ids == {
        item["id"] for item in inactive_staff if service_id in item["service_ids"]
    }

    page.reload(wait_until="domcontentloaded")
    expect(page.locator("#admin-app")).to_be_visible()
    page.evaluate("showAdminSection('services')")
    service_card = page.locator(f".admin-service-item[data-service-id='{service_id}']")
    expect(service_card.locator("header p")).to_contain_text("2 profesionales")
    with page.expect_response(
        lambda response: (
            response.request.method == "PATCH" and response.url.endswith(f"/services/{service_id}")
        )
    ):
        service_card.locator(".service-active").check()
        service_card.get_by_role("button", name="Guardar servicio").click()

    page.evaluate("showAdminSection('staff')")
    for member_id in assigned_member_ids:
        expect(
            page.locator(
                f"[data-staff-id='{member_id}'] .staff-service-checkbox[value='{service_id}']"
            )
        ).to_be_checked()
    page.reload(wait_until="domcontentloaded")
    expect(page.locator("#admin-app")).to_be_visible()
    page.evaluate("showAdminSection('services')")
    expect(
        page.locator(f".admin-service-item[data-service-id='{service_id}']").locator("header p")
    ).to_contain_text("2 profesionales")
    final_staff = page.request.get(staff_path).json()["staff"]
    assert {
        item["id"]: item["service_ids"] for item in final_staff if item["id"] in assigned_member_ids
    } == initial_service_ids
    with SessionLocal() as db:
        assert (
            db.query(BusinessUserService)
            .join(BusinessService, BusinessUserService.service_id == BusinessService.id)
            .filter(BusinessService.business_id == other_business_id)
            .count()
            == other_assignment_count
        )


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
    home_opportunity = today.locator(".dashboard-growth-opportunity").filter(
        has_text="María Cliente E2E"
    )
    expect(home_opportunity).to_contain_text(
        "Creación de página profesional de Instagram y TikTok con estrategia de contenidos E2E"
    )
    expect(
        home_opportunity.locator(".dashboard-growth-opportunity__actions .ag-button")
    ).to_have_count(2)
    for size in (
        {"width": 1280, "height": 800},
        {"width": 900, "height": 900},
        {"width": 768, "height": 1024},
        {"width": 390, "height": 844},
    ):
        page.set_viewport_size(size)
        page.locator('.admin-tab[data-section="summary"]').evaluate("button => button.click()")
        expect(home_opportunity).to_be_visible()
        home_opportunity.locator("h5").evaluate(
            "element => { element.textContent = 'María Cliente E2E con un nombre deliberadamente largo está en fecha de volver'; }"
        )
        geometry = home_opportunity.evaluate(
            """element => {
              const card = element.getBoundingClientRect();
              const header = element.querySelector('.dashboard-growth-opportunity__header').getBoundingClientRect();
              const title = element.querySelector('h5');
              const actions = element.querySelector('.dashboard-growth-opportunity__actions').getBoundingClientRect();
              const description = element.querySelector('.dashboard-growth-opportunity__description');
              const metadata = element.querySelector('.dashboard-growth-opportunity__metadata');
              const descriptionRect = description.getBoundingClientRect();
              const metadataRect = metadata.getBoundingClientRect();
              return {
                card,
                header,
                titleWidth: title.getBoundingClientRect().width,
                titleWordBreak: getComputedStyle(title).wordBreak,
                actions,
                description: descriptionRect,
                descriptionScrollWidth: description.scrollWidth,
                descriptionClientWidth: description.clientWidth,
                descriptionOverflowWrap: getComputedStyle(description).overflowWrap,
                metadata: metadataRect,
                metadataScrollWidth: metadata.scrollWidth,
                metadataClientWidth: metadata.clientWidth
              };
            }"""
        )
        block_widths = [
            geometry["header"]["width"],
            geometry["actions"]["width"],
            geometry["description"]["width"],
            geometry["metadata"]["width"],
        ]
        assert max(block_widths) - min(block_widths) <= 1
        assert min(block_widths) >= geometry["card"]["width"] * 0.8
        assert geometry["titleWidth"] >= geometry["header"]["width"] * 0.7
        assert geometry["header"]["bottom"] <= geometry["actions"]["top"] + 1
        assert geometry["actions"]["bottom"] <= geometry["description"]["top"] + 1
        assert geometry["description"]["bottom"] <= geometry["metadata"]["top"] + 1
        assert geometry["descriptionScrollWidth"] <= geometry["descriptionClientWidth"] + 1
        assert geometry["metadataScrollWidth"] <= geometry["metadataClientWidth"] + 1
        assert geometry["descriptionOverflowWrap"] == "break-word"
        assert geometry["titleWordBreak"] == "normal"
        _assert_no_horizontal_overflow(page)
    secondary_action = home_opportunity.get_by_role("button", name="Ver oportunidad")
    secondary_action.evaluate("element => { element.hidden = true; }")
    expect(home_opportunity.get_by_role("button", name="Preparar mensaje")).to_be_visible()
    one_action_widths = home_opportunity.evaluate(
        """element => ({
          actions: element.querySelector('.dashboard-growth-opportunity__actions').getBoundingClientRect().width,
          description: element.querySelector('.dashboard-growth-opportunity__description').getBoundingClientRect().width
        })"""
    )
    assert abs(one_action_widths["actions"] - one_action_widths["description"]) <= 1
    _assert_no_horizontal_overflow(page)
    secondary_action.evaluate("element => { element.hidden = false; }")
    page.set_viewport_size({"width": 1280, "height": 800})
    page.locator('.admin-tab[data-section="summary"]').evaluate("button => button.click()")
    _assert_no_horizontal_overflow(page)
    today.get_by_role("button", name="Ver oportunidad").first.click()

    opportunity = page.locator("[data-customer-opportunity]").filter(has_text="Cliente E2E")
    expect(opportunity).to_be_visible()
    _assert_no_horizontal_overflow(page)
    opportunity.get_by_role("button", name="Ver cliente").click()

    customer_growth = page.locator(".customer-growth")
    expect(customer_growth).to_be_visible()
    expect(customer_growth).to_contain_text("Oportunidades activas")
    expect(customer_growth).to_contain_text("profesional de Instagram")
    _assert_no_horizontal_overflow(page)
    customer_growth.get_by_role("button", name="Abrir conversación").click()

    page.locator("#conversation-customer-close").click()
    follow_up = page.locator(".conversation-growth-follow-up")
    expect(follow_up).to_contain_text("Este cliente requiere seguimiento porque")
    expect(follow_up).to_contain_text("Esta nota E2E es deliberadamente larga")
    follow_up.get_by_role("button", name="Ver oportunidad").click()
    expect(opportunity).to_be_visible()

    for size in ({"width": 768, "height": 1024}, {"width": 390, "height": 844}):
        page.set_viewport_size(size)
        page.locator('.admin-tab[data-section="summary"]').evaluate("button => button.click()")
        expect(today).to_contain_text("Oportunidades para hoy")
        _assert_no_horizontal_overflow(page)
        today.get_by_role("button", name="Ver oportunidad").first.click()
        expect(opportunity).to_be_visible()
        _assert_no_horizontal_overflow(page)
        opportunity.get_by_role("button", name="Ver cliente").click()
        expect(customer_growth).to_be_visible()
        _assert_no_horizontal_overflow(page)
        page.locator("#conversation-customer-close").click()


def test_growth_message_modal_stays_usable_with_long_service_name(journey) -> None:
    _session, page = _open_admin(journey)
    page.locator('.admin-tab[data-section="growth"]').click()
    page.get_by_role("button", name="Oportunidades").click()

    opportunity = page.locator("[data-customer-opportunity]").first
    expect(opportunity).to_be_visible()
    expect(opportunity).to_contain_text("profesional de Instagram")
    opportunity.get_by_role("button", name="Preparar mensaje").click()

    modal = page.locator("#growth-action-modal.open")
    textarea = page.locator("#growth-action-text")
    expect(modal).to_be_visible()
    expect(textarea).to_be_visible()
    expect(page.locator(".growth-action-modal-actions")).to_be_visible()
    for size in ((1280, 800), (390, 844)):
        page.set_viewport_size({"width": size[0], "height": size[1]})
        geometry = modal.evaluate(
            """element => {
              const modal = element.getBoundingClientRect();
              const textarea = document.querySelector('#growth-action-text').getBoundingClientRect();
              const actions = document.querySelector('.growth-action-modal-actions').getBoundingClientRect();
              return { modal, textarea, actions, viewport: innerHeight };
            }"""
        )
        assert geometry["modal"]["top"] >= 0
        assert geometry["modal"]["bottom"] <= geometry["viewport"]
        assert geometry["textarea"]["height"] >= 100
        assert geometry["actions"]["bottom"] <= geometry["viewport"]
        textarea.evaluate(
            "element => { element.value = 'https://example.test/' + 'signed-token-'.repeat(180); }"
        )
        assert textarea.evaluate("element => element.scrollWidth <= element.clientWidth + 1")


def test_growth_action_cancel_expire_and_safe_retry_journeys(journey) -> None:
    from app.core.database import SessionLocal
    from app.models import (
        Business,
        BusinessChannelIntegration,
        ChannelOutboxMessage,
        ConversationMessage,
        CustomerOpportunity,
        OpportunityAction,
    )

    _session, page = _open_admin(journey)
    page.locator('.admin-tab[data-section="growth"]').click()
    page.get_by_role("button", name="Oportunidades").click()
    opportunity_card = page.locator("[data-customer-opportunity]").filter(
        has_text="Cliente E2E"
    )
    opportunity_card.get_by_role("button", name="Preparar mensaje").click()
    modal = page.locator("#growth-action-modal.open")
    expect(modal).to_be_visible()
    page.locator("#growth-action-text").fill("Primer intento editado por E2E")
    modal.get_by_role("button", name="Cancelar intento").click()
    expect(page.locator("#growth-action-modal")).not_to_have_class(re.compile(r"\bopen\b"))
    expect(
        opportunity_card.get_by_role("button", name="Preparar nuevo mensaje")
    ).to_be_visible()

    opportunity_card.get_by_role("button", name="Preparar nuevo mensaje").click()
    expect(modal).to_be_visible()
    expect(page.locator("#growth-action-text")).to_be_editable()
    modal.get_by_role("button", name="Cerrar").click()
    with SessionLocal() as db:
        business = db.query(Business).filter(Business.slug == "salon-e2e").one()
        opportunity = (
            db.query(CustomerOpportunity)
            .filter(
                CustomerOpportunity.business_id == business.id,
                CustomerOpportunity.reason_code == "service_due_e2e",
            )
            .one()
        )
        attempts = (
            db.query(OpportunityAction)
            .filter(OpportunityAction.opportunity_id == opportunity.id)
            .order_by(OpportunityAction.id)
            .all()
        )
        assert [item.status for item in attempts] == ["cancelled", "draft"]
        expired_action = attempts[-1]
        expired_id = expired_action.id
        expired_url = expired_action.final_text
        expired_action.expires_at = datetime.now(timezone.utc) - timedelta(seconds=1)
        db.commit()

    opportunity_card.get_by_role("button", name="Continuar borrador").click()
    expect(modal).to_be_visible()
    expect(page.locator("#growth-action-text")).to_be_editable()
    modal.get_by_role("button", name="Cerrar").click()
    with SessionLocal() as db:
        opportunity = (
            db.query(CustomerOpportunity)
            .filter(CustomerOpportunity.reason_code == "service_due_e2e")
            .one()
        )
        attempts = (
            db.query(OpportunityAction)
            .filter(OpportunityAction.opportunity_id == opportunity.id)
            .order_by(OpportunityAction.id)
            .all()
        )
        assert len(attempts) == 3
        assert attempts[-2].id == expired_id
        assert attempts[-2].failure_reason == "draft_expired"
        current = attempts[-1]
        assert current.id != expired_id
        assert current.final_text != expired_url
        integration = BusinessChannelIntegration(
            business_id=current.business_id,
            channel="whatsapp",
            provider="whatsapp",
            external_account_id="e2e-recovery-phone-id",
            integration_status="connected",
        )
        message = ConversationMessage(
            conversation_id=current.conversation_id,
            direction="outbound",
            sender_type="business",
            body=current.final_text,
            delivery_status="blocked",
        )
        db.add_all((integration, message))
        db.flush()
        current.status = "failed"
        current.message_id = message.id
        current.failed_at = datetime.now(timezone.utc)
        current.failure_reason = "integration_not_configured"
        outbox = ChannelOutboxMessage(
            business_id=current.business_id,
            integration_id=integration.id,
            conversation_id=current.conversation_id,
            conversation_message_id=message.id,
            channel="whatsapp",
            provider="whatsapp",
            recipient_external_id="34600000001",
            payload_json=json.dumps({"text": message.body}),
            idempotency_key=f"whatsapp:outbound-message:{message.id}",
            status="blocked",
            max_attempts=3,
            available_at=datetime.now(timezone.utc).replace(tzinfo=None),
        )
        db.add(outbox)
        db.commit()
        action_id = current.id

    page.reload(wait_until="domcontentloaded")
    expect(page.locator("#admin-app")).to_be_visible()
    page.locator('.admin-tab[data-section="growth"]').click()
    page.get_by_role("button", name="Oportunidades").click()
    opportunity_card = page.locator("[data-customer-opportunity]").filter(
        has_text="Cliente E2E"
    )
    opportunity_card.get_by_role("button", name="Reintentar envío").click()
    expect(page.locator("#growth-action-notice")).to_contain_text(
        "Puedes reintentar de forma segura"
    )
    modal.get_by_role("button", name="Reintentar envío").click()
    expect(page.locator("#growth-action-status")).to_have_text("Pendiente de entrega")
    with SessionLocal() as db:
        assert db.get(OpportunityAction, action_id).status == "approved"
        assert db.query(ConversationMessage).count() == 1
        assert db.query(ChannelOutboxMessage).count() == 1
        assert db.query(ChannelOutboxMessage).one().status == "pending"


def test_growth_opportunity_opens_customer_without_conversation(journey) -> None:
    _session, page = _open_admin(journey)
    page.locator('.admin-tab[data-section="growth"]').click()
    page.get_by_role("button", name="Oportunidades").click()

    opportunity = page.locator("[data-customer-opportunity]").filter(has_text="Invitado Fixture")
    expect(opportunity).to_be_visible()
    expect(opportunity.get_by_role("button", name="Ver conversaci\u00f3n")).to_have_count(0)
    opportunity.get_by_role("button", name="Ver cliente").click()
    expect(page.locator("#conversation-customer-content")).to_contain_text("Invitado Fixture")


def test_growth_results_and_reviews_keep_separate_product_surfaces(journey) -> None:
    _session, page = _open_admin(journey)
    page.get_by_role("button", name="Crecimiento", exact=True).click()

    page.locator('[data-growth-target="growth-opportunities"]:visible').click()
    opportunities = page.locator('[data-admin-section="growth-opportunities"]')
    expect(opportunities).to_be_visible()
    expect(opportunities.locator("[data-customer-opportunity]").first).to_be_visible()
    expect(opportunities).not_to_contain_text("Solicitudes de reseña asistidas")

    page.locator('[data-growth-target="growth"]:visible').click()
    results = page.locator(".growth-results-card")
    expect(results).to_be_visible()
    for label in (
        "Oportunidades detectadas",
        "Acciones preparadas",
        "Mensajes enviados",
        "Reservas vinculadas a acciones Growth",
        "Citas completadas",
        "Ingresos registrados en reservas vinculadas",
    ):
        expect(results).to_contain_text(label)
    expect(results).not_to_contain_text("Solicitudes preparadas")

    page.locator('[data-growth-target="reviews"]:visible').click()
    reviews = page.locator('[data-admin-section="reviews"]')
    expect(reviews).to_be_visible()
    expect(reviews).to_contain_text("Clientes atendidos")
    expect(reviews).to_contain_text("Solicitudes preparadas")
    expect(reviews).to_contain_text("Marcadas como enviadas")
    expect(reviews).to_contain_text("Solicitudes con error")


def test_conversation_uses_customer_instagram_as_visual_fallback_only(journey) -> None:
    _session, page = _open_admin(journey)
    page.locator('.admin-tab[data-section="conversations"]').click()

    fallback = page.locator(".conversation-list-item").filter(has_text="@mihii_mihii")
    expect(fallback).to_be_visible()
    fallback.click()
    expect(page.locator("#conversation-detail")).to_contain_text("@mihii_mihii")
    expect(page.locator("#conversation-send-button")).to_have_count(0)

    page.locator('[data-admin-action="open-conversation-customer-panel"]').click()
    expect(page.locator("#conversation-customer-content")).to_contain_text("Instagram del cliente")
    expect(page.locator("#conversation-customer-content")).to_contain_text("@mihii_mihii")


@pytest.mark.parametrize(
    ("email", "role"),
    (
        ("admin-a@e2e.test", "business_admin"),
        ("pro-1@e2e.test", "business_staff"),
    ),
)
@pytest.mark.parametrize(
    "viewport",
    (
        pytest.param({"width": 1440, "height": 900}, id="1440x900"),
        pytest.param({"width": 1024, "height": 768}, id="1024x768"),
        pytest.param({"width": 768, "height": 1024}, id="768x1024"),
        pytest.param({"width": 430, "height": 932}, id="430x932"),
        pytest.param({"width": 390, "height": 844}, id="390x844"),
        pytest.param({"width": 375, "height": 667}, id="375x667"),
    ),
)
def test_customer_details_drawer_keeps_final_content_above_mobile_navigation(
    journey, email: str, role: str, viewport: dict[str, int]
) -> None:
    session = journey(email=email)
    page = session.goto("/autonogrow-admin/?b=salon-e2e#conversations")
    page.set_viewport_size(viewport)
    expect(page.locator("#admin-app")).to_be_visible()
    assert page.evaluate("adminMembership.role") == role

    conversation = page.locator(".conversation-list-item").filter(
        has_text="María Cliente E2E"
    ).first
    expect(conversation).to_have_count(1, timeout=15_000)
    conversation.evaluate("button => button.click()")
    customer_button = page.locator(
        '[data-admin-action="open-conversation-customer-panel"]'
    )
    expect(customer_button).to_be_visible()
    customer_button.evaluate("button => button.click()")

    panel = page.locator(".conversation-customer-panel.is-open")
    content = page.locator("#conversation-customer-content")
    final_content = content.locator(".customer-memory--activity")
    expect(panel).to_be_visible()
    expect(page.locator("#conversation-customer-close")).to_be_visible()
    expect(final_content).to_contain_text("Comportamiento observado", timeout=15_000)

    content.evaluate("element => { element.scrollTop = element.scrollHeight; }")
    page.wait_for_timeout(50)
    manual_geometry = _customer_drawer_geometry(page)
    maximum_scroll = (
        manual_geometry["contentScrollHeight"] - manual_geometry["contentClientHeight"]
    )
    assert abs(manual_geometry["contentScrollTop"] - maximum_scroll) <= 1, manual_geometry
    assert manual_geometry["lastBottom"] <= manual_geometry["navTop"] + 1, manual_geometry
    assert manual_geometry["horizontalOverflow"] <= 1, manual_geometry
    assert manual_geometry["headerTop"] >= -1, manual_geometry
    if viewport["width"] <= 639:
        assert manual_geometry["navVisible"], manual_geometry
        assert abs(manual_geometry["navHeight"] - manual_geometry["mobileNavToken"]) <= 1
        assert manual_geometry["panelBottom"] <= manual_geometry["navTop"] + 1
    else:
        assert not manual_geometry["navVisible"], manual_geometry

    content.evaluate("element => { element.scrollTop = 0; }")
    final_content.evaluate("element => element.scrollIntoView({ block: 'end' })")
    page.wait_for_timeout(50)
    into_view_geometry = _customer_drawer_geometry(page)
    assert into_view_geometry["lastBottom"] <= into_view_geometry["navTop"] + 1, (
        into_view_geometry
    )

    page.locator("#conversation-customer-close").click()
    expect(panel).to_be_hidden()
    customer_button.evaluate("button => button.click()")
    expect(panel).to_be_visible()
    expect(final_content).to_be_visible()
    _assert_no_horizontal_overflow(page)


@pytest.mark.parametrize(
    ("email", "role"),
    (
        ("admin-a@e2e.test", "business_admin"),
        ("pro-1@e2e.test", "business_staff"),
    ),
)
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
def test_conversation_focus_workspace_navigation_for_admin_and_staff(
    journey, email: str, role: str, viewport: dict[str, int]
) -> None:
    session = journey(email=email)
    session.page.set_viewport_size(viewport)
    page = session.goto("/autonogrow-admin/?b=salon-e2e#conversations")
    expect(page.locator("#admin-app")).to_be_visible()
    assert page.evaluate("adminMembership.role") == role

    instagram_conversation = page.locator(".conversation-list-item").filter(
        has_text="Consulta por Instagram."
    )
    whatsapp_conversation = page.locator(".conversation-list-item").filter(
        has_text="Gracias, lo revisaré."
    )
    expect(instagram_conversation).to_be_visible(timeout=15_000)
    expect(whatsapp_conversation).to_be_visible()
    page.evaluate("window.__conversationFocusNavigationMarker = 'preserved'")

    instagram_conversation.click()
    detail = page.locator("#conversation-detail")
    expect(detail).to_be_visible()
    expect(page.locator(".conversation-list-panel")).to_be_hidden()
    expect(page.locator("#conversation-detail-title")).to_be_focused()
    expect(detail.locator(".conversation-detail-meta")).to_contain_text("@mihii_mihii")
    expect(page).to_have_url(re.compile(r"[?&]conversation=\d+#conversations$"))
    assert detail.locator(".conversation-channel").count() == 0
    assert detail.locator(".conversation-provider").count() == 0
    assert detail.locator(".conversation-intent-badge").count() == 0
    assert detail.locator(".conversation-attention-states").count() == 0

    templates = page.locator("#conversation-templates-control")
    automation = page.locator("#conversation-automation-control")
    tool_overlay = page.locator("#conversation-tool-overlay")
    expect(tool_overlay).to_be_hidden()
    expect(templates).to_have_attribute("aria-expanded", "false")
    expect(automation).to_have_attribute("aria-expanded", "false")
    conversation_title = page.locator("#conversation-detail-title").text_content()
    templates.click()
    expect(tool_overlay).to_be_visible()
    expect(tool_overlay).to_have_attribute("aria-hidden", "false")
    expect(templates).to_have_attribute("aria-expanded", "true")
    expect(page.locator("#conversation-tool-title")).to_have_text("Plantillas")
    expect(page.locator("#conversation-tool-title")).to_be_focused()
    expect(page.locator(".conversation-template-option").first).to_be_visible()
    page.get_by_role("button", name="Cerrar herramienta").click()
    expect(tool_overlay).to_be_hidden()
    expect(templates).to_be_focused()
    expect(page.locator("#conversation-detail-title")).to_have_text(conversation_title)
    automation.click()
    expect(tool_overlay).to_be_visible()
    expect(automation).to_have_attribute("aria-expanded", "true")
    expect(page.locator("#conversation-tool-title")).to_have_text("Automatización")
    expect(page.locator("#conversation-automation-duration")).to_be_visible()
    page.keyboard.press("Escape")
    expect(tool_overlay).to_be_hidden()
    expect(automation).to_be_focused()

    back_button = detail.get_by_role("button", name="Volver a conversaciones")
    customer_button = detail.get_by_role("button", name="Información del cliente")
    expect(back_button).to_be_visible()
    expect(customer_button).to_be_visible()
    customer_button.click()
    instagram_customer_panel = page.locator(".conversation-customer-panel.is-open")
    expect(instagram_customer_panel.locator(".conversation-customer-context")).to_contain_text("Instagram")
    expect(instagram_customer_panel.locator(".conversation-customer-context")).to_contain_text("Requiere seguimiento")
    expect(instagram_customer_panel.locator(".conversation-provider")).to_be_visible()
    instagram_customer_panel.get_by_role("button", name="Cerrar información del cliente").click()
    expect(customer_button).to_be_focused()

    back_button.click()
    expect(instagram_conversation).to_be_visible()
    expect(whatsapp_conversation).to_be_visible()
    expect(page).to_have_url(re.compile(r"\?b=salon-e2e#conversations$"))
    assert page.evaluate("window.__conversationFocusNavigationMarker") == "preserved"
    whatsapp_conversation.click()
    expect(detail).to_be_visible()
    expect(detail.locator(".conversation-detail-meta")).to_contain_text("+34 612 345 678")
    expect(page.locator("#conversation-reply-body")).to_be_visible()
    templates.click()
    expect(tool_overlay).to_be_visible()
    page.locator(".conversation-template-option").first.click()
    expect(tool_overlay).to_be_hidden()
    expect(page.locator("#conversation-reply-body")).not_to_have_value("")

    page.evaluate("history.back()")
    expect(whatsapp_conversation).to_be_visible()
    expect(page.locator(".conversation-list-panel")).to_be_visible()
    page.evaluate("history.forward()")
    expect(detail.locator(".conversation-detail-meta")).to_contain_text("+34 612 345 678")
    expect(page.locator(".conversation-list-panel")).to_be_hidden()
    assert page.evaluate("window.__conversationFocusNavigationMarker") == "preserved"
    workspace_geometry = page.evaluate(
        """() => {
          const workspace = document.querySelector('#conversation-center').getBoundingClientRect();
          const thread = document.querySelector('#conversation-thread');
          const footer = document.querySelector('.conversation-footer').getBoundingClientRect();
          const header = document.querySelector('.conversation-detail-header').getBoundingClientRect();
          const context = document.querySelector('.conversation-contextual-banner').getBoundingClientRect();
          const nav = document.querySelector('.ag-mobile-nav');
          const navRect = nav?.getBoundingClientRect();
          const navVisible = nav && getComputedStyle(nav).display !== 'none';
          return {
            workspace: { top: workspace.top, right: workspace.right, bottom: workspace.bottom, left: workspace.left },
            threadClientHeight: thread.clientHeight,
            threadScrollHeight: thread.scrollHeight,
            threadOverflowY: getComputedStyle(thread).overflowY,
            gridRows: getComputedStyle(document.querySelector('#conversation-detail')).gridTemplateRows,
            headerHeight: header.height,
            titleCenter: (() => { const rect = document.querySelector('#conversation-detail-title').getBoundingClientRect(); return rect.top + rect.height / 2; })(),
            actionCenter: (() => { const rect = document.querySelector('.conversation-operational-actions').getBoundingClientRect(); return rect.top + rect.height / 2; })(),
            contextHeight: context.height,
            footerHeight: footer.height,
            footerChildren: [...document.querySelector('.conversation-footer').children].map(element => ({
              className: element.className,
              height: element.getBoundingClientRect().height,
            })),
            footerBottom: footer.bottom,
            usableBottom: navVisible ? navRect.top : innerHeight,
            documentOverflow: document.documentElement.scrollWidth - document.documentElement.clientWidth,
          };
        }"""
    )
    assert workspace_geometry["threadClientHeight"] > 0, workspace_geometry
    assert abs(workspace_geometry["titleCenter"] - workspace_geometry["actionCenter"]) <= 2, workspace_geometry
    assert workspace_geometry["threadOverflowY"] == "auto", workspace_geometry
    assert workspace_geometry["footerBottom"] <= workspace_geometry["usableBottom"] + 1, json.dumps(
        workspace_geometry, indent=2
    )
    assert workspace_geometry["documentOverflow"] <= 1, workspace_geometry

    customer_button = detail.get_by_role("button", name="Información del cliente")
    customer_button.click()
    panel = page.locator(".conversation-customer-panel.is-open")
    final_content = panel.locator(".customer-memory--activity")
    expect(panel).to_be_visible()
    expect(final_content).to_contain_text("Comportamiento observado", timeout=15_000)
    final_content.scroll_into_view_if_needed()
    geometry = _customer_drawer_geometry(page)
    assert geometry["lastBottom"] <= geometry["navTop"] + 1, geometry

    panel.get_by_role("button", name="Cerrar información del cliente").click()
    expect(panel).to_be_hidden()
    expect(detail).to_be_visible()
    expect(detail.locator(".conversation-detail-meta")).to_contain_text("+34 612 345 678")

    if role == "business_staff":
        expect(page.locator("#toggle-conversation-create")).to_be_hidden()
        expect(panel.get_by_role("button", name="Cambiar cliente")).to_have_count(0)

    back_button = detail.get_by_role("button", name="Volver a conversaciones")
    back_button.click()
    expect(instagram_conversation).to_be_visible()
    instagram_conversation.click()
    expect(detail.locator(".conversation-detail-meta")).to_contain_text("@mihii_mihii")
    _assert_no_horizontal_overflow(page)


@pytest.mark.parametrize(
    "email",
    (
        pytest.param("admin-a@e2e.test", id="admin"),
        pytest.param("pro-1@e2e.test", id="staff"),
    ),
)
def test_conversation_focus_deep_link_survives_reload_and_rejects_unknown_id(
    journey, email: str
) -> None:
    session = journey(email=email)
    page = session.goto("/autonogrow-admin/?b=salon-e2e#conversations")
    conversation = page.locator(".conversation-list-item").filter(
        has_text="Gracias, lo revisaré."
    )
    expect(conversation).to_be_visible(timeout=15_000)
    conversation_id = int(conversation.get_attribute("data-id"))

    page = session.goto(
        f"/autonogrow-admin/?b=salon-e2e&conversation={conversation_id}#conversations"
    )
    expect(page.locator("#conversation-detail-title")).to_be_visible(timeout=15_000)
    expect(page.locator(".conversation-list-panel")).to_be_hidden()
    expect(page.locator(".conversation-detail-meta")).to_contain_text("+34 612 345 678")

    page.reload()
    expect(page.locator("#admin-app")).to_be_visible()
    expect(page.locator("#conversation-detail-title")).to_be_visible(timeout=15_000)
    expect(page.locator(".conversation-list-panel")).to_be_hidden()
    expect(page).to_have_url(
        re.compile(rf"[?&]conversation={conversation_id}#conversations$")
    )

    invalid_id = 999999999
    session.expect_response_error(404, "GET", f"/conversations/{invalid_id}")
    page = session.goto(
        f"/autonogrow-admin/?b=salon-e2e&conversation={invalid_id}#conversations"
    )
    expect(page.locator(".conversation-list-panel")).to_be_visible(timeout=15_000)
    expect(page).to_have_url(re.compile(r"\?b=salon-e2e#conversations$"))
    expect(page.locator("#conversation-feedback")).to_contain_text(
        "Has vuelto a la bandeja"
    )


def test_late_conversation_response_cannot_replace_new_focus(journey) -> None:
    session = journey(email="admin-a@e2e.test")
    page = session.goto("/autonogrow-admin/?b=salon-e2e#conversations")
    first = page.locator(".conversation-list-item").filter(
        has_text="Consulta por Instagram."
    )
    second = page.locator(".conversation-list-item").filter(
        has_text="Gracias, lo revisaré."
    )
    expect(first).to_be_visible(timeout=15_000)
    expect(second).to_be_visible()
    first_id = int(first.get_attribute("data-id"))

    delayed_routes = []

    def delay_first_conversation(route) -> None:
        delayed_routes.append(route)

    route_pattern = f"**/conversations/{first_id}"
    page.route(route_pattern, delay_first_conversation)

    first.click()
    expect(page.locator("#conversation-detail")).to_contain_text("Cargando conversación")
    page.get_by_role("button", name="Volver a conversaciones").click()
    expect(second).to_be_visible()
    second.click()
    expect(page.locator(".conversation-detail-meta")).to_contain_text("+34 612 345 678")

    assert len(delayed_routes) == 1
    delayed_routes[0].continue_()
    page.wait_for_timeout(250)
    expect(page.locator(".conversation-detail-meta")).to_contain_text("+34 612 345 678")
    expect(page.locator(".conversation-detail-meta")).not_to_contain_text("@mihii_mihii")
    page.unroute(route_pattern, delay_first_conversation)


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


def test_review_cycle_is_not_recreated_when_same_customer_returns(journey) -> None:
    from app.core.database import SessionLocal
    from app.models import Booking, Customer, ReviewRequest

    _session, page = _open_admin(journey)
    with SessionLocal() as db:
        returning_customer = db.query(Customer).filter(Customer.name == "Invitado Fixture").one()
        original_cycle = (
            db.query(ReviewRequest).filter(ReviewRequest.customer_id == returning_customer.id).one()
        )
        return_booking = (
            db.query(Booking)
            .filter(
                Booking.customer_id == returning_customer.id,
                Booking.status == "requested",
            )
            .one()
        )
        second_customer_booking = (
            db.query(Booking)
            .filter(
                Booking.customer_id != returning_customer.id,
                Booking.business_id == returning_customer.business_id,
                Booking.status == "completed",
            )
            .one()
        )
        original_cycle_id = original_cycle.id
        original_booking_id = original_cycle.booking_id
        returning_customer_id = returning_customer.id

    def mutate(path: str, payload: dict[str, str] | None = None) -> dict:
        return page.evaluate(
            """async ({ path, payload }) => {
              const response = await fetch(path, {
                method: payload ? 'PATCH' : 'POST',
                headers: payload ? { 'Content-Type': 'application/json' } : undefined,
                body: payload ? JSON.stringify(payload) : undefined
              });
              return { status: response.status, body: await response.json() };
            }""",
            {"path": path, "payload": payload},
        )

    sent = mutate(
        f"/api/admin/businesses/salon-e2e/review-requests/{original_cycle_id}/status",
        {"status": "sent"},
    )
    assert sent["status"] == 200
    assert (
        mutate(
            f"/api/admin/businesses/salon-e2e/bookings/{return_booking.id}/status",
            {"status": "confirmed"},
        )["status"]
        == 200
    )
    completed = mutate(
        f"/api/admin/businesses/salon-e2e/bookings/{return_booking.id}/status",
        {"status": "completed"},
    )
    assert completed["status"] == 200
    assert completed["body"]["review_request"]["id"] == original_cycle_id
    assert completed["body"]["review_request"]["booking_id"] == original_booking_id
    assert completed["body"]["review_request_reused"] is True
    assert completed["body"]["outbox_message"] is None

    second_customer = mutate(
        f"/api/admin/businesses/salon-e2e/bookings/{second_customer_booking.id}/review-request"
    )
    assert second_customer["status"] == 200
    assert second_customer["body"]["review_request"]["id"] != original_cycle_id

    review_rows = page.request.get("/api/admin/businesses/salon-e2e/review-requests").json()[
        "review_requests"
    ]
    assert len(review_rows) == 2
    assert len([item for item in review_rows if item["customer_id"] == returning_customer_id]) == 1

    page.reload(wait_until="domcontentloaded")
    page.get_by_role("button", name="Crecimiento", exact=True).click()
    page.locator('[data-growth-target="reviews"]:visible').click()
    expect(page.locator("#review-candidates-list")).not_to_contain_text("Invitado Fixture")
    expect(page.locator("#review-requests-history-list")).to_contain_text("Invitado Fixture")
    expect(page.locator("#review-metric-sent")).to_have_text("1")
    expect(page.locator("#review-metric-prepared")).to_have_text("1")


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


def test_admin_browser_history_deep_links_roles_and_services_cta(journey) -> None:
    session = journey(email="admin-a@e2e.test")
    page = session.goto("/autonogrow-admin/?b=salon-e2e#summary")
    expect(page.locator("#admin-app")).to_be_visible()
    expect(page.locator('[data-admin-section="summary"]')).to_have_class(
        re.compile(r"\badmin-section-active\b")
    )

    page.locator('.admin-tab[data-section="bookings"]').click()
    expect(page).to_have_url(re.compile(r"\?b=salon-e2e#bookings$"))
    page.locator('.admin-tab[data-section="conversations"]').click()
    expect(page).to_have_url(re.compile(r"\?b=salon-e2e#conversations$"))

    page.go_back(wait_until="domcontentloaded")
    expect(page).to_have_url(re.compile(r"#bookings$"))
    expect(page.locator('[data-admin-section="bookings"]')).to_have_class(
        re.compile(r"\badmin-section-active\b")
    )
    page.go_back(wait_until="domcontentloaded")
    expect(page).to_have_url(re.compile(r"#summary$"))
    expect(page.locator('[data-admin-section="summary"]')).to_have_class(
        re.compile(r"\badmin-section-active\b")
    )
    page.go_forward(wait_until="domcontentloaded")
    expect(page).to_have_url(re.compile(r"#bookings$"))

    page.reload(wait_until="domcontentloaded")
    expect(page.locator("#admin-app")).to_be_visible()
    expect(page).to_have_url(re.compile(r"\?b=salon-e2e#bookings$"))
    expect(page.locator('[data-admin-section="bookings"]')).to_have_class(
        re.compile(r"\badmin-section-active\b")
    )

    page.locator('.admin-tab[data-section="growth"]').click()
    expect(page).to_have_url(re.compile(r"#growth$"))
    page.locator('[data-admin-section="growth"] [data-growth-target="reviews"]').click()
    expect(page).to_have_url(re.compile(r"#reviews$"))
    page.reload(wait_until="domcontentloaded")
    expect(page.locator("#admin-app")).to_be_visible()
    expect(page).to_have_url(re.compile(r"\?b=salon-e2e#reviews$"))
    expect(page.locator('[data-admin-section="reviews"]')).to_have_class(
        re.compile(r"\badmin-section-active\b")
    )
    page.go_back(wait_until="domcontentloaded")
    expect(page).to_have_url(re.compile(r"#growth$"))
    expect(page.locator('[data-admin-section="growth"]')).to_have_class(
        re.compile(r"\badmin-section-active\b")
    )

    page.locator('.admin-tab[data-section="configuration"]').click()
    page.locator('[data-admin-section="configuration"] [data-configuration-target="services"]').click()
    expect(page).to_have_url(re.compile(r"#services$"))
    expect(page.locator('[data-admin-section="services"]')).to_have_class(
        re.compile(r"\badmin-section-active\b")
    )
    expect(page.locator("#services-settings-title")).to_have_text("Servicios")
    page.go_back(wait_until="domcontentloaded")
    expect(page).to_have_url(re.compile(r"#configuration$"))
    page.go_forward(wait_until="domcontentloaded")
    expect(page).to_have_url(re.compile(r"#services$"))
    expect(page.locator('[data-admin-section="services"]')).to_have_class(
        re.compile(r"\badmin-section-active\b")
    )
    page.go_back(wait_until="domcontentloaded")
    expect(page).to_have_url(re.compile(r"#configuration$"))

    staff_session = journey(email="pro-1@e2e.test")
    staff = staff_session.goto("/autonogrow-admin/?b=salon-e2e#services")
    expect(staff.locator("#admin-app")).to_be_visible()
    expect(staff).to_have_url(re.compile(r"\?b=salon-e2e#bookings$"))
    expect(staff.locator('[data-admin-section="bookings"]')).to_have_class(
        re.compile(r"\badmin-section-active\b")
    )


def test_growth_reviews_fit_every_supported_viewport_with_long_content(journey) -> None:
    _session, page = _open_admin(journey)
    page.evaluate("showAdminSection('reviews', 'replace')")
    expect(page.locator("#growth-reviews-title")).to_be_visible()
    expect(page.locator("#growth-review-link-card")).to_be_visible()
    expect(page.locator(".growth-review-block").first).to_be_visible()
    page.locator("#growth-review-link-card small").evaluate(
        "element => { element.textContent = 'https://reviews.example.test/' + 'identificador-muy-largo-'.repeat(30); }"
    )
    first_card_title = page.locator(".review-summary-card h4").first
    if first_card_title.count():
        first_card_title.evaluate(
            "element => { element.textContent = 'Cliente con un nombre deliberadamente largo para comprobar el ajuste correcto del contenido'; }"
        )

    for viewport in (
        {"width": 1440, "height": 900},
        {"width": 1280, "height": 800},
        {"width": 1024, "height": 768},
        {"width": 768, "height": 1024},
        {"width": 390, "height": 844},
    ):
        page.set_viewport_size(viewport)
        navigation = page.locator('[data-admin-section="reviews"] .growth-navigation')
        expect(navigation).to_be_visible()
        expect(navigation.locator("[data-growth-target='growth']")).to_be_visible()
        expect(page.locator("#growth-review-link-card")).to_be_visible()
        expect(page.locator(".growth-review-block").first).to_be_visible()
        _assert_no_horizontal_overflow(page)


def test_admin_social_formats_and_long_content_fit_responsive_matrix(journey) -> None:
    _session, page = _open_admin(journey)
    page.evaluate("showAdminSection('instagram-content', 'replace')")
    expect(page.locator("#admin-instagram-workspace")).to_be_visible()
    expect(page.locator("[data-admin-instagram-open]").first).to_be_visible(timeout=15_000)
    page.evaluate(
        """() => {
          const base = adminInstagramContents[0];
          const formats = ['single_image', 'carousel', 'reel', 'story'];
          adminInstagramCalendarView = 'today';
          adminInstagramCalendarDate = getMadridDateKey();
          adminInstagramContents = formats.map((format, index) => ({
            ...base,
            id: 9100 + index,
            title: `${format} ${'título editorial muy largo '.repeat(12)}`,
            status: 'ready_for_review',
            planned_publish_at: new Date(Date.now() + index * 60000).toISOString(),
            current_version: { ...base.current_version, format }
          }));
          adminInstagramSelectedContentId = null;
          renderAdminInstagramContents();
        }"""
    )
    format_filter = page.locator("#admin-instagram-format-filter")
    assert format_filter.locator("option").all_text_contents()[-4:] == [
        "Imagen",
        "Carrusel",
        "Reel",
        "Story",
    ]
    for label in ("Imagen", "Carrusel", "Reel", "Story"):
        expect(page.locator(".instagram-calendar-item", has_text=label)).to_have_count(1)

    for viewport in (
        {"width": 1440, "height": 900},
        {"width": 1280, "height": 800},
        {"width": 1024, "height": 768},
        {"width": 768, "height": 1024},
        {"width": 390, "height": 844},
    ):
        page.set_viewport_size(viewport)
        expect(page.locator("#admin-instagram-calendar")).to_be_visible()
        expect(format_filter).to_be_visible()
        _assert_no_horizontal_overflow(page)


def test_schedule_time_inputs_are_named_and_keyboard_focusable(journey) -> None:
    _session, page = _open_admin(journey)
    page.evaluate("showAdminSection('schedule', 'replace')")
    start = page.get_by_label(re.compile(r"Hora de inicio del tramo 1 de Lunes", re.I))
    end = page.get_by_label(re.compile(r"Hora de fin del tramo 1 de Lunes", re.I))
    expect(start).to_be_visible()
    expect(end).to_be_visible()
    start.focus()
    expect(start).to_be_focused()
    reached_end_with_keyboard = False
    for _attempt in range(4):
        page.keyboard.press("Tab")
        if end.evaluate("element => document.activeElement === element"):
            reached_end_with_keyboard = True
            break
    assert reached_end_with_keyboard

    page.locator('#exception-type').select_option("custom_hours")
    special_start = page.get_by_label("Hora de inicio del tramo especial 1")
    special_end = page.get_by_label("Hora de fin del tramo especial 1")
    expect(special_start).to_be_visible()
    expect(special_end).to_be_visible()
    page.locator('#exception-windows-panel [data-admin-action="add-exception-window"]').click()
    expect(page.get_by_label("Hora de inicio del tramo especial 2")).to_be_visible()
    expect(page.get_by_label("Hora de fin del tramo especial 2")).to_be_visible()


def test_owner_business_detail_fits_complete_viewport_matrix(journey) -> None:
    session = journey(email="owner@e2e.test")
    session.expect_response_error(404, "GET", "/api/owner/businesses/1/integrations/instagram")
    page = session.goto("/autonogrow-owner/")
    expect(page.locator("#owner-app")).to_be_visible()
    page.locator('[data-tab="businesses"]').click()
    row = page.locator("[data-business-row-id]").filter(has_text="Salón E2E")
    expect(row).to_be_visible()
    row.get_by_role("button", name="Abrir negocio").click()
    expect(page.locator("#business-detail")).to_be_visible()
    page.locator("#business-detail-title").evaluate(
        "element => { element.textContent = 'Certificación de negocio con un nombre deliberadamente largo para validar el layout Owner'; }"
    )

    for viewport in (
        {"width": 1440, "height": 900},
        {"width": 1280, "height": 800},
        {"width": 1024, "height": 768},
        {"width": 768, "height": 1024},
        {"width": 390, "height": 844},
    ):
        page.set_viewport_size(viewport)
        if viewport["width"] <= 1024:
            page.locator("[data-ag-shell-open]").click()
        page.locator('[data-tab="businesses"]').click()
        page.locator("#business-detail-title").evaluate(
            "element => { element.textContent = 'Certificación de negocio con un nombre deliberadamente largo para validar el layout Owner'; }"
        )
        for detail in ("summary", "activation", "modules", "users", "brand", "channels"):
            page.locator(f'[data-owner-detail-tab="{detail}"]').click()
            expect(page.locator(f'[data-owner-detail-panel="{detail}"]')).to_be_visible()
            _assert_no_horizontal_overflow(page)
        for main_view in ("overview", "integrations", "incidents", "operations", "audit"):
            if viewport["width"] <= 1024:
                page.locator("[data-ag-shell-open]").click()
            page.locator(f'[data-tab="{main_view}"]').click()
            active_panel = page.locator(f'[data-panel="{main_view}"]')
            expect(active_panel).to_be_visible()
            page.wait_for_timeout(100)
            _assert_no_horizontal_overflow(page)
