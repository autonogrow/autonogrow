import json
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import patch

import pytest
import requests
from fastapi import HTTPException
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from starlette.requests import Request

from app.core.config import Settings
from app.core.database import Base
from app.models import (
    AutomationCreditTransaction,
    Business,
    BusinessChannelIntegration,
    ChannelOutboxMessage,
    Conversation,
    ConversationMessage,
    ConversationSuggestion,
    User,
    WebhookInboxEvent,
)
from app.routers.conversations import (
    admin_prepare_assisted_whatsapp_delivery,
    admin_send_conversation_message,
)
from app.schemas.conversation import AssistedDeliveryCreate, ConversationMessageCreate
from app.services.channel_provider_contracts import ProviderSendResult
from app.services.channel_provider_service import (
    DELIVERY_PROVIDERS_BY_CHANNEL,
    PROVIDER_SENDERS,
    delivery_supported,
    process_channel_inbox_event,
)
from app.services.conversation_automation_service import (
    ensure_automation_configuration,
    process_inbound_automation,
)
from app.services.conversation_service import (
    ConversationDeliveryUnavailable,
    add_message,
    conversation_delivery_capabilities,
    is_whatsapp_customer_service_window_open,
    send_outbound_message,
    serialize_conversation,
)
from app.services.inbox_queue_service import (
    claim_inbox_jobs,
    enqueue_whatsapp_events,
    extract_whatsapp_webhook_events,
)
from app.services.integration_crypto_service import encrypt_secret
from app.services.outbox_queue_service import create_channel_outbox
from app.services.whatsapp_provider import send_whatsapp_text_message
from app.workers.channel_worker import ChannelWorker

PHONE_NUMBER_ID = "123456789012345"
RECIPIENT_ID = "34600000001"
KEYRING = '{"v1":"AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA="}'


def outbound_settings(**overrides) -> Settings:
    values = {
        "app_env": "test",
        "meta_graph_api_version": "v23.0",
        "integration_encryption_keys_json": KEYRING,
        "integration_encryption_active_key_version": "v1",
        "worker_id": "whatsapp-outbound-worker",
        "whatsapp_customer_service_window_hours": 24,
    }
    values.update(overrides)
    return Settings(_env_file=None, **values)


@pytest.fixture
def database(tmp_path):
    engine = create_engine(
        f"sqlite:///{tmp_path / 'whatsapp-outbound.db'}",
        connect_args={"check_same_thread": False},
    )
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, autoflush=False, autocommit=False)
    with factory() as db:
        yield db, factory
    engine.dispose()


def request_for(path: str, method: str = "POST") -> Request:
    return Request(
        {
            "type": "http",
            "method": method,
            "path": path,
            "headers": [],
            "client": ("127.0.0.1", 50000),
        }
    )


def add_business(db, slug="whatsapp-outbound"):
    business = Business(slug=slug, name=slug, status="active")
    db.add(business)
    db.flush()
    return business


def add_integration(db, business, settings, *, state="connected", phone_number_id=PHONE_NUMBER_ID):
    ciphertext, version = encrypt_secret("whatsapp-access-token", settings=settings)
    integration = BusinessChannelIntegration(
        business_id=business.id,
        channel="whatsapp",
        provider="whatsapp",
        external_account_id=phone_number_id,
        encrypted_access_token=ciphertext,
        encryption_key_version=version,
        integration_status=state,
        metadata_json=json.dumps({"waba_id": "waba-test"}),
    )
    db.add(integration)
    db.flush()
    return integration


def add_whatsapp_conversation(db, business, *, inbound_at=None):
    conversation = Conversation(
        business_id=business.id,
        channel="whatsapp",
        external_user_id=RECIPIENT_ID,
        customer_phone=RECIPIENT_ID,
        status="pending",
    )
    db.add(conversation)
    db.flush()
    timestamp = inbound_at or datetime.now(timezone.utc)
    inbound = add_message(
        db,
        conversation=conversation,
        direction="inbound",
        sender_type="customer",
        body="¿Hay que pedir cita?",
        provider_message_id=f"wamid-inbound-{conversation.id}",
        raw_payload={"timestamp": str(int(timestamp.timestamp()))},
    )
    db.flush()
    return conversation, inbound


def status_payload(message_id, state, *, phone_number_id=PHONE_NUMBER_ID, errors=None):
    status = {
        "id": message_id,
        "status": state,
        "timestamp": str(int(datetime.now(timezone.utc).timestamp())),
        "recipient_id": RECIPIENT_ID,
    }
    if errors is not None:
        status["errors"] = errors
    return {
        "object": "whatsapp_business_account",
        "entry": [
            {
                "id": "waba-test",
                "changes": [
                    {
                        "field": "messages",
                        "value": {
                            "metadata": {"phone_number_id": phone_number_id},
                            "statuses": [status],
                        },
                    }
                ],
            }
        ],
    }


def process_status(db, payload):
    enqueue_whatsapp_events(db, extract_whatsapp_webhook_events(payload), max_attempts=5)
    db.commit()
    inbox_id = claim_inbox_jobs(
        db,
        worker_id="status-worker",
        limit=10,
        lock_timeout_seconds=60,
    )[-1]
    db.commit()
    result = process_channel_inbox_event(db, inbox_id)
    db.commit()
    return result


def test_sender_posts_official_text_payload_and_extracts_message_id():
    response = SimpleNamespace(
        ok=True,
        status_code=200,
        json=lambda: {"messages": [{"id": "wamid.outbound-1"}]},
    )
    with (
        patch("app.services.whatsapp_provider.requests.post", return_value=response) as post,
        patch("logging.Logger._log") as logger_log,
    ):
        result = send_whatsapp_text_message(
            RECIPIENT_ID,
            "Respuesta",
            access_token="secret-access-token",
            external_account_id=PHONE_NUMBER_ID,
            settings=outbound_settings(),
        )

    assert result.ok
    assert result.provider_message_id == "wamid.outbound-1"
    assert post.call_args.args[0] == (
        f"https://graph.facebook.com/v23.0/{PHONE_NUMBER_ID}/messages"
    )
    assert post.call_args.kwargs["headers"]["Authorization"] == "Bearer secret-access-token"
    assert post.call_args.kwargs["json"] == {
        "messaging_product": "whatsapp",
        "recipient_type": "individual",
        "to": RECIPIENT_ID,
        "type": "text",
        "text": {"preview_url": False, "body": "Respuesta"},
    }
    logger_log.assert_not_called()


@pytest.mark.parametrize(
    ("recipient", "text", "phone_number_id", "expected_code"),
    [
        ("invalid", "text", PHONE_NUMBER_ID, "invalid_recipient"),
        (RECIPIENT_ID, "", PHONE_NUMBER_ID, "invalid_payload"),
        (RECIPIENT_ID, "x" * 4097, PHONE_NUMBER_ID, "invalid_payload"),
        (RECIPIENT_ID, "text", "../invalid", "invalid_phone_number_id"),
    ],
)
def test_sender_rejects_invalid_inputs_without_http(
    recipient, text, phone_number_id, expected_code
):
    with patch("app.services.whatsapp_provider.requests.post") as post:
        result = send_whatsapp_text_message(
            recipient,
            text,
            access_token="token",
            external_account_id=phone_number_id,
            settings=outbound_settings(),
        )
    assert not result.ok
    assert result.error_code == expected_code
    post.assert_not_called()


@pytest.mark.parametrize("http_status", [429, 500, 502, 503, 504])
def test_sender_returns_http_failures_for_common_retry_classification(http_status):
    response = SimpleNamespace(
        ok=False,
        status_code=http_status,
        json=lambda: {"error": {"code": 130429 if http_status == 429 else 131000}},
    )
    with patch("app.services.whatsapp_provider.requests.post", return_value=response):
        result = send_whatsapp_text_message(
            RECIPIENT_ID,
            "text",
            access_token="token",
            external_account_id=PHONE_NUMBER_ID,
            settings=outbound_settings(),
        )
    assert result.http_status == http_status
    assert result.error_code in {"provider_rate_limited", "provider_unavailable"}


@pytest.mark.parametrize(
    ("meta_code", "expected_code"),
    [
        (190, "token_revoked"),
        (131005, "insufficient_permissions"),
        (100, "invalid_payload"),
        (131030, "invalid_recipient"),
        (131047, "whatsapp_template_required"),
        (131031, "account_suspended"),
        (133010, "number_not_registered"),
    ],
)
def test_sender_maps_permanent_meta_errors(meta_code, expected_code):
    response = SimpleNamespace(
        ok=False,
        status_code=400,
        json=lambda: {
            "error": {
                "code": meta_code,
                "message": "sensitive provider detail",
                "type": "OAuthException",
            }
        },
    )
    with patch("app.services.whatsapp_provider.requests.post", return_value=response):
        result = send_whatsapp_text_message(
            RECIPIENT_ID,
            "text",
            access_token="token",
            external_account_id=PHONE_NUMBER_ID,
            settings=outbound_settings(),
        )
    assert result.error_code == expected_code
    assert "sensitive" not in (result.error_message or "")


def test_sender_timeout_connection_invalid_json_and_missing_message_id():
    with patch("app.services.whatsapp_provider.requests.post", side_effect=requests.Timeout):
        timed_out = send_whatsapp_text_message(
            RECIPIENT_ID,
            "text",
            access_token="token",
            external_account_id=PHONE_NUMBER_ID,
            settings=outbound_settings(),
        )
    assert timed_out.timed_out
    assert timed_out.error_code == "provider_timeout"

    with patch(
        "app.services.whatsapp_provider.requests.post",
        side_effect=requests.ConnectionError,
    ):
        connection = send_whatsapp_text_message(
            RECIPIENT_ID,
            "text",
            access_token="token",
            external_account_id=PHONE_NUMBER_ID,
            settings=outbound_settings(),
        )
    assert connection.error_code == "request_failed"

    for payload_factory in (lambda: (_ for _ in ()).throw(ValueError()), lambda: {}):
        response = SimpleNamespace(ok=True, status_code=200, json=payload_factory)
        with patch("app.services.whatsapp_provider.requests.post", return_value=response):
            invalid = send_whatsapp_text_message(
                RECIPIENT_ID,
                "text",
                access_token="token",
                external_account_id=PHONE_NUMBER_ID,
                settings=outbound_settings(),
            )
        assert invalid.error_code == "invalid_provider_response"


def test_dispatcher_and_delivery_capabilities_require_usable_integration(database):
    db, _ = database
    settings = outbound_settings()
    business = add_business(db)
    conversation, inbound = add_whatsapp_conversation(db, business)
    db.commit()

    def serialized_state():
        with patch("app.services.conversation_service.get_settings", return_value=settings):
            serialized = serialize_conversation(db, conversation)
        return {
            key: serialized[key]
            for key in (
                "delivery_supported",
                "provider_configured",
                "integration_status",
                "integrated_delivery_available",
                "assisted_delivery_available",
                "delivery_mode",
                "customer_service_window_open",
                "delivery_unavailable_reason",
            )
        }

    assert "whatsapp" in PROVIDER_SENDERS
    assert DELIVERY_PROVIDERS_BY_CHANNEL["whatsapp"] == "whatsapp"
    assert delivery_supported(channel="whatsapp")
    assert serialized_state() == {
        "delivery_supported": True,
        "provider_configured": False,
        "integration_status": None,
        "integrated_delivery_available": False,
        "assisted_delivery_available": True,
        "delivery_mode": "assisted",
        "customer_service_window_open": True,
        "delivery_unavailable_reason": "provider_not_configured",
    }

    integration = add_integration(db, business, settings, state="disconnected")
    db.commit()
    valid_ciphertext = integration.encrypted_access_token
    valid_key_version = integration.encryption_key_version
    assert serialized_state() == {
        "delivery_supported": True,
        "provider_configured": True,
        "integration_status": "disconnected",
        "integrated_delivery_available": False,
        "assisted_delivery_available": True,
        "delivery_mode": "assisted",
        "customer_service_window_open": True,
        "delivery_unavailable_reason": "delivery_not_available",
    }

    integration.integration_status = "connected"
    integration.encrypted_access_token = None
    integration.encryption_key_version = None
    assert serialized_state()["provider_configured"] is True
    assert serialized_state()["integrated_delivery_available"] is False
    assert serialized_state()["delivery_unavailable_reason"] == "delivery_not_available"

    integration.encrypted_access_token = "not-an-encrypted-token"
    integration.encryption_key_version = valid_key_version
    assert serialized_state()["provider_configured"] is True
    assert serialized_state()["integrated_delivery_available"] is False
    assert serialized_state()["delivery_unavailable_reason"] == "delivery_not_available"

    integration.encrypted_access_token = valid_ciphertext
    integration.external_account_id = "../invalid"
    assert serialized_state()["provider_configured"] is True
    assert serialized_state()["integrated_delivery_available"] is False
    integration.external_account_id = PHONE_NUMBER_ID
    assert serialized_state() == {
        "delivery_supported": True,
        "provider_configured": True,
        "integration_status": "connected",
        "integrated_delivery_available": True,
        "assisted_delivery_available": True,
        "delivery_mode": "integrated",
        "customer_service_window_open": True,
        "delivery_unavailable_reason": None,
    }

    inbound.raw_payload_json = json.dumps(
        {"timestamp": str(int((datetime.now(timezone.utc) - timedelta(hours=25)).timestamp()))}
    )
    assert serialized_state()["customer_service_window_open"] is False
    assert serialized_state()["integrated_delivery_available"] is False
    assert serialized_state()["delivery_unavailable_reason"] == "whatsapp_template_required"

    inbound.raw_payload_json = json.dumps(
        {"timestamp": str(int(datetime.now(timezone.utc).timestamp()))}
    )
    automation, _ = ensure_automation_configuration(db, business)
    automation.whatsapp_channel_enabled = False
    assert serialized_state()["customer_service_window_open"] is True
    assert serialized_state()["integrated_delivery_available"] is False
    assert serialized_state()["delivery_unavailable_reason"] == "integrated_delivery_not_in_plan"


@pytest.mark.parametrize(
    ("integration_status", "health_status"),
    [("revoked", "healthy"), ("connected", "suspended")],
)
def test_revoked_or_suspended_integration_uses_assisted_delivery(
    database, integration_status, health_status
):
    db, _ = database
    settings = outbound_settings()
    business = add_business(db)
    integration = add_integration(db, business, settings, state=integration_status)
    integration.health_status = health_status
    conversation, _ = add_whatsapp_conversation(db, business)
    db.commit()

    capabilities = conversation_delivery_capabilities(
        db,
        conversation=conversation,
        settings=settings,
    )

    assert not capabilities.integrated_delivery_available
    assert capabilities.assisted_delivery_available
    assert capabilities.delivery_mode == "assisted"


def test_invalid_recipient_makes_delivery_unavailable(database):
    db, _ = database
    business = add_business(db)
    conversation, _ = add_whatsapp_conversation(db, business)
    conversation.customer_phone = "sin-telefono"
    conversation.external_user_id = "invalid"
    db.commit()

    capabilities = conversation_delivery_capabilities(db, conversation=conversation)

    assert not capabilities.integrated_delivery_available
    assert not capabilities.assisted_delivery_available
    assert capabilities.delivery_mode == "unavailable"


def test_manual_integrated_send_creates_idempotent_outbox_and_worker_persists_mid(database):
    db, factory = database
    settings = outbound_settings()
    business = add_business(db)
    integration = add_integration(db, business, settings)
    conversation, _ = add_whatsapp_conversation(db, business)
    actor = User(email="whatsapp-admin@test.invalid")
    db.add(actor)
    db.commit()

    payload = ConversationMessageCreate.model_validate(
        {
            "body": "Respuesta integrada",
            "provider": "instagram",
            "integration_id": 999999,
            "phone_number_id": "999999999999999",
            "business_id": 999999,
            "delivery_mode": "sent",
        }
    )
    assert payload.model_dump() == {
        "body": "Respuesta integrada",
        "suggestion_id": None,
    }

    with patch("app.services.conversation_service.get_settings", return_value=settings):
        response = admin_send_conversation_message(
            business.slug,
            conversation.id,
            payload,
            request_for(f"/conversations/{conversation.id}/messages"),
            actor=actor,
            db=db,
        )
    assert response["message"]["delivery_status"] == "queued"
    assert "whatsapp-access-token" not in json.dumps(response)
    outbox = db.query(ChannelOutboxMessage).one()
    assert outbox.business_id == business.id
    assert outbox.integration_id == integration.id
    assert outbox.provider == outbox.channel == "whatsapp"
    assert outbox.idempotency_key == f"whatsapp:outbound-message:{outbox.conversation_message_id}"
    same_outbox = create_channel_outbox(
        db,
        conversation=conversation,
        message=db.get(ConversationMessage, outbox.conversation_message_id),
        provider="whatsapp",
        channel="whatsapp",
        integration_id=integration.id,
        recipient_external_id=RECIPIENT_ID,
        max_attempts=settings.worker_max_attempts,
    )
    assert same_outbox.id == outbox.id
    assert db.query(ChannelOutboxMessage).count() == 1

    sender = lambda *args, **kwargs: ProviderSendResult(  # noqa: E731
        delivery_status="sent", provider_message_id="wamid.outbound-worker"
    )
    worker = ChannelWorker(
        settings=settings,
        session_factory=factory,
        senders={"whatsapp": sender},
        sleep=lambda _: None,
    )
    assert worker.run_once() == 1
    db.expire_all()
    outbox = db.query(ChannelOutboxMessage).one()
    message = db.get(ConversationMessage, outbox.conversation_message_id)
    assert outbox.status == "sent"
    assert outbox.sent_at is not None
    assert outbox.provider_message_id == "wamid.outbound-worker"
    assert message.delivery_status == "sent"
    assert message.provider_message_id == "wamid.outbound-worker"


@pytest.mark.parametrize(
    ("provider_result", "expected_status", "expected_integration_status"),
    [
        (
            ProviderSendResult(
                delivery_status="failed",
                error_code="provider_timeout",
                timed_out=True,
            ),
            "retry",
            "connected",
        ),
        (
            ProviderSendResult(
                delivery_status="failed",
                error_code="token_revoked",
                http_status=401,
            ),
            "blocked",
            "revoked",
        ),
        (
            ProviderSendResult(
                delivery_status="failed",
                error_code="invalid_recipient",
                http_status=400,
            ),
            "failed",
            "connected",
        ),
        (
            ProviderSendResult(
                delivery_status="failed",
                error_code="whatsapp_template_required",
                http_status=400,
            ),
            "failed",
            "connected",
        ),
        (
            ProviderSendResult(
                delivery_status="failed",
                error_code="insufficient_permissions",
                http_status=403,
            ),
            "blocked",
            "error",
        ),
    ],
)
def test_worker_retries_transient_and_blocks_permanent_whatsapp_errors(
    database,
    provider_result,
    expected_status,
    expected_integration_status,
):
    db, factory = database
    settings = outbound_settings()
    business = add_business(db)
    integration = add_integration(db, business, settings)
    conversation, _ = add_whatsapp_conversation(db, business)
    with patch("app.services.conversation_service.get_settings", return_value=settings):
        send_outbound_message(
            db,
            conversation=conversation,
            body="Respuesta",
            sender_type="business",
        )
    db.commit()

    def sender(*args, **kwargs):
        return provider_result

    worker = ChannelWorker(
        settings=settings,
        session_factory=factory,
        senders={"whatsapp": sender},
        sleep=lambda _: None,
    )
    assert worker.run_once() == 1
    db.expire_all()
    outbox = db.query(ChannelOutboxMessage).one()
    assert outbox.status == expected_status
    assert outbox.attempt_count == 1
    assert integration.integration_status == expected_integration_status
    if expected_status == "retry":
        assert outbox.next_retry_at is not None
    else:
        assert outbox.next_retry_at is None


def test_automatic_recent_inbound_creates_outbox_and_consumes_credit_once(database):
    db, factory = database
    settings = outbound_settings()
    business = add_business(db)
    add_integration(db, business, settings)
    conversation, inbound = add_whatsapp_conversation(db, business)
    automation, rules = ensure_automation_configuration(db, business)
    automation.automation_enabled = True
    automation.period_started_at = datetime.now(timezone.utc) - timedelta(days=1)
    automation.period_ends_at = datetime.now(timezone.utc) + timedelta(days=29)
    automation.period_status = "active"
    rule = next(item for item in rules if item.intent == "booking_intent")
    rule.mode = "automatic"
    rule.active = True
    db.commit()

    with patch("app.services.conversation_service.get_settings", return_value=settings):
        result = process_inbound_automation(
            db,
            business=business,
            conversation=conversation,
            message=inbound,
        )
        replay = process_inbound_automation(
            db,
            business=business,
            conversation=conversation,
            message=inbound,
        )
    db.commit()

    assert result["action"] == "automatic"
    assert result["delivery_status"] == "queued"
    assert replay["action"] != "automatic"
    assert db.query(ChannelOutboxMessage).count() == 1
    assert db.query(AutomationCreditTransaction).count() == 1
    transaction = db.query(AutomationCreditTransaction).one()
    assert transaction.idempotency_key == f"automatic-message:{result['outbound_message_id']}"
    assert transaction.reason == "Mensaje automático encolado"
    assert automation.included_credits_used == 1

    provider_results = iter(
        (
            ProviderSendResult(
                delivery_status="failed",
                error_code="provider_timeout",
                timed_out=True,
            ),
            ProviderSendResult(
                delivery_status="failed",
                error_code="token_revoked",
                http_status=401,
            ),
        )
    )
    worker = ChannelWorker(
        settings=settings,
        session_factory=factory,
        senders={"whatsapp": lambda *_args, **_kwargs: next(provider_results)},
        sleep=lambda _: None,
    )
    assert worker.run_once() == 1
    db.expire_all()
    outbox = db.query(ChannelOutboxMessage).one()
    assert outbox.status == "retry"
    assert db.query(AutomationCreditTransaction).count() == 1
    outbox.next_retry_at = datetime.utcnow() - timedelta(seconds=1)
    db.commit()

    assert worker.run_once() == 1
    db.expire_all()
    assert db.query(ChannelOutboxMessage).one().status == "blocked"
    assert db.query(AutomationCreditTransaction).count() == 1
    assert automation.included_credits_used == 1


@pytest.mark.parametrize("integration_state", [None, "disconnected"])
def test_automatic_without_usable_integration_creates_suggestion_without_credit(
    database, integration_state
):
    db, _ = database
    settings = outbound_settings()
    business = add_business(db)
    if integration_state is not None:
        add_integration(db, business, settings, state=integration_state)
    conversation, inbound = add_whatsapp_conversation(db, business)
    automation, rules = ensure_automation_configuration(db, business)
    automation.automation_enabled = True
    automation.period_started_at = datetime.now(timezone.utc) - timedelta(days=1)
    automation.period_ends_at = datetime.now(timezone.utc) + timedelta(days=29)
    automation.period_status = "active"
    next(item for item in rules if item.intent == "booking_intent").mode = "automatic"
    db.commit()

    with patch("app.services.conversation_service.get_settings", return_value=settings):
        result = process_inbound_automation(
            db,
            business=business,
            conversation=conversation,
            message=inbound,
        )
    db.commit()

    assert result["action"] == "suggestion"
    assert result["reason"] == (
        "provider_not_configured" if integration_state is None else "delivery_not_available"
    )
    assert db.query(ConversationSuggestion).count() == 1
    assert db.query(ChannelOutboxMessage).count() == 0
    assert db.query(AutomationCreditTransaction).count() == 0


def test_closed_window_requires_template_without_outbox_or_credit(database):
    db, _ = database
    settings = outbound_settings()
    business = add_business(db)
    add_integration(db, business, settings)
    conversation, inbound = add_whatsapp_conversation(
        db,
        business,
        inbound_at=datetime.now(timezone.utc) - timedelta(hours=25),
    )
    automation, rules = ensure_automation_configuration(db, business)
    automation.automation_enabled = True
    automation.period_started_at = datetime.now(timezone.utc) - timedelta(days=1)
    automation.period_ends_at = datetime.now(timezone.utc) + timedelta(days=29)
    automation.period_status = "active"
    next(item for item in rules if item.intent == "booking_intent").mode = "automatic"
    db.commit()

    assert not is_whatsapp_customer_service_window_open(
        db,
        conversation=conversation,
        settings=settings,
    )
    with patch("app.services.conversation_service.get_settings", return_value=settings):
        result = process_inbound_automation(
            db,
            business=business,
            conversation=conversation,
            message=inbound,
        )
        with pytest.raises(ConversationDeliveryUnavailable) as denied:
            send_outbound_message(
                db,
                conversation=conversation,
                body="Respuesta libre",
                sender_type="business",
            )
    assert result["action"] == "suggestion"
    assert result["reason"] == "whatsapp_template_required"
    assert denied.value.reason == "whatsapp_template_required"
    assert (
        db.query(ConversationMessage).filter(ConversationMessage.direction == "outbound").count()
        == 0
    )
    assert db.query(ChannelOutboxMessage).count() == 0
    assert db.query(AutomationCreditTransaction).count() == 0
    assert db.query(ConversationSuggestion).count() == 1
    assert not is_whatsapp_customer_service_window_open(
        db,
        conversation=conversation,
        settings=settings,
    )

    add_message(
        db,
        conversation=conversation,
        direction="outbound",
        sender_type="business",
        body="Echo saliente",
        provider_message_id="wamid-outbound-echo",
        raw_payload={
            "timestamp": str(int(datetime.now(timezone.utc).timestamp())),
            "is_echo": True,
        },
    )
    assert not is_whatsapp_customer_service_window_open(
        db,
        conversation=conversation,
        settings=settings,
    )

    assert process_status(db, status_payload("wamid-unknown", "read")).action == "status_recorded"
    assert not is_whatsapp_customer_service_window_open(
        db,
        conversation=conversation,
        settings=settings,
    )

    inbound.raw_payload_json = json.dumps({"timestamp": "invalid"})
    assert not is_whatsapp_customer_service_window_open(
        db,
        conversation=conversation,
        settings=settings,
    )
    inbound.raw_payload_json = json.dumps(
        {"timestamp": str(int((datetime.now(timezone.utc) + timedelta(minutes=1)).timestamp()))}
    )
    assert not is_whatsapp_customer_service_window_open(
        db,
        conversation=conversation,
        settings=settings,
    )


def test_window_uses_latest_provider_timestamp_when_inbounds_arrive_out_of_order(database):
    db, _ = database
    settings = outbound_settings()
    business = add_business(db)
    conversation, _ = add_whatsapp_conversation(
        db,
        business,
        inbound_at=datetime.now(timezone.utc) - timedelta(hours=1),
    )
    add_message(
        db,
        conversation=conversation,
        direction="inbound",
        sender_type="customer",
        body="Evento antiguo recibido después",
        provider_message_id="wamid-inbound-delayed",
        raw_payload={
            "timestamp": str(int((datetime.now(timezone.utc) - timedelta(hours=30)).timestamp()))
        },
    )
    db.commit()

    assert is_whatsapp_customer_service_window_open(
        db,
        conversation=conversation,
        settings=settings,
    )


def test_commercial_channel_flag_disables_integrated_but_keeps_assisted(database):
    db, _ = database
    settings = outbound_settings()
    business = add_business(db)
    add_integration(db, business, settings)
    conversation, _ = add_whatsapp_conversation(db, business)
    automation, _ = ensure_automation_configuration(db, business)
    automation.whatsapp_channel_enabled = False
    db.commit()

    capabilities = conversation_delivery_capabilities(
        db,
        conversation=conversation,
        settings=settings,
    )
    assert capabilities.provider_configured
    assert not capabilities.integrated_delivery_available
    assert capabilities.assisted_delivery_available
    assert capabilities.unavailable_reason == "integrated_delivery_not_in_plan"


def test_assisted_fallback_returns_url_without_message_outbox_or_credit(database):
    db, _ = database
    business = add_business(db)
    conversation, _ = add_whatsapp_conversation(db, business)
    actor = User(email="assisted@test.invalid")
    db.add(actor)
    db.commit()
    initial_messages = db.query(ConversationMessage).count()

    payload = AssistedDeliveryCreate.model_validate(
        {
            "body": "Respuesta asistida",
            "provider": "whatsapp",
            "integration_id": 999999,
            "sent": True,
        }
    )
    assert payload.model_dump() == {"body": "Respuesta asistida"}

    result = admin_prepare_assisted_whatsapp_delivery(
        business.slug,
        conversation.id,
        payload,
        request_for(f"/conversations/{conversation.id}/assisted-delivery"),
        actor=actor,
        db=db,
    )

    assert result["delivery_mode"] == "assisted"
    assert result["sent"] is False
    assert result["whatsapp_url"].startswith(f"https://wa.me/{RECIPIENT_ID}?text=")
    assert db.query(ConversationMessage).count() == initial_messages
    assert db.query(ChannelOutboxMessage).count() == 0
    assert db.query(AutomationCreditTransaction).count() == 0


def test_other_business_cannot_send_conversation(database):
    db, _ = database
    settings = outbound_settings()
    business = add_business(db, "tenant-a")
    other = add_business(db, "tenant-b")
    add_integration(db, business, settings)
    conversation, _ = add_whatsapp_conversation(db, business)
    actor = User(email="tenant@test.invalid")
    db.add(actor)
    db.commit()

    with pytest.raises(HTTPException) as hidden:
        admin_send_conversation_message(
            other.slug,
            conversation.id,
            ConversationMessageCreate(body="Cross tenant"),
            request_for(f"/conversations/{conversation.id}/messages"),
            actor=actor,
            db=db,
        )
    assert hidden.value.status_code == 404
    assert db.query(ChannelOutboxMessage).count() == 0


def test_manual_integrated_send_rejects_closed_window_without_side_effects(database):
    db, _ = database
    settings = outbound_settings()
    business = add_business(db)
    add_integration(db, business, settings)
    conversation, _ = add_whatsapp_conversation(
        db,
        business,
        inbound_at=datetime.now(timezone.utc) - timedelta(hours=25),
    )
    actor = User(email="closed-window@test.invalid")
    db.add(actor)
    db.commit()

    with (
        patch("app.services.conversation_service.get_settings", return_value=settings),
        pytest.raises(HTTPException) as rejected,
    ):
        admin_send_conversation_message(
            business.slug,
            conversation.id,
            ConversationMessageCreate(body="Texto fuera de ventana"),
            request_for(f"/conversations/{conversation.id}/messages"),
            actor=actor,
            db=db,
        )

    assert rejected.value.status_code == 409
    assert rejected.value.detail["reason"] == "whatsapp_template_required"
    assert "plantilla aprobada" in rejected.value.detail["message"]
    assert db.query(ConversationMessage).count() == 1
    assert db.query(ChannelOutboxMessage).count() == 0


def test_statuses_reconcile_monotonically_and_wrong_phone_is_rejected(database):
    db, _ = database
    settings = outbound_settings()
    business = add_business(db)
    integration = add_integration(db, business, settings)
    conversation, _ = add_whatsapp_conversation(db, business)
    with patch("app.services.conversation_service.get_settings", return_value=settings):
        delivery = send_outbound_message(
            db,
            conversation=conversation,
            body="Respuesta",
            sender_type="business",
        )
    outbox = db.query(ChannelOutboxMessage).one()
    outbox.status = "sent"
    outbox.provider_message_id = "wamid.status-target"
    delivery.message.delivery_status = "sent"
    delivery.message.provider_message_id = "wamid.status-target"
    db.commit()

    assert process_status(db, status_payload("wamid.status-target", "delivered")).action == (
        "status_reconciled"
    )
    assert process_status(db, status_payload("wamid.status-target", "read")).action == (
        "status_reconciled"
    )
    assert process_status(db, status_payload("wamid.status-target", "sent")).action == (
        "status_unchanged"
    )
    db.refresh(delivery.message)
    assert delivery.message.delivery_status == "read"
    delivery_metadata = json.loads(delivery.message.raw_payload_json)["whatsapp_delivery"]
    assert delivery_metadata["status"] == "read"
    assert delivery_metadata["timestamp"].isdigit()
    assert outbox.integration_id == integration.id
    assert db.query(Conversation).count() == 1

    enqueue_whatsapp_events(
        db,
        extract_whatsapp_webhook_events(
            status_payload(
                "wamid.status-target",
                "failed",
                phone_number_id="999999999999999",
            )
        ),
        max_attempts=5,
    )
    db.commit()
    inbox_id = claim_inbox_jobs(
        db,
        worker_id="wrong-phone",
        limit=10,
        lock_timeout_seconds=60,
    )[-1]
    db.commit()
    with pytest.raises(Exception, match="WhatsApp status context is invalid"):
        process_channel_inbox_event(db, inbox_id)
    db.rollback()
    db.refresh(delivery.message)
    assert delivery.message.delivery_status == "read"


def test_failed_status_persists_only_safe_error_fields(database):
    db, _ = database
    settings = outbound_settings()
    business = add_business(db)
    add_integration(db, business, settings)
    conversation, _ = add_whatsapp_conversation(db, business)
    with patch("app.services.conversation_service.get_settings", return_value=settings):
        delivery = send_outbound_message(
            db,
            conversation=conversation,
            body="Respuesta",
            sender_type="business",
        )
    outbox = db.query(ChannelOutboxMessage).one()
    outbox.status = "sent"
    outbox.provider_message_id = "wamid.failed-target"
    delivery.message.delivery_status = "sent"
    delivery.message.provider_message_id = "wamid.failed-target"
    db.commit()

    payload = status_payload(
        "wamid.failed-target",
        "failed",
        errors=[
            {
                "code": 131047,
                "title": "Re-engagement message",
                "type": "OAuthException",
                "message": "sensitive recipient and provider detail",
            }
        ],
    )
    assert process_status(db, payload).action == "status_reconciled"
    db.refresh(outbox)
    db.refresh(delivery.message)
    inbox = db.query(WebhookInboxEvent).order_by(WebhookInboxEvent.id.desc()).first()
    assert outbox.status == "failed"
    assert outbox.failed_at is not None
    assert outbox.last_error_code == "131047"
    assert outbox.last_error_type == "OAuthException"
    assert outbox.safe_error_message == "WhatsApp delivery failed"
    assert delivery.message.delivery_status == "failed"
    delivery_metadata = json.loads(delivery.message.raw_payload_json)["whatsapp_delivery"]
    assert delivery_metadata == {
        "error_code": "131047",
        "error_type": "OAuthException",
        "status": "failed",
        "timestamp": payload["entry"][0]["changes"][0]["value"]["statuses"][0]["timestamp"],
    }
    assert "sensitive recipient" not in inbox.payload_json
    assert "sensitive recipient" not in (delivery.message.raw_payload_json or "")

    payload["entry"][0]["changes"][0]["value"]["statuses"][0]["timestamp"] = str(
        int(datetime.now(timezone.utc).timestamp()) + 1
    )
    assert process_status(db, payload).action == "status_unchanged"
    db.refresh(outbox)
    assert outbox.status == "failed"
