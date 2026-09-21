import json
from types import SimpleNamespace
from unittest.mock import patch

import pytest
import requests
from fastapi import HTTPException
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.core.database import Base
from app.core.security import get_current_user, require_business_access
from app.models import Business, BusinessUser, Conversation, ConversationMessage, User
from app.routers.conversations import admin_get_conversation_attachment, admin_router
from app.services.conversation_media_service import (
    ConversationMediaError,
    fetch_message_attachment,
    get_message_attachment,
    serialize_message_attachments,
)
from app.services.conversation_service import serialize_message


class FakeResponse:
    def __init__(
        self,
        *,
        content=b"media",
        content_type="image/jpeg",
        status_code=200,
        payload=None,
        content_length=None,
    ):
        self.content = content
        self.headers = {
            "Content-Type": content_type,
            "Content-Length": str(len(content) if content_length is None else content_length),
        }
        self.status_code = status_code
        self.ok = 200 <= status_code < 300
        self._payload = payload

    def iter_content(self, chunk_size=64 * 1024):
        del chunk_size
        yield self.content

    def json(self):
        if self._payload is None:
            raise ValueError
        return self._payload


@pytest.fixture
def media_db():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    db = sessionmaker(bind=engine)()
    business = Business(slug="media-a", name="Media A", status="active")
    other = Business(slug="media-b", name="Media B", status="active")
    db.add_all([business, other])
    db.flush()
    conversation = Conversation(
        business=business,
        channel="instagram",
        external_user_id="ig-media-user",
        status="replied",
    )
    foreign = Conversation(
        business=other,
        channel="instagram",
        external_user_id="ig-foreign-user",
        status="replied",
    )
    db.add_all([conversation, foreign])
    db.commit()
    yield db, business, other, conversation, foreign
    db.close()
    engine.dispose()


def instagram_message(db, conversation, *, body="[Adjunto recibido]", attachments=None):
    message = ConversationMessage(
        conversation=conversation,
        direction="inbound",
        sender_type="customer",
        body=body,
        raw_payload_json=json.dumps(
            {"message": {"attachments": attachments or []}}, ensure_ascii=False
        ),
    )
    db.add(message)
    db.commit()
    db.refresh(message)
    return message


def test_serializer_normalizes_media_without_leaking_provider_urls(media_db):
    db, business, _, conversation, _ = media_db
    message = instagram_message(
        db,
        conversation,
        attachments=[
            {
                "type": "image",
                "payload": {
                    "url": "https://lookaside.fbsbx.com/image/private-signature",
                    "thumbnail_url": "https://lookaside.fbsbx.com/image/thumb-signature",
                    "filename": "foto<script>.jpg",
                },
            },
            {
                "type": "video",
                "payload": {"url": "https://video.xx.fbcdn.net/video/1"},
            },
            {
                "type": "audio",
                "payload": {"url": "https://lookaside.fbsbx.com/audio/1"},
            },
            {
                "type": "file",
                "payload": {
                    "url": "https://lookaside.fbsbx.com/file/1",
                    "filename": "presupuesto.pdf",
                },
            },
            {"type": "share", "payload": {}},
        ],
    )

    serialized = serialize_message(message, business_slug=business.slug)

    assert [item["kind"] for item in serialized["attachments"]] == [
        "image",
        "video",
        "audio",
        "document",
        "unknown",
    ]
    assert serialized["body_is_attachment_fallback"] is True
    assert serialized["attachments"][0]["filename"] == "foto_script_.jpg"
    assert serialized["attachments"][0]["thumbnail_url"].endswith(
        "/attachments/1/content?variant=thumbnail"
    )
    assert serialized["attachments"][4]["status"] == "unsupported"
    assert serialized["attachments"][4]["access_url"] is None
    encoded = json.dumps(serialized)
    assert "lookaside.fbsbx.com" not in encoded
    assert "private-signature" not in encoded


def test_text_and_media_preserves_text_and_malformed_url_is_unavailable(media_db):
    db, business, _, conversation, _ = media_db
    message = instagram_message(
        db,
        conversation,
        body="Aquí tienes la imagen",
        attachments=[
            {"type": "image", "payload": {"url": "https://lookaside.fbsbx.com:bad/x"}},
            {
                "type": "document",
                "status": "expired",
                "payload": {"url": "https://lookaside.fbsbx.com/expired"},
            },
        ],
    )

    serialized = serialize_message(message, business_slug=business.slug)

    assert serialized["body"] == "Aquí tienes la imagen"
    assert serialized["body_is_attachment_fallback"] is False
    assert serialized["attachments"][0]["status"] == "unavailable"
    assert serialized["attachments"][0]["access_url"] is None
    assert serialized["attachments"][1]["status"] == "unavailable"
    assert serialized["attachments"][1]["access_url"] is None


def test_media_route_requires_business_access_for_staff_customer_and_guest(media_db):
    db, business, other, _, _ = media_db
    staff = User(email="staff@media.test", is_active=True)
    customer = User(email="customer@media.test", is_active=True)
    membership = BusinessUser(
        business=business,
        user=staff,
        role="business_staff",
        active=True,
    )
    db.add_all([staff, customer, membership])
    db.commit()

    assert any(
        dependency.dependency is require_business_access
        for dependency in admin_router.dependencies
    )
    assert require_business_access(business.slug, staff, db) is staff
    for slug, actor, expected_status in (
        (other.slug, staff, 403),
        (business.slug, customer, 403),
    ):
        with pytest.raises(HTTPException) as denied:
            require_business_access(slug, actor, db)
        assert denied.value.status_code == expected_status
    with pytest.raises(HTTPException) as guest:
        get_current_user(None)
    assert guest.value.status_code == 401


def test_authorized_endpoint_scopes_business_conversation_message_and_attachment(media_db):
    db, business, other, conversation, foreign = media_db
    message = instagram_message(
        db,
        conversation,
        attachments=[
            {
                "type": "image",
                "payload": {"url": "https://lookaside.fbsbx.com/image/allowed"},
            }
        ],
    )
    foreign_message = instagram_message(
        db,
        foreign,
        attachments=[
            {
                "type": "image",
                "payload": {"url": "https://lookaside.fbsbx.com/image/foreign"},
            }
        ],
    )

    with patch(
        "app.services.conversation_media_service.requests.get",
        return_value=FakeResponse(content=b"jpeg", content_type="image/jpeg"),
    ) as get:
        response = admin_get_conversation_attachment(
            business.slug,
            conversation.id,
            message.id,
            "1",
            variant="content",
            db=db,
        )
    assert response.body == b"jpeg"
    assert response.media_type == "image/jpeg"
    assert response.headers["x-content-type-options"] == "nosniff"
    assert "inline" in response.headers["content-disposition"]
    assert get.call_args.kwargs["allow_redirects"] is False
    assert "Authorization" not in get.call_args.kwargs["headers"]

    for values in (
        (other.slug, conversation.id, message.id, "1"),
        (business.slug, conversation.id, foreign_message.id, "1"),
        (business.slug, conversation.id, message.id, "99"),
    ):
        with pytest.raises(HTTPException) as denied:
            admin_get_conversation_attachment(*values, variant="content", db=db)
        assert denied.value.status_code == 404


def test_unsafe_inline_mime_downloads_and_provider_failures_are_isolated(media_db):
    db, business, _, conversation, _ = media_db
    message = instagram_message(
        db,
        conversation,
        attachments=[
            {
                "type": "image",
                "payload": {
                    "url": "https://lookaside.fbsbx.com/image/svg",
                    "filename": "unsafe.svg",
                },
            }
        ],
    )
    attachment = get_message_attachment(message, "1")
    assert attachment is not None

    with patch(
        "app.services.conversation_media_service.requests.get",
        return_value=FakeResponse(content=b"<svg/>", content_type="image/svg+xml"),
    ):
        media = fetch_message_attachment(db, message=message, attachment=attachment)
    assert media.content_type == "application/octet-stream"
    assert media.disposition == "attachment"

    with patch(
        "app.services.conversation_media_service.requests.get",
        side_effect=requests.Timeout,
    ):
        with pytest.raises(ConversationMediaError) as timeout:
            fetch_message_attachment(db, message=message, attachment=attachment)
    assert timeout.value.status_code == 504

    with patch(
        "app.services.conversation_media_service.requests.get",
        return_value=FakeResponse(status_code=403),
    ):
        with pytest.raises(ConversationMediaError) as forbidden:
            fetch_message_attachment(db, message=message, attachment=attachment)
    assert forbidden.value.status_code == 410

    with patch(
        "app.services.conversation_media_service.requests.get",
        return_value=FakeResponse(content_length=25 * 1024 * 1024 + 1),
    ):
        with pytest.raises(ConversationMediaError) as too_large:
            fetch_message_attachment(db, message=message, attachment=attachment)
    assert too_large.value.status_code == 413
    assert serialize_message_attachments(message, business_slug=business.slug)[0]["status"] == "available"


def test_whatsapp_fetches_metadata_then_content_with_token_without_exposing_it(media_db):
    db, _, _, conversation, _ = media_db
    conversation.channel = "whatsapp"
    message = ConversationMessage(
        conversation=conversation,
        direction="inbound",
        sender_type="customer",
        body="Documento recibido",
        raw_payload_json=json.dumps(
            {
                "attachments": [
                    {
                        "kind": "document",
                        "provider_media_id": "media_123",
                        "mime_type": "application/pdf",
                        "filename": "cita.pdf",
                        "status": "available",
                    }
                ]
            }
        ),
    )
    db.add(message)
    db.commit()
    attachment = get_message_attachment(message, "1")
    metadata = FakeResponse(
        content_type="application/json",
        payload={"url": "https://lookaside.fbsbx.com/whatsapp/document"},
    )
    content = FakeResponse(content=b"pdf", content_type="application/pdf")

    with (
        patch(
            "app.services.conversation_media_service._integration_token",
            return_value="provider-secret",
        ),
        patch(
            "app.services.conversation_media_service._provider_get",
            side_effect=[metadata, content],
        ) as provider_get,
    ):
        result = fetch_message_attachment(
            db,
            message=message,
            attachment=attachment,
            settings=SimpleNamespace(meta_graph_api_version="v23.0"),
        )

    assert result.content == b"pdf"
    assert result.disposition == "attachment"
    assert provider_get.call_args_list[0].args[0].endswith("/v23.0/media_123")
    assert provider_get.call_args_list[1].args[0].startswith("https://lookaside.fbsbx.com/")
    assert all(call.kwargs["token"] == "provider-secret" for call in provider_get.call_args_list)
