from __future__ import annotations

import json
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path
from threading import Barrier
from types import SimpleNamespace
from urllib.parse import parse_qs, urlparse

import pytest
from alembic import command
from fastapi import HTTPException
from sqlalchemy import create_engine, inspect
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, sessionmaker
from starlette.requests import Request

from app.core.database import Base
from app.core.migration_state import alembic_config
from app.core.security import require_business_access, require_business_admin
from app.models import (
    AuditLog,
    Booking,
    BookingAttribution,
    Business,
    BusinessChannelIntegration,
    BusinessService,
    BusinessUser,
    ChannelOutboxMessage,
    Conversation,
    ConversationMessage,
    Customer,
    CustomerOpportunity,
    OpportunityAction,
    User,
)
from app.routers.growth_actions import (
    action_or_404,
    cancel_opportunity_action,
    edit_opportunity_action,
    get_growth_metrics,
    manually_attribute_booking,
    mark_opportunity_handled,
    prepare_opportunity_action,
    prepare_opportunity_assisted_delivery,
    send_opportunity_action,
)
from app.routers.growth_opportunities import transition_opportunity
from app.schemas.customer_opportunity import OpportunityStatusUpdate
from app.schemas.opportunity_action import (
    ManualBookingAttributionCreate,
    OpportunityActionPrepare,
    OpportunityActionUpdate,
)
from app.services.booking_attribution_service import (
    POST_ACTION_ATTRIBUTION_WINDOW,
    attribute_new_booking,
    sync_attributed_booking_status,
)
from app.services.conversation_service import (
    ConversationDeliveryCapabilities,
    OutboundMessageResult,
)
from app.services.growth_metrics_service import growth_metrics
from app.services.opportunity_action_service import (
    OpportunityActionService,
    expire_drafts,
    invalidate_actions_for_resolved_opportunity,
    resolve_action_channel,
)
from app.services.opportunity_template_service import create_attribution_token
from app.services.outbox_queue_service import (
    claim_outbox_jobs,
    fail_outbox_job,
    finish_outbox_job,
)
from app.services.queue_error_service import classify_queue_error

NOW = datetime(2026, 8, 14, 12, 0, tzinfo=timezone.utc)


@pytest.fixture
def db() -> Session:
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine)()
    yield session
    session.close()
    engine.dispose()


@pytest.fixture(autouse=True)
def action_settings(monkeypatch: pytest.MonkeyPatch) -> None:
    settings = SimpleNamespace(
        session_secret="opportunity-action-tests",
        frontend_origin_list=["https://app.example.test"],
    )
    monkeypatch.setattr(
        "app.services.opportunity_template_service.get_settings", lambda: settings
    )


def request(path: str = "/api/admin/businesses/action-a/opportunities") -> Request:
    return Request(
        {
            "type": "http",
            "method": "POST",
            "path": path,
            "headers": [],
            "client": ("testclient", 50000),
        }
    )


@pytest.fixture
def records(db: Session) -> dict[str, object]:
    business_a = Business(
        slug="action-a", name="Action A", status="active", currency="EUR"
    )
    business_b = Business(
        slug="action-b", name="Action B", status="active", currency="EUR"
    )
    admin = User(email="action-admin@test.local")
    staff = User(email="action-staff@test.local")
    other = User(email="action-other@test.local")
    db.add_all((business_a, business_b, admin, staff, other))
    db.flush()
    db.add_all(
        (
            BusinessUser(
                business_id=business_a.id,
                user_id=admin.id,
                role="business_admin",
                active=True,
            ),
            BusinessUser(
                business_id=business_a.id,
                user_id=staff.id,
                role="business_staff",
                active=True,
            ),
            BusinessUser(
                business_id=business_b.id,
                user_id=other.id,
                role="business_admin",
                active=True,
            ),
        )
    )
    customer_a = Customer(
        business_id=business_a.id, name="Ana", phone="+34 600 000 001"
    )
    customer_b = Customer(
        business_id=business_b.id, name="Bea", phone="+34 600 000 001"
    )
    other_customer_a = Customer(
        business_id=business_a.id, name="Alicia", phone="+34 600 000 002"
    )
    service_a = BusinessService(
        business_id=business_a.id,
        name="Manicura",
        duration_minutes=45,
        price_amount=Decimal("45.00"),
        currency="EUR",
        follow_up_enabled=True,
        follow_up_interval_days=21,
        follow_up_window_days=4,
    )
    service_b = BusinessService(
        business_id=business_b.id,
        name="Aceite",
        duration_minutes=60,
        price_amount=Decimal("80.00"),
        currency="EUR",
    )
    db.add_all((customer_a, customer_b, other_customer_a, service_a, service_b))
    db.flush()
    conversation_a = Conversation(
        business_id=business_a.id,
        channel="whatsapp",
        external_user_id="34600000001",
        customer_name="Ana",
        customer_phone=customer_a.phone,
        status="pending",
        last_message_at=NOW,
        last_inbound_at=NOW,
    )
    conversation_b = Conversation(
        business_id=business_b.id,
        channel="instagram",
        external_user_id="ig-bea",
        customer_name="Bea",
        status="pending",
        last_message_at=NOW,
    )
    db.add_all((conversation_a, conversation_b))
    db.commit()
    return {
        "a": business_a,
        "b": business_b,
        "admin": admin,
        "staff": staff,
        "other": other,
        "customer_a": customer_a,
        "customer_b": customer_b,
        "other_customer_a": other_customer_a,
        "service_a": service_a,
        "service_b": service_b,
        "conversation_a": conversation_a,
        "conversation_b": conversation_b,
    }


def opportunity(
    db: Session,
    records: dict[str, object],
    *,
    opportunity_type: str = "service_due",
    customer_key: str = "customer_a",
    conversation: Conversation | None = None,
    status: str = "pending",
) -> CustomerOpportunity:
    business = records["a"]
    customer = records[customer_key]
    service = records["service_a"]
    assert isinstance(business, Business)
    assert isinstance(customer, Customer)
    assert isinstance(service, BusinessService)
    row = CustomerOpportunity(
        business_id=business.id,
        customer_id=customer.id,
        type=opportunity_type,
        status=status,
        priority="normal",
        detected_at=NOW - timedelta(days=1),
        due_at=NOW - timedelta(hours=1),
        expires_at=NOW + timedelta(days=30),
        source_service_id=service.id,
        source_conversation_id=conversation.id if conversation else None,
        reason_code=f"test_{opportunity_type}",
        reason_text="Seguimiento determinista de prueba.",
        dedupe_key=f"{opportunity_type}:{customer.id}:{datetime.now().timestamp()}",
        source_occurred_at=NOW - timedelta(days=21),
        follow_up_interval_days_snapshot=21,
        follow_up_window_days_snapshot=4,
    )
    db.add(row)
    db.commit()
    return row


def booking(
    db: Session,
    records: dict[str, object],
    *,
    customer_key: str = "customer_a",
    business_key: str = "a",
    created_at: datetime = NOW,
    status: str = "requested",
) -> Booking:
    business = records[business_key]
    customer = records[customer_key]
    service = records["service_a"] if business_key == "a" else records["service_b"]
    assert isinstance(business, Business)
    assert isinstance(customer, Customer)
    assert isinstance(service, BusinessService)
    row = Booking(
        business_id=business.id,
        customer_id=customer.id,
        service_id=service.id,
        service_name=service.name,
        duration_minutes=service.duration_minutes,
        price_amount_snapshot=service.price_amount,
        currency_snapshot=service.currency,
        start_datetime=(created_at + timedelta(days=1)).replace(tzinfo=None),
        end_datetime=(created_at + timedelta(days=1, minutes=45)).replace(tzinfo=None),
        preferred_date=(created_at + timedelta(days=1)).date().isoformat(),
        preferred_time="12:00",
        source="landing",
        status=status,
        created_at=created_at,
    )
    db.add(row)
    db.commit()
    return row


def available_capabilities(
    _db: Session, *, conversation: Conversation
) -> ConversationDeliveryCapabilities:
    return ConversationDeliveryCapabilities(
        provider=conversation.channel,
        integration=None,
        delivery_supported=True,
        provider_configured=True,
        channel_enabled=True,
        customer_service_window_open=True,
        integrated_delivery_available=True,
        assisted_delivery_available=conversation.channel == "whatsapp",
        unavailable_reason=None,
    )


def test_associated_conversation_is_resolved_without_phone_or_sender_fallback(
    db: Session, records: dict[str, object]
) -> None:
    customer = records["customer_a"]
    business = records["a"]
    assert isinstance(customer, Customer)
    assert isinstance(business, Business)
    customer.phone = None
    conversation = Conversation(
        business_id=business.id,
        customer_id=customer.id,
        channel="instagram",
        external_user_id="associated-instagram-customer",
        customer_username=None,
        status="replied",
        last_message_at=NOW,
    )
    db.add(conversation)
    db.commit()
    row = opportunity(db, records)

    resolution = resolve_action_channel(db, opportunity=row)
    assert resolution.conversation is not None
    assert resolution.conversation.id == conversation.id


@pytest.mark.parametrize(
    ("opportunity_type", "expected"),
    [
        ("service_due", "ya est\u00e1s en fecha de volver"),
        ("cancelled_not_rebooked", "quedó cancelada"),
        ("no_show_not_rebooked", "retomar tu cita"),
        ("lead_not_converted", "hace poco nos preguntaste"),
        ("scheduled_followup", "retomamos el seguimiento"),
    ],
)
def test_prepare_creates_deterministic_editable_draft_without_sending(
    db: Session,
    records: dict[str, object],
    monkeypatch: pytest.MonkeyPatch,
    opportunity_type: str,
    expected: str,
) -> None:
    conversation = records["conversation_a"]
    assert isinstance(conversation, Conversation)
    row = opportunity(
        db, records, opportunity_type=opportunity_type, conversation=conversation
    )
    monkeypatch.setattr(
        "app.services.opportunity_action_service.conversation_delivery_capabilities",
        available_capabilities,
    )
    response = prepare_opportunity_action(
        "action-a",
        row.id,
        OpportunityActionPrepare(),
        request(),
        actor=records["staff"],
        db=db,
    )
    action = response["action"]
    assert response["created"] is True
    assert action["status"] == "draft"
    assert action["message_id"] is None
    assert action["can_send"] is True
    assert expected in action["suggested_text"]
    if opportunity_type == "service_due":
        assert "aproximadamente" not in action["suggested_text"]
    assert "https://app.example.test/autonogrow-landing/" in action["booking_url"]
    assert db.query(ConversationMessage).count() == 0
    assert {
        log.action for log in db.query(AuditLog).all()
    } >= {"opportunity_viewed", "action_prepared"}


def test_prepare_rejects_closed_and_cross_tenant_and_handles_no_channel(
    db: Session, records: dict[str, object]
) -> None:
    closed = opportunity(db, records, status="resolved")
    with pytest.raises(HTTPException) as invalid:
        prepare_opportunity_action(
            "action-a",
            closed.id,
            OpportunityActionPrepare(),
            request(),
            actor=records["staff"],
            db=db,
        )
    assert invalid.value.status_code == 409
    active = opportunity(
        db,
        records,
        opportunity_type="lead_not_converted",
        customer_key="other_customer_a",
    )
    with pytest.raises(HTTPException) as hidden:
        prepare_opportunity_action(
            "action-b",
            active.id,
            OpportunityActionPrepare(),
            request(),
            actor=records["other"],
            db=db,
        )
    assert hidden.value.status_code == 404
    prepared = prepare_opportunity_action(
        "action-a",
        active.id,
        OpportunityActionPrepare(),
        request(),
        actor=records["staff"],
        db=db,
    )["action"]
    assert prepared["channel"] is None
    assert prepared["can_send"] is False
    assert prepared["assisted_delivery_available"] is True
    assert prepared["delivery_mode"] == "assisted"
    assert prepared["unavailable_reason"] == "no_customer_channel"


def test_assisted_opportunity_uses_customer_phone_without_delivery_side_effects(
    db: Session, records: dict[str, object]
) -> None:
    row = opportunity(
        db,
        records,
        opportunity_type="scheduled_followup",
        customer_key="other_customer_a",
    )
    action = prepare_opportunity_action(
        "action-a",
        row.id,
        OpportunityActionPrepare(),
        request(),
        actor=records["staff"],
        db=db,
    )["action"]
    initial_conversations = db.query(Conversation).count()

    result = prepare_opportunity_assisted_delivery(
        "action-a",
        action["id"],
        request(f"/actions/{action['id']}/assisted-delivery"),
        actor=records["staff"],
        db=db,
    )

    parsed = urlparse(result["whatsapp_url"])
    assert parsed.scheme == "https"
    assert parsed.netloc == "wa.me"
    assert parsed.path == "/34600000002"
    assert parse_qs(parsed.query)["text"] == [action["final_text"]]
    assert result["delivery_mode"] == "assisted"
    assert result["sent"] is False
    assert result["action"]["status"] == "draft"
    assert result["action"]["message_id"] is None
    assert db.query(Conversation).count() == initial_conversations
    assert db.query(ConversationMessage).count() == 0
    assert db.query(ChannelOutboxMessage).count() == 0
    assert "opportunity_action_assisted_delivery_opened" in {
        log.action for log in db.query(AuditLog).all()
    }

    with pytest.raises(HTTPException) as hidden:
        prepare_opportunity_assisted_delivery(
            "action-b",
            action["id"],
            request(),
            actor=records["other"],
            db=db,
        )
    assert hidden.value.status_code == 404


def test_opportunity_without_valid_phone_is_unavailable(
    db: Session, records: dict[str, object]
) -> None:
    customer = records["other_customer_a"]
    assert isinstance(customer, Customer)
    customer.phone = "sin telefono"
    row = opportunity(
        db,
        records,
        opportunity_type="lead_not_converted",
        customer_key="other_customer_a",
    )

    action = prepare_opportunity_action(
        "action-a",
        row.id,
        OpportunityActionPrepare(),
        request(),
        actor=records["staff"],
        db=db,
    )["action"]

    assert action["delivery_mode"] == "unavailable"
    assert action["assisted_delivery_available"] is False
    with pytest.raises(HTTPException) as unavailable:
        prepare_opportunity_assisted_delivery(
            "action-a", action["id"], request(), actor=records["staff"], db=db
        )
    assert unavailable.value.status_code == 409
    assert "teléfono válido" in unavailable.value.detail


def test_edit_only_draft_and_staff_permissions_are_preserved(
    db: Session,
    records: dict[str, object],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    conversation = records["conversation_a"]
    assert isinstance(conversation, Conversation)
    row = opportunity(db, records, conversation=conversation)
    monkeypatch.setattr(
        "app.services.opportunity_action_service.conversation_delivery_capabilities",
        available_capabilities,
    )
    created = prepare_opportunity_action(
        "action-a",
        row.id,
        OpportunityActionPrepare(),
        request(),
        actor=records["staff"],
        db=db,
    )["action"]
    edited = edit_opportunity_action(
        "action-a",
        created["id"],
        OpportunityActionUpdate(final_text="Texto revisado por el equipo."),
        request(),
        actor=records["staff"],
        db=db,
    )["action"]
    assert edited["final_text"] == "Texto revisado por el equipo."
    assert edited["last_edited_by_user_id"] == records["staff"].id
    persisted = db.get(OpportunityAction, created["id"])
    persisted.status = "sent"
    persisted.sent_at = NOW
    db.commit()
    with pytest.raises(HTTPException) as immutable:
        edit_opportunity_action(
            "action-a",
            persisted.id,
            OpportunityActionUpdate(final_text="No debe cambiar"),
            request(),
            actor=records["staff"],
            db=db,
        )
    assert immutable.value.status_code == 409
    assert require_business_access("action-a", records["staff"], db) is records["staff"]
    with pytest.raises(HTTPException):
        require_business_admin("action-a", records["staff"], db)


def test_send_is_explicit_and_double_click_idempotent(
    db: Session,
    records: dict[str, object],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    conversation = records["conversation_a"]
    assert isinstance(conversation, Conversation)
    row = opportunity(db, records, conversation=conversation)
    monkeypatch.setattr(
        "app.services.opportunity_action_service.conversation_delivery_capabilities",
        available_capabilities,
    )
    monkeypatch.setattr(
        "app.routers.growth_actions.conversation_delivery_capabilities",
        available_capabilities,
    )
    action_id = prepare_opportunity_action(
        "action-a",
        row.id,
        OpportunityActionPrepare(),
        request(),
        actor=records["staff"],
        db=db,
    )["action"]["id"]
    calls: list[str] = []

    def fake_send(
        session: Session, *, conversation: Conversation, body: str, sender_type: str
    ) -> OutboundMessageResult:
        calls.append(body)
        message = ConversationMessage(
            conversation_id=conversation.id,
            direction="outbound",
            sender_type=sender_type,
            body=body,
            delivery_status="queued",
        )
        session.add(message)
        session.flush()
        return OutboundMessageResult(message, True, False)

    monkeypatch.setattr("app.routers.growth_actions.send_outbound_message", fake_send)
    first = send_opportunity_action(
        "action-a", action_id, request(), actor=records["staff"], db=db
    )
    second = send_opportunity_action(
        "action-a", action_id, request(), actor=records["staff"], db=db
    )
    assert first["action"]["status"] == "approved"
    assert first["action"]["message_id"] is not None
    assert second["idempotent"] is True
    assert len(calls) == 1
    assert db.query(ConversationMessage).count() == 1


def test_send_blocks_closed_whatsapp_window_without_simulating_success(
    db: Session,
    records: dict[str, object],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    conversation = records["conversation_a"]
    assert isinstance(conversation, Conversation)
    row = opportunity(db, records, conversation=conversation)
    monkeypatch.setattr(
        "app.services.opportunity_action_service.conversation_delivery_capabilities",
        available_capabilities,
    )
    action_id = prepare_opportunity_action(
        "action-a",
        row.id,
        OpportunityActionPrepare(),
        request(),
        actor=records["admin"],
        db=db,
    )["action"]["id"]

    def closed_window(
        _db: Session, *, conversation: Conversation
    ) -> ConversationDeliveryCapabilities:
        return ConversationDeliveryCapabilities(
            provider="whatsapp",
            integration=None,
            delivery_supported=True,
            provider_configured=True,
            channel_enabled=True,
            customer_service_window_open=False,
            integrated_delivery_available=False,
            assisted_delivery_available=True,
            unavailable_reason="whatsapp_template_required",
        )

    monkeypatch.setattr(
        "app.routers.growth_actions.conversation_delivery_capabilities", closed_window
    )
    monkeypatch.setattr(
        "app.services.opportunity_action_service.conversation_delivery_capabilities",
        closed_window,
    )
    response = send_opportunity_action(
        "action-a", action_id, request(), actor=records["admin"], db=db
    )
    body = json.loads(response.body)
    assert response.status_code == 409
    assert body["detail"]["reason"] == "whatsapp_template_required"
    assert body["action"]["status"] == "draft"
    assert db.query(ConversationMessage).count() == 0


def test_failed_integrated_action_can_offer_assisted_without_duplicate_delivery(
    db: Session,
    records: dict[str, object],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    conversation = records["conversation_a"]
    assert isinstance(conversation, Conversation)
    row = opportunity(
        db,
        records,
        opportunity_type="cancelled_not_rebooked",
        conversation=conversation,
    )
    monkeypatch.setattr(
        "app.services.opportunity_action_service.conversation_delivery_capabilities",
        available_capabilities,
    )
    monkeypatch.setattr(
        "app.routers.growth_actions.conversation_delivery_capabilities",
        available_capabilities,
    )
    action = prepare_opportunity_action(
        "action-a",
        row.id,
        OpportunityActionPrepare(),
        request(),
        actor=records["admin"],
        db=db,
    )["action"]

    def failed_send(
        session: Session, *, conversation: Conversation, body: str, sender_type: str
    ) -> OutboundMessageResult:
        message = ConversationMessage(
            conversation_id=conversation.id,
            direction="outbound",
            sender_type=sender_type,
            body=body,
            delivery_status="failed",
            provider_message_id=None,
        )
        session.add(message)
        session.flush()
        return OutboundMessageResult(
            message,
            provider_configured=True,
            provider_attempted=True,
            client_error_message="No se pudo entregar.",
        )

    monkeypatch.setattr("app.routers.growth_actions.send_outbound_message", failed_send)
    failed = send_opportunity_action(
        "action-a", action["id"], request(), actor=records["admin"], db=db
    )
    failed_body = json.loads(failed.body)
    assert failed.status_code == 502
    assert failed_body["action"]["status"] == "failed"
    assert db.query(ConversationMessage).count() == 1

    assisted = prepare_opportunity_assisted_delivery(
        "action-a", action["id"], request(), actor=records["admin"], db=db
    )

    message = db.query(ConversationMessage).one()
    assert assisted["sent"] is False
    assert assisted["action"]["status"] == "failed"
    assert db.query(ConversationMessage).count() == 1
    assert db.query(ChannelOutboxMessage).count() == 0
    assert message.delivery_status == "failed"
    assert message.provider_message_id is None
    with pytest.raises(HTTPException) as unsafe_retry:
        send_opportunity_action(
            "action-a", action["id"], request(), actor=records["admin"], db=db
        )
    assert unsafe_retry.value.status_code == 409
    assert "evitar duplicados" in unsafe_retry.value.detail
    assert db.query(ConversationMessage).count() == 1


def test_cancelled_contact_action_can_be_prepared_again_with_history_preserved(
    db: Session,
    records: dict[str, object],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    conversation = records["conversation_a"]
    assert isinstance(conversation, Conversation)
    row = opportunity(db, records, conversation=conversation)
    monkeypatch.setattr(
        "app.services.opportunity_action_service.conversation_delivery_capabilities",
        available_capabilities,
    )
    first = prepare_opportunity_action(
        "action-a",
        row.id,
        OpportunityActionPrepare(),
        request(),
        actor=records["staff"],
        db=db,
    )["action"]

    cancel_opportunity_action(
        "action-a", first["id"], request(), actor=records["staff"], db=db
    )
    recovered = prepare_opportunity_action(
        "action-a",
        row.id,
        OpportunityActionPrepare(),
        request(),
        actor=records["staff"],
        db=db,
    )

    assert recovered["created"] is True
    assert recovered["action"]["status"] == "draft"
    assert recovered["action"]["id"] != first["id"]
    assert row.status == "pending"
    assert [item.status for item in row.actions] == ["cancelled", "draft"]


def test_expired_draft_prepares_a_fresh_attempt_and_does_not_reuse_its_link(
    db: Session,
    records: dict[str, object],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    conversation = records["conversation_a"]
    assert isinstance(conversation, Conversation)
    row = opportunity(db, records, conversation=conversation)
    monkeypatch.setattr(
        "app.services.opportunity_action_service.conversation_delivery_capabilities",
        available_capabilities,
    )
    first = prepare_opportunity_action(
        "action-a",
        row.id,
        OpportunityActionPrepare(),
        request(),
        actor=records["staff"],
        db=db,
    )["action"]
    stored = db.get(OpportunityAction, first["id"])
    assert stored is not None
    stored.expires_at = NOW - timedelta(seconds=1)
    db.commit()
    assert expire_drafts(db, business_id=records["a"].id, now=NOW) == 1
    db.commit()

    recovered = prepare_opportunity_action(
        "action-a",
        row.id,
        OpportunityActionPrepare(),
        request(),
        actor=records["staff"],
        db=db,
    )

    assert recovered["created"] is True
    assert recovered["action"]["id"] != first["id"]
    assert recovered["action"]["booking_url"] != first["booking_url"]
    assert recovered["action"]["final_text"] != first["final_text"]
    assert stored.status == "cancelled"
    assert stored.failure_reason == "draft_expired"


def test_failed_pre_provider_delivery_can_be_retried_without_new_message_or_outbox(
    db: Session,
    records: dict[str, object],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    conversation = records["conversation_a"]
    assert isinstance(conversation, Conversation)
    row = opportunity(db, records, conversation=conversation)
    integration = BusinessChannelIntegration(
        business_id=records["a"].id,
        channel="whatsapp",
        provider="whatsapp",
        external_account_id="phone-id-recovery",
        integration_status="connected",
    )
    message = ConversationMessage(
        conversation_id=conversation.id,
        direction="outbound",
        sender_type="business",
        body="Seguimiento recuperable",
        delivery_status="blocked",
    )
    db.add_all((integration, message))
    db.flush()
    action = OpportunityAction(
        business_id=records["a"].id,
        opportunity_id=row.id,
        customer_id=records["customer_a"].id,
        action_type="contact_customer",
        status="failed",
        channel="whatsapp",
        conversation_id=conversation.id,
        message_id=message.id,
        failed_at=NOW,
        failure_reason="integration_not_configured",
    )
    outbox = ChannelOutboxMessage(
        business_id=records["a"].id,
        integration_id=integration.id,
        conversation_id=conversation.id,
        conversation_message_id=message.id,
        channel="whatsapp",
        provider="whatsapp",
        recipient_external_id="34600000001",
        payload_json='{"text":"Seguimiento recuperable"}',
        idempotency_key=f"whatsapp:outbound-message:{message.id}",
        status="blocked",
        max_attempts=3,
        available_at=NOW.replace(tzinfo=None),
    )
    db.add_all((action, outbox))
    db.commit()
    monkeypatch.setattr(
        "app.routers.growth_actions.conversation_delivery_capabilities",
        available_capabilities,
    )

    recovered = send_opportunity_action(
        "action-a", action.id, request(), actor=records["admin"], db=db
    )
    repeated = send_opportunity_action(
        "action-a", action.id, request(), actor=records["admin"], db=db
    )

    assert recovered["action"]["status"] == "approved"
    assert repeated["idempotent"] is True
    assert outbox.status == "pending"
    assert message.delivery_status == "queued"
    assert db.query(ConversationMessage).count() == 1
    assert db.query(ChannelOutboxMessage).count() == 1


def test_sent_action_is_terminal_for_automatic_preparation(
    db: Session,
    records: dict[str, object],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    conversation = records["conversation_a"]
    assert isinstance(conversation, Conversation)
    row = opportunity(db, records, conversation=conversation)
    monkeypatch.setattr(
        "app.services.opportunity_action_service.conversation_delivery_capabilities",
        available_capabilities,
    )
    action, created = OpportunityActionService(db, now=NOW).prepare(
        business=records["a"],
        opportunity=row,
        actor_user_id=records["admin"].id,
    )
    assert created is True
    action.status = "sent"
    action.sent_at = NOW
    db.commit()

    reused, created = OpportunityActionService(db, now=NOW + timedelta(days=21)).prepare(
        business=records["a"],
        opportunity=row,
        actor_user_id=records["admin"].id,
    )

    assert created is False
    assert reused.id == action.id
    assert reused.status == "sent"
    assert db.query(OpportunityAction).count() == 1


def test_multiple_attempts_count_without_duplicate_attribution_or_revenue(
    db: Session,
    records: dict[str, object],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    current = datetime.now(timezone.utc).replace(microsecond=0)
    conversation = records["conversation_a"]
    assert isinstance(conversation, Conversation)
    row = opportunity(db, records, conversation=conversation)
    monkeypatch.setattr(
        "app.services.opportunity_action_service.conversation_delivery_capabilities",
        available_capabilities,
    )
    service = OpportunityActionService(db, now=current)
    cancelled, _ = service.prepare(
        business=records["a"],
        opportunity=row,
        actor_user_id=records["admin"].id,
    )
    cancelled.status = "cancelled"
    cancelled.cancelled_at = current
    db.flush()
    sent, created = OpportunityActionService(db, now=current + timedelta(minutes=1)).prepare(
        business=records["a"],
        opportunity=row,
        actor_user_id=records["admin"].id,
    )
    assert created is True
    sent.status = "sent"
    sent.sent_at = current + timedelta(minutes=2)
    db.commit()
    attributed_booking = booking(
        db,
        records,
        created_at=current + timedelta(hours=1),
        status="completed",
    )

    attribution = attribute_new_booking(
        db,
        booking=attributed_booking,
        now=current + timedelta(hours=1),
    )
    db.commit()
    metrics = growth_metrics(
        db,
        business=records["a"],
        period="30d",
        now=current + timedelta(hours=2),
    )

    assert attribution is not None
    assert attribution.action_id == sent.id
    assert db.query(BookingAttribution).count() == 1
    assert metrics["summary"]["actions_prepared"] == 2
    assert metrics["summary"]["messages_sent"] == 1
    assert metrics["summary"]["bookings_attributed"] == 1
    assert metrics["summary"]["attributed_revenue"] == "45.00"


def test_booking_before_send_invalidates_draft_and_queued_action(
    db: Session,
    records: dict[str, object],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    conversation = records["conversation_a"]
    assert isinstance(conversation, Conversation)
    row = opportunity(db, records, conversation=conversation)
    monkeypatch.setattr(
        "app.services.opportunity_action_service.conversation_delivery_capabilities",
        available_capabilities,
    )
    action = OpportunityActionService(db, now=NOW).prepare(
        business=records["a"],
        opportunity=row,
        actor_user_id=records["staff"].id,
    )[0]
    db.commit()
    new_booking = booking(db, records, created_at=NOW + timedelta(hours=1))
    row.status = "resolved"
    row.resolved_at = NOW + timedelta(hours=1)
    invalidate_actions_for_resolved_opportunity(db, opportunity=row)
    db.commit()
    assert action.status == "cancelled"
    assert action.message_id is None
    assert new_booking.customer_id == row.customer_id


def test_post_action_attribution_is_conservative_and_ambiguity_is_not_attributed(
    db: Session, records: dict[str, object]
) -> None:
    first_opportunity = opportunity(db, records)
    first_action = OpportunityAction(
        business_id=records["a"].id,
        opportunity_id=first_opportunity.id,
        customer_id=records["customer_a"].id,
        action_type="contact_customer",
        status="sent",
        sent_at=NOW - timedelta(days=2),
        created_by_user_id=records["admin"].id,
        created_at=NOW - timedelta(days=3),
    )
    db.add(first_action)
    db.commit()
    later = booking(db, records, created_at=NOW)
    attributed = attribute_new_booking(db, booking=later, now=NOW)
    db.commit()
    assert attributed is not None
    assert attributed.method == "post_action_window"
    assert first_opportunity.status == "resolved"
    assert first_action.status == "completed"

    prior_opportunity = opportunity(
        db, records, opportunity_type="cancelled_not_rebooked"
    )
    prior_action = OpportunityAction(
        business_id=records["a"].id,
        opportunity_id=prior_opportunity.id,
        customer_id=records["customer_a"].id,
        action_type="contact_customer",
        status="sent",
        sent_at=NOW + timedelta(hours=1),
    )
    db.add(prior_action)
    db.commit()
    prior_booking = booking(db, records, created_at=NOW - timedelta(hours=1))
    assert attribute_new_booking(db, booking=prior_booking, now=NOW) is None

    other_customer_booking = booking(
        db, records, customer_key="other_customer_a", created_at=NOW
    )
    assert attribute_new_booking(db, booking=other_customer_booking, now=NOW) is None

    ambiguous_one = opportunity(
        db,
        records,
        opportunity_type="lead_not_converted",
        customer_key="other_customer_a",
    )
    ambiguous_two = opportunity(
        db,
        records,
        opportunity_type="scheduled_followup",
        customer_key="other_customer_a",
    )
    db.add_all(
        (
            OpportunityAction(
                business_id=records["a"].id,
                opportunity_id=ambiguous_one.id,
                customer_id=records["other_customer_a"].id,
                action_type="contact_customer",
                status="sent",
                sent_at=NOW - timedelta(days=1),
            ),
            OpportunityAction(
                business_id=records["a"].id,
                opportunity_id=ambiguous_two.id,
                customer_id=records["other_customer_a"].id,
                action_type="contact_customer",
                status="sent",
                sent_at=NOW - timedelta(hours=12),
            ),
        )
    )
    db.commit()
    ambiguous_booking = booking(
        db,
        records,
        customer_key="other_customer_a",
        created_at=NOW + timedelta(hours=1),
    )
    assert attribute_new_booking(db, booking=ambiguous_booking, now=NOW) is None


def test_direct_link_manual_attribution_tenant_guards_and_completion_metrics(
    db: Session, records: dict[str, object]
) -> None:
    row = opportunity(db, records)
    action = OpportunityAction(
        business_id=records["a"].id,
        opportunity_id=row.id,
        customer_id=records["customer_a"].id,
        action_type="contact_customer",
        status="sent",
        sent_at=NOW - timedelta(hours=2),
        created_at=NOW - timedelta(days=1),
    )
    db.add(action)
    db.commit()
    token = create_attribution_token(action)
    attributed_booking = booking(db, records, created_at=NOW)
    attribution = attribute_new_booking(
        db, booking=attributed_booking, attribution_token=token, now=NOW
    )
    db.commit()
    assert attribution is not None and attribution.method == "direct_link"
    assert attribution.price_amount_snapshot == Decimal("45.00")

    attributed_booking.status = "completed"
    sync_attributed_booking_status(db, booking=attributed_booking, now=NOW)
    db.commit()
    metrics = growth_metrics(db, business=records["a"], period="30d", now=NOW)
    assert metrics["summary"]["bookings_attributed"] == 1
    assert metrics["summary"]["attributed_bookings_completed"] == 1
    assert metrics["summary"]["attributed_revenue"] == "45.00"
    assert metrics["by_type"]["service_due"]["bookings_attributed"] == 1
    assert metrics["funnel"]["completed"] == 1

    attributed_booking.status = "cancelled"
    db.commit()
    metrics_after_cancel = growth_metrics(
        db, business=records["a"], period="30d", now=NOW
    )
    assert db.query(BookingAttribution).count() == 1
    assert metrics_after_cancel["summary"]["bookings_attributed"] == 1
    assert metrics_after_cancel["summary"]["attributed_bookings_completed"] == 0

    cross_booking = booking(
        db,
        records,
        customer_key="customer_b",
        business_key="b",
        created_at=NOW,
    )
    with pytest.raises(HTTPException) as hidden:
        manually_attribute_booking(
            "action-a",
            action.id,
            ManualBookingAttributionCreate(booking_id=cross_booking.id),
            request(),
            actor=records["admin"],
            db=db,
        )
    assert hidden.value.status_code == 404
    with pytest.raises(HTTPException):
        action_or_404(db, business_id=records["b"].id, action_id=action.id)


def test_manual_handled_action_and_draft_expiration_are_audited(
    db: Session, records: dict[str, object]
) -> None:
    handled_opportunity = opportunity(db, records)
    result = mark_opportunity_handled(
        "action-a",
        handled_opportunity.id,
        request(),
        actor=records["staff"],
        db=db,
    )
    assert result["action"]["action_type"] == "mark_handled"
    assert result["action"]["status"] == "completed"
    assert handled_opportunity.status == "actioned"
    assert db.query(AuditLog).filter(AuditLog.action == "opportunity_handled").count() == 1

    expiring_opportunity = opportunity(
        db, records, opportunity_type="lead_not_converted"
    )
    draft = OpportunityAction(
        business_id=records["a"].id,
        opportunity_id=expiring_opportunity.id,
        customer_id=records["customer_a"].id,
        action_type="contact_customer",
        status="draft",
        expires_at=NOW - timedelta(seconds=1),
    )
    db.add(draft)
    db.commit()
    assert expire_drafts(db, business_id=records["a"].id, now=NOW) == 1
    assert draft.status == "cancelled"
    assert draft.failure_reason == "draft_expired"


def test_outbox_claim_retry_and_success_update_the_same_action(
    db: Session, records: dict[str, object]
) -> None:
    conversation = records["conversation_a"]
    assert isinstance(conversation, Conversation)
    row = opportunity(db, records, conversation=conversation)
    integration = BusinessChannelIntegration(
        business_id=records["a"].id,
        channel="whatsapp",
        provider="whatsapp",
        external_account_id="phone-id",
        integration_status="connected",
    )
    message = ConversationMessage(
        conversation_id=conversation.id,
        direction="outbound",
        sender_type="business",
        body="Seguimiento",
        delivery_status="queued",
    )
    db.add_all((integration, message))
    db.flush()
    action = OpportunityAction(
        business_id=records["a"].id,
        opportunity_id=row.id,
        customer_id=records["customer_a"].id,
        action_type="contact_customer",
        status="approved",
        channel="whatsapp",
        conversation_id=conversation.id,
        message_id=message.id,
    )
    outbox = ChannelOutboxMessage(
        business_id=records["a"].id,
        integration_id=integration.id,
        conversation_id=conversation.id,
        conversation_message_id=message.id,
        channel="whatsapp",
        provider="whatsapp",
        recipient_external_id="34600000001",
        payload_json='{"text":"Seguimiento"}',
        idempotency_key=f"whatsapp:outbound-message:{message.id}",
        status="pending",
        max_attempts=3,
        available_at=NOW.replace(tzinfo=None),
    )
    db.add_all((action, outbox))
    db.commit()
    claimed = claim_outbox_jobs(
        db, worker_id="growth-worker", limit=1, lock_timeout_seconds=60, now=NOW.replace(tzinfo=None)
    )
    assert claimed == [outbox.id]
    assert action.status == "sending"
    fail_outbox_job(
        outbox,
        message,
        classification=classify_queue_error(http_status=429),
        now=NOW.replace(tzinfo=None),
    )
    assert outbox.status == "retry"
    assert action.status == "approved"
    outbox.status = "processing"
    finish_outbox_job(
        outbox,
        message,
        provider_message_id="provider-message-1",
        now=NOW.replace(tzinfo=None),
    )
    assert action.status == "sent"
    assert action.sent_at is not None
    assert message.provider_message_id == "provider-message-1"


def seed_action_concurrency_database(database_url: str) -> tuple[int, int, int]:
    engine = create_engine(
        database_url,
        connect_args={"check_same_thread": False, "timeout": 10},
    )
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    with factory() as db:
        business = Business(
            slug="action-race",
            name="Action Race",
            status="active",
            currency="EUR",
        )
        actor = User(email="action-race@test.local")
        db.add_all((business, actor))
        db.flush()
        customer = Customer(
            business_id=business.id,
            name="Concurrent Customer",
            phone="+34 600 000 099",
        )
        db.add(customer)
        db.flush()
        conversation = Conversation(
            business_id=business.id,
            customer_id=customer.id,
            channel="whatsapp",
            external_user_id="34600000099",
            customer_phone=customer.phone,
            status="pending",
            last_message_at=NOW,
        )
        db.add(conversation)
        db.flush()
        row = CustomerOpportunity(
            business_id=business.id,
            customer_id=customer.id,
            type="service_due",
            status="pending",
            priority="normal",
            detected_at=NOW,
            due_at=NOW,
            expires_at=NOW + timedelta(days=30),
            source_conversation_id=conversation.id,
            reason_code="concurrency",
            reason_text="Concurrent action recovery",
            dedupe_key="concurrency:service-due",
        )
        db.add(row)
        db.commit()
        result = business.id, row.id, actor.id
    engine.dispose()
    return result


def test_action_prepare_cancel_retry_and_resolution_are_concurrency_safe(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    database_url = f"sqlite:///{(tmp_path / 'action-race.db').as_posix()}"
    business_id, opportunity_id, actor_id = seed_action_concurrency_database(database_url)
    engine = create_engine(
        database_url,
        connect_args={"check_same_thread": False, "timeout": 10},
    )
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    monkeypatch.setattr(
        "app.services.opportunity_action_service.conversation_delivery_capabilities",
        available_capabilities,
    )

    prepare_barrier = Barrier(2)

    def prepare_once() -> dict:
        with factory() as db:
            actor = db.get(User, actor_id)
            prepare_barrier.wait()
            return prepare_opportunity_action(
                "action-race",
                opportunity_id,
                OpportunityActionPrepare(),
                request(),
                actor=actor,
                db=db,
            )

    with ThreadPoolExecutor(max_workers=2) as executor:
        prepared = list(executor.map(lambda _index: prepare_once(), range(2)))
    assert len({item["action"]["id"] for item in prepared}) == 1

    first_action_id = prepared[0]["action"]["id"]
    cancel_barrier = Barrier(2)

    def cancel_or_prepare(operation: str) -> None:
        with factory() as db:
            actor = db.get(User, actor_id)
            cancel_barrier.wait()
            if operation == "cancel":
                cancel_opportunity_action(
                    "action-race",
                    first_action_id,
                    request(),
                    actor=actor,
                    db=db,
                )
            else:
                prepare_opportunity_action(
                    "action-race",
                    opportunity_id,
                    OpportunityActionPrepare(),
                    request(),
                    actor=actor,
                    db=db,
                )

    with ThreadPoolExecutor(max_workers=2) as executor:
        list(executor.map(cancel_or_prepare, ("cancel", "prepare")))
    with factory() as db:
        active = (
            db.query(OpportunityAction)
            .filter(
                OpportunityAction.opportunity_id == opportunity_id,
                OpportunityAction.status.in_(("draft", "approved", "sending")),
            )
            .all()
        )
        assert len(active) <= 1
        if not active:
            actor = db.get(User, actor_id)
            recovered = prepare_opportunity_action(
                "action-race",
                opportunity_id,
                OpportunityActionPrepare(),
                request(),
                actor=actor,
                db=db,
            )["action"]
            action_id = recovered["id"]
        else:
            action_id = active[0].id

        action = db.get(OpportunityAction, action_id)
        conversation = action.conversation
        integration = BusinessChannelIntegration(
            business_id=business_id,
            channel="whatsapp",
            provider="whatsapp",
            external_account_id="race-phone-id",
            integration_status="connected",
        )
        message = ConversationMessage(
            conversation_id=conversation.id,
            direction="outbound",
            sender_type="business",
            body=action.final_text or "Concurrent retry",
            delivery_status="blocked",
        )
        db.add_all((integration, message))
        db.flush()
        action.status = "failed"
        action.message_id = message.id
        action.failed_at = NOW
        outbox = ChannelOutboxMessage(
            business_id=business_id,
            integration_id=integration.id,
            conversation_id=conversation.id,
            conversation_message_id=message.id,
            channel="whatsapp",
            provider="whatsapp",
            recipient_external_id="34600000099",
            payload_json=json.dumps({"text": message.body}),
            idempotency_key=f"whatsapp:outbound-message:{message.id}",
            status="blocked",
            max_attempts=3,
            available_at=NOW.replace(tzinfo=None),
        )
        db.add(outbox)
        db.commit()
        outbox_id = outbox.id

    retry_barrier = Barrier(2)

    def retry_once() -> dict:
        with factory() as db:
            actor = db.get(User, actor_id)
            retry_barrier.wait()
            return send_opportunity_action(
                "action-race", action_id, request(), actor=actor, db=db
            )

    with ThreadPoolExecutor(max_workers=2) as executor:
        retried = list(executor.map(lambda _index: retry_once(), range(2)))
    assert sum(bool(item.get("recovered")) for item in retried) == 1
    assert sum(bool(item.get("idempotent")) for item in retried) == 1
    with factory() as db:
        assert db.query(ConversationMessage).count() == 1
        assert db.query(ChannelOutboxMessage).count() == 1
        action = db.get(OpportunityAction, action_id)
        outbox = db.get(ChannelOutboxMessage, outbox_id)
        action.status = "failed"
        action.failure_reason = "integration_not_configured"
        action.message.delivery_status = "blocked"
        outbox.status = "blocked"
        db.commit()

    resolution_barrier = Barrier(2)

    def retry_or_resolve(operation: str) -> str:
        with factory() as db:
            actor = db.get(User, actor_id)
            resolution_barrier.wait()
            try:
                if operation == "retry":
                    send_opportunity_action(
                        "action-race", action_id, request(), actor=actor, db=db
                    )
                else:
                    transition_opportunity(
                        "action-race",
                        opportunity_id,
                        OpportunityStatusUpdate(status="actioned"),
                        request(),
                        actor,
                        db,
                    )
            except HTTPException:
                return "blocked"
            return "ok"

    with ThreadPoolExecutor(max_workers=2) as executor:
        list(executor.map(retry_or_resolve, ("retry", "resolve")))
    with factory() as db:
        assert db.get(CustomerOpportunity, opportunity_id).status == "actioned"
        assert db.get(OpportunityAction, action_id).status not in {"approved", "sending"}
        assert db.get(ChannelOutboxMessage, outbox_id).status not in {
            "pending",
            "processing",
            "retry",
        }
    engine.dispose()


def test_constraints_metrics_periods_and_frontend_contracts(
    db: Session, records: dict[str, object]
) -> None:
    row = opportunity(db, records)
    first = OpportunityAction(
        business_id=records["a"].id,
        opportunity_id=row.id,
        customer_id=records["customer_a"].id,
        action_type="contact_customer",
        status="draft",
    )
    db.add(first)
    db.commit()
    db.add(
        OpportunityAction(
            business_id=records["a"].id,
            opportunity_id=row.id,
            customer_id=records["customer_a"].id,
            action_type="contact_customer",
            status="draft",
        )
    )
    with pytest.raises(IntegrityError):
        db.flush()
    db.rollback()
    assert POST_ACTION_ATTRIBUTION_WINDOW == timedelta(days=14)
    custom = get_growth_metrics(
        "action-a",
        period="custom",
        date_from=NOW - timedelta(days=2),
        date_to=NOW + timedelta(days=1),
        db=db,
    )
    assert custom["period"] == "custom"
    with pytest.raises(HTTPException):
        get_growth_metrics(
            "action-a", period="custom", date_from=None, date_to=None, db=db
        )

    root = Path(__file__).resolve().parents[2]
    html = (root / "autonogrow-admin" / "index.html").read_text(encoding="utf-8")
    js = (root / "autonogrow-admin" / "admin.js").read_text(encoding="utf-8")
    landing = (root / "autonogrow-landing" / "script.js").read_text(encoding="utf-8")
    assert html.count('id="growth-action-modal"') == 1
    assert "Nada se enviará hasta que pulses Enviar" in html
    assert "Ingresos registrados en reservas vinculadas" in html
    assert "/actions/prepare" in js
    assert "/growth-metrics?period=30d" in js
    assert "Todavía no se muestra como enviado" in js
    assert "attribution_token" in landing
    assert "getOpportunityAttributionToken" in landing


def test_action_attempt_migration_preserves_history_and_limits_active_attempts(
    tmp_path: Path,
) -> None:
    database_url = f"sqlite:///{(tmp_path / 'action-attempt-migration.db').as_posix()}"
    config = alembic_config()
    config.attributes["database_url"] = database_url
    command.upgrade(config, "20260903_32")
    engine = create_engine(database_url)
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    with factory() as db:
        business = Business(slug="legacy-actions", name="Legacy Actions", status="active")
        customer = Customer(
            business=business,
            name="Legacy Customer",
            phone="+34 600 000 088",
        )
        db.add_all((business, customer))
        db.flush()
        legacy_opportunity = CustomerOpportunity(
            business_id=business.id,
            customer_id=customer.id,
            type="service_due",
            status="pending",
            priority="normal",
            detected_at=NOW,
            due_at=NOW,
            expires_at=NOW + timedelta(days=30),
            reason_code="legacy_action",
            reason_text="Legacy action history",
            dedupe_key="legacy:action",
        )
        db.add(legacy_opportunity)
        db.flush()
        legacy_action = OpportunityAction(
            business_id=business.id,
            opportunity_id=legacy_opportunity.id,
            customer_id=customer.id,
            action_type="contact_customer",
            status="cancelled",
            cancelled_at=NOW,
        )
        db.add(legacy_action)
        db.commit()
        business_id = business.id
        customer_id = customer.id
        opportunity_id = legacy_opportunity.id
        legacy_action_id = legacy_action.id
    engine.dispose()

    command.upgrade(config, "head")
    engine = create_engine(database_url)
    index_names = {item["name"] for item in inspect(engine).get_indexes("opportunity_actions")}
    unique_names = {
        item["name"] for item in inspect(engine).get_unique_constraints("opportunity_actions")
    }
    assert "uq_opportunity_action_active_contact" in index_names
    assert "uq_opportunity_action_singleton_non_contact" in index_names
    assert "uq_opportunity_action_conservative_dedupe" not in unique_names
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    with factory() as db:
        assert db.get(OpportunityAction, legacy_action_id).status == "cancelled"
        first_active = OpportunityAction(
            business_id=business_id,
            opportunity_id=opportunity_id,
            customer_id=customer_id,
            action_type="contact_customer",
            status="draft",
        )
        db.add(first_active)
        db.commit()
        db.add(
            OpportunityAction(
                business_id=business_id,
                opportunity_id=opportunity_id,
                customer_id=customer_id,
                action_type="contact_customer",
                status="draft",
            )
        )
        with pytest.raises(IntegrityError):
            db.flush()
        db.rollback()
        first_active = db.get(OpportunityAction, first_active.id)
        first_active.status = "sent"
        first_active.sent_at = NOW
        db.add(
            OpportunityAction(
                business_id=business_id,
                opportunity_id=opportunity_id,
                customer_id=customer_id,
                action_type="contact_customer",
                status="draft",
            )
        )
        db.commit()
        assert db.query(OpportunityAction).count() == 3
    engine.dispose()

    clean_url = f"sqlite:///{(tmp_path / 'action-attempt-clean-downgrade.db').as_posix()}"
    clean_config = alembic_config()
    clean_config.attributes["database_url"] = clean_url
    command.upgrade(clean_config, "head")
    command.downgrade(clean_config, "20260903_32")
    clean_engine = create_engine(clean_url)
    clean_unique_names = {
        item["name"]
        for item in inspect(clean_engine).get_unique_constraints("opportunity_actions")
    }
    assert "uq_opportunity_action_conservative_dedupe" in clean_unique_names
    clean_engine.dispose()
