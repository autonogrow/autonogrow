from __future__ import annotations

import base64
import io
import json
from datetime import datetime, timezone

import pytest
from PIL import Image
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.core.config import Settings
from app.core.database import Base
from app.models import (
    Business,
    BusinessChannelIntegration,
    InstagramContent,
    InstagramContentVersion,
    InstagramMediaSyncState,
    InstagramPublishJob,
    InstagramRemoteMedia,
    MetaIntegrationJob,
    User,
)
from app.services.instagram_media_sync_service import enqueue_instagram_media_sync
from app.services.instagram_meta_client import (
    InstagramMetaClient,
    InstagramRemoteMediaItem,
    InstagramRemoteMediaPage,
    MetaHTTPError,
)
from app.services.instagram_remote_asset_service import RemoteAssetError, download_remote_image
from app.services.instagram_story_renderer import (
    StoryRenderError,
    StoryTransform,
    render_story_jpeg,
    story_derivation_fingerprint,
    story_geometry,
)
from app.services.integration_crypto_service import encrypt_secret
from app.services.meta_integration_job_service import (
    claim_meta_integration_jobs,
    schedule_due_meta_jobs,
)
from app.workers.channel_worker import ChannelWorker


def test_settings(**overrides) -> Settings:
    key = base64.urlsafe_b64encode(b"s" * 32).decode()
    values = {
        "app_env": "test",
        "integration_encryption_keys_json": json.dumps({"v1": key}),
        "integration_encryption_active_key_version": "v1",
        "instagram_media_sync_page_size": 2,
        "instagram_media_unavailable_probe_limit": 10,
        "meta_integration_failure_threshold": 3,
    }
    values.update(overrides)
    return Settings(_env_file=None, **values)


def image_bytes(width: int, height: int, color=(210, 40, 30), *, format="PNG") -> bytes:
    output = io.BytesIO()
    Image.new("RGB", (width, height), color).save(output, format=format)
    return output.getvalue()


@pytest.mark.parametrize("size", [(900, 1600), (800, 1200), (1600, 900), (900, 900)])
@pytest.mark.parametrize("mode", ["fill", "fit"])
def test_story_renderer_outputs_real_nine_by_sixteen_jpeg(size, mode):
    original = image_bytes(*size)
    snapshot = bytes(original)
    rendered = render_story_jpeg(
        original,
        transform=StoryTransform(mode=mode, background="light"),
        max_output_bytes=8 * 1024 * 1024,
    )

    assert original == snapshot
    assert rendered.startswith(b"\xff\xd8\xff")
    with Image.open(io.BytesIO(rendered)) as output:
        assert output.format == "JPEG"
        assert output.width * 16 == output.height * 9
        assert output.width <= 1080


def test_story_fit_background_position_zoom_and_fingerprint_are_deterministic():
    source = image_bytes(800, 800, (220, 20, 10))
    dark = StoryTransform(mode="fit", background="dark")
    light = StoryTransform(
        mode="fit", background="light", zoom=1.2, position_x=0.2, position_y=0.8
    )
    rendered_dark = render_story_jpeg(source, transform=dark, max_output_bytes=8 * 1024 * 1024)
    rendered_light = render_story_jpeg(
        source, transform=light, max_output_bytes=8 * 1024 * 1024
    )
    with Image.open(io.BytesIO(rendered_dark)) as output:
        dark_pixel = output.getpixel((5, 5))
    with Image.open(io.BytesIO(rendered_light)) as output:
        light_pixel = output.getpixel((5, 5))
    assert sum(light_pixel) > sum(dark_pixel)
    assert story_derivation_fingerprint("a" * 64, dark) == story_derivation_fingerprint(
        "a" * 64, dark
    )
    assert story_derivation_fingerprint("a" * 64, dark) != story_derivation_fingerprint(
        "a" * 64, light
    )


def test_story_geometry_matches_normalized_preview_contract_and_reset():
    reset = StoryTransform.from_json("{}")
    assert reset == StoryTransform()
    assert story_geometry(
        source_width=1600,
        source_height=900,
        canvas_width=360,
        canvas_height=640,
        transform=StoryTransform(mode="fill", position_x=0.0, position_y=1.0),
    ) == (1138, 640, 0, 0)
    assert StoryTransform.from_json(StoryTransform(mode="fit", zoom=2.5).to_json()).zoom == 2.5
    with pytest.raises(StoryRenderError):
        StoryTransform.from_json('{"zoom": 3}')


class FakeDownloadResponse:
    def __init__(self, content: bytes, *, content_type="image/png", status=200, headers=None):
        self.status_code = status
        self._content = content
        self.headers = {"Content-Type": content_type, **(headers or {})}
        self.closed = False

    def iter_content(self, chunk_size):
        del chunk_size
        yield self._content

    def close(self):
        self.closed = True


class FakeDownloadSession:
    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = []

    def get(self, url, **kwargs):
        self.calls.append((url, kwargs))
        return self.responses.pop(0)


def public_resolver(host, port, **kwargs):
    del host, port, kwargs
    return [(2, 1, 6, "", ("93.184.216.34", 443))]


def private_resolver(host, port, **kwargs):
    del host, port, kwargs
    return [(2, 1, 6, "", ("127.0.0.1", 443))]


def test_remote_download_validates_redirects_mime_magic_size_and_ssrf():
    content = image_bytes(40, 40)
    redirect = FakeDownloadResponse(
        b"", status=302, headers={"Location": "https://cdn.example.test/photo.png"}
    )
    final = FakeDownloadResponse(content, headers={"Content-Length": str(len(content))})
    session = FakeDownloadSession([redirect, final])
    result = download_remote_image(
        "https://media.example.test/start",
        settings=test_settings(),
        session=session,
        resolver=public_resolver,
    )
    assert result.content == content
    assert result.media_type == "image/png"
    assert len(session.calls) == 2
    assert all(call[1]["allow_redirects"] is False for call in session.calls)

    with pytest.raises(RemoteAssetError, match="not public"):
        download_remote_image(
            "https://localhost/private",
            settings=test_settings(),
            session=FakeDownloadSession([]),
            resolver=private_resolver,
        )
    with pytest.raises(RemoteAssetError, match="MIME"):
        download_remote_image(
            "https://media.example.test/photo",
            settings=test_settings(),
            session=FakeDownloadSession([FakeDownloadResponse(content, content_type="image/jpeg")]),
            resolver=public_resolver,
        )


class FakeMetaResponse:
    def __init__(self, payload, *, status_code=200):
        self.payload = payload
        self.status_code = status_code
        self.ok = status_code < 400
        self.headers = {}
        self.content = json.dumps(payload).encode()

    def json(self):
        return self.payload


class FakeMetaSession:
    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = []

    def request(self, method, url, **kwargs):
        self.calls.append((method, url, kwargs))
        return self.responses.pop(0)


def test_meta_read_client_parses_cursor_without_following_provider_next_url():
    session = FakeMetaSession(
        [
            FakeMetaResponse(
                {
                    "data": [
                        {
                            "id": "media-1",
                            "media_type": "IMAGE",
                            "media_product_type": "FEED",
                            "media_url": "https://cdn.example.test/a.jpg",
                            "permalink": "https://instagram.com/p/a",
                            "timestamp": "2026-08-24T10:00:00+0000",
                        }
                    ],
                    "paging": {
                        "cursors": {"after": "cursor-2"},
                        "next": "https://attacker.invalid/never-followed",
                    },
                }
            )
        ]
    )
    page = InstagramMetaClient(test_settings(), session=session).list_account_media(
        account_id="account-1", access_token="secret", limit=25
    )
    assert page.after_cursor == "cursor-2"
    assert page.items[0].provider_media_id == "media-1"
    assert len(session.calls) == 1
    assert session.calls[0][2]["headers"]["Authorization"] == "Bearer secret"


def test_meta_read_client_classifies_only_safe_not_found_as_unavailable():
    response = FakeMetaResponse({"error": {"code": 100, "type": "GraphMethodException"}}, status_code=400)
    client = InstagramMetaClient(test_settings(), session=FakeMetaSession([response]))
    with pytest.raises(MetaHTTPError) as raised:
        client.get_media(media_id="missing", access_token="secret")
    assert raised.value.unavailable is True
    assert raised.value.authentication is False


def remote_item(media_id: str, *, media_type="IMAGE") -> InstagramRemoteMediaItem:
    return InstagramRemoteMediaItem(
        provider_media_id=media_id,
        media_type=media_type,
        media_product_type="FEED",
        caption=f"caption-{media_id}",
        timestamp=datetime(2026, 8, 24, 10, 0, tzinfo=timezone.utc),
        permalink=f"https://instagram.com/p/{media_id}",
        media_url=f"https://cdn.example.test/{media_id}.jpg",
        thumbnail_url=None,
    )


class FakeSyncClient:
    def __init__(self):
        self.pages = {}
        self.children = {}
        self.details = {}
        self.list_error = None
        self.calls = []

    def list_account_media(self, **kwargs):
        self.calls.append(("list", kwargs["after_cursor"]))
        if self.list_error:
            raise self.list_error
        return self.pages[kwargs["after_cursor"]]

    def list_media_children(self, **kwargs):
        self.calls.append(("children", kwargs["media_id"]))
        return self.children[kwargs["media_id"]]

    def get_media(self, **kwargs):
        self.calls.append(("get", kwargs["media_id"]))
        value = self.details[kwargs["media_id"]]
        if isinstance(value, Exception):
            raise value
        return value


@pytest.fixture
def sync_context(tmp_path):
    engine = create_engine(
        f"sqlite:///{tmp_path / 'sync.db'}", connect_args={"check_same_thread": False}
    )
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    settings = test_settings()
    with factory() as db:
        business = Business(slug="sync-business", name="Sync Business", status="active")
        owner = User(email="sync-owner@example.test", is_owner=True)
        db.add_all([business, owner])
        db.flush()
        ciphertext, version = encrypt_secret("test-token", settings=settings)
        integration = BusinessChannelIntegration(
            business_id=business.id,
            channel="instagram",
            provider="instagram",
            external_account_id="account-1",
            encrypted_access_token=ciphertext,
            encryption_key_version=version,
            integration_status="connected",
        )
        db.add(integration)
        db.commit()
        yield db, factory, settings, business, owner, integration
    engine.dispose()


def process_next_sync(factory, settings, client):
    with factory() as db:
        ids = claim_meta_integration_jobs(
            db, worker_id="sync-test", limit=1, lock_ttl_seconds=120
        )
        db.commit()
    assert len(ids) == 1
    ChannelWorker(
        settings=settings,
        session_factory=factory,
        instagram_media_client=client,
        sleep=lambda _: None,
    )._process_meta_job(ids[0])
    return ids[0]


def test_periodic_scheduler_enqueues_one_conservative_sync(sync_context):
    db, _factory, _settings, business, _owner, integration = sync_context
    settings = test_settings(instagram_provider_enabled=True)
    db.add(
        InstagramMediaSyncState(
            business_id=business.id,
            integration_id=integration.id,
            status="succeeded",
            last_success_at=datetime(2026, 8, 23, tzinfo=timezone.utc),
            last_completed_at=datetime(2026, 8, 23, tzinfo=timezone.utc),
        )
    )
    db.flush()
    assert schedule_due_meta_jobs(db, settings=settings) == 1
    db.commit()
    job = db.query(MetaIntegrationJob).one()
    assert job.job_type == "instagram_media_sync"
    assert job.origin == "scheduler"
    assert schedule_due_meta_jobs(db, settings=settings) == 0


def test_sync_is_paginated_idempotent_and_reconciles_autonogrow(sync_context):
    db, factory, settings, business, owner, integration = sync_context
    content = InstagramContent(
        business_id=business.id,
        title="Known post",
        status="published",
        created_by_user_id=owner.id,
    )
    db.add(content)
    db.flush()
    version = InstagramContentVersion(
        business_id=business.id,
        content_id=content.id,
        version_number=1,
        caption="known",
        format="single_image",
        created_by_user_id=owner.id,
    )
    db.add(version)
    db.flush()
    db.add(
        InstagramPublishJob(
            business_id=business.id,
            content_item_id=content.id,
            content_version_id=version.id,
            integration_id=integration.id,
            status="published",
            scheduled_for=datetime.now(timezone.utc),
            attempt_count=1,
            max_attempts=3,
            idempotency_key="known-media-job",
            provider_media_id="known",
        )
    )
    db.commit()

    client = FakeSyncClient()
    client.pages = {
        None: InstagramRemoteMediaPage((remote_item("known"),), "cursor-2"),
        "cursor-2": InstagramRemoteMediaPage((remote_item("external"),), None),
    }
    client.details = {}
    enqueue_instagram_media_sync(db, business_id=business.id, origin="owner", settings=settings)
    db.commit()
    process_next_sync(factory, settings, client)
    assert db.query(InstagramRemoteMedia).count() == 1
    assert db.query(InstagramRemoteMedia).one().remote_status == "available"
    process_next_sync(factory, settings, client)

    rows = db.query(InstagramRemoteMedia).order_by(InstagramRemoteMedia.provider_media_id).all()
    assert len(rows) == 2
    known = next(row for row in rows if row.provider_media_id == "known")
    assert known.origin == "autonogrow"
    assert known.internal_content_id == content.id
    assert db.query(InstagramMediaSyncState).one().status == "succeeded"

    client.pages = {None: InstagramRemoteMediaPage(tuple(item for item in map(remote_item, ("known", "external"))), None)}
    enqueue_instagram_media_sync(db, business_id=business.id, origin="owner", settings=settings)
    db.commit()
    process_next_sync(factory, settings, client)
    assert db.query(InstagramRemoteMedia).count() == 2


def test_incomplete_or_failed_sync_never_marks_media_unavailable(sync_context):
    db, factory, settings, business, _owner, integration = sync_context
    old = InstagramRemoteMedia(
        business_id=business.id,
        integration_id=integration.id,
        provider_media_id="old",
        media_type="IMAGE",
        origin="instagram",
        remote_status="available",
    )
    db.add(old)
    db.commit()
    client = FakeSyncClient()
    client.pages = {None: InstagramRemoteMediaPage((remote_item("new"),), "cursor-2")}
    enqueue_instagram_media_sync(db, business_id=business.id, origin="owner", settings=settings)
    db.commit()
    process_next_sync(factory, settings, client)
    db.refresh(old)
    assert old.remote_status == "available"

    client.list_error = MetaHTTPError(503, "2", None, "Server", True, False, False)
    process_next_sync(factory, settings, client)
    db.refresh(old)
    assert old.remote_status == "available"
    state = db.query(InstagramMediaSyncState).one()
    assert state.status == "failed"
    assert state.after_cursor == "cursor-2"
    failed_run = state.run_id
    retry_job = (
        db.query(MetaIntegrationJob)
        .filter(MetaIntegrationJob.job_type == "instagram_media_sync")
        .order_by(MetaIntegrationJob.id.desc())
        .first()
    )
    retry_job.status = "dead_letter"
    db.commit()
    replacement, created, state = enqueue_instagram_media_sync(
        db, business_id=business.id, origin="owner", settings=settings
    )
    assert created is True
    assert replacement.id != retry_job.id
    assert state.run_id != failed_run
    assert state.after_cursor is None


def test_complete_sync_marks_only_confirmed_unavailable_and_restores(sync_context):
    db, factory, settings, business, _owner, integration = sync_context
    old = InstagramRemoteMedia(
        business_id=business.id,
        integration_id=integration.id,
        provider_media_id="old",
        media_type="IMAGE",
        origin="instagram",
        remote_status="available",
    )
    db.add(old)
    db.commit()
    client = FakeSyncClient()
    client.pages = {None: InstagramRemoteMediaPage((), None)}
    client.details = {
        "old": MetaHTTPError(400, "100", None, "GraphMethodException", False, False, False, unavailable=True)
    }
    enqueue_instagram_media_sync(db, business_id=business.id, origin="owner", settings=settings)
    db.commit()
    process_next_sync(factory, settings, client)
    db.refresh(old)
    assert old.remote_status == "unavailable"

    client.pages = {None: InstagramRemoteMediaPage((remote_item("old"),), None)}
    client.details = {}
    enqueue_instagram_media_sync(db, business_id=business.id, origin="owner", settings=settings)
    db.commit()
    process_next_sync(factory, settings, client)
    db.refresh(old)
    assert old.remote_status == "available"
    assert db.query(InstagramRemoteMedia).count() == 1
