from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from fastapi import HTTPException
from sqlalchemy import create_engine
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, sessionmaker
from starlette.requests import Request

from app.core.database import Base
from app.core.security import require_business_access, require_business_admin
from app.models import (
    Booking,
    Business,
    BusinessService,
    BusinessUser,
    Conversation,
    Customer,
    CustomerOpportunity,
    ScheduledCustomerFollowUp,
    User,
)
from app.routers.admin import admin_update_service
from app.routers.growth_opportunities import (
    cancel_scheduled_followup,
    create_scheduled_followup,
    get_opportunity,
    list_opportunities,
    transition_opportunity,
)
from app.schemas.customer_opportunity import OpportunityStatusUpdate, ScheduledFollowUpCreate
from app.schemas.service import AdminServiceUpdate
from app.services.growth_opportunity_service import (
    GrowthOpportunityService,
    snapshot_booking_follow_up,
)

NOW = datetime(2026, 8, 14, 10, 0, tzinfo=timezone.utc)


@pytest.fixture
def db() -> Session:
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine)()
    yield session
    session.close()
    engine.dispose()


@pytest.fixture
def records(db: Session) -> dict:
    first = Business(slug="growth-a", name="Growth A", status="active")
    second = Business(slug="growth-b", name="Growth B", status="active")
    owner = User(email="growth-owner@test.local", is_owner=True)
    admin_user = User(email="growth-admin@test.local")
    staff_user = User(email="growth-staff@test.local")
    other_user = User(email="growth-other@test.local")
    db.add_all((first, second, owner, admin_user, staff_user, other_user))
    db.flush()
    db.add_all(
        (
            BusinessUser(
                business_id=first.id,
                user_id=admin_user.id,
                role="business_admin",
                active=True,
            ),
            BusinessUser(
                business_id=first.id,
                user_id=staff_user.id,
                role="business_staff",
                active=True,
            ),
            BusinessUser(
                business_id=second.id,
                user_id=other_user.id,
                role="business_admin",
                active=True,
            ),
        )
    )
    customer_a = Customer(business_id=first.id, name="Ana", phone="+34600000001")
    customer_b = Customer(business_id=second.id, name="Bea", phone="+34600000001")
    service_a = BusinessService(
        business_id=first.id,
        name="Corte",
        duration_minutes=30,
        follow_up_enabled=True,
        follow_up_interval_days=30,
        follow_up_window_days=7,
    )
    service_b = BusinessService(
        business_id=second.id,
        name="Aceite",
        duration_minutes=60,
        follow_up_enabled=False,
    )
    db.add_all((customer_a, customer_b, service_a, service_b))
    db.commit()
    return {
        "a": first,
        "b": second,
        "owner": owner,
        "admin_user": admin_user,
        "staff_user": staff_user,
        "other_user": other_user,
        "customer_a": customer_a,
        "customer_b": customer_b,
        "service_a": service_a,
        "service_b": service_b,
    }


def booking(
    db: Session,
    *,
    business: Business,
    customer: Customer,
    service: BusinessService,
    status: str,
    days_ago: int,
    snapshot: bool | None = None,
) -> Booking:
    ended = (NOW - timedelta(days=days_ago)).replace(tzinfo=None)
    row = Booking(
        business_id=business.id,
        customer_id=customer.id,
        service_id=service.id,
        service_name=service.name,
        duration_minutes=service.duration_minutes,
        start_datetime=ended - timedelta(minutes=service.duration_minutes or 30),
        end_datetime=ended,
        preferred_date=ended.date().isoformat(),
        preferred_time=ended.strftime("%H:%M"),
        status=status,
        updated_at=ended,
        follow_up_enabled_snapshot=(
            service.follow_up_enabled if snapshot is None else snapshot
        ),
        follow_up_interval_days_snapshot=(
            service.follow_up_interval_days
            if (service.follow_up_enabled if snapshot is None else snapshot)
            else None
        ),
        follow_up_window_days_snapshot=(
            service.follow_up_window_days
            if (service.follow_up_enabled if snapshot is None else snapshot)
            else None
        ),
    )
    db.add(row)
    db.commit()
    return row


def request(path: str = "/api/admin/businesses/growth-a/opportunities") -> Request:
    return Request(
        {
            "type": "http",
            "method": "POST",
            "path": path,
            "headers": [],
            "client": ("testclient", 50000),
        }
    )


def test_service_due_respects_snapshot_timing_repeat_and_tenant_isolation(
    db: Session, records: dict
) -> None:
    source = booking(
        db,
        business=records["a"],
        customer=records["customer_a"],
        service=records["service_a"],
        status="completed",
        days_ago=25,
    )
    not_recurrent = booking(
        db,
        business=records["b"],
        customer=records["customer_b"],
        service=records["service_b"],
        status="completed",
        days_ago=400,
    )
    GrowthOpportunityService(db, now=NOW).evaluate_business(records["a"].id)
    db.commit()
    opportunity = db.query(CustomerOpportunity).one()
    assert opportunity.type == "service_due"
    assert opportunity.source_booking_id == source.id
    assert opportunity.follow_up_interval_days_snapshot == 30
    assert opportunity.business_id == records["a"].id

    records["service_a"].follow_up_interval_days = 60
    db.commit()
    GrowthOpportunityService(db, now=NOW).evaluate_business(records["a"].id)
    db.commit()
    assert db.query(CustomerOpportunity).count() == 1
    assert opportunity.follow_up_interval_days_snapshot == 30

    GrowthOpportunityService(db, now=NOW).evaluate_business(records["b"].id)
    db.commit()
    assert not_recurrent.follow_up_enabled_snapshot is False
    assert db.query(CustomerOpportunity).count() == 1

    repeat = booking(
        db,
        business=records["a"],
        customer=records["customer_a"],
        service=records["service_a"],
        status="confirmed",
        days_ago=-2,
    )
    GrowthOpportunityService(db, now=NOW).resolve_for_rebooking(repeat)
    db.commit()
    assert opportunity.status == "resolved"


def test_service_due_not_generated_before_window(db: Session, records: dict) -> None:
    booking(
        db,
        business=records["a"],
        customer=records["customer_a"],
        service=records["service_a"],
        status="completed",
        days_ago=22,
    )
    GrowthOpportunityService(db, now=NOW).evaluate_business(records["a"].id)
    assert db.query(CustomerOpportunity).count() == 0


@pytest.mark.parametrize(
    ("status", "expected_type"),
    (("cancelled", "cancelled_not_rebooked"), ("no_show", "no_show_not_rebooked")),
)
def test_cancel_and_no_show_are_idempotent_and_resolve_on_rebooking(
    db: Session, records: dict, status: str, expected_type: str
) -> None:
    source = booking(
        db,
        business=records["a"],
        customer=records["customer_a"],
        service=records["service_a"],
        status=status,
        days_ago=5,
        snapshot=False,
    )
    for _ in range(2):
        GrowthOpportunityService(db, now=NOW).evaluate_business(records["a"].id)
        db.commit()
    row = db.query(CustomerOpportunity).one()
    assert row.type == expected_type
    assert row.source_booking_id == source.id
    assert db.query(CustomerOpportunity).count() == 1

    later = booking(
        db,
        business=records["a"],
        customer=records["customer_a"],
        service=records["service_a"],
        status="requested",
        days_ago=-1,
        snapshot=False,
    )
    GrowthOpportunityService(db, now=NOW).resolve_for_rebooking(later)
    db.commit()
    assert row.status == "resolved"


def test_dismissed_and_expired_events_do_not_reappear(db: Session, records: dict) -> None:
    booking(
        db,
        business=records["a"],
        customer=records["customer_a"],
        service=records["service_a"],
        status="cancelled",
        days_ago=5,
        snapshot=False,
    )
    GrowthOpportunityService(db, now=NOW).evaluate_business(records["a"].id)
    row = db.query(CustomerOpportunity).one()
    transition_opportunity(
        "growth-a",
        row.id,
        OpportunityStatusUpdate(status="dismissed"),
        request(),
        records["owner"],
        db,
    )
    GrowthOpportunityService(db, now=NOW + timedelta(days=2)).evaluate_business(records["a"].id)
    db.commit()
    assert db.query(CustomerOpportunity).count() == 1
    assert row.status == "dismissed"

    old = booking(
        db,
        business=records["a"],
        customer=records["customer_a"],
        service=records["service_a"],
        status="no_show",
        days_ago=60,
        snapshot=False,
    )
    GrowthOpportunityService(db, now=NOW).evaluate_business(records["a"].id)
    db.commit()
    expired = db.query(CustomerOpportunity).filter_by(source_booking_id=old.id).one()
    assert expired.status == "expired"
    GrowthOpportunityService(db, now=NOW + timedelta(days=1)).evaluate_business(records["a"].id)
    assert db.query(CustomerOpportunity).filter_by(source_booking_id=old.id).count() == 1


def test_lead_detection_is_conservative_and_conversation_scoped(
    db: Session, records: dict
) -> None:
    commercial = Conversation(
        business_id=records["a"].id,
        channel="whatsapp",
        external_user_id="lead-1",
        customer_phone=records["customer_a"].phone,
        status="pending",
        detected_intent="booking_intent",
        intent_confidence=92,
        last_inbound_at=(NOW - timedelta(hours=50)).replace(tzinfo=None),
    )
    noncommercial = Conversation(
        business_id=records["a"].id,
        channel="whatsapp",
        external_user_id="lead-2",
        customer_phone=records["customer_a"].phone,
        status="pending",
        detected_intent="welcome_intent",
        intent_confidence=99,
        last_inbound_at=(NOW - timedelta(hours=80)).replace(tzinfo=None),
    )
    closed = Conversation(
        business_id=records["a"].id,
        channel="manual",
        external_user_id="lead-3",
        customer_phone=records["customer_a"].phone,
        status="closed",
        detected_intent="price_intent",
        intent_confidence=90,
        last_inbound_at=(NOW - timedelta(hours=80)).replace(tzinfo=None),
    )
    db.add_all((commercial, noncommercial, closed))
    db.commit()
    GrowthOpportunityService(db, now=NOW).evaluate_business(records["a"].id)
    GrowthOpportunityService(db, now=NOW).evaluate_business(records["a"].id)
    db.commit()
    rows = db.query(CustomerOpportunity).all()
    assert len(rows) == 1
    assert rows[0].source_conversation_id == commercial.id

    booking(
        db,
        business=records["a"],
        customer=records["customer_a"],
        service=records["service_a"],
        status="confirmed",
        days_ago=-1,
        snapshot=False,
    )
    GrowthOpportunityService(db, now=NOW).evaluate_business(records["a"].id)
    assert rows[0].status == "resolved"


def test_manual_followup_create_due_cancel_resolve_and_cross_ids(
    db: Session, records: dict
) -> None:
    current = datetime.now(timezone.utc)
    payload = ScheduledFollowUpCreate(
        customer_id=records["customer_a"].id,
        service_id=records["service_a"].id,
        due_at=current - timedelta(minutes=1),
        note="Revisar con Ana.",
    )
    created = create_scheduled_followup(
        "growth-a", payload, request(), records["owner"], db
    )
    reused = create_scheduled_followup(
        "growth-a", payload, request(), records["owner"], db
    )
    assert created["created"] is True
    assert reused["created"] is False
    row = db.query(ScheduledCustomerFollowUp).one()
    opportunity = db.query(CustomerOpportunity).one()
    assert opportunity.type == "scheduled_followup"

    cancelled = cancel_scheduled_followup(
        "growth-a", row.id, request(), records["owner"], db
    )
    assert cancelled["followup"]["status"] == "cancelled"
    assert opportunity.status == "dismissed"

    second = create_scheduled_followup(
        "growth-a",
        ScheduledFollowUpCreate(
            customer_id=records["customer_a"].id,
            service_id=records["service_a"].id,
            due_at=current - timedelta(minutes=2),
        ),
        request(),
        records["owner"],
        db,
    )
    second_opportunity = (
        db.query(CustomerOpportunity)
        .filter_by(scheduled_followup_id=second["followup"]["id"])
        .one()
    )
    later = booking(
        db,
        business=records["a"],
        customer=records["customer_a"],
        service=records["service_a"],
        status="confirmed",
        days_ago=-1,
        snapshot=False,
    )
    GrowthOpportunityService(db, now=current).resolve_for_rebooking(later)
    db.commit()
    assert second_opportunity.status == "resolved"
    assert second_opportunity.scheduled_followup.status == "converted"

    with pytest.raises(HTTPException) as crossed:
        create_scheduled_followup(
            "growth-a",
            ScheduledFollowUpCreate(
                customer_id=records["customer_b"].id,
                due_at=NOW + timedelta(days=1),
            ),
            request(),
            records["owner"],
            db,
        )
    assert crossed.value.status_code == 404


def test_state_machine_and_tenant_scoped_api(db: Session, records: dict) -> None:
    booking(
        db,
        business=records["a"],
        customer=records["customer_a"],
        service=records["service_a"],
        status="cancelled",
        days_ago=5,
        snapshot=False,
    )
    GrowthOpportunityService(db, now=NOW).evaluate_business(records["a"].id)
    db.commit()
    row = db.query(CustomerOpportunity).one()
    listed = list_opportunities("growth-a", "pending", None, None, None, None, 100, db)
    assert listed["pending_count"] == 1
    assert listed["opportunities"][0]["reason_text"]
    with pytest.raises(HTTPException) as hidden:
        get_opportunity("growth-b", row.id, db)
    assert hidden.value.status_code == 404
    with pytest.raises(HTTPException) as hidden_mutation:
        transition_opportunity(
            "growth-b",
            row.id,
            OpportunityStatusUpdate(status="dismissed"),
            request(),
            records["owner"],
            db,
        )
    assert hidden_mutation.value.status_code == 404

    assert require_business_access("growth-a", records["staff_user"], db) is records["staff_user"]
    assert require_business_access("growth-a", records["admin_user"], db) is records["admin_user"]
    with pytest.raises(HTTPException) as denied:
        require_business_access("growth-a", records["other_user"], db)
    assert denied.value.status_code == 403
    with pytest.raises(HTTPException) as staff_settings:
        require_business_admin("growth-a", records["staff_user"], db)
    assert staff_settings.value.status_code == 403

    transition_opportunity(
        "growth-a",
        row.id,
        OpportunityStatusUpdate(status="actioned"),
        request(),
        records["owner"],
        db,
    )
    assert row.actioned_at is not None
    with pytest.raises(HTTPException) as invalid:
        transition_opportunity(
            "growth-a",
            row.id,
            OpportunityStatusUpdate(status="actioned"),
            request(),
            records["owner"],
            db,
        )
    assert invalid.value.status_code == 409


def test_database_dedupe_constraint_is_final_guard(db: Session, records: dict) -> None:
    values = {
        "business_id": records["a"].id,
        "customer_id": records["customer_a"].id,
        "type": "lead_not_converted",
        "status": "pending",
        "priority": "normal",
        "detected_at": NOW,
        "due_at": NOW,
        "reason_code": "test",
        "reason_text": "Deterministic reason",
        "dedupe_key": "same-event",
    }
    db.add(CustomerOpportunity(**values))
    db.commit()
    db.add(CustomerOpportunity(**values))
    with pytest.raises(IntegrityError):
        db.commit()


def test_service_configuration_validates_tenant_and_snapshot_is_immutable(
    db: Session, records: dict
) -> None:
    with pytest.raises(HTTPException) as missing_interval:
        admin_update_service(
            "growth-b",
            records["service_b"].id,
            AdminServiceUpdate(follow_up_enabled=True),
            db,
        )
    assert missing_interval.value.status_code == 422

    updated = admin_update_service(
        "growth-b",
        records["service_b"].id,
        AdminServiceUpdate(
            follow_up_enabled=True,
            follow_up_interval_days=365,
            follow_up_window_days=14,
        ),
        db,
    )
    assert updated["service"]["follow_up_interval_days"] == 365
    with pytest.raises(HTTPException) as cross_tenant:
        admin_update_service(
            "growth-a",
            records["service_b"].id,
            AdminServiceUpdate(follow_up_window_days=7),
            db,
        )
    assert cross_tenant.value.status_code == 404

    source = booking(
        db,
        business=records["b"],
        customer=records["customer_b"],
        service=records["service_b"],
        status="confirmed",
        days_ago=1,
        snapshot=False,
    )
    snapshot_booking_follow_up(source, records["service_b"])
    assert source.follow_up_interval_days_snapshot == 365
    records["service_b"].follow_up_interval_days = 180
    snapshot_booking_follow_up(source, records["service_b"])
    assert source.follow_up_interval_days_snapshot == 365


def test_admin_ui_exposes_real_opportunities_and_plain_followup_controls() -> None:
    root = Path(__file__).resolve().parents[2]
    html = (root / "autonogrow-admin" / "index.html").read_text(encoding="utf-8")
    js = (root / "autonogrow-admin" / "admin.js").read_text(encoding="utf-8")
    for element_id in (
        "new-service-follow-up-enabled",
        "new-service-follow-up-interval",
        "new-service-follow-up-window",
        "growth-tasks-list",
    ):
        assert html.count(f'id="{element_id}"') == 1
    assert "/opportunities?status=pending" in js
    assert 'data-opportunity-action="dismissed"' in js
    assert 'data-opportunity-action="actioned"' in js
    assert "item.reason_text" in js
    assert "envía mensajes automáticamente" in html
