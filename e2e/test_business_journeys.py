from __future__ import annotations

import io
import re
from datetime import datetime, timedelta, timezone

import pytest
from PIL import Image
from playwright.sync_api import expect

from e2e.seed import JPEG_BYTES

pytestmark = pytest.mark.e2e


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
    assert page.request.get("/api/admin/businesses/salon-e2e/opportunities").status == 403


def test_admin_booking_day_week_month_and_confirm_without_reload(journey) -> None:
    _session, page = _open_admin(journey)
    expect(page.get_by_role("tab", name="Día")).to_have_attribute("aria-selected", "true")
    page.get_by_role("tab", name="Semana").click()
    expect(page.get_by_role("tab", name="Semana")).to_have_attribute("aria-selected", "true")
    page.get_by_role("tab", name="Mes").click()
    expect(page.get_by_role("tab", name="Mes")).to_have_attribute("aria-selected", "true")
    page.get_by_role("button", name="Hoy", exact=True).click()
    page.get_by_role("tab", name="Día").click()
    page.get_by_role("button", name=re.compile("Invitado Fixture, Color E2E")).click()
    pending = page.locator(".booking-card", has_text="Invitado Fixture")
    expect(pending).to_be_visible()
    expect(pending).to_contain_text("Color E2E")
    page.once("dialog", lambda dialog: dialog.accept())
    pending.get_by_role("button", name="Confirmar").click()
    expect(pending).to_contain_text("Confirmada", timeout=15_000)
    expect(pending).to_contain_text(re.compile(r"60\s*min"))


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
    with page.expect_response(lambda response: "editorial-review" in response.url) as review_info:
        detail.get_by_role("button", name="Aprobar editorialmente").click()
    assert review_info.value.status == 201
    assert review_info.value.json()["decision"] == "approve"
    reviewed = page.request.get(
        "/api/admin/businesses/salon-e2e/instagram-content/contents/1"
    ).json()
    assert any("editorial registrada" in comment["body"] for comment in reviewed["comments"])
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

    assert any(
        url.startswith("https://wa.me/34611000111")
        for url in session.whatsapp_urls
    ), session.whatsapp_urls
    popup.close()
    expect(pending).to_contain_text("Abierta en WhatsApp")
    expect(pending).to_contain_text(re.compile("no lo marc. como enviado", re.IGNORECASE))
    expect(pending).not_to_contain_text("Marcada como enviada")


def test_owner_business_switching_isolates_bookings_and_instagram(journey) -> None:
    _session, page = _open_owner_instagram(journey)
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
    expect(item).to_contain_text("Procesando en Instagram")

    with SessionLocal() as db:
        content = db.get(InstagramContent, content_id)
        job = db.get(InstagramPublishJob, job_id)
        content.status = "published"
        job.status = "published"
        job.provider_status = "published_simulated"
        job.provider_error_code = None
        job.safe_error_message = None
        job.provider_media_id = "e2e-media-published"
        job.provider_permalink = "https://www.instagram.com/p/e2e-safe/"
        job.published_at = datetime.now(timezone.utc)
        job.next_attempt_at = None
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
    composer.locator("#owner-instagram-composer-file").set_input_files(
        {"name": "reel.mp4", "mimeType": "video/mp4", "buffer": b"\x00\x00\x00\x18ftypisom"}
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
        lambda response: response.request.method == "POST"
        and response.url.endswith("/story-image")
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
    expect(library.get_by_role("tab", name="Instagram")).to_have_attribute(
        "aria-selected", "true"
    )
    expect(library.get_by_role("tab", name="Material del negocio")).to_be_disabled()
    library.get_by_role("button", name="Elegir imagen").click()
    expect(library.get_by_text("¿Qué imagen quieres usar?")).to_be_visible()
    library.get_by_role("button", name="Usar en Story").first.click()
    expect(library).to_be_hidden()
    expect(composer.locator("#owner-instagram-story-editor")).to_be_visible()


def test_owner_raw_association_manager_protects_and_updates_without_reload(journey) -> None:
    session, page = _open_owner_instagram(journey)
    page.locator("summary", has_text="Herramientas avanzadas de material").click()
    shared = page.locator("[data-owner-instagram-raw]", has_text="Material compartido SALON")
    session.expect_response_error(409, "DELETE", "/instagram-content/raw-assets/")
    page.once("dialog", lambda confirmation: confirmation.accept())
    shared.get_by_role("button", name="Eliminar").click()
    dialog = page.locator("#owner-instagram-associations-dialog")
    expect(dialog).to_be_visible()
    expect(page.locator("#owner-instagram-associations-count")).to_have_text("2")
    protected = page.locator("[data-owner-instagram-association]", has_text="histórico protegido")
    expect(protected).to_contain_text("ModificableNo")
    expect(protected.get_by_role("button", name="Desasociar")).to_have_count(0)
    modifiable = page.locator(
        "[data-owner-instagram-association]", has_text="SALON borrador eliminable"
    )
    modifiable.get_by_role("button", name="Desasociar").click()
    expect(page.locator("#owner-instagram-associations-count")).to_have_text("1")
    protected.get_by_role("button", name="Abrir contenido").click()
    expect(page.locator("#owner-instagram-composer")).to_be_visible()
    expect(page.locator("#owner-instagram-composer-title")).to_have_text("Editar publicación")
    expect(page.locator("#owner-instagram-composer-caption")).to_have_value(
        "Caption publicada SALON"
    )
    page.locator("#owner-instagram-composer-close").click()

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
