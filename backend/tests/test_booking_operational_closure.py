from datetime import datetime, timedelta, timezone

import pytest
from fastapi import HTTPException
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from starlette.requests import Request

from app.core.database import Base
from app.core.security import require_business_access
from app.models import (
    AuditLog,
    AvailabilitySettings,
    Booking,
    Business,
    BusinessService,
    BusinessUser,
    Customer,
    MessageOutbox,
    ReviewRequest,
    User,
)
from app.routers.admin import (
    BookingStatusUpdate,
    admin_list_booking_close_tasks,
    update_booking_status,
)
from app.schemas.booking import BookingRequestCreate
from app.services.availability_service import get_operational_business_now
from app.services.booking_service import create_booking_request, serialize_booking
from app.services.booking_status_service import list_booking_close_tasks


def request_for(path: str = "/test") -> Request:
    return Request(
        {
            "type": "http",
            "method": "PATCH",
            "path": path,
            "headers": [(b"x-request-id", b"booking-closure-test")],
            "query_string": b"",
            "scheme": "http",
            "server": ("test", 80),
            "client": ("test", 123),
        }
    )


@pytest.fixture
def records():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    db = sessionmaker(bind=engine)()
    business = Business(
        slug="closure-a",
        name="Closure A",
        status="active",
        reviews_url="https://reviews.example.test/a",
    )
    other_business = Business(slug="closure-b", name="Closure B", status="active")
    admin_user = User(email="closure-admin@test.local", name="Admin", is_active=True)
    staff_user = User(email="closure-staff@test.local", name="Staff", is_active=True)
    other_staff_user = User(email="closure-other-staff@test.local", name="Other", is_active=True)
    outsider = User(email="closure-outsider@test.local", name="Outsider", is_active=True)
    db.add_all(
        [business, other_business, admin_user, staff_user, other_staff_user, outsider]
    )
    db.flush()
    service = BusinessService(
        business_id=business.id,
        name="Service",
        duration_minutes=45,
        duration_text="45 min",
        active=True,
    )
    other_service = BusinessService(
        business_id=other_business.id,
        name="Other service",
        duration_minutes=30,
        duration_text="30 min",
        active=True,
    )
    admin = BusinessUser(
        business_id=business.id,
        user_id=admin_user.id,
        role="business_admin",
        active=True,
    )
    staff = BusinessUser(
        business_id=business.id,
        user_id=staff_user.id,
        role="business_staff",
        active=True,
        bookable=True,
        show_schedule=True,
        public_name="Staff",
    )
    other_staff = BusinessUser(
        business_id=business.id,
        user_id=other_staff_user.id,
        role="business_staff",
        active=True,
        bookable=True,
        show_schedule=True,
        public_name="Other",
    )
    schedule = "{" + ",".join(
        f'"{day}":[{{"start":"09:00","end":"18:00"}}]' for day in range(7)
    ) + "}"
    settings = AvailabilitySettings(
        business_id=business.id,
        timezone="Europe/Madrid",
        slot_interval_minutes=15,
        buffer_between_bookings_minutes=0,
        min_notice_minutes=0,
        max_days_ahead=30,
        weekly_schedule_json=schedule,
    )
    other_settings = AvailabilitySettings(
        business_id=other_business.id,
        timezone="Europe/Madrid",
        weekly_schedule_json=schedule,
    )
    customer = Customer(
        business_id=business.id,
        name="Customer",
        phone="600000000",
        phone_normalized="+34600000000",
    )
    other_customer = Customer(business_id=other_business.id, name="Other customer")
    db.add_all(
        [
            service,
            other_service,
            admin,
            staff,
            other_staff,
            settings,
            other_settings,
            customer,
            other_customer,
        ]
    )
    db.flush()
    staff.services.append(service)
    other_staff.services.append(service)
    db.commit()
    yield {
        "db": db,
        "business": business,
        "other_business": other_business,
        "service": service,
        "other_service": other_service,
        "admin_user": admin_user,
        "staff_user": staff_user,
        "outsider": outsider,
        "staff": staff,
        "other_staff": other_staff,
        "customer": customer,
        "other_customer": other_customer,
        "settings": settings,
    }
    db.close()
    engine.dispose()


def add_booking(
    records,
    *,
    status: str = "confirmed",
    staff=None,
    start: datetime | None = None,
    end: datetime | None = None,
    duration: int | None = 45,
    business=None,
    service=None,
    customer=None,
) -> Booking:
    db = records["db"]
    business = business or records["business"]
    service = service or records["service"]
    customer = customer or records["customer"]
    if staff is None and business.id == records["business"].id:
        staff = records["staff"]
    start = start or datetime(2026, 1, 10, 10)
    booking = Booking(
        business_id=business.id,
        customer_id=customer.id,
        service_id=service.id,
        staff_business_user_id=staff.id if staff else None,
        service_name=service.name,
        duration_minutes=duration,
        start_datetime=start,
        end_datetime=end,
        preferred_date=start.date().isoformat(),
        preferred_time=start.strftime("%H:%M"),
        status=status,
    )
    db.add(booking)
    db.commit()
    db.refresh(booking)
    return booking


def test_booking_notes_round_trip_without_contaminating_customer(records) -> None:
    db = records["db"]
    business = records["business"]
    service = records["service"]
    staff = records["staff"]
    target = get_operational_business_now(db, business.id).date() + timedelta(days=2)
    payload = BookingRequestCreate(
        customer_name="New customer",
        customer_phone="611111111",
        service_id=service.id,
        staff_business_user_id=staff.id,
        start_datetime=f"{target.isoformat()}T10:00:00",
        notes="Revisar la rueda trasera.",
    )
    booking = create_booking_request(db, business_slug=business.slug, payload=payload)
    assert booking.notes == "Revisar la rueda trasera."
    assert serialize_booking(booking)["notes"] == "Revisar la rueda trasera."
    assert booking.customer.notes is None

    booking.customer.notes = "Prefiere dejar el coche antes de las 9."
    db.commit()
    second = create_booking_request(
        db,
        business_slug=business.slug,
        payload=payload.model_copy(
            update={
                "start_datetime": f"{target.isoformat()}T11:00:00",
                "notes": "Comentario solo de la segunda cita.",
            }
        ),
    )
    db.refresh(second.customer)
    assert second.notes == "Comentario solo de la segunda cita."
    assert second.customer.notes == "Prefiere dejar el coche antes de las 9."


@pytest.mark.parametrize("status", ["completed", "no_show", "cancelled", "rejected"])
def test_only_overdue_confirmed_bookings_are_close_tasks(records, status: str) -> None:
    now = datetime(2026, 1, 10, 12)
    add_booking(
        records,
        status="confirmed",
        start=now - timedelta(hours=2),
        end=now - timedelta(hours=1),
    )
    add_booking(
        records,
        status="confirmed",
        staff=records["other_staff"],
        start=now,
        end=now + timedelta(minutes=45),
    )
    add_booking(
        records,
        status=status,
        start=now - timedelta(hours=2),
        end=now - timedelta(hours=1),
    )
    tasks = list_booking_close_tasks(
        records["db"], business=records["business"], now=now
    )
    assert len(tasks) == 1
    assert tasks[0]["status"] == "confirmed"
    assert tasks[0]["effective_end_datetime"] == (now - timedelta(hours=1)).isoformat()


def test_close_task_uses_legacy_service_and_default_duration_fallbacks(records) -> None:
    now = datetime(2026, 1, 10, 12)
    service_fallback = add_booking(
        records,
        start=now - timedelta(minutes=50),
        end=None,
        duration=None,
    )
    default_service = BusinessService(
        business_id=records["business"].id,
        name="Legacy service",
        duration_minutes=None,
        active=True,
    )
    records["db"].add(default_service)
    records["db"].commit()
    default_fallback = add_booking(
        records,
        service=default_service,
        staff=records["other_staff"],
        start=now - timedelta(minutes=35),
        end=None,
        duration=None,
    )
    tasks = list_booking_close_tasks(
        records["db"], business=records["business"], now=now
    )
    assert {task["id"] for task in tasks} == {service_fallback.id, default_fallback.id}

    without_start = add_booking(
        records,
        start=now - timedelta(hours=1),
        end=None,
        duration=None,
    )
    without_start.start_datetime = None
    without_start.preferred_date = None
    records["db"].commit()
    tasks = list_booking_close_tasks(
        records["db"], business=records["business"], now=now
    )
    assert without_start.id not in {task["id"] for task in tasks}


def test_operational_timezone_and_dst_are_deterministic(records) -> None:
    db = records["db"]
    records["settings"].timezone = "Pacific/Auckland"
    db.commit()
    fixed_utc = datetime(2026, 1, 10, 0, 0, tzinfo=timezone.utc)
    auckland_now = get_operational_business_now(
        db,
        records["business"].id,
        now=fixed_utc,
    )
    assert auckland_now == datetime(2026, 1, 10, 13)
    booking = add_booking(
        records,
        start=auckland_now - timedelta(hours=1),
        end=auckland_now - timedelta(minutes=1),
    )
    tasks = list_booking_close_tasks(
        db,
        business=records["business"],
        now=fixed_utc,
    )
    assert booking.id in {task["id"] for task in tasks}

    records["settings"].timezone = "Europe/Madrid"
    db.commit()
    before_jump = get_operational_business_now(
        db,
        records["business"].id,
        now=datetime(2026, 3, 29, 0, 30, tzinfo=timezone.utc),
    )
    after_jump = get_operational_business_now(
        db,
        records["business"].id,
        now=datetime(2026, 3, 29, 1, 30, tzinfo=timezone.utc),
    )
    assert before_jump == datetime(2026, 3, 29, 1, 30)
    assert after_jump == datetime(2026, 3, 29, 3, 30)


def test_close_task_scopes_admin_staff_and_business(records) -> None:
    past = datetime(2020, 1, 10, 10)
    own = add_booking(records, start=past, end=past + timedelta(minutes=45))
    other = add_booking(
        records,
        staff=records["other_staff"],
        start=past + timedelta(hours=1),
        end=past + timedelta(hours=1, minutes=45),
    )
    admin_result = admin_list_booking_close_tasks(
        records["business"].slug,
        actor=records["admin_user"],
        db=records["db"],
    )
    staff_result = admin_list_booking_close_tasks(
        records["business"].slug,
        actor=records["staff_user"],
        db=records["db"],
    )
    assert {task["id"] for task in admin_result["tasks"]} == {own.id, other.id}
    assert {task["id"] for task in staff_result["tasks"]} == {own.id}
    with pytest.raises(HTTPException) as denied:
        require_business_access(
            records["other_business"].slug,
            records["admin_user"],
            records["db"],
        )
    assert denied.value.status_code == 403


def test_same_status_completion_is_idempotent(records) -> None:
    booking = add_booking(
        records,
        start=datetime(2020, 1, 10, 10),
        end=datetime(2020, 1, 10, 10, 45),
    )
    first = update_booking_status(
        records["business"].slug,
        booking.id,
        BookingStatusUpdate(status="completed"),
        request_for(),
        records["admin_user"],
        records["db"],
    )
    second = update_booking_status(
        records["business"].slug,
        booking.id,
        BookingStatusUpdate(status="completed"),
        request_for(),
        records["admin_user"],
        records["db"],
    )
    assert first["already_in_status"] is False
    assert second["already_in_status"] is True
    assert records["db"].query(ReviewRequest).filter_by(booking_id=booking.id).count() == 1
    assert (
        records["db"]
        .query(MessageOutbox)
        .filter_by(booking_id=booking.id, message_type="booking_completed_review")
        .count()
        == 1
    )
    assert (
        records["db"]
        .query(AuditLog)
        .filter_by(resource_type="booking", resource_id=str(booking.id))
        .count()
        == 1
    )


@pytest.mark.parametrize("target_status", ["completed", "no_show"])
def test_closing_booking_removes_derived_task(records, target_status: str) -> None:
    now = datetime(2026, 1, 10, 12)
    booking = add_booking(
        records,
        start=now - timedelta(hours=2),
        end=now - timedelta(hours=1),
    )
    assert booking.id in {
        task["id"]
        for task in list_booking_close_tasks(
            records["db"], business=records["business"], now=now
        )
    }
    result = update_booking_status(
        records["business"].slug,
        booking.id,
        BookingStatusUpdate(status=target_status),
        request_for(),
        records["admin_user"],
        records["db"],
    )
    assert result["booking"]["status"] == target_status
    assert booking.id not in {
        task["id"]
        for task in list_booking_close_tasks(
            records["db"], business=records["business"], now=now
        )
    }
    second = update_booking_status(
        records["business"].slug,
        booking.id,
        BookingStatusUpdate(status=target_status),
        request_for(),
        records["admin_user"],
        records["db"],
    )
    assert second["already_in_status"] is True
    assert (
        records["db"]
        .query(AuditLog)
        .filter_by(resource_type="booking", resource_id=str(booking.id))
        .count()
        == 1
    )


@pytest.mark.parametrize("terminal_status", ["completed", "no_show", "cancelled", "rejected"])
def test_terminal_status_cannot_return_to_confirmed(records, terminal_status: str) -> None:
    booking = add_booking(records, status=terminal_status)
    with pytest.raises(HTTPException) as conflict:
        update_booking_status(
            records["business"].slug,
            booking.id,
            BookingStatusUpdate(status="confirmed"),
            request_for(),
            records["admin_user"],
            records["db"],
        )
    assert conflict.value.status_code == 409


def test_booking_without_staff_and_expired_request_cannot_be_confirmed(records) -> None:
    future = datetime(2030, 1, 10, 10)
    without_staff = add_booking(
        records,
        status="requested",
        staff=False,
        start=future,
        end=future + timedelta(minutes=45),
    )
    without_staff.staff_business_user_id = None
    records["db"].commit()
    with pytest.raises(HTTPException) as missing_staff:
        update_booking_status(
            records["business"].slug,
            without_staff.id,
            BookingStatusUpdate(status="confirmed"),
            request_for(),
            records["admin_user"],
            records["db"],
        )
    assert missing_staff.value.status_code == 409

    for status in ("requested", "pending"):
        expired = add_booking(
            records,
            status=status,
            start=datetime(2020, 1, 10, 10),
            end=datetime(2020, 1, 10, 10, 45),
        )
        with pytest.raises(HTTPException) as expired_conflict:
            update_booking_status(
                records["business"].slug,
                expired.id,
                BookingStatusUpdate(status="confirmed"),
                request_for(),
                records["admin_user"],
                records["db"],
            )
        assert expired_conflict.value.status_code == 409
        serialized = serialize_booking(
            expired,
            operational_now=datetime(2020, 1, 10, 11),
        )
        assert serialized["request_expired"] is True
