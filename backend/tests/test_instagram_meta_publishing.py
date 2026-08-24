from __future__ import annotations

import hashlib
from datetime import datetime, timezone
from io import BytesIO
from types import SimpleNamespace
from urllib.parse import parse_qs, urlsplit

import pytest
import requests
from alembic import command
from fastapi.testclient import TestClient
from PIL import Image
from sqlalchemy import create_engine, inspect
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.core.config import Settings
from app.core.database import Base, get_db
from app.core.migration_state import alembic_config
from app.main import app as fastapi_app
from app.models import (
    Business,
    InstagramContent,
    InstagramContentValidation,
    InstagramContentVersion,
    InstagramContentVersionAsset,
    InstagramFinalAsset,
    User,
)
from app.services.instagram_asset_url_service import (
    SignedAssetURLInvalid,
    build_signed_asset_url,
    resolve_authorized_final_asset,
    resolve_private_asset_path,
    verify_signed_asset_request,
)
from app.services.instagram_image_validation import (
    validate_instagram_caption,
    validate_instagram_image,
)
from app.services.instagram_login_provider import (
    INSTAGRAM_CONTENT_PUBLISH_SCOPE,
    build_instagram_authorization_url,
)
from app.services.instagram_meta_client import InstagramMetaClient, MetaHTTPError
from app.services.instagram_publishing_adapter import (
    InstagramPublishRequest,
    MetaInstagramPublishingAdapter,
    PermanentPublishingError,
    PublishingActionRequired,
    PublishingAuthenticationError,
    PublishingResultUnknown,
    PublishingValidationError,
    SimulatedInstagramPublishingAdapter,
    TemporaryPublishingError,
    get_instagram_publishing_adapter,
)


def settings(**overrides) -> Settings:
    values = {
        "app_env": "test",
        "instagram_asset_url_base": "https://assets.example.test",
        "instagram_asset_url_secret": "s" * 32,
    }
    values.update(overrides)
    return Settings(_env_file=None, **values)


def jpeg_bytes(size: tuple[int, int] = (1080, 1080)) -> bytes:
    stream = BytesIO()
    Image.new("RGB", size, (20, 40, 60)).save(stream, format="JPEG")
    return stream.getvalue()


def asset_for(path, *, media_type: str = "image/jpeg"):
    return SimpleNamespace(
        media_type=media_type,
        size_bytes=path.stat().st_size,
        sha256=hashlib.sha256(path.read_bytes()).hexdigest(),
    )


def request(**overrides) -> InstagramPublishRequest:
    values = {
        "idempotency_key": "instagram-publish:1:2:3",
        "business_id": 1,
        "content_id": 2,
        "version_id": 3,
        "caption": "  Caption exacto ✨\n#marca  ",
        "format": "single_image",
        "asset_storage_keys": ("final.jpg",),
        "professional_account_id": "178900000001",
        "access_token": "secret-token",
        "asset_urls": (
            "https://assets.example.test/signed?signature=secret",
        ),
    }
    values.update(overrides)
    return InstagramPublishRequest(**values)


def test_mode_factory_defaults_to_simulated_and_meta_requires_acknowledgement():
    assert isinstance(
        get_instagram_publishing_adapter(settings()), SimulatedInstagramPublishingAdapter
    )
    with pytest.raises(ValueError, match="ACKNOWLEDGED"):
        settings(instagram_publishing_mode="meta")


def test_meta_mode_explicitly_adds_publish_scope_to_new_reconnections():
    active = settings(
        instagram_publishing_mode="meta",
        instagram_real_publishing_acknowledged=True,
        instagram_login_client_id="client",
        instagram_login_redirect_uri="https://app.example.test/callback",
    )
    query = parse_qs(urlsplit(build_instagram_authorization_url("state", settings=active)).query)
    assert INSTAGRAM_CONTENT_PUBLISH_SCOPE in query["scope"][0].split(",")


def test_signed_asset_url_is_bound_to_all_ids_and_expires():
    active = settings(instagram_asset_url_ttl_seconds=60)
    url = build_signed_asset_url(active, business_id=7, version_id=8, asset_id=9, now=1_000)
    parsed = urlsplit(url)
    query = parse_qs(parsed.query)
    signature = query["signature"][0]
    expires = int(query["expires"][0])
    verify_signed_asset_request(
        active,
        business_id=7,
        version_id=8,
        asset_id=9,
        expires=expires,
        signature=signature,
        now=1_001,
    )
    with pytest.raises(SignedAssetURLInvalid):
        verify_signed_asset_request(
            active,
            business_id=70,
            version_id=8,
            asset_id=9,
            expires=expires,
            signature=signature,
            now=1_001,
        )
    with pytest.raises(SignedAssetURLInvalid):
        verify_signed_asset_request(
            active,
            business_id=7,
            version_id=8,
            asset_id=9,
            expires=expires,
            signature=signature,
            now=1_061,
        )


def test_private_asset_path_rejects_traversal(tmp_path):
    assert (
        resolve_private_asset_path("safe/final.jpg", root=tmp_path)
        == (tmp_path / "safe" / "final.jpg").resolve()
    )
    with pytest.raises(SignedAssetURLInvalid):
        resolve_private_asset_path("../outside.jpg", root=tmp_path)


def test_signed_delivery_resolver_enforces_business_version_and_validation(tmp_path, monkeypatch):
    engine = create_engine(
        "sqlite:///:memory:", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    with factory() as db:
        business = Business(slug="signed-a", name="Signed A")
        other = Business(slug="signed-b", name="Signed B")
        owner = User(email="signed-owner@example.test", is_owner=True)
        db.add_all([business, other, owner])
        db.flush()
        content = InstagramContent(
            business_id=business.id,
            title="Final",
            status="scheduled",
            created_by_user_id=owner.id,
        )
        db.add(content)
        db.flush()
        path = tmp_path / "_instagram_content" / str(business.id) / "final" / "asset.jpg"
        path.parent.mkdir(parents=True)
        path.write_bytes(jpeg_bytes())
        asset = InstagramFinalAsset(
            business_id=business.id,
            content_id=content.id,
            uploaded_by_user_id=owner.id,
            original_filename="asset.jpg",
            storage_key=path.relative_to(tmp_path).as_posix(),
            media_type="image/jpeg",
            size_bytes=path.stat().st_size,
            sha256=hashlib.sha256(path.read_bytes()).hexdigest(),
        )
        version = InstagramContentVersion(
            business_id=business.id,
            content_id=content.id,
            version_number=1,
            caption="Final",
            format="single_image",
            created_by_user_id=owner.id,
        )
        db.add_all([asset, version])
        db.flush()
        db.add_all(
            [
                InstagramContentVersionAsset(
                    version_id=version.id, asset_id=asset.id, position=0, is_cover=True
                ),
                InstagramContentValidation(
                    business_id=business.id,
                    content_id=content.id,
                    version_id=version.id,
                    validated_by_user_id=owner.id,
                    validator_role="owner_delegate",
                    validated_at=datetime.now(timezone.utc),
                ),
            ]
        )
        db.commit()
        monkeypatch.setattr(
            "app.services.instagram_asset_url_service.get_uploads_dir", lambda: tmp_path
        )
        resolved = resolve_authorized_final_asset(
            db, business_id=business.id, version_id=version.id, asset_id=asset.id
        )
        assert resolved.path == path
        active = settings(instagram_asset_url_ttl_seconds=60)
        signed_url = build_signed_asset_url(
            active, business_id=business.id, version_id=version.id, asset_id=asset.id
        )
        parsed = urlsplit(signed_url)
        monkeypatch.setattr("app.routers.instagram_asset_delivery.get_settings", lambda: active)

        def override_db():
            yield db

        fastapi_app.dependency_overrides[get_db] = override_db
        try:
            client = TestClient(fastapi_app)
            response = client.get(f"{parsed.path}?{parsed.query}")
            assert response.status_code == 200
            assert response.headers["content-type"] == "image/jpeg"
            assert response.content == path.read_bytes()
            assert client.head(f"{parsed.path}?{parsed.query}").status_code == 200
            tampered = parse_qs(parsed.query)
            tampered_signature = ("0" if tampered["signature"][0][0] != "0" else "1") + tampered[
                "signature"
            ][0][1:]
            assert (
                client.get(
                    f"{parsed.path}?expires={tampered['expires'][0]}&signature={tampered_signature}"
                ).status_code
                == 404
            )
            original_bytes = path.read_bytes()
            path.write_bytes(b"X" + original_bytes[1:])
            assert client.get(f"{parsed.path}?{parsed.query}").status_code == 404
            path.write_bytes(original_bytes)
        finally:
            fastapi_app.dependency_overrides.pop(get_db, None)
        with pytest.raises(SignedAssetURLInvalid):
            resolve_authorized_final_asset(
                db, business_id=other.id, version_id=version.id, asset_id=asset.id
            )
        validation = db.query(InstagramContentValidation).one()
        validation.invalidated_at = datetime.now(timezone.utc)
        db.commit()
        with pytest.raises(SignedAssetURLInvalid):
            resolve_authorized_final_asset(
                db, business_id=business.id, version_id=version.id, asset_id=asset.id
            )
    engine.dispose()


def test_image_and_caption_validation_preserve_valid_payload(tmp_path):
    path = tmp_path / "final.jpg"
    path.write_bytes(jpeg_bytes())
    validated = validate_instagram_image(asset_for(path), path)
    assert (validated.width, validated.height) == (1080, 1080)
    assert len(validated.sha256) == 64
    validate_instagram_caption("  emoji ✨\n#uno #dos  ")


@pytest.mark.parametrize(
    ("size", "media_type", "code"),
    [
        ((1080, 2000), "image/jpeg", "instagram_image_aspect_ratio_invalid"),
        ((200, 200), "image/jpeg", "instagram_image_dimensions_invalid"),
        ((1080, 1080), "image/png", "instagram_image_type_unsupported"),
    ],
)
def test_image_validation_rejects_unsupported_inputs(tmp_path, size, media_type, code):
    path = tmp_path / "final.jpg"
    path.write_bytes(jpeg_bytes(size))
    with pytest.raises(PublishingValidationError) as raised:
        validate_instagram_image(asset_for(path, media_type=media_type), path)
    assert raised.value.code == code


def test_image_validation_rejects_corrupt_and_caption_rejects_invalid_unicode(tmp_path):
    path = tmp_path / "final.jpg"
    path.write_bytes(b"not-a-jpeg")
    with pytest.raises(PublishingValidationError, match="decoded"):
        validate_instagram_image(asset_for(path), path)
    with pytest.raises(PublishingValidationError) as raised:
        validate_instagram_caption("bad-surrogate-\ud800")
    assert raised.value.code == "instagram_caption_encoding"


class Progress:
    def __init__(self):
        self.events: list[tuple] = []

    def carousel_child_created(
        self,
        position: int,
        container_id: str,
    ) -> None:
        self.events.append(("carousel_child", position, container_id))

    def container_created(self, container_id: str) -> None:
        self.events.append(("container", container_id))

    def media_published(self, media_id: str) -> None:
        self.events.append(("media", media_id))

    def publishing_started(self) -> None:
        self.events.append(("publishing", "started"))


class FakeMetaClient:
    def __init__(self):
        self.calls: list[tuple] = []
        self.create_error = None
        self.publish_error = None
        self.permalink_error = None
        self.inspect_status = None
        self.reel_status = "FINISHED"
        self.container_statuses: dict[str, str] = {}
        self.reel_status_error = None
        self.carousel_child_error_at = None
        self.carousel_child_counter = 0

    def create_image_container(self, **kwargs):
        self.calls.append(("create", kwargs))
        if self.create_error:
            raise self.create_error
        return "container-1"

    def create_carousel_image_container(self, **kwargs):
        self.carousel_child_counter += 1
        self.calls.append(
            ("create_carousel_child", self.carousel_child_counter, kwargs)
        )

        if self.carousel_child_error_at == self.carousel_child_counter:
            raise requests.ConnectTimeout("carousel child timeout")

        return f"carousel-child-{self.carousel_child_counter}"

    def create_carousel_container(self, **kwargs):
        self.calls.append(("create_carousel", kwargs))
        return "carousel-container-1"

    def create_reel_container(self, **kwargs):
        self.calls.append(("create_reel", kwargs))
        if self.create_error:
            raise self.create_error
        return "reel-container-1"

    def create_story_image_container(self, **kwargs):
        self.calls.append(("create_story_image", kwargs))
        if self.create_error:
            raise self.create_error
        return "story-image-container-1"

    def create_story_video_container(self, **kwargs):
        self.calls.append(("create_story_video", kwargs))
        if self.create_error:
            raise self.create_error
        return "story-video-container-1"

    def get_container_status(self, container_id, access_token):
        self.calls.append(("status", container_id, access_token))
        if self.reel_status_error:
            raise self.reel_status_error
        return self.container_statuses.get(container_id, self.reel_status)

    def publish_container(self, **kwargs):
        self.calls.append(("publish", kwargs))
        if self.publish_error:
            raise self.publish_error
        return "media-1"

    def get_permalink(self, media_id, access_token):
        self.calls.append(("permalink", media_id, access_token))
        if self.permalink_error:
            raise self.permalink_error
        return "https://www.instagram.com/p/example/"

    def inspect_container_best_effort(self, container_id, access_token):
        self.calls.append(("inspect", container_id, access_token))
        return self.inspect_status


def test_meta_adapter_persists_each_irreversible_step_and_preserves_caption():
    client = FakeMetaClient()
    progress = Progress()
    publish_request = request(progress=progress)
    result = MetaInstagramPublishingAdapter(client).publish(publish_request)
    assert [call[0] for call in client.calls] == ["create", "publish", "permalink"]
    assert client.calls[0][1]["caption"] == publish_request.caption
    assert progress.events == [
        ("container", "container-1"),
        ("publishing", "started"),
        ("media", "media-1"),
    ]
    assert result.media_id == "media-1"
    assert result.permalink == "https://www.instagram.com/p/example/"


def test_meta_adapter_restart_reuses_container_and_persisted_media():
    client = FakeMetaClient()
    result = MetaInstagramPublishingAdapter(client).publish(
        request(existing_container_id="container-old", existing_media_id="media-old")
    )
    assert [call[0] for call in client.calls] == ["permalink"]
    assert result.container_id == "container-old"
    assert result.media_id == "media-old"


def test_publish_timeout_is_unknown_and_never_a_temporary_retry():
    client = FakeMetaClient()
    client.publish_error = requests.ReadTimeout("provider did not answer")
    with pytest.raises(PublishingResultUnknown) as raised:
        MetaInstagramPublishingAdapter(client).publish(request(existing_container_id="container"))
    assert raised.value.code == "instagram_publish_timeout_unknown"
    assert [call[0] for call in client.calls] == ["publish", "inspect"]


def test_unknown_publish_records_observable_container_state_without_assuming_success():
    client = FakeMetaClient()
    client.publish_error = requests.ReadTimeout("provider did not answer")
    client.inspect_status = "FINISHED"
    with pytest.raises(PublishingResultUnknown) as raised:
        MetaInstagramPublishingAdapter(client).publish(
            request(existing_container_id="container")
        )
    assert raised.value.code == "instagram_publish_timeout_unknown_finished"


def test_container_timeout_is_safe_to_retry_before_irreversible_publish():
    client = FakeMetaClient()
    client.create_error = requests.ConnectTimeout("provider did not answer")
    with pytest.raises(TemporaryPublishingError) as raised:
        MetaInstagramPublishingAdapter(client).publish(request())
    assert raised.value.code == "instagram_container_timeout"
    assert [call[0] for call in client.calls] == ["create"]


def test_retryable_provider_response_after_publish_started_is_unknown():
    client = FakeMetaClient()
    client.publish_error = MetaHTTPError(503, "2", None, "Server", True, False, False)
    with pytest.raises(PublishingResultUnknown) as raised:
        MetaInstagramPublishingAdapter(client).publish(request(existing_container_id="container"))
    assert raised.value.code == "instagram_publish_provider_unknown"


def test_permalink_failure_does_not_turn_a_successful_publish_into_a_retry():
    client = FakeMetaClient()
    client.permalink_error = requests.ReadTimeout("optional enrichment timed out")
    result = MetaInstagramPublishingAdapter(client).publish(request())
    assert result.media_id == "media-1"
    assert result.permalink is None


def test_provider_authentication_is_action_required():
    client = FakeMetaClient()
    client.publish_error = MetaHTTPError(401, "190", None, "OAuthException", False, True, False)
    with pytest.raises(PublishingAuthenticationError) as raised:
        MetaInstagramPublishingAdapter(client).publish(request(existing_container_id="container"))
    assert raised.value.code == "instagram_authentication_190"


class FakeResponse:
    ok = True
    status_code = 200

    def __init__(self, payload):
        self.payload = payload

    def json(self):
        return self.payload

def test_carousel_creates_children_in_order_parent_and_publish():
    client = FakeMetaClient()
    progress = Progress()

    result = MetaInstagramPublishingAdapter(client).publish(
        request(
            format="carousel",
            asset_storage_keys=("one.jpg", "two.jpg", "three.jpg"),
            asset_urls=(
                "https://assets.example.test/one.jpg",
                "https://assets.example.test/two.jpg",
                "https://assets.example.test/three.jpg",
            ),
            progress=progress,
        )
    )

    assert [call[0] for call in client.calls] == [
        "create_carousel_child",
        "create_carousel_child",
        "create_carousel_child",
        "status",
        "status",
        "status",
        "create_carousel",
        "status",
        "publish",
        "permalink",
    ]

    assert progress.events == [
        ("carousel_child", 0, "carousel-child-1"),
        ("carousel_child", 1, "carousel-child-2"),
        ("carousel_child", 2, "carousel-child-3"),
        ("container", "carousel-container-1"),
        ("publishing", "started"),
        ("media", "media-1"),
    ]

    assert client.calls[6][1]["children"] == (
        "carousel-child-1",
        "carousel-child-2",
        "carousel-child-3",
    )
    assert result.container_id == "carousel-container-1"
    assert result.media_id == "media-1"
    assert result.metadata["format"] == "carousel"
    assert result.metadata["carousel_asset_count"] == "3"


def test_carousel_restart_reuses_persisted_children_and_creates_only_missing_child():
    client = FakeMetaClient()
    progress = Progress()

    result = MetaInstagramPublishingAdapter(client).publish(
        request(
            format="carousel",
            asset_storage_keys=("one.jpg", "two.jpg", "three.jpg"),
            asset_urls=(
                "https://assets.example.test/one.jpg",
                "https://assets.example.test/two.jpg",
                "https://assets.example.test/three.jpg",
            ),
            existing_child_container_ids=(
                "persisted-child-1",
                None,
                "persisted-child-3",
            ),
            progress=progress,
        )
    )

    assert [call[0] for call in client.calls] == [
        "create_carousel_child",
        "status",
        "status",
        "status",
        "create_carousel",
        "status",
        "publish",
        "permalink",
    ]

    assert client.calls[4][1]["children"] == (
        "persisted-child-1",
        "carousel-child-1",
        "persisted-child-3",
    )

    assert progress.events[0] == (
        "carousel_child",
        1,
        "carousel-child-1",
    )
    assert result.container_id == "carousel-container-1"


def test_carousel_restart_with_persisted_parent_skips_children_and_parent_creation():
    client = FakeMetaClient()

    result = MetaInstagramPublishingAdapter(client).publish(
        request(
            format="carousel",
            asset_storage_keys=("one.jpg", "two.jpg"),
            asset_urls=(
                "https://assets.example.test/one.jpg",
                "https://assets.example.test/two.jpg",
            ),
            existing_child_container_ids=(
                "persisted-child-1",
                "persisted-child-2",
            ),
            existing_container_id="persisted-carousel-parent",
        )
    )

    assert [call[0] for call in client.calls] == [
        "status",
        "publish",
        "permalink",
    ]
    assert result.container_id == "persisted-carousel-parent"


def test_carousel_restart_with_persisted_media_only_fetches_permalink():
    client = FakeMetaClient()

    result = MetaInstagramPublishingAdapter(client).publish(
        request(
            format="carousel",
            asset_storage_keys=("one.jpg", "two.jpg"),
            asset_urls=(
                "https://assets.example.test/one.jpg",
                "https://assets.example.test/two.jpg",
            ),
            existing_child_container_ids=(
                "persisted-child-1",
                "persisted-child-2",
            ),
            existing_container_id="persisted-carousel-parent",
            existing_media_id="persisted-media",
        )
    )

    assert [call[0] for call in client.calls] == ["permalink"]
    assert result.container_id == "persisted-carousel-parent"
    assert result.media_id == "persisted-media"


def test_carousel_child_timeout_preserves_progress_before_failed_child():
    client = FakeMetaClient()
    client.carousel_child_error_at = 2
    progress = Progress()

    with pytest.raises(TemporaryPublishingError) as raised:
        MetaInstagramPublishingAdapter(client).publish(
            request(
                format="carousel",
                asset_storage_keys=("one.jpg", "two.jpg", "three.jpg"),
                asset_urls=(
                    "https://assets.example.test/one.jpg",
                    "https://assets.example.test/two.jpg",
                    "https://assets.example.test/three.jpg",
                ),
                progress=progress,
            )
        )

    assert raised.value.code == "instagram_container_timeout"

    assert progress.events == [
        ("carousel_child", 0, "carousel-child-1"),
    ]

    assert [call[0] for call in client.calls] == [
        "create_carousel_child",
        "create_carousel_child",
    ]


def test_carousel_waits_for_every_child_before_creating_parent():
    client = FakeMetaClient()
    client.container_statuses["carousel-child-2"] = "IN_PROGRESS"

    with pytest.raises(TemporaryPublishingError) as raised:
        MetaInstagramPublishingAdapter(client).publish(
            request(
                format="carousel",
                asset_storage_keys=("one.jpg", "two.jpg"),
                asset_urls=(
                    "https://assets.example.test/one.jpg",
                    "https://assets.example.test/two.jpg",
                ),
            )
        )

    assert raised.value.code == "instagram_carousel_child_processing"
    assert raised.value.provider_diagnostics == {
        "operation": "carousel_child_status",
        "container_status": "IN_PROGRESS",
        "carousel_position": 1,
    }
    assert "create_carousel" not in [call[0] for call in client.calls]


@pytest.mark.parametrize("status", ["ERROR", "EXPIRED"])
def test_carousel_child_terminal_status_requires_action(status):
    client = FakeMetaClient()
    client.container_statuses["carousel-child-1"] = status

    with pytest.raises(PublishingActionRequired) as raised:
        MetaInstagramPublishingAdapter(client).publish(
            request(
                format="carousel",
                asset_storage_keys=("one.jpg", "two.jpg"),
                asset_urls=(
                    "https://assets.example.test/one.jpg",
                    "https://assets.example.test/two.jpg",
                ),
            )
        )

    expected_code = {
        "ERROR": "instagram_carousel_child_processing_failed",
        "EXPIRED": "instagram_carousel_child_container_expired",
    }[status]
    assert raised.value.code == expected_code
    assert raised.value.provider_diagnostics["carousel_position"] == 0
    assert "create_carousel" not in [call[0] for call in client.calls]


def test_carousel_parent_is_persisted_and_rechecked_without_recreation():
    client = FakeMetaClient()
    client.container_statuses["carousel-container-1"] = "IN_PROGRESS"
    progress = Progress()
    publish_request = request(
        format="carousel",
        asset_storage_keys=("one.jpg", "two.jpg"),
        asset_urls=(
            "https://assets.example.test/one.jpg",
            "https://assets.example.test/two.jpg",
        ),
        progress=progress,
    )

    with pytest.raises(TemporaryPublishingError) as raised:
        MetaInstagramPublishingAdapter(client).publish(publish_request)

    assert raised.value.code == "instagram_carousel_parent_processing"
    assert ("container", "carousel-container-1") in progress.events
    assert "publish" not in [call[0] for call in client.calls]

    retry_client = FakeMetaClient()
    result = MetaInstagramPublishingAdapter(retry_client).publish(
        request(
            format="carousel",
            asset_storage_keys=("one.jpg", "two.jpg"),
            asset_urls=(
                "https://assets.example.test/one.jpg",
                "https://assets.example.test/two.jpg",
            ),
            existing_child_container_ids=("carousel-child-1", "carousel-child-2"),
            existing_container_id="carousel-container-1",
        )
    )
    assert [call[0] for call in retry_client.calls] == ["status", "publish", "permalink"]
    assert result.media_id == "media-1"


def test_carousel_parent_already_published_never_calls_publish_again():
    client = FakeMetaClient()
    client.container_statuses["persisted-parent"] = "PUBLISHED"

    with pytest.raises(PublishingResultUnknown) as raised:
        MetaInstagramPublishingAdapter(client).publish(
            request(
                format="carousel",
                asset_storage_keys=("one.jpg", "two.jpg"),
                asset_urls=(
                    "https://assets.example.test/one.jpg",
                    "https://assets.example.test/two.jpg",
                ),
                existing_child_container_ids=("child-1", "child-2"),
                existing_container_id="persisted-parent",
            )
        )

    assert raised.value.code == "instagram_carousel_parent_already_published_unknown"
    assert [call[0] for call in client.calls] == ["status"]


@pytest.mark.parametrize("asset_count", [2, 5, 10])
def test_carousel_supports_valid_asset_counts(asset_count):
    client = FakeMetaClient()
    names = tuple(f"asset-{index}.jpg" for index in range(asset_count))
    urls = tuple(f"https://assets.example.test/{name}" for name in names)

    result = MetaInstagramPublishingAdapter(client).publish(
        request(format="carousel", asset_storage_keys=names, asset_urls=urls)
    )

    assert result.metadata["carousel_asset_count"] == str(asset_count)
    assert [call[0] for call in client.calls].count("status") == asset_count + 1


@pytest.mark.parametrize(
    ("is_transient", "provider_code", "expected_error"),
    [
        (True, -1, TemporaryPublishingError),
        (False, 2, PermanentPublishingError),
        (None, 2, TemporaryPublishingError),
    ],
)
def test_provider_is_transient_controls_error_classification(
    is_transient, provider_code, expected_error
):
    client = InstagramMetaClient(settings())
    response = SimpleNamespace(status_code=400)
    error = client._error(
        response,
        {
            "error": {
                "code": provider_code,
                "error_subcode": 2207001,
                "type": "OAuthException",
                "message": "safe provider message",
                **({"is_transient": is_transient} if is_transient is not None else {}),
            }
        },
        provider_request_id="trace-safe",
        operation="carousel_parent_create",
    )

    with pytest.raises(expected_error) as raised:
        raise MetaInstagramPublishingAdapter._mapped_error(error)

    assert raised.value.provider_diagnostics == {
        "operation": "carousel_parent_create",
        "http_status": 400,
        "error_code": str(provider_code),
        "error_subcode": "2207001",
        "error_type": "OAuthException",
        "is_transient": is_transient,
        "trace_id": "trace-safe",
    }


def test_reel_requires_exactly_one_final_video():
    client = FakeMetaClient()

    with pytest.raises(PublishingValidationError) as raised:
        MetaInstagramPublishingAdapter(client).publish(
            request(
                format="reel",
                asset_storage_keys=("one.mp4", "two.mp4"),
                asset_urls=(
                    "https://assets.example.test/one.mp4",
                    "https://assets.example.test/two.mp4",
                ),
            )
        )

    assert raised.value.code == "instagram_reel_assets_invalid"
    assert client.calls == []


def test_reel_creates_container_checks_finished_then_publishes():
    client = FakeMetaClient()
    progress = Progress()

    result = MetaInstagramPublishingAdapter(client).publish(
        request(
            format="reel",
            asset_storage_keys=("video.mp4",),
            asset_urls=("https://assets.example.test/video.mp4",),
            progress=progress,
        )
    )

    assert [call[0] for call in client.calls] == [
        "create_reel",
        "status",
        "publish",
        "permalink",
    ]
    assert client.calls[0][1]["video_url"] == "https://assets.example.test/video.mp4"
    assert client.calls[0][1]["caption"] == request().caption
    assert progress.events == [
        ("container", "reel-container-1"),
        ("publishing", "started"),
        ("media", "media-1"),
    ]
    assert result.container_id == "reel-container-1"
    assert result.media_id == "media-1"
    assert result.metadata["format"] == "reel"


def test_reel_in_progress_is_temporary_and_persists_container_before_retry():
    client = FakeMetaClient()
    client.reel_status = "IN_PROGRESS"
    progress = Progress()

    with pytest.raises(TemporaryPublishingError) as raised:
        MetaInstagramPublishingAdapter(client).publish(
            request(
                format="reel",
                asset_storage_keys=("video.mp4",),
                asset_urls=("https://assets.example.test/video.mp4",),
                progress=progress,
            )
        )

    assert raised.value.code == "instagram_reel_processing"
    assert [call[0] for call in client.calls] == ["create_reel", "status"]
    assert progress.events == [("container", "reel-container-1")]


def test_reel_retry_reuses_existing_container_and_publishes_when_finished():
    client = FakeMetaClient()
    progress = Progress()

    result = MetaInstagramPublishingAdapter(client).publish(
        request(
            format="reel",
            asset_storage_keys=("video.mp4",),
            asset_urls=("https://assets.example.test/video.mp4",),
            existing_container_id="persisted-reel-container",
            progress=progress,
        )
    )

    assert [call[0] for call in client.calls] == [
        "status",
        "publish",
        "permalink",
    ]
    assert progress.events == [
        ("publishing", "started"),
        ("media", "media-1"),
    ]
    assert result.container_id == "persisted-reel-container"


@pytest.mark.parametrize(
    ("status", "code"),
    [
        ("ERROR", "instagram_reel_processing_failed"),
        ("EXPIRED", "instagram_reel_container_expired"),
    ],
)
def test_reel_terminal_processing_status_requires_attention(status, code):
    client = FakeMetaClient()
    client.reel_status = status

    with pytest.raises(PublishingActionRequired) as raised:
        MetaInstagramPublishingAdapter(client).publish(
            request(
                format="reel",
                asset_storage_keys=("video.mp4",),
                asset_urls=("https://assets.example.test/video.mp4",),
                existing_container_id="persisted-reel-container",
            )
        )

    assert raised.value.code == code
    assert [call[0] for call in client.calls] == ["status"]


def test_reel_status_timeout_is_safe_temporary_retry():
    client = FakeMetaClient()
    client.reel_status_error = requests.ReadTimeout("status timed out")

    with pytest.raises(TemporaryPublishingError) as raised:
        MetaInstagramPublishingAdapter(client).publish(
            request(
                format="reel",
                asset_storage_keys=("video.mp4",),
                asset_urls=("https://assets.example.test/video.mp4",),
                existing_container_id="persisted-reel-container",
            )
        )

    assert raised.value.code == "instagram_reel_status_timeout"
    assert [call[0] for call in client.calls] == ["status"]


def test_reel_status_network_error_is_safe_temporary_retry():
    client = FakeMetaClient()
    client.reel_status_error = requests.ConnectionError("status network error")

    with pytest.raises(TemporaryPublishingError) as raised:
        MetaInstagramPublishingAdapter(client).publish(
            request(
                format="reel",
                asset_storage_keys=("video.mp4",),
                asset_urls=("https://assets.example.test/video.mp4",),
                existing_container_id="persisted-reel-container",
            )
        )

    assert raised.value.code == "instagram_reel_status_network"
    assert [call[0] for call in client.calls] == ["status"]


def test_reel_published_without_persisted_media_is_unknown_not_republished():
    client = FakeMetaClient()
    client.reel_status = "PUBLISHED"

    with pytest.raises(PublishingResultUnknown) as raised:
        MetaInstagramPublishingAdapter(client).publish(
            request(
                format="reel",
                asset_storage_keys=("video.mp4",),
                asset_urls=("https://assets.example.test/video.mp4",),
                existing_container_id="persisted-reel-container",
            )
        )

    assert raised.value.code == "instagram_reel_already_published_unknown"
    assert [call[0] for call in client.calls] == ["status"]


def test_reel_with_persisted_media_skips_status_and_publish():
    client = FakeMetaClient()

    result = MetaInstagramPublishingAdapter(client).publish(
        request(
            format="reel",
            asset_storage_keys=("video.mp4",),
            asset_urls=("https://assets.example.test/video.mp4",),
            existing_container_id="persisted-reel-container",
            existing_media_id="persisted-reel-media",
        )
    )

    assert [call[0] for call in client.calls] == ["permalink"]
    assert result.container_id == "persisted-reel-container"
    assert result.media_id == "persisted-reel-media"



def test_story_requires_exactly_one_supported_final_asset():
    client = FakeMetaClient()

    with pytest.raises(PublishingValidationError) as raised:
        MetaInstagramPublishingAdapter(client).publish(
            request(
                format="story",
                asset_storage_keys=("one.jpg", "two.jpg"),
                asset_media_types=("image/jpeg", "image/jpeg"),
                asset_urls=(
                    "https://assets.example.test/one.jpg",
                    "https://assets.example.test/two.jpg",
                ),
            )
        )

    assert raised.value.code == "instagram_story_assets_invalid"
    assert client.calls == []

    with pytest.raises(PublishingValidationError) as raised:
        MetaInstagramPublishingAdapter(client).publish(
            request(
                format="story",
                asset_storage_keys=("one.png",),
                asset_media_types=("image/png",),
                asset_urls=("https://assets.example.test/one.png",),
            )
        )

    assert raised.value.code == "instagram_story_type_unsupported"
    assert client.calls == []


def test_story_image_creates_container_and_publishes_without_status_poll():
    client = FakeMetaClient()
    progress = Progress()

    result = MetaInstagramPublishingAdapter(client).publish(
        request(
            format="story",
            asset_storage_keys=("story.jpg",),
            asset_media_types=("image/jpeg",),
            asset_urls=("https://assets.example.test/story.jpg",),
            progress=progress,
        )
    )

    assert [call[0] for call in client.calls] == [
        "create_story_image",
        "publish",
        "permalink",
    ]
    assert client.calls[0][1]["image_url"] == "https://assets.example.test/story.jpg"
    assert progress.events == [
        ("container", "story-image-container-1"),
        ("publishing", "started"),
        ("media", "media-1"),
    ]
    assert result.container_id == "story-image-container-1"
    assert result.media_id == "media-1"
    assert result.metadata["format"] == "story"
    assert result.metadata["story_media_type"] == "image/jpeg"


def test_story_video_checks_processing_and_reuses_persisted_container():
    client = FakeMetaClient()
    client.reel_status = "IN_PROGRESS"
    progress = Progress()

    with pytest.raises(TemporaryPublishingError) as raised:
        MetaInstagramPublishingAdapter(client).publish(
            request(
                format="story",
                asset_storage_keys=("story.mp4",),
                asset_media_types=("video/mp4",),
                asset_urls=("https://assets.example.test/story.mp4",),
                progress=progress,
            )
        )

    assert raised.value.code == "instagram_story_video_processing"
    assert [call[0] for call in client.calls] == [
        "create_story_video",
        "status",
    ]
    assert progress.events == [("container", "story-video-container-1")]

    client = FakeMetaClient()
    progress = Progress()

    result = MetaInstagramPublishingAdapter(client).publish(
        request(
            format="story",
            asset_storage_keys=("story.mp4",),
            asset_media_types=("video/mp4",),
            asset_urls=("https://assets.example.test/story.mp4",),
            existing_container_id="persisted-story-video-container",
            progress=progress,
        )
    )

    assert [call[0] for call in client.calls] == [
        "status",
        "publish",
        "permalink",
    ]
    assert progress.events == [
        ("publishing", "started"),
        ("media", "media-1"),
    ]
    assert result.container_id == "persisted-story-video-container"
    assert result.metadata["story_media_type"] == "video/mp4"


class RecordingSession:
    def __init__(self):
        self.calls = []

    def request(self, method, url, **kwargs):
        self.calls.append((method, url, kwargs))
        return FakeResponse({"id": "container-xyz"})


def test_http_client_uses_bearer_header_and_never_puts_token_in_url():
    session = RecordingSession()
    client = InstagramMetaClient(settings(), session=session)
    caption = "  exacto ✨\n#marca  "
    client.create_image_container(
        account_id="17890001",
        image_url="https://assets.example.test/file?signature=signed",
        caption=caption,
        access_token="very-secret-token",
    )
    method, url, kwargs = session.calls[0]
    assert method == "POST"
    assert "very-secret-token" not in url
    assert kwargs["headers"]["Authorization"] == "Bearer very-secret-token"
    assert kwargs["data"]["caption"] == caption
    assert kwargs["timeout"] == (5.0, 20.0)


def test_http_client_creates_reel_with_video_url_and_media_type():
    session = RecordingSession()
    client = InstagramMetaClient(settings(), session=session)

    client.create_reel_container(
        account_id="17890001",
        video_url="https://assets.example.test/video.mp4?signature=signed",
        caption="Reel exacto",
        access_token="very-secret-token",
    )

    method, url, kwargs = session.calls[0]
    assert method == "POST"
    assert "very-secret-token" not in url
    assert kwargs["headers"]["Authorization"] == "Bearer very-secret-token"
    assert kwargs["data"] == {
        "media_type": "REELS",
        "video_url": "https://assets.example.test/video.mp4?signature=signed",
        "caption": "Reel exacto",
    }



def test_http_client_creates_story_image_and_video_containers():
    image_session = RecordingSession()
    image_client = InstagramMetaClient(settings(), session=image_session)

    image_client.create_story_image_container(
        account_id="17890001",
        image_url="https://assets.example.test/story.jpg?signature=signed",
        access_token="very-secret-token",
    )

    method, url, kwargs = image_session.calls[0]
    assert method == "POST"
    assert "very-secret-token" not in url
    assert kwargs["headers"]["Authorization"] == "Bearer very-secret-token"
    assert kwargs["data"] == {
        "media_type": "STORIES",
        "image_url": "https://assets.example.test/story.jpg?signature=signed",
    }

    video_session = RecordingSession()
    video_client = InstagramMetaClient(settings(), session=video_session)

    video_client.create_story_video_container(
        account_id="17890001",
        video_url="https://assets.example.test/story.mp4?signature=signed",
        access_token="very-secret-token",
    )

    method, url, kwargs = video_session.calls[0]
    assert method == "POST"
    assert "very-secret-token" not in url
    assert kwargs["headers"]["Authorization"] == "Bearer very-secret-token"
    assert kwargs["data"] == {
        "media_type": "STORIES",
        "video_url": "https://assets.example.test/story.mp4?signature=signed",
    }


class StatusRecordingSession:
    def __init__(self, status: str):
        self.calls = []
        self.status = status

    def request(self, method, url, **kwargs):
        self.calls.append((method, url, kwargs))
        return FakeResponse({"status_code": self.status})


def test_http_client_get_container_status_is_strict():
    session = StatusRecordingSession("FINISHED")
    client = InstagramMetaClient(settings(), session=session)

    status = client.get_container_status(
        "container-xyz",
        "very-secret-token",
    )

    assert status == "FINISHED"
    method, url, kwargs = session.calls[0]
    assert method == "GET"
    assert "very-secret-token" not in url
    assert kwargs["headers"]["Authorization"] == "Bearer very-secret-token"
    assert kwargs["params"] == {"fields": "status_code"}


def test_migration_13_upgrade_downgrade_and_reupgrade(tmp_path):
    database_url = f"sqlite:///{(tmp_path / 'instagram-meta.db').as_posix()}"
    config = alembic_config()
    config.attributes["database_url"] = database_url
    command.upgrade(config, "20260806_12")

    command.upgrade(config, "20260806_13")
    engine = create_engine(database_url)
    constraints = inspect(engine).get_check_constraints("instagram_publish_jobs")
    status_sql = next(
        item["sqltext"]
        for item in constraints
        if item["name"] == "ck_instagram_publish_jobs_status"
    )
    assert "creating_container" in status_sql
    assert "publishing" in status_sql
    assert "sha256" in {
        item["name"] for item in inspect(engine).get_columns("instagram_final_assets")
    }
    engine.dispose()

    command.downgrade(config, "20260806_12")
    engine = create_engine(database_url)
    constraints = inspect(engine).get_check_constraints("instagram_publish_jobs")
    status_sql = next(
        item["sqltext"]
        for item in constraints
        if item["name"] == "ck_instagram_publish_jobs_status"
    )
    assert "creating_container" not in status_sql
    assert "sha256" not in {
        item["name"] for item in inspect(engine).get_columns("instagram_final_assets")
    }
    engine.dispose()

    command.upgrade(config, "20260806_13")
