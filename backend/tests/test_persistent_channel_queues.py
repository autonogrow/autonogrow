import asyncio
import base64
import hashlib
import hmac
import json
from datetime import datetime, timedelta
from unittest.mock import patch

import pytest
from fastapi import HTTPException
from pydantic import ValidationError
from scripts.cleanup_queue_history import cleanup
from sqlalchemy import create_engine
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import sessionmaker
from starlette.requests import Request

from app.core.config import Settings
from app.core.database import Base
from app.models import (
    AuditLog,
    Business,
    BusinessChannelIntegration,
    ChannelOutboxMessage,
    Conversation,
    ConversationMessage,
    User,
    WebhookInboxEvent,
    WorkerHeartbeat,
)
from app.routers.instagram_webhook import receive_instagram_webhook
from app.routers.owner import cancel_outbox_job, get_queue_status, retry_outbox_job
from app.schemas.owner import QueueJobActionRequest
from app.services.conversation_service import add_message
from app.services.inbox_queue_service import (
    claim_inbox_jobs,
    enqueue_instagram_events,
    extract_instagram_webhook_events,
    fail_inbox_job,
)
from app.services.instagram_provider import ProviderSendResult
from app.services.integration_crypto_service import encrypt_secret
from app.services.outbox_queue_service import (
    create_channel_outbox,
    fail_outbox_job,
)
from app.services.queue_error_service import calculate_next_retry, classify_queue_error
from app.services.worker_heartbeat_service import heartbeat_is_stale, update_worker_heartbeat
from app.workers.channel_worker import ChannelWorker


def settings(**overrides):
    key = base64.urlsafe_b64encode(b"q" * 32).decode()
    values = {
        "app_env": "test",
        "meta_app_secret": "test-meta-secret",
        "instagram_require_signature": True,
        "instagram_provider_enabled": True,
        "integration_encryption_keys_json": json.dumps({"v1": key}),
        "integration_encryption_active_key_version": "v1",
        "worker_id": "queue-test-worker",
    }
    values.update(overrides)
    return Settings(_env_file=None, **values)


@pytest.fixture
def database(tmp_path):
    engine = create_engine(
        f"sqlite:///{tmp_path / 'queues.db'}", connect_args={"check_same_thread": False}
    )
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, autoflush=False, autocommit=False)
    with factory() as db:
        yield db, factory
    engine.dispose()


def payload(*, mids=("mid-1",), recipient="account-1", echo=False):
    events = []
    for index, mid in enumerate(mids):
        events.append(
            {
                "sender": {"id": recipient if echo else f"customer-{index}"},
                "recipient": {"id": f"customer-{index}" if echo else recipient},
                "timestamp": 100 + index,
                "message": {"mid": mid, "text": "hello", "is_echo": echo},
            }
        )
    return {"object": "instagram", "entry": [{"messaging": events}]}


def request_for(raw: bytes) -> Request:
    sent = False

    async def receive():
        nonlocal sent
        if sent:
            return {"type": "http.request", "body": b"", "more_body": False}
        sent = True
        return {"type": "http.request", "body": raw, "more_body": False}

    return Request(
        {"type": "http", "method": "POST", "path": "/api/webhooks/instagram", "headers": []},
        receive,
    )


def owner_request() -> Request:
    return Request(
        {
            "type": "http",
            "method": "POST",
            "path": "/api/owner/queue/outbox/1/retry",
            "headers": [],
            "client": ("test", 1),
        }
    )


def add_channel_context(
    db, active_settings, *, slug="queue-business", account="account-1", token="token-1"
):
    business = Business(slug=slug, name=slug, status="active")
    db.add(business)
    db.flush()
    encrypted, version = encrypt_secret(token, settings=active_settings)
    integration = BusinessChannelIntegration(
        business_id=business.id,
        channel="instagram",
        provider="instagram",
        external_account_id=account,
        encrypted_access_token=encrypted,
        encryption_key_version=version,
        integration_status="connected",
    )
    db.add(integration)
    conversation = Conversation(
        business_id=business.id,
        channel="instagram",
        external_user_id=f"recipient-{slug}",
        status="pending",
    )
    db.add(conversation)
    db.flush()
    message = add_message(
        db,
        conversation=conversation,
        direction="outbound",
        sender_type="automation",
        body="safe response",
        delivery_status="queued",
    )
    outbox = create_channel_outbox(
        db,
        conversation=conversation,
        message=message,
        integration_id=integration.id,
        recipient_external_id=conversation.external_user_id,
        max_attempts=5,
    )
    db.commit()
    return business, integration, conversation, message, outbox


def test_extraction_splits_payload_and_uses_provider_message_id():
    rows = extract_instagram_webhook_events(payload(mids=("a", "b")))
    assert len(rows) == 2
    assert rows[0].idempotency_key == "instagram:message:a"
    assert rows[0].payload_hash == hashlib.sha256(rows[0].payload_json.encode()).hexdigest()


def test_database_uniqueness_and_savepoint_deduplicate(database):
    db, _ = database
    rows = extract_instagram_webhook_events(payload())
    assert enqueue_instagram_events(db, rows, max_attempts=5) == (1, 0)
    assert enqueue_instagram_events(db, rows, max_attempts=5) == (0, 1)
    db.commit()
    assert db.query(WebhookInboxEvent).count() == 1
    db.add(
        WebhookInboxEvent(
            provider="instagram",
            channel="instagram",
            idempotency_key=rows[0].idempotency_key,
            payload_hash="x" * 64,
            payload_json="{}",
            payload_size_bytes=2,
        )
    )
    with pytest.raises(IntegrityError):
        db.flush()
    db.rollback()


def test_webhook_signature_multiple_events_and_no_provider(database):
    db, _ = database
    active = settings()
    raw = json.dumps(payload(mids=("a", "b"))).encode()
    signature = (
        "sha256=" + hmac.new(active.meta_app_secret.encode(), raw, hashlib.sha256).hexdigest()
    )
    with (
        patch("app.routers.instagram_webhook.get_settings", return_value=active),
        patch("app.services.instagram_provider.send_instagram_text_message") as provider,
    ):
        result = asyncio.run(receive_instagram_webhook(request_for(raw), signature, db))
    assert result == {"ok": True, "accepted": 2, "duplicates": 0}
    provider.assert_not_called()


def test_webhook_rejects_bad_signature_and_oversize(database):
    db, _ = database
    raw = json.dumps(payload()).encode()
    with patch("app.routers.instagram_webhook.get_settings", return_value=settings()):
        with pytest.raises(HTTPException) as invalid:
            asyncio.run(receive_instagram_webhook(request_for(raw), "sha256=bad", db))
    assert invalid.value.status_code == 403
    with patch(
        "app.routers.instagram_webhook.get_settings",
        return_value=settings(webhook_max_payload_bytes=1024),
    ):
        with pytest.raises(HTTPException) as oversized:
            asyncio.run(receive_instagram_webhook(request_for(b"x" * 1025), None, db))
    assert oversized.value.status_code == 413
    assert db.query(WebhookInboxEvent).count() == 0


def test_claim_pending_retry_and_expired_lock_but_not_future_or_live(database):
    db, _ = database
    now = datetime.utcnow()
    rows = [
        WebhookInboxEvent(
            provider="instagram",
            channel="instagram",
            idempotency_key=f"k-{index}",
            payload_hash="x" * 64,
            payload_json="{}",
            payload_size_bytes=2,
            status=status,
            available_at=now - timedelta(seconds=2),
            next_retry_at=retry,
            lock_expires_at=lock,
        )
        for index, (status, retry, lock) in enumerate(
            [
                ("pending", None, None),
                ("retry", now - timedelta(seconds=1), None),
                ("retry", now + timedelta(minutes=1), None),
                ("processing", None, now - timedelta(seconds=1)),
                ("processing", None, now + timedelta(minutes=1)),
            ]
        )
    ]
    db.add_all(rows)
    db.commit()
    claimed = claim_inbox_jobs(db, worker_id="w", limit=10, lock_timeout_seconds=60, now=now)
    assert claimed == [rows[0].id, rows[1].id, rows[3].id]
    assert all(db.get(WebhookInboxEvent, job_id).attempt_count == 1 for job_id in claimed)


@pytest.mark.parametrize("attempt,minimum", [(1, 27), (2, 108), (3, 540), (4, 1620), (5, 6480)])
def test_backoff_schedule_and_jitter(attempt, minimum):
    now = datetime(2026, 1, 1)
    low = (calculate_next_retry(attempt, now=now, random_value=0) - now).total_seconds()
    high = (calculate_next_retry(attempt, now=now, random_value=1) - now).total_seconds()
    assert low == minimum
    assert high > low
    assert high / low < 1.23


@pytest.mark.parametrize("http_status", [408, 429, 500, 502, 503, 504])
def test_transient_http_errors_are_retryable(http_status):
    assert classify_queue_error(http_status=http_status).retryable


def test_attempt_exhaustion_creates_dead_letter_state(database):
    db, _ = database
    row = WebhookInboxEvent(
        provider="instagram",
        channel="instagram",
        idempotency_key="dead",
        payload_hash="x" * 64,
        payload_json="{}",
        payload_size_bytes=2,
        status="processing",
        attempt_count=5,
        max_attempts=5,
    )
    db.add(row)
    db.flush()
    fail_inbox_job(row, error_code="timeout", safe_message="temporary", retryable=True)
    assert row.status == "dead_letter"
    assert row.locked_by is None


def test_outbox_retry_block_and_dead_letter_transitions(database):
    db, _ = database
    active = settings()
    *_, message, outbox = add_channel_context(db, active)
    outbox.status = "processing"
    outbox.attempt_count = 1
    fail_outbox_job(outbox, message, classification=classify_queue_error(http_status=429))
    assert outbox.status == "retry" and message.delivery_status == "retry"
    outbox.status = "processing"
    fail_outbox_job(
        outbox, message, classification=classify_queue_error(error_code="integration_expired")
    )
    assert outbox.status == "blocked" and message.delivery_status == "blocked"


def test_worker_sends_outbox_and_persists_provider_id(database):
    db, factory = database
    active = settings()
    *_, message, outbox = add_channel_context(db, active)
    calls = []

    def provider(recipient, text, **kwargs):
        calls.append((recipient, text, kwargs["access_token"]))
        return ProviderSendResult("sent", "provider-mid")

    worker = ChannelWorker(
        settings=active, session_factory=factory, provider_sender=provider, sleep=lambda _: None
    )
    assert worker.run_once() == 1
    db.expire_all()
    assert db.get(ChannelOutboxMessage, outbox.id).status == "sent"
    assert db.get(ConversationMessage, message.id).provider_message_id == "provider-mid"
    assert calls == [("recipient-queue-business", "safe response", "token-1")]


def test_worker_timeout_retries_without_duplicate_message(database):
    db, factory = database
    active = settings()
    *_, message, outbox = add_channel_context(db, active)
    worker = ChannelWorker(
        settings=active,
        session_factory=factory,
        provider_sender=lambda *args, **kwargs: ProviderSendResult("failed", timed_out=True),
        sleep=lambda _: None,
    )
    worker.run_once()
    db.expire_all()
    assert db.get(ChannelOutboxMessage, outbox.id).status == "retry"
    assert db.query(ConversationMessage).filter(ConversationMessage.id == message.id).count() == 1
    assert db.query(ChannelOutboxMessage).count() == 1


def test_disconnected_integration_blocks_without_provider_call(database):
    db, factory = database
    active = settings()
    _, integration, _, _, outbox = add_channel_context(db, active)
    integration.integration_status = "disconnected"
    db.commit()
    calls = []
    worker = ChannelWorker(
        settings=active,
        session_factory=factory,
        provider_sender=lambda *args, **kwargs: calls.append(1),
        sleep=lambda _: None,
    )
    worker.run_once()
    db.expire_all()
    assert db.get(ChannelOutboxMessage, outbox.id).status == "blocked"
    assert calls == []


def test_two_businesses_use_their_own_decrypted_token(database):
    db, factory = database
    active = settings(worker_batch_size=10)
    add_channel_context(db, active, slug="one", account="a1", token="token-one")
    add_channel_context(db, active, slug="two", account="a2", token="token-two")
    tokens = []

    def provider(*args, **kwargs):
        tokens.append(kwargs["access_token"])
        return ProviderSendResult("sent")

    ChannelWorker(
        settings=active, session_factory=factory, provider_sender=provider, sleep=lambda _: None
    ).run_once()
    assert tokens == ["token-one", "token-two"]


def test_heartbeat_create_update_stale_and_clean_stop(database):
    db, factory = database
    now = datetime.utcnow()
    row = update_worker_heartbeat(db, worker_id="heartbeat", status="starting", now=now)
    db.commit()
    update_worker_heartbeat(
        db, worker_id="heartbeat", status="idle", now=now + timedelta(seconds=1)
    )
    db.commit()
    assert db.query(WorkerHeartbeat).count() == 1
    assert heartbeat_is_stale(row, stale_after_seconds=60, now=now + timedelta(seconds=62))
    worker = ChannelWorker(
        settings=settings(worker_id="stop-worker"), session_factory=factory, sleep=lambda _: None
    )
    worker.request_stop()
    worker.run_forever()
    assert (
        db.query(WorkerHeartbeat).filter(WorkerHeartbeat.worker_id == "stop-worker").one().status
        == "stopped"
    )


def test_worker_configuration_rejects_unsafe_ranges():
    with pytest.raises(ValueError):
        settings(worker_batch_size=101)
    with pytest.raises(ValueError):
        settings(worker_lock_timeout_seconds=1, worker_poll_interval_seconds=1)
    with pytest.raises(ValueError):
        settings(worker_heartbeat_interval_seconds=60, worker_stale_after_seconds=60)


def test_owner_queue_status_is_safe_and_actions_are_audited(database):
    db, _ = database
    active = settings()
    *_, message, outbox = add_channel_context(db, active)
    owner = User(email="owner@queue.test", is_owner=True)
    db.add(owner)
    outbox.status = "dead_letter"
    db.commit()
    status = get_queue_status(db=db)
    serialized = json.dumps(status)
    assert "payload_json" not in serialized and "safe response" not in serialized
    result = retry_outbox_job(
        outbox.id,
        QueueJobActionRequest(reason="fixed integration"),
        owner_request(),
        actor=owner,
        db=db,
    )
    assert result["job"]["status"] == "pending"
    assert db.get(ConversationMessage, message.id).delivery_status == "queued"
    cancel_outbox_job(
        outbox.id,
        QueueJobActionRequest(reason="operator cancellation"),
        owner_request(),
        actor=owner,
        db=db,
    )
    assert db.get(ConversationMessage, message.id).delivery_status == "cancelled"
    assert db.query(AuditLog).filter(AuditLog.action.like("queue_outbox_%")).count() == 2
    with pytest.raises(ValidationError):
        QueueJobActionRequest(reason="valid reason", payload="forbidden")


def test_cleanup_is_dry_run_and_preserves_pending_and_dead_letters(database):
    db, factory = database
    old = datetime.utcnow() - timedelta(days=100)
    db.add_all(
        [
            WebhookInboxEvent(
                provider="instagram",
                channel="instagram",
                idempotency_key="old-processed",
                payload_hash="x" * 64,
                payload_json="{}",
                payload_size_bytes=2,
                status="processed",
                processed_at=old,
            ),
            WebhookInboxEvent(
                provider="instagram",
                channel="instagram",
                idempotency_key="old-pending",
                payload_hash="x" * 64,
                payload_json="{}",
                payload_size_bytes=2,
                status="pending",
                created_at=old,
                available_at=old,
            ),
            WebhookInboxEvent(
                provider="instagram",
                channel="instagram",
                idempotency_key="old-dead",
                payload_hash="x" * 64,
                payload_json="{}",
                payload_size_bytes=2,
                status="dead_letter",
                failed_at=old,
                created_at=old,
            ),
        ]
    )
    db.commit()
    result = cleanup(
        apply=False,
        session_factory=factory,
        settings=settings(webhook_inbox_retention_days=30),
        now=datetime.utcnow(),
    )
    assert result["inbox"] == 1
    assert db.query(WebhookInboxEvent).count() == 3
