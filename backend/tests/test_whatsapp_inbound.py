import asyncio
import hashlib
import hmac
import json
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

import pytest
from fastapi import HTTPException
from sqlalchemy import create_engine
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import sessionmaker
from starlette.requests import Request

from app.core.config import Settings
from app.core.database import Base
from app.models import (
    Business,
    BusinessChannelIntegration,
    ChannelOutboxMessage,
    Conversation,
    ConversationMessage,
    ConversationSuggestion,
    WebhookInboxEvent,
)
from app.routers.whatsapp_webhook import (
    receive_whatsapp_webhook,
    verify_whatsapp_webhook,
)
from app.services.channel_provider_service import (
    DELIVERY_PROVIDERS_BY_CHANNEL,
    INBOX_PROCESSORS,
    PROVIDER_SENDERS,
    delivery_supported,
    process_channel_inbox_event,
)
from app.services.conversation_automation_service import ensure_automation_configuration
from app.services.inbox_queue_service import (
    claim_inbox_jobs,
    enqueue_whatsapp_events,
    extract_whatsapp_webhook_events,
)
from app.services.whatsapp_provider import parse_whatsapp_webhook
from app.workers.channel_worker import ChannelWorker


def whatsapp_settings(**overrides):
    values = {
        "app_env": "test",
        "meta_app_secret": "whatsapp-meta-secret",
        "whatsapp_webhook_enabled": True,
        "whatsapp_verify_token": "whatsapp-verify-token",
        "whatsapp_require_signature": False,
        "worker_id": "whatsapp-test-worker",
    }
    values.update(overrides)
    return Settings(_env_file=None, **values)


@pytest.fixture
def database(tmp_path):
    engine = create_engine(
        f"sqlite:///{tmp_path / 'whatsapp.db'}",
        connect_args={"check_same_thread": False},
    )
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, autoflush=False, autocommit=False)
    with factory() as db:
        yield db, factory
    engine.dispose()


def request_for(raw_body: bytes) -> Request:
    sent = False

    async def receive():
        nonlocal sent
        if sent:
            return {"type": "http.request", "body": b"", "more_body": False}
        sent = True
        return {"type": "http.request", "body": raw_body, "more_body": False}

    return Request(
        {
            "type": "http",
            "method": "POST",
            "path": "/api/webhooks/whatsapp",
            "headers": [],
            "client": ("127.0.0.1", 50000),
        },
        receive,
    )


def message(mid, *, sender="34600000001", text="Hola", message_type="text"):
    payload = {
        "from": sender,
        "id": mid,
        "timestamp": "1760000000",
        "type": message_type,
    }
    if message_type == "text":
        payload["text"] = {"body": text}
    else:
        payload[message_type] = {"id": f"media-{mid}"}
    return payload


def status(mid, state="delivered", *, recipient="34600000001", timestamp="1760000001"):
    return {
        "id": mid,
        "status": state,
        "timestamp": timestamp,
        "recipient_id": recipient,
    }


def whatsapp_payload(
    *,
    messages=None,
    statuses=None,
    phone_number_id="phone-1",
    waba_id="waba-1",
    contact_name="Cliente WhatsApp",
):
    value = {
        "messaging_product": "whatsapp",
        "metadata": {
            "display_phone_number": "+34 600 000 000",
            "phone_number_id": phone_number_id,
        },
    }
    if messages is not None:
        value["messages"] = messages
        if contact_name is not None and messages:
            value["contacts"] = [
                {
                    "profile": {"name": contact_name},
                    "wa_id": messages[0].get("from"),
                }
            ]
    if statuses is not None:
        value["statuses"] = statuses
    return {
        "object": "whatsapp_business_account",
        "entry": [
            {
                "id": waba_id,
                "changes": [{"field": "messages", "value": value}],
            }
        ],
    }


def add_integration(db, *, slug="whatsapp-business", phone_number_id="phone-1", state="connected"):
    business = Business(slug=slug, name=slug, status="active")
    db.add(business)
    db.flush()
    integration = BusinessChannelIntegration(
        business_id=business.id,
        channel="whatsapp",
        provider="whatsapp",
        external_account_id=phone_number_id,
        external_account_name=f"WhatsApp {slug}",
        integration_status=state,
        metadata_json=json.dumps({"waba_id": f"waba-{slug}"}),
    )
    db.add(integration)
    db.commit()
    return business, integration


def enqueue_and_claim(db, payload, *, worker_id="whatsapp-direct"):
    events = extract_whatsapp_webhook_events(payload)
    accepted, duplicates = enqueue_whatsapp_events(db, events, max_attempts=5)
    db.commit()
    job_ids = claim_inbox_jobs(db, worker_id=worker_id, limit=20, lock_timeout_seconds=60)
    db.commit()
    return accepted, duplicates, job_ids


def test_get_verification_success_and_rejections():
    active = whatsapp_settings()
    with patch("app.routers.whatsapp_webhook.get_settings", return_value=active):
        response = verify_whatsapp_webhook(
            hub_mode="subscribe",
            hub_verify_token="whatsapp-verify-token",
            hub_challenge="challenge-value",
        )
        assert response.body == b"challenge-value"
        for values in (
            ("subscribe", "wrong-token", "challenge"),
            ("invalid", "whatsapp-verify-token", "challenge"),
            ("subscribe", "whatsapp-verify-token", None),
            (None, None, None),
        ):
            with pytest.raises(HTTPException) as denied:
                verify_whatsapp_webhook(
                    hub_mode=values[0],
                    hub_verify_token=values[1],
                    hub_challenge=values[2],
                )
            assert denied.value.status_code == 403

    with patch(
        "app.routers.whatsapp_webhook.get_settings",
        return_value=whatsapp_settings(whatsapp_webhook_enabled=False),
    ):
        with pytest.raises(HTTPException) as disabled:
            verify_whatsapp_webhook(
                hub_mode="subscribe",
                hub_verify_token="whatsapp-verify-token",
                hub_challenge="challenge",
            )
    assert disabled.value.status_code == 503


def test_parser_normalizes_text_contacts_batches_unsupported_and_statuses():
    first = whatsapp_payload(
        messages=[message("wamid-1"), message("wamid-2", sender="34600000002")]
    )
    second = whatsapp_payload(
        messages=[message("wamid-3")],
        phone_number_id="phone-2",
        waba_id="waba-2",
        contact_name=None,
    )
    batched = {"object": "whatsapp_business_account", "entry": first["entry"] + second["entry"]}
    events = parse_whatsapp_webhook(batched)

    assert [event.message_id for event in events] == ["wamid-1", "wamid-2", "wamid-3"]
    assert events[0].contact_name == "Cliente WhatsApp"
    assert events[1].contact_name is None
    assert events[2].phone_number_id == "phone-2"

    mixed = whatsapp_payload(
        messages=[message("wamid-image", message_type="image")],
        statuses=[status("wamid-outbound", "read")],
    )
    mixed_events = parse_whatsapp_webhook(mixed)
    assert [event.event_type for event in mixed_events] == ["unsupported_message", "status"]
    assert mixed_events[0].text is None
    assert mixed_events[1].status == "read"
    assert parse_whatsapp_webhook({"object": "whatsapp_business_account", "entry": []}) == []
    assert parse_whatsapp_webhook({"object": "instagram", "entry": []}) == []


def test_post_signature_valid_optional_invalid_missing_and_modified(database):
    db, _ = database
    payload = whatsapp_payload(messages=[message("wamid-signature")])
    raw = json.dumps(payload).encode()
    signature = "sha256=" + hmac.new(b"whatsapp-meta-secret", raw, hashlib.sha256).hexdigest()
    required = whatsapp_settings(whatsapp_require_signature=True)

    with patch("app.routers.whatsapp_webhook.get_settings", return_value=required):
        accepted = asyncio.run(
            receive_whatsapp_webhook(request_for(raw), x_hub_signature_256=signature, db=db)
        )
        assert accepted == {"ok": True, "accepted": 1, "duplicates": 0}
        for supplied_signature, body in (
            (None, raw),
            ("sha256=bad", raw),
            (signature, raw + b" "),
        ):
            with pytest.raises(HTTPException) as denied:
                asyncio.run(
                    receive_whatsapp_webhook(
                        request_for(body),
                        x_hub_signature_256=supplied_signature,
                        db=db,
                    )
                )
            assert denied.value.status_code == 403

    optional_payload = whatsapp_payload(messages=[message("wamid-optional")])
    optional_raw = json.dumps(optional_payload).encode()
    with patch(
        "app.routers.whatsapp_webhook.get_settings",
        return_value=whatsapp_settings(whatsapp_require_signature=False),
    ):
        optional = asyncio.run(receive_whatsapp_webhook(request_for(optional_raw), db=db))
    assert optional == {"ok": True, "accepted": 1, "duplicates": 0}


def test_post_rejects_invalid_json_object_oversize_and_disabled(database):
    db, _ = database
    active = whatsapp_settings()
    with patch("app.routers.whatsapp_webhook.get_settings", return_value=active):
        for raw in (b"{", json.dumps({"object": "instagram", "entry": []}).encode()):
            with pytest.raises(HTTPException) as invalid:
                asyncio.run(receive_whatsapp_webhook(request_for(raw), db=db))
            assert invalid.value.status_code == 400

    with patch(
        "app.routers.whatsapp_webhook.get_settings",
        return_value=whatsapp_settings(webhook_max_payload_bytes=1024),
    ):
        with pytest.raises(HTTPException) as oversized:
            asyncio.run(receive_whatsapp_webhook(request_for(b"x" * 1025), db=db))
    assert oversized.value.status_code == 413

    with patch(
        "app.routers.whatsapp_webhook.get_settings",
        return_value=whatsapp_settings(whatsapp_webhook_enabled=False),
    ):
        with pytest.raises(HTTPException) as disabled:
            asyncio.run(receive_whatsapp_webhook(request_for(b"{}"), db=db))
    assert disabled.value.status_code == 503
    assert db.query(WebhookInboxEvent).count() == 0


def test_inbox_idempotency_multiple_messages_and_partial_duplicates(database):
    db, _ = database
    first = whatsapp_payload(messages=[message("wamid-a"), message("wamid-b")])
    second = whatsapp_payload(messages=[message("wamid-b"), message("wamid-c")])
    first_events = extract_whatsapp_webhook_events(first)
    second_events = extract_whatsapp_webhook_events(second)

    assert enqueue_whatsapp_events(db, first_events, max_attempts=5) == (2, 0)
    assert enqueue_whatsapp_events(db, second_events, max_attempts=5) == (1, 1)
    db.commit()
    rows = db.query(WebhookInboxEvent).order_by(WebhookInboxEvent.id).all()
    assert len(rows) == 3
    assert {row.provider for row in rows} == {"whatsapp"}
    assert {row.channel for row in rows} == {"whatsapp"}
    assert {row.event_type for row in rows} == {"message"}
    assert rows[0].provider_event_id == "wamid-a"
    assert rows[0].idempotency_key == "whatsapp:message:wamid-a"
    assert rows[0].payload_hash == hashlib.sha256(rows[0].payload_json.encode()).hexdigest()
    assert rows[0].payload_size_bytes == len(rows[0].payload_json.encode())


def test_processor_resolves_business_creates_and_reuses_conversation_without_token(database):
    db, _ = database
    business, integration = add_integration(db)
    first = whatsapp_payload(messages=[message("wamid-first", text="Hola")])
    second = whatsapp_payload(messages=[message("wamid-second", text="Otra consulta")])

    for payload in (first, second):
        accepted, duplicates, job_ids = enqueue_and_claim(db, payload)
        assert (accepted, duplicates) == (1, 0)
        result = process_channel_inbox_event(db, job_ids[0])
        db.commit()
        assert result.action == "processed"

    conversations = db.query(Conversation).filter(Conversation.channel == "whatsapp").all()
    messages = db.query(ConversationMessage).order_by(ConversationMessage.id).all()
    assert len(conversations) == 1
    assert conversations[0].business_id == business.id
    assert conversations[0].external_user_id == "34600000001"
    assert conversations[0].customer_name == "Cliente WhatsApp"
    assert conversations[0].customer_phone == "34600000001"
    assert [item.provider_message_id for item in messages] == ["wamid-first", "wamid-second"]
    assert integration.encrypted_access_token is None
    assert db.query(ChannelOutboxMessage).count() == 0


def test_status_and_unsupported_messages_do_not_create_conversations(database):
    db, _ = database
    payload = whatsapp_payload(
        messages=[message("wamid-document", message_type="document")],
        statuses=[status("wamid-sent", "sent")],
    )
    accepted, _, job_ids = enqueue_and_claim(db, payload)
    assert accepted == 2
    actions = []
    for job_id in job_ids:
        actions.append(process_channel_inbox_event(db, job_id).action)
        db.commit()

    assert actions == ["ignored", "status_recorded"]
    assert db.query(Conversation).count() == 0
    assert db.query(ConversationMessage).count() == 0
    assert db.query(ChannelOutboxMessage).count() == 0


@pytest.mark.parametrize("state", ["sent", "delivered", "read", "failed"])
def test_all_supported_statuses_are_recorded_without_side_effects(database, state):
    db, _ = database
    _, _, job_ids = enqueue_and_claim(
        db,
        whatsapp_payload(statuses=[status("wamid-status", state)]),
    )

    assert process_channel_inbox_event(db, job_ids[0]).action == "status_recorded"
    db.commit()
    assert db.query(Conversation).count() == 0
    assert db.query(ConversationMessage).count() == 0
    assert db.query(ChannelOutboxMessage).count() == 0


def test_structurally_invalid_messages_fail_permanently_without_side_effects(database):
    db, factory = database
    add_integration(db)
    payloads = [
        whatsapp_payload(messages=[message(None)]),
        whatsapp_payload(messages=[message("wamid-no-sender", sender=None)]),
        whatsapp_payload(messages=[message("wamid-no-phone")], phone_number_id=None),
        whatsapp_payload(messages=[message("wamid-too-long", text="x" * 10_001)]),
    ]
    for payload in payloads:
        enqueue_whatsapp_events(db, extract_whatsapp_webhook_events(payload), max_attempts=5)
    db.commit()

    worker = ChannelWorker(
        settings=whatsapp_settings(worker_batch_size=10),
        session_factory=factory,
        sleep=lambda _: None,
    )
    assert worker.run_once() == 4
    db.expire_all()
    rows = db.query(WebhookInboxEvent).order_by(WebhookInboxEvent.id).all()
    assert {row.status for row in rows} == {"failed"}
    assert {row.attempt_count for row in rows} == {1}
    assert {row.last_error_code for row in rows} == {"invalid_payload"}
    assert db.query(Conversation).count() == 0
    assert db.query(ConversationMessage).count() == 0
    assert db.query(ChannelOutboxMessage).count() == 0


def test_wrong_channel_integration_cannot_route_whatsapp_event(database):
    db, factory = database
    business = Business(slug="wrong-channel", name="wrong-channel", status="active")
    db.add(business)
    db.flush()
    db.add(
        BusinessChannelIntegration(
            business_id=business.id,
            channel="instagram",
            provider="whatsapp",
            external_account_id="phone-1",
            integration_status="connected",
        )
    )
    db.commit()
    enqueue_whatsapp_events(
        db,
        extract_whatsapp_webhook_events(
            whatsapp_payload(messages=[message("wamid-wrong-channel")])
        ),
        max_attempts=5,
    )
    db.commit()

    assert (
        ChannelWorker(
            settings=whatsapp_settings(),
            session_factory=factory,
            sleep=lambda _: None,
        ).run_once()
        == 1
    )
    db.expire_all()
    row = db.query(WebhookInboxEvent).one()
    assert row.status == "failed"
    assert row.last_error_code == "whatsapp_integration_not_found"
    assert row.business_id is None
    assert db.query(Conversation).count() == 0


@pytest.mark.parametrize("integration_state", [None, "disconnected", "expired"])
def test_worker_marks_missing_or_inactive_integration_permanent(database, integration_state):
    db, factory = database
    if integration_state is not None:
        add_integration(db, state=integration_state)
    payload = whatsapp_payload(messages=[message(f"wamid-{integration_state or 'missing'}")])
    events = extract_whatsapp_webhook_events(payload)
    enqueue_whatsapp_events(db, events, max_attempts=5)
    db.commit()
    row_id = db.query(WebhookInboxEvent.id).scalar()

    assert (
        ChannelWorker(
            settings=whatsapp_settings(worker_batch_size=10),
            session_factory=factory,
            sleep=lambda _: None,
        ).run_once()
        == 1
    )
    db.expire_all()
    row = db.get(WebhookInboxEvent, row_id)
    assert row.status == "failed"
    assert row.attempt_count == 1
    assert row.processed_at is None
    assert row.next_retry_at is None
    assert row.last_error_code == (
        "whatsapp_integration_not_found"
        if integration_state is None
        else f"integration_{integration_state}"
    )


def test_worker_processes_whatsapp_without_access_token(database):
    db, factory = database
    add_integration(db)
    events = extract_whatsapp_webhook_events(whatsapp_payload(messages=[message("wamid-worker")]))
    enqueue_whatsapp_events(db, events, max_attempts=5)
    db.commit()
    row_id = db.query(WebhookInboxEvent.id).scalar()

    worker = ChannelWorker(
        settings=whatsapp_settings(),
        session_factory=factory,
        sleep=lambda _: None,
    )
    assert worker.run_once() == 1
    db.expire_all()
    row = db.get(WebhookInboxEvent, row_id)
    assert row.status == "processed"
    assert row.attempt_count == 1
    assert row.business_id is not None
    assert row.integration_id is not None
    assert db.query(ConversationMessage).count() == 1
    assert db.query(ChannelOutboxMessage).count() == 0


def test_automatic_whatsapp_creates_suggestion_without_credit_or_outbox(database):
    db, _ = database
    business, _ = add_integration(db)
    automation_settings, rules = ensure_automation_configuration(db, business)
    automation_settings.automation_enabled = True
    automation_settings.period_started_at = datetime.now(timezone.utc) - timedelta(days=1)
    automation_settings.period_ends_at = datetime.now(timezone.utc) + timedelta(days=29)
    automation_settings.period_status = "active"
    booking_rule = next(item for item in rules if item.intent == "booking_intent")
    booking_rule.mode = "automatic"
    booking_rule.active = True
    db.commit()

    _, _, job_ids = enqueue_and_claim(
        db,
        whatsapp_payload(messages=[message("wamid-automatic", text="¿Hay que pedir cita?")]),
    )
    result = process_channel_inbox_event(db, job_ids[0])
    db.commit()

    assert result.automation["action"] == "suggestion"
    assert result.automation["reason"] == "delivery_not_supported"
    assert db.query(ConversationSuggestion).count() == 1
    assert (
        db.query(ConversationMessage).filter(ConversationMessage.direction == "outbound").count()
        == 0
    )
    assert db.query(ChannelOutboxMessage).count() == 0
    assert automation_settings.included_credits_used == 0
    assert automation_settings.additional_credits_balance == 0


def test_two_businesses_are_isolated_by_phone_number_id(database):
    db, factory = database
    business_a, _ = add_integration(db, slug="whatsapp-a", phone_number_id="phone-a")
    business_b, _ = add_integration(db, slug="whatsapp-b", phone_number_id="phone-b")
    payload_a = whatsapp_payload(
        messages=[message("wamid-a", sender="34600000001")],
        phone_number_id="phone-a",
    )
    payload_b = whatsapp_payload(
        messages=[message("wamid-b", sender="34600000002")],
        phone_number_id="phone-b",
    )
    enqueue_whatsapp_events(db, extract_whatsapp_webhook_events(payload_a), max_attempts=5)
    enqueue_whatsapp_events(db, extract_whatsapp_webhook_events(payload_b), max_attempts=5)
    db.commit()

    ChannelWorker(
        settings=whatsapp_settings(worker_batch_size=10),
        session_factory=factory,
        sleep=lambda _: None,
    ).run_once()
    conversations = db.query(Conversation).order_by(Conversation.id).all()
    assert [(item.business_id, item.external_user_id) for item in conversations] == [
        (business_a.id, "34600000001"),
        (business_b.id, "34600000002"),
    ]
    assert db.query(ChannelOutboxMessage).count() == 0


def test_database_prevents_ambiguous_phone_number_mapping(database):
    db, _ = database
    add_integration(db, slug="mapping-a", phone_number_id="shared-phone")
    other = Business(slug="mapping-b", name="mapping-b", status="active")
    db.add(other)
    db.flush()
    db.add(
        BusinessChannelIntegration(
            business_id=other.id,
            channel="whatsapp",
            provider="whatsapp",
            external_account_id="shared-phone",
            integration_status="connected",
        )
    )
    with pytest.raises(IntegrityError):
        db.commit()
    db.rollback()


def test_whatsapp_is_inbound_only_and_never_delivery_supported():
    assert "whatsapp" in INBOX_PROCESSORS
    assert "whatsapp" not in PROVIDER_SENDERS
    assert "whatsapp" not in DELIVERY_PROVIDERS_BY_CHANNEL
    assert not delivery_supported(channel="whatsapp")
