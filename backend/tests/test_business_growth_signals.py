from __future__ import annotations

import json
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
    AvailabilityException,
    AvailabilitySettings,
    Booking,
    Business,
    BusinessCalendarEvent,
    BusinessGrowthSignal,
    BusinessService,
    BusinessUser,
    Customer,
    CustomerOpportunity,
    User,
)
from app.routers.growth_signals import (
    create_calendar_event,
    delete_calendar_event,
    dismiss_growth_signal,
    get_growth_signal,
    growth_signals_summary,
    list_calendar_events,
    list_growth_signals,
    update_calendar_event,
)
from app.schemas.business_growth_signal import (
    BusinessCalendarEventCreate,
    BusinessCalendarEventUpdate,
)
from app.services.business_growth_signal_service import (
    BusinessGrowthSignalService,
    serialize_growth_signal,
)

NOW = datetime(2026, 8, 14, 12, 0, tzinfo=timezone.utc)


@pytest.fixture
def db() -> Session:
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine)()
    yield session
    session.close()
    engine.dispose()


def request(method: str = "POST") -> Request:
    return Request(
        {
            "type": "http",
            "method": method,
            "path": "/api/admin/businesses/signals-a/growth-signals",
            "headers": [],
            "client": ("testclient", 50000),
        }
    )


@pytest.fixture
def records(db: Session) -> dict[str, object]:
    a = Business(
        slug="signals-a", name="Signals A", status="active", timezone="UTC"
    )
    b = Business(
        slug="signals-b", name="Signals B", status="active", timezone="UTC"
    )
    admin = User(email="signals-admin@test.local")
    staff = User(email="signals-staff@test.local")
    other = User(email="signals-other@test.local")
    db.add_all((a, b, admin, staff, other))
    db.flush()
    admin_membership = BusinessUser(
        business_id=a.id,
        user_id=admin.id,
        role="business_admin",
        active=True,
        bookable=True,
        show_schedule=True,
        public_name="Profesional A",
    )
    staff_membership = BusinessUser(
        business_id=a.id,
        user_id=staff.id,
        role="business_staff",
        active=True,
    )
    other_membership = BusinessUser(
        business_id=b.id,
        user_id=other.id,
        role="business_admin",
        active=True,
        bookable=True,
        show_schedule=True,
    )
    db.add_all((admin_membership, staff_membership, other_membership))
    service = BusinessService(
        business_id=a.id,
        name="Color",
        duration_minutes=60,
        active=True,
        bookable=True,
        follow_up_enabled=True,
        follow_up_interval_days=10,
        follow_up_window_days=0,
        created_at=(NOW - timedelta(days=300)).replace(tzinfo=None),
    )
    second_service = BusinessService(
        business_id=a.id,
        name="Manicura",
        duration_minutes=45,
        active=True,
        bookable=True,
        created_at=(NOW - timedelta(days=300)).replace(tzinfo=None),
    )
    other_service = BusinessService(
        business_id=b.id,
        name="Aceite",
        duration_minutes=60,
        active=True,
        bookable=True,
        created_at=(NOW - timedelta(days=300)).replace(tzinfo=None),
    )
    db.add_all((service, second_service, other_service))
    db.flush()
    admin_membership.services.extend((service, second_service))
    other_membership.services.append(other_service)
    schedule = json.dumps(
        {str(day): [{"start": "09:00", "end": "17:00"}] for day in range(7)}
    )
    db.add_all(
        (
            AvailabilitySettings(
                business_id=a.id,
                timezone="UTC",
                weekly_schedule_json=schedule,
                slot_interval_minutes=15,
                buffer_between_bookings_minutes=0,
                min_notice_minutes=0,
                max_days_ahead=365,
            ),
            AvailabilitySettings(
                business_id=b.id,
                timezone="UTC",
                weekly_schedule_json=schedule,
                slot_interval_minutes=15,
                buffer_between_bookings_minutes=0,
                min_notice_minutes=0,
                max_days_ahead=365,
            ),
        )
    )
    db.commit()
    return {
        "a": a,
        "b": b,
        "admin": admin,
        "staff": staff,
        "other": other,
        "admin_membership": admin_membership,
        "other_membership": other_membership,
        "service": service,
        "second_service": second_service,
        "other_service": other_service,
    }


def customer(db: Session, business: Business, index: int) -> Customer:
    row = Customer(
        business_id=business.id,
        name=f"Cliente {business.id}-{index}",
        phone=f"+34600{business.id:03d}{index:03d}",
    )
    db.add(row)
    db.flush()
    return row


def booking(
    db: Session,
    *,
    business: Business,
    service: BusinessService,
    customer_row: Customer,
    start: datetime,
    duration_minutes: int = 60,
    status: str = "completed",
    staff_id: int | None = None,
    created_at: datetime | None = None,
    recurring: bool = False,
) -> Booking:
    row = Booking(
        business_id=business.id,
        customer_id=customer_row.id,
        service_id=service.id,
        staff_business_user_id=staff_id,
        service_name=service.name,
        duration_minutes=duration_minutes,
        start_datetime=start.replace(tzinfo=None),
        end_datetime=(start + timedelta(minutes=duration_minutes)).replace(tzinfo=None),
        preferred_date=start.date().isoformat(),
        preferred_time=start.strftime("%H:%M"),
        status=status,
        created_at=(created_at or start).replace(tzinfo=None),
        updated_at=(start + timedelta(minutes=duration_minutes)).replace(tzinfo=None),
        follow_up_enabled_snapshot=recurring,
        follow_up_interval_days_snapshot=10 if recurring else None,
        follow_up_window_days_snapshot=0 if recurring else None,
    )
    db.add(row)
    db.flush()
    return row


def signals(db: Session, signal_type: str) -> list[BusinessGrowthSignal]:
    return (
        db.query(BusinessGrowthSignal)
        .filter(BusinessGrowthSignal.type == signal_type)
        .order_by(BusinessGrowthSignal.id)
        .all()
    )


def test_low_future_occupancy_uses_staffed_capacity_and_lifecycle(
    db: Session, records: dict[str, object]
) -> None:
    business = records["a"]
    service = records["service"]
    staff = records["admin_membership"]
    assert isinstance(business, Business)
    assert isinstance(service, BusinessService)
    assert isinstance(staff, BusinessUser)
    future_start = NOW.date() + timedelta(days=1)
    for week in range(1, 7):
        week_start = future_start - timedelta(weeks=week)
        for day_offset in range(4):
            day = week_start + timedelta(days=day_offset)
            booking(
                db,
                business=business,
                service=service,
                customer_row=customer(db, business, week * 10 + day_offset),
                start=datetime.combine(day, datetime.min.time(), tzinfo=timezone.utc)
                + timedelta(hours=9),
                duration_minutes=480,
                staff_id=staff.id,
            )
    cancelled = booking(
        db,
        business=business,
        service=service,
        customer_row=customer(db, business, 99),
        start=datetime.combine(future_start, datetime.min.time(), tzinfo=timezone.utc)
        + timedelta(hours=9),
        duration_minutes=480,
        status="cancelled",
        staff_id=staff.id,
    )
    db.add(
        AvailabilityException(
            business_id=business.id,
            date=(future_start + timedelta(days=6)).isoformat(),
            type="closed",
            reason="Cierre real",
        )
    )
    db.commit()
    evaluator = BusinessGrowthSignalService(db, now=NOW)
    snapshot = evaluator.capacity_snapshot(
        business, start=future_start, end=future_start + timedelta(days=7)
    )
    assert snapshot.capacity_minutes == 6 * 8 * 60
    assert snapshot.booked_minutes == 0
    assert cancelled.status == "cancelled"

    first = evaluator.evaluate_business(business.id)
    db.commit()
    row = signals(db, "low_future_occupancy")[0]
    assert first.created == 1
    assert row.status == "active"
    assert serialize_growth_signal(row)["observed"]["occupancy_rate"] == 0
    original_id = row.id

    second = BusinessGrowthSignalService(db, now=NOW + timedelta(hours=1)).evaluate_business(
        business.id
    )
    db.commit()
    assert second.updated >= 1
    assert signals(db, "low_future_occupancy")[0].id == original_id

    for offset in range(5):
        day = future_start + timedelta(days=offset)
        booking(
            db,
            business=business,
            service=service,
            customer_row=customer(db, business, 200 + offset),
            start=datetime.combine(day, datetime.min.time(), tzinfo=timezone.utc)
            + timedelta(hours=9),
            duration_minutes=480,
            status="confirmed",
            staff_id=staff.id,
        )
    db.commit()
    BusinessGrowthSignalService(db, now=NOW + timedelta(hours=2)).evaluate_business(
        business.id
    )
    db.commit()
    assert db.get(BusinessGrowthSignal, original_id).status == "resolved"
    assert not db.query(BusinessGrowthSignal).filter(
        BusinessGrowthSignal.business_id == records["b"].id
    ).count()


def test_low_occupancy_requires_real_history(db: Session, records: dict[str, object]) -> None:
    business = records["b"]
    assert isinstance(business, Business)
    BusinessGrowthSignalService(db, now=NOW).evaluate_business(business.id)
    db.commit()
    assert not signals(db, "low_future_occupancy")


def add_due_opportunity(
    db: Session,
    *,
    business: Business,
    service: BusinessService,
    customer_row: Customer,
    suffix: str,
    status: str = "pending",
) -> CustomerOpportunity:
    row = CustomerOpportunity(
        business_id=business.id,
        customer_id=customer_row.id,
        type="service_due",
        status=status,
        priority="normal",
        detected_at=NOW - timedelta(days=1),
        due_at=NOW,
        expires_at=NOW + timedelta(days=10),
        source_service_id=service.id,
        reason_code="configured_service_return_window",
        reason_text="Periodo de retorno configurado.",
        dedupe_key=f"service_due:test:{suffix}",
        source_occurred_at=NOW - timedelta(days=20),
    )
    db.add(row)
    db.flush()
    return row


def test_due_pool_groups_unique_customers_and_resolves(
    db: Session, records: dict[str, object]
) -> None:
    business = records["a"]
    service = records["service"]
    second_service = records["second_service"]
    assert isinstance(business, Business)
    assert isinstance(service, BusinessService)
    assert isinstance(second_service, BusinessService)
    customers = [customer(db, business, 300 + index) for index in range(5)]
    rows = [
        add_due_opportunity(
            db,
            business=business,
            service=service,
            customer_row=customer_row,
            suffix=str(index),
        )
        for index, customer_row in enumerate(customers[:3])
    ]
    db.commit()
    BusinessGrowthSignalService(db, now=NOW).evaluate_business(business.id)
    db.commit()
    assert not signals(db, "high_due_customer_pool")
    rows.extend(
        (
            add_due_opportunity(
                db,
                business=business,
                service=service,
                customer_row=customers[3],
                suffix="3",
            ),
            add_due_opportunity(
                db,
                business=business,
                service=second_service,
                customer_row=customers[4],
                suffix="4",
            ),
        )
    )
    add_due_opportunity(
        db,
        business=business,
        service=service,
        customer_row=customers[0],
        suffix="duplicate-customer",
    )
    db.commit()
    BusinessGrowthSignalService(db, now=NOW).evaluate_business(business.id)
    db.commit()
    pools = signals(db, "high_due_customer_pool")
    assert len(pools) == 2
    assert {row.scope_type for row in pools} == {"business", "service"}
    assert sorted(serialize_growth_signal(row)["observed"]["customers_due"] for row in pools) == [4, 5]
    assert all("Cliente" not in row.observed_json for row in pools)

    for row in rows[:2]:
        row.status = "resolved"
        row.resolved_at = NOW
    db.commit()
    BusinessGrowthSignalService(db, now=NOW + timedelta(hours=1)).evaluate_business(
        business.id
    )
    db.commit()
    assert all(row.status == "resolved" for row in pools)


def add_return_case(
    db: Session,
    *,
    business: Business,
    service: BusinessService,
    staff_id: int,
    index: int,
    deadline: datetime,
    returned: bool,
) -> tuple[Booking, Booking | None]:
    customer_row = customer(db, business, 1000 + index)
    source_start = deadline - timedelta(days=10, hours=1)
    source = booking(
        db,
        business=business,
        service=service,
        customer_row=customer_row,
        start=source_start,
        staff_id=staff_id,
        recurring=True,
    )
    followup = None
    if returned:
        followup = booking(
            db,
            business=business,
            service=service,
            customer_row=customer_row,
            start=source_start + timedelta(days=5),
            status="confirmed",
            staff_id=staff_id,
            recurring=False,
        )
    return source, followup


def test_low_return_rate_needs_samples_and_resolves_on_recovery(
    db: Session, records: dict[str, object]
) -> None:
    business = records["a"]
    service = records["service"]
    staff = records["admin_membership"]
    assert isinstance(business, Business)
    assert isinstance(service, BusinessService)
    assert isinstance(staff, BusinessUser)
    current_sources = []
    for index in range(10):
        source, _ = add_return_case(
            db,
            business=business,
            service=service,
            staff_id=staff.id,
            index=index,
            deadline=NOW - timedelta(days=15),
            returned=index < 2,
        )
        current_sources.append(source)
    for index in range(30):
        period = index // 10
        add_return_case(
            db,
            business=business,
            service=service,
            staff_id=staff.id,
            index=100 + index,
            deadline=NOW - timedelta(days=45 + period * 30),
            returned=index % 10 < 8,
        )
    db.commit()
    BusinessGrowthSignalService(db, now=NOW).evaluate_business(business.id)
    db.commit()
    row = signals(db, "low_return_rate")[0]
    payload = serialize_growth_signal(row)
    assert payload["observed"]["sample_size"] == 10
    assert payload["observed"]["return_rate"] == 0.2
    assert payload["baseline"]["sample_size"] == 30

    for index, source in enumerate(current_sources[2:8], start=2):
        booking(
            db,
            business=business,
            service=service,
            customer_row=source.customer,
            start=NOW - timedelta(days=18) + timedelta(minutes=index),
            status="confirmed",
            staff_id=staff.id,
        )
    db.commit()
    BusinessGrowthSignalService(db, now=NOW + timedelta(hours=1)).evaluate_business(
        business.id
    )
    db.commit()
    assert row.status == "resolved"


def test_return_rate_ignores_small_and_nonrecurring_samples(
    db: Session, records: dict[str, object]
) -> None:
    business = records["b"]
    service = records["other_service"]
    staff = records["other_membership"]
    assert isinstance(business, Business)
    assert isinstance(service, BusinessService)
    assert isinstance(staff, BusinessUser)
    for index in range(9):
        booking(
            db,
            business=business,
            service=service,
            customer_row=customer(db, business, 2000 + index),
            start=NOW - timedelta(days=20 + index),
            staff_id=staff.id,
            recurring=False,
        )
    db.commit()
    BusinessGrowthSignalService(db, now=NOW).evaluate_business(business.id)
    db.commit()
    assert not signals(db, "low_return_rate")


def add_demand_history(
    db: Session,
    *,
    business: Business,
    service: BusinessService,
    staff_id: int,
    current_count: int,
) -> None:
    index = 0
    for period in range(3):
        for offset in range(6):
            created = NOW - timedelta(days=35 + period * 30 + offset)
            booking(
                db,
                business=business,
                service=service,
                customer_row=customer(db, business, 3000 + service.id * 1000 + index),
                start=created,
                created_at=created,
                staff_id=staff_id,
            )
            index += 1
    for offset in range(current_count):
        created = NOW - timedelta(days=5 + offset)
        booking(
            db,
            business=business,
            service=service,
            customer_row=customer(db, business, 3500 + service.id * 1000 + offset),
            start=created,
            created_at=created,
            staff_id=staff_id,
        )


def test_service_demand_drop_stability_new_inactive_and_closed_business(
    db: Session, records: dict[str, object]
) -> None:
    business = records["a"]
    service = records["second_service"]
    staff = records["admin_membership"]
    assert isinstance(business, Business)
    assert isinstance(service, BusinessService)
    assert isinstance(staff, BusinessUser)
    add_demand_history(
        db, business=business, service=service, staff_id=staff.id, current_count=2
    )
    stable = BusinessService(
        business_id=business.id,
        name="Estable",
        duration_minutes=30,
        active=True,
        bookable=True,
        created_at=(NOW - timedelta(days=300)).replace(tzinfo=None),
    )
    new_service = BusinessService(
        business_id=business.id,
        name="Nuevo",
        duration_minutes=30,
        active=True,
        bookable=True,
        created_at=(NOW - timedelta(days=20)).replace(tzinfo=None),
    )
    inactive = BusinessService(
        business_id=business.id,
        name="Inactivo",
        duration_minutes=30,
        active=False,
        bookable=True,
        created_at=(NOW - timedelta(days=300)).replace(tzinfo=None),
    )
    db.add_all((stable, new_service, inactive))
    db.flush()
    add_demand_history(
        db, business=business, service=stable, staff_id=staff.id, current_count=6
    )
    add_demand_history(
        db, business=business, service=new_service, staff_id=staff.id, current_count=0
    )
    add_demand_history(
        db, business=business, service=inactive, staff_id=staff.id, current_count=0
    )
    db.commit()
    BusinessGrowthSignalService(db, now=NOW).evaluate_business(business.id)
    db.commit()
    rows = signals(db, "service_demand_drop")
    assert [row.service_id for row in rows] == [service.id]
    assert serialize_growth_signal(rows[0])["baseline"]["average_booking_count"] == 6

    other_business = records["b"]
    other_service = records["other_service"]
    other_staff = records["other_membership"]
    assert isinstance(other_business, Business)
    assert isinstance(other_service, BusinessService)
    assert isinstance(other_staff, BusinessUser)
    add_demand_history(
        db,
        business=other_business,
        service=other_service,
        staff_id=other_staff.id,
        current_count=0,
    )
    for offset in range(30):
        db.add(
            AvailabilityException(
                business_id=other_business.id,
                date=(NOW.date() - timedelta(days=offset)).isoformat(),
                type="closed",
            )
        )
    db.commit()
    BusinessGrowthSignalService(db, now=NOW).evaluate_business(other_business.id)
    db.commit()
    assert not db.query(BusinessGrowthSignal).filter(
        BusinessGrowthSignal.business_id == other_business.id,
        BusinessGrowthSignal.type == "service_demand_drop",
    ).count()


def test_seasonal_events_crud_recurrence_permissions_and_isolation(
    db: Session, records: dict[str, object]
) -> None:
    business = records["a"]
    service = records["service"]
    other_service = records["other_service"]
    admin = records["admin"]
    staff = records["staff"]
    assert isinstance(business, Business)
    assert isinstance(service, BusinessService)
    assert isinstance(other_service, BusinessService)
    assert isinstance(admin, User)
    assert isinstance(staff, User)
    created = create_calendar_event(
        "signals-a",
        BusinessCalendarEventCreate(
            title="Campaña cambio de temporada",
            starts_at=NOW + timedelta(days=12),
            ends_at=NOW + timedelta(days=20),
            category="propia",
            service_id=service.id,
        ),
        request(),
        admin,
        db,
    )["event"]
    annual = create_calendar_event(
        "signals-a",
        BusinessCalendarEventCreate(
            title="Aniversario",
            starts_at=datetime(2020, 8, 20, tzinfo=timezone.utc),
            ends_at=datetime(2020, 8, 21, tzinfo=timezone.utc),
            yearly_recurrence=True,
        ),
        request(),
        admin,
        db,
    )["event"]
    create_calendar_event(
        "signals-a",
        BusinessCalendarEventCreate(
            title="Desactivado",
            starts_at=NOW + timedelta(days=2),
            ends_at=NOW + timedelta(days=3),
            enabled=False,
        ),
        request(),
        admin,
        db,
    )
    create_calendar_event(
        "signals-a",
        BusinessCalendarEventCreate(
            title="Fuera de ventana",
            starts_at=NOW + timedelta(days=60),
            ends_at=NOW + timedelta(days=61),
        ),
        request(),
        admin,
        db,
    )
    with pytest.raises(HTTPException) as cross_service:
        create_calendar_event(
            "signals-a",
            BusinessCalendarEventCreate(
                title="Inválido",
                starts_at=NOW + timedelta(days=1),
                ends_at=NOW + timedelta(days=2),
                service_id=other_service.id,
            ),
            request(),
            admin,
            db,
        )
    assert cross_service.value.status_code == 422
    with pytest.raises(HTTPException) as staff_denied:
        require_business_admin("signals-a", staff, db)
    assert staff_denied.value.status_code == 403
    assert require_business_access("signals-a", staff, db) is staff

    BusinessGrowthSignalService(db, now=NOW).evaluate_business(business.id)
    db.commit()
    seasonal = signals(db, "seasonal_window")
    assert len(seasonal) == 2
    assert all(row.severity == "info" for row in seasonal)
    assert {row.calendar_event_id for row in seasonal} == {created["id"], annual["id"]}

    updated = update_calendar_event(
        "signals-a",
        created["id"],
        BusinessCalendarEventUpdate(title="Campaña revisada"),
        request("PATCH"),
        admin,
        db,
    )["event"]
    assert updated["title"] == "Campaña revisada"
    assert len(list_calendar_events("signals-a", None, db)["events"]) == 4
    assert not list_calendar_events("signals-b", None, db)["events"]
    assert delete_calendar_event(
        "signals-a", created["id"], request("DELETE"), admin, db
    ) == {"ok": True}
    assert db.get(BusinessCalendarEvent, created["id"]) is None


def test_signal_api_filters_dismissal_history_and_constraints(
    db: Session, records: dict[str, object]
) -> None:
    business = records["a"]
    service = records["service"]
    admin = records["admin"]
    assert isinstance(business, Business)
    assert isinstance(service, BusinessService)
    assert isinstance(admin, User)
    event = BusinessCalendarEvent(
        business_id=business.id,
        title="Navidad propia",
        starts_at=NOW + timedelta(days=5),
        ends_at=NOW + timedelta(days=10),
        service_id=service.id,
        enabled=True,
    )
    db.add(event)
    db.commit()
    BusinessGrowthSignalService(db, now=NOW).evaluate_business(business.id)
    db.commit()
    row = signals(db, "seasonal_window")[0]
    listed = list_growth_signals(
        "signals-a", "active", "seasonal_window", "info", service.id, None, None, 20, db
    )
    assert [item["id"] for item in listed["signals"]] == [row.id]
    assert get_growth_signal("signals-a", row.id, db)["signal"]["id"] == row.id
    with pytest.raises(HTTPException) as isolated:
        get_growth_signal("signals-b", row.id, db)
    assert isolated.value.status_code == 404

    first = dismiss_growth_signal("signals-a", row.id, request(), admin, db)
    second = dismiss_growth_signal("signals-a", row.id, request(), admin, db)
    assert first["idempotent"] is False
    assert second["idempotent"] is True
    BusinessGrowthSignalService(db, now=NOW + timedelta(hours=1)).evaluate_business(
        business.id
    )
    db.commit()
    assert db.query(BusinessGrowthSignal).count() == 1
    assert row.status == "dismissed"
    summary = growth_signals_summary("signals-a", db)
    assert summary["active_count"] == 0
    assert summary["data_state"] == "evaluated"

    duplicate = BusinessGrowthSignal(
        business_id=business.id,
        type="seasonal_window",
        status="active",
        severity="info",
        scope_type="service",
        service_id=service.id,
        detected_at=NOW,
        period_start=NOW + timedelta(days=5),
        period_end=NOW + timedelta(days=10),
        last_evaluated_at=NOW,
        reason_code="test",
        explanation_json="{}",
        observed_json="{}",
        recommendation_code="consider_campaign",
        dedupe_key=row.dedupe_key,
    )
    db.add(duplicate)
    with pytest.raises(IntegrityError):
        db.commit()
    db.rollback()


def test_expiry_and_new_temporal_window_are_preserved(
    db: Session, records: dict[str, object]
) -> None:
    business = records["a"]
    assert isinstance(business, Business)
    annual = BusinessCalendarEvent(
        business_id=business.id,
        title="Evento anual",
        starts_at=datetime(2020, 8, 16, tzinfo=timezone.utc),
        ends_at=datetime(2020, 8, 17, tzinfo=timezone.utc),
        enabled=True,
        yearly_recurrence=True,
    )
    db.add(annual)
    db.commit()
    BusinessGrowthSignalService(db, now=NOW).evaluate_business(business.id)
    db.commit()
    first = signals(db, "seasonal_window")[0]
    first.expires_at = NOW - timedelta(seconds=1)
    db.commit()
    BusinessGrowthSignalService(db, now=NOW + timedelta(hours=1)).evaluate_business(
        business.id
    )
    db.commit()
    assert first.status == "expired"
    BusinessGrowthSignalService(db, now=NOW.replace(year=2027)).evaluate_business(
        business.id
    )
    db.commit()
    assert len(signals(db, "seasonal_window")) == 2


def test_contracts_document_future_social_context_without_automation() -> None:
    root = Path(__file__).resolve().parents[2]
    architecture = (root / "docs/business_growth_signals_architecture.md").read_text(
        encoding="utf-8"
    )
    admin = (root / "autonogrow-admin/admin.js").read_text(encoding="utf-8")
    html = (root / "autonogrow-admin/index.html").read_text(encoding="utf-8")
    maintenance = (root / "scripts/run_maintenance.py").read_text(encoding="utf-8")
    assert "BusinessGrowthSignal" in architecture
    assert "Content Opportunity" in architecture
    assert "no se crean mensajes individuales" in architecture
    assert "growth-signals?status=active" in admin
    assert "Ver oportunidades relacionadas" in admin
    assert "Señales del negocio" in html
    assert '"growth-signals"' in maintenance
