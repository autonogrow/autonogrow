from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta
from threading import Barrier

import pytest
from alembic import command
from fastapi import HTTPException
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, sessionmaker
from starlette.requests import Request

from app.core.database import Base
from app.core.migration_state import alembic_config
from app.models import (
    Booking,
    Business,
    BusinessUser,
    Customer,
    MessageOutbox,
    ReviewRequest,
    User,
)
from app.models.registry import register_models
from app.routers.admin import create_review_request_for_booking
from app.services.booking_status_service import transition_booking_status
from app.services.message_outbox_service import (
    create_review_request_message,
    mark_opened,
)
from app.services.review_request_service import (
    ReviewRequestLifecycleError,
    get_or_create_review_request,
    transition_review_request_status,
)


def request_for(path: str = "/review-test") -> Request:
    return Request(
        {
            "type": "http",
            "method": "PATCH",
            "path": path,
            "headers": [(b"x-request-id", b"review-customer-dedupe-test")],
            "query_string": b"",
            "scheme": "http",
            "server": ("test", 80),
            "client": ("test", 123),
        }
    )


@pytest.fixture
def db() -> Session:
    register_models()
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine, expire_on_commit=False)()
    try:
        yield session
    finally:
        session.close()
        engine.dispose()


def add_business(db: Session, slug: str) -> Business:
    business = Business(
        slug=slug,
        name=slug,
        status="active",
        reviews_url=f"https://reviews.example.test/{slug}",
    )
    db.add(business)
    db.flush()
    return business


def add_customer(db: Session, business: Business, marker: str) -> Customer:
    customer = Customer(
        business_id=business.id,
        name=f"Customer {marker}",
        phone=f"+34600{business.id:03d}{len(marker):03d}",
    )
    db.add(customer)
    db.flush()
    return customer


def add_booking(
    db: Session,
    business: Business,
    customer: Customer,
    marker: int,
    *,
    status: str = "completed",
) -> Booking:
    start = datetime(2026, 1, 1, 9) + timedelta(days=marker)
    booking = Booking(
        business_id=business.id,
        customer_id=customer.id,
        service_name=f"Service {marker}",
        duration_minutes=45,
        start_datetime=start,
        end_datetime=start + timedelta(minutes=45),
        preferred_date=start.date().isoformat(),
        preferred_time=start.strftime("%H:%M"),
        status=status,
    )
    db.add(booking)
    db.flush()
    return booking


def create_cycle(db: Session, business: Business, booking: Booking) -> ReviewRequest:
    review_request = get_or_create_review_request(db, business=business, booking=booking)
    assert review_request is not None
    create_review_request_message(db, business=business, review_request=review_request)
    db.commit()
    return review_request


def test_one_customer_cycle_across_three_bookings_with_tenant_isolation(db: Session) -> None:
    first_business = add_business(db, "reviews-first")
    same_customer = add_customer(db, first_business, "same")
    bookings = [add_booking(db, first_business, same_customer, marker) for marker in range(3)]

    cycles = [create_cycle(db, first_business, booking) for booking in bookings]

    assert {cycle.id for cycle in cycles} == {cycles[0].id}
    assert cycles[0].booking_id == bookings[0].id
    assert cycles[0].customer_id == same_customer.id
    assert db.query(ReviewRequest).filter_by(business_id=first_business.id).count() == 1
    assert db.query(MessageOutbox).filter_by(message_type="booking_completed_review").count() == 1

    other_customer = add_customer(db, first_business, "other")
    other_cycle = create_cycle(
        db, first_business, add_booking(db, first_business, other_customer, 4)
    )
    assert other_cycle.id != cycles[0].id

    other_business = add_business(db, "reviews-second")
    same_identity_data = add_customer(db, other_business, "same")
    cross_business_cycle = create_cycle(
        db,
        other_business,
        add_booking(db, other_business, same_identity_data, 5),
    )
    assert cross_business_cycle.id not in {cycles[0].id, other_cycle.id}


@pytest.mark.parametrize("status", ["pending", "copied", "sent", "skipped"])
def test_every_review_status_blocks_another_customer_cycle(db: Session, status: str) -> None:
    business = add_business(db, f"reviews-{status}")
    customer = add_customer(db, business, status)
    first_booking = add_booking(db, business, customer, 1)
    first = create_cycle(db, business, first_booking)
    if status != "pending":
        transition_review_request_status(first, status)
        db.commit()

    second = get_or_create_review_request(
        db,
        business=business,
        booking=add_booking(db, business, customer, 2),
    )

    assert second is not None
    assert second.id == first.id
    assert second.booking_id == first_booking.id
    assert db.query(ReviewRequest).filter_by(customer_id=customer.id).count() == 1


@pytest.mark.parametrize(
    ("terminal_status", "rejected_status"),
    [("sent", "copied"), ("sent", "skipped"), ("skipped", "sent")],
)
def test_sent_and_skipped_are_terminal(
    db: Session,
    terminal_status: str,
    rejected_status: str,
) -> None:
    business = add_business(db, f"terminal-{terminal_status}-{rejected_status}")
    customer = add_customer(db, business, terminal_status + rejected_status)
    cycle = create_cycle(db, business, add_booking(db, business, customer, 1))
    transition_review_request_status(cycle, terminal_status)

    with pytest.raises(ReviewRequestLifecycleError, match="invalid_review_request_transition"):
        transition_review_request_status(cycle, rejected_status)


def test_failed_outbox_reopens_same_origin_message_without_new_cycle(db: Session) -> None:
    business = add_business(db, "failed-review")
    customer = add_customer(db, business, "failed")
    first_booking = add_booking(db, business, customer, 1)
    cycle = create_cycle(db, business, first_booking)
    message = cycle.message_outbox[0]
    message.status = "failed"
    db.commit()

    second_booking = add_booking(db, business, customer, 2)
    reused_cycle = get_or_create_review_request(db, business=business, booking=second_booking)
    assert reused_cycle is not None
    reused_message = create_review_request_message(
        db,
        business=business,
        review_request=reused_cycle,
    )

    assert reused_cycle.id == cycle.id
    assert reused_message is not None
    assert reused_message.id == message.id
    assert reused_message.booking_id == first_booking.id
    assert mark_opened(reused_message).status == "opened"
    assert db.query(ReviewRequest).filter_by(customer_id=customer.id).count() == 1
    assert db.query(MessageOutbox).filter_by(message_type="booking_completed_review").count() == 1


def test_manual_preparation_reuses_customer_cycle_and_origin_booking(db: Session) -> None:
    business = add_business(db, "manual-review")
    customer = add_customer(db, business, "manual")
    first_booking = add_booking(db, business, customer, 1)
    second_booking = add_booking(db, business, customer, 2)
    db.commit()

    first = create_review_request_for_booking(business.slug, first_booking.id, db)
    second = create_review_request_for_booking(business.slug, second_booking.id, db)

    assert first["review_request"]["id"] == second["review_request"]["id"]
    assert second["review_request"]["booking_id"] == first_booking.id
    assert second["outbox_message"]["booking_id"] == first_booking.id
    assert db.query(ReviewRequest).count() == 1
    assert db.query(MessageOutbox).count() == 1


def seed_concurrency_database(
    database_url: str, *, include_owner: bool
) -> tuple[int, list[int], int | None]:
    engine = create_engine(database_url, connect_args={"check_same_thread": False, "timeout": 10})
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    with factory() as db:
        business = add_business(db, "concurrent-review")
        customer = add_customer(db, business, "concurrent")
        bookings = [
            add_booking(
                db, business, customer, marker, status="confirmed" if include_owner else "completed"
            )
            for marker in (1, 2)
        ]
        owner_id = None
        if include_owner:
            owner = User(email="review-admin@test.invalid", is_active=True)
            db.add(owner)
            db.flush()
            db.add(
                BusinessUser(
                    business_id=business.id,
                    user_id=owner.id,
                    role="business_admin",
                    active=True,
                )
            )
            owner_id = owner.id
        db.commit()
        result = business.id, [booking.id for booking in bookings], owner_id
    engine.dispose()
    return result


def test_two_manual_posts_are_idempotent_without_server_error(tmp_path) -> None:
    database_url = f"sqlite:///{(tmp_path / 'review-post-race.db').as_posix()}"
    business_id, booking_ids, _owner_id = seed_concurrency_database(
        database_url, include_owner=False
    )
    factory = sessionmaker(
        bind=create_engine(
            database_url,
            connect_args={"check_same_thread": False, "timeout": 10},
        ),
        expire_on_commit=False,
    )
    barrier = Barrier(2)

    def prepare(booking_id: int) -> dict:
        with factory() as db:
            business = db.get(Business, business_id)
            assert business is not None
            barrier.wait()
            return create_review_request_for_booking(business.slug, booking_id, db)

    with ThreadPoolExecutor(max_workers=2) as executor:
        results = list(executor.map(prepare, booking_ids))

    assert len({result["review_request"]["id"] for result in results}) == 1
    with factory() as db:
        assert db.query(ReviewRequest).count() == 1
        assert (
            db.query(MessageOutbox).filter_by(message_type="booking_completed_review").count() == 1
        )
    factory.kw["bind"].dispose()


def test_two_bookings_completed_concurrently_create_one_customer_cycle(tmp_path) -> None:
    database_url = f"sqlite:///{(tmp_path / 'review-booking-race.db').as_posix()}"
    business_id, booking_ids, owner_id = seed_concurrency_database(database_url, include_owner=True)
    assert owner_id is not None
    engine = create_engine(
        database_url,
        connect_args={"check_same_thread": False, "timeout": 10},
    )
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    barrier = Barrier(2)

    def complete(booking_id: int) -> int:
        with factory() as db:
            business = db.get(Business, business_id)
            owner = db.get(User, owner_id)
            assert business is not None and owner is not None
            barrier.wait()
            result = transition_booking_status(
                db,
                business_slug=business.slug,
                booking_id=booking_id,
                target_status="completed",
                actor=owner,
                request=request_for(),
            )
            assert result.review_request is not None
            return result.review_request.id

    with ThreadPoolExecutor(max_workers=2) as executor:
        review_ids = list(executor.map(complete, booking_ids))

    assert len(set(review_ids)) == 1
    with factory() as db:
        assert db.query(Booking).filter_by(status="completed").count() == 2
        assert db.query(ReviewRequest).count() == 1
        assert (
            db.query(MessageOutbox).filter_by(message_type="booking_completed_review").count() == 1
        )
    engine.dispose()


def test_manual_preparation_rejects_cross_business_booking(db: Session) -> None:
    first_business = add_business(db, "tenant-first")
    second_business = add_business(db, "tenant-second")
    customer = add_customer(db, first_business, "tenant")
    booking = add_booking(db, first_business, customer, 1)
    db.commit()

    with pytest.raises(HTTPException) as missing:
        create_review_request_for_booking(second_business.slug, booking.id, db)
    assert missing.value.status_code == 404


def test_review_cycle_fails_closed_without_stable_customer(db: Session) -> None:
    business = add_business(db, "missing-review-customer")
    customer = add_customer(db, business, "missing")
    booking = add_booking(db, business, customer, 1)
    booking.customer_id = None

    with pytest.raises(ReviewRequestLifecycleError, match="booking_without_stable_customer"):
        get_or_create_review_request(db, business=business, booking=booking)

    with db.no_autoflush:
        assert db.query(ReviewRequest).count() == 0


def test_legacy_migration_preserves_history_and_anchors_earliest_cycle(tmp_path) -> None:
    database_url = f"sqlite:///{(tmp_path / 'review-legacy.db').as_posix()}"
    config = alembic_config()
    config.attributes["database_url"] = database_url
    command.upgrade(config, "20260901_31")
    engine = create_engine(database_url)
    factory = sessionmaker(bind=engine, expire_on_commit=False)

    with factory() as db:
        business = add_business(db, "legacy-reviews")
        repeated_customer = add_customer(db, business, "legacy-repeated")
        other_customer = add_customer(db, business, "legacy-other")
        bookings = [
            add_booking(db, business, repeated_customer, 1),
            add_booking(db, business, repeated_customer, 2),
            add_booking(db, business, other_customer, 3),
        ]
        db.commit()
        booking_ids = [booking.id for booking in bookings]
        business_id = business.id
        repeated_customer_id = repeated_customer.id
        other_customer_id = other_customer.id

    with engine.begin() as connection:
        for request_id, booking_id, created_at, status in (
            (10, booking_ids[0], datetime(2026, 1, 2), "sent"),
            (11, booking_ids[1], datetime(2026, 2, 2), "pending"),
            (12, booking_ids[2], datetime(2026, 3, 2), "copied"),
        ):
            connection.execute(
                text(
                    "INSERT INTO review_requests "
                    "(id, business_id, booking_id, customer_name, customer_phone, reviews_url, "
                    "message, status, created_at) "
                    "VALUES (:id, :business_id, :booking_id, :name, NULL, :url, :message, "
                    ":status, :created_at)"
                ),
                {
                    "id": request_id,
                    "business_id": business_id,
                    "booking_id": booking_id,
                    "name": "Legacy customer",
                    "url": "https://reviews.example.test/legacy",
                    "message": "Legacy request",
                    "status": status,
                    "created_at": created_at,
                },
            )
    engine.dispose()

    command.upgrade(config, "head")
    engine = create_engine(database_url)
    with engine.connect() as connection:
        rows = connection.execute(
            text(
                "SELECT id, customer_id, is_customer_cycle_anchor FROM review_requests ORDER BY id"
            )
        ).all()
    assert rows == [
        (10, repeated_customer_id, 1),
        (11, repeated_customer_id, 0),
        (12, other_customer_id, 1),
    ]
    assert "customer_id" in {
        item["name"] for item in inspect(engine).get_columns("review_requests")
    }
    with pytest.raises(IntegrityError):
        with engine.begin() as connection:
            connection.execute(
                text("UPDATE review_requests SET is_customer_cycle_anchor = 1 WHERE id = 11")
            )
    engine.dispose()

    command.downgrade(config, "20260901_31")
    engine = create_engine(database_url)
    assert "customer_id" not in {
        item["name"] for item in inspect(engine).get_columns("review_requests")
    }
    with engine.connect() as connection:
        assert connection.execute(text("SELECT COUNT(*) FROM review_requests")).scalar_one() == 3
    engine.dispose()
