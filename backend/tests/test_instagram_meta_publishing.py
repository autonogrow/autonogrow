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
        "asset_url": "https://assets.example.test/signed?signature=secret",
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
        self.events: list[tuple[str, str]] = []

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

    def create_image_container(self, **kwargs):
        self.calls.append(("create", kwargs))
        if self.create_error:
            raise self.create_error
        return "container-1"

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
