from __future__ import annotations

import os
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta
from pathlib import Path
from threading import Barrier, Event

import pytest
from alembic import command
from scripts.migrate_sqlite_to_postgresql import (
    COPY_ORDER,
    copy_and_validate_atomic,
    require_complete_source,
    require_destination_at_head,
    require_empty_destination,
)
from sqlalchemy import create_engine, func, select, text
from sqlalchemy.engine import Engine, make_url
from sqlalchemy.exc import DBAPIError
from sqlalchemy.orm import Session, sessionmaker
from starlette.requests import Request

from app.core.config import Settings
from app.core.database import create_database_engine
from app.core.migration_state import alembic_config
from app.models import (
    AuditLog,
    AutomationCreditTransaction,
    AvailabilitySettings,
    Booking,
    Business,
    BusinessChannelIntegration,
    BusinessOnboardingSession,
    BusinessService,
    BusinessUser,
    ChannelOutboxMessage,
    Conversation,
    ConversationAutomationSettings,
    ConversationMessage,
    Customer,
    SystemIncident,
    User,
    WebhookInboxEvent,
    WorkerHeartbeat,
)
from app.routers.owner_onboarding import activate_business
from app.schemas.onboarding import ActivationRequest
from app.services.automation_credit_service import consume_automation_credit, lock_credit_wallet
from app.services.booking_service import ensure_no_booking_overlap, lock_business_schedule
from app.services.business_readiness_service import evaluate_business_readiness
from app.services.database_error_service import classify_database_error
from app.services.inbox_queue_service import claim_inbox_jobs
from app.services.instagram_integration_service import (
    lock_instagram_integration,
    verify_instagram_integration,
)
from app.services.instagram_provider import InstagramVerificationResult
from app.services.outbox_queue_service import claim_outbox_jobs

pytestmark = pytest.mark.postgresql


@pytest.fixture
def postgresql_engine() -> Engine:
    database_url = os.getenv("POSTGRES_TEST_DATABASE_URL", "")
    if not database_url or make_url(database_url).get_backend_name() != "postgresql":
        pytest.skip("POSTGRES_TEST_DATABASE_URL is not configured")
    settings = Settings(
        _env_file=None,
        app_env="test",
        database_url=database_url,
        worker_concurrency_mode="multi",
        database_application_name="autonogrow-pytest",
    )
    engine = create_database_engine(database_url, settings=settings)
    require_destination_at_head(engine)
    tables = ", ".join(f'"{name}"' for name in reversed(COPY_ORDER))
    with engine.begin() as connection:
        connection.execute(text(f"TRUNCATE TABLE {tables} RESTART IDENTITY CASCADE"))
    try:
        yield engine
    finally:
        with engine.begin() as connection:
            connection.execute(text(f"TRUNCATE TABLE {tables} RESTART IDENTITY CASCADE"))
        engine.dispose()


def test_concurrent_business_activation_is_locked_and_idempotent(
    postgresql_engine: Engine,
) -> None:
    factory = sessionmaker(postgresql_engine, expire_on_commit=False)
    with factory.begin() as db:
        owner = User(email="postgres-onboarding-owner@test.local", is_owner=True)
        business = Business(
            name="Concurrent activation",
            slug="concurrent-activation",
            status="onboarding",
        )
        db.add_all([owner, business])
        db.flush()
        db.add_all(
            [
                BusinessOnboardingSession(
                    business_id=business.id,
                    started_by_user_id=owner.id,
                    last_updated_by_user_id=owner.id,
                ),
                BusinessService(
                    business_id=business.id,
                    name="Bookable",
                    duration_minutes=30,
                ),
                AvailabilitySettings(
                    business_id=business.id,
                    weekly_schedule_json='{"1":[{"start":"09:00","end":"17:00"}]}',
                ),
            ]
        )
    with factory() as db:
        business_id = db.query(Business.id).filter_by(slug="concurrent-activation").scalar()
        owner_id = (
            db.query(User.id).filter_by(email="postgres-onboarding-owner@test.local").scalar()
        )
        version = evaluate_business_readiness(db, db.get(Business, business_id))["version"]

    start = Barrier(2)

    def activate_once() -> bool:
        with factory() as db:
            start.wait(timeout=5)
            result = activate_business(
                business_id,
                ActivationRequest(
                    reason="Concurrent owner approval",
                    expected_readiness_version=version,
                ),
                Request(
                    {
                        "type": "http",
                        "method": "POST",
                        "path": f"/api/owner/businesses/{business_id}/activate",
                        "headers": [(b"x-request-id", b"postgres-onboarding-test")],
                        "query_string": b"",
                        "scheme": "http",
                        "server": ("test", 80),
                        "client": ("test", 123),
                    }
                ),
                db.get(User, owner_id),
                db,
            )
            return result["already_active"]

    with ThreadPoolExecutor(max_workers=2) as executor:
        results = list(executor.map(lambda _index: activate_once(), range(2)))
    assert sorted(results) == [False, True]
    with factory() as db:
        assert db.get(Business, business_id).status == "active"
        assert (
            db.query(AuditLog)
            .filter(
                AuditLog.business_id == business_id,
                AuditLog.action == "business_activated",
            )
            .count()
            == 1
        )


def test_two_workers_claim_distinct_inbox_rows_with_skip_locked(
    postgresql_engine: Engine,
) -> None:
    factory = sessionmaker(postgresql_engine, expire_on_commit=False)
    with factory.begin() as db:
        db.add_all(
            [
                WebhookInboxEvent(
                    provider="instagram",
                    channel="instagram",
                    idempotency_key=f"claim-{index}",
                    payload_hash=f"{index:064d}",
                    payload_json="{}",
                    payload_size_bytes=2,
                    status="pending",
                    max_attempts=5,
                )
                for index in range(2)
            ]
        )

    start = Barrier(2)
    claimed = Barrier(2)

    def worker(worker_id: str) -> int:
        with factory() as db:
            start.wait(timeout=5)
            ids = claim_inbox_jobs(
                db,
                worker_id=worker_id,
                limit=1,
                lock_timeout_seconds=60,
            )
            claimed.wait(timeout=5)
            db.commit()
            return ids[0]

    with ThreadPoolExecutor(max_workers=2) as executor:
        futures = [executor.submit(worker, f"worker-{index}") for index in range(2)]
        ids = [future.result(timeout=10) for future in futures]
    assert len(set(ids)) == 2


def test_concurrent_credit_consumption_never_makes_wallet_negative(
    postgresql_engine: Engine,
) -> None:
    factory = sessionmaker(postgresql_engine, expire_on_commit=False)
    with factory.begin() as db:
        business = Business(slug="credit-lock", name="Credit lock")
        db.add(business)
        db.flush()
        wallet = ConversationAutomationSettings(
            business_id=business.id,
            period_yyyymm="2026-07",
            included_credits_per_period=1,
            included_credits_used=0,
            additional_credits_balance=0,
        )
        conversation = Conversation(
            business_id=business.id,
            channel="instagram",
            external_user_id="credit-user",
        )
        db.add_all([wallet, conversation])
        db.flush()
        messages = [
            ConversationMessage(
                conversation_id=conversation.id,
                direction="outbound",
                sender_type="automation",
                body=f"message-{index}",
            )
            for index in range(2)
        ]
        db.add_all(messages)
        db.flush()
        wallet_id = wallet.id
        message_ids = [message.id for message in messages]

    start = Barrier(2)

    def consume(message_id: int) -> bool:
        with factory() as db:
            wallet = db.get(ConversationAutomationSettings, wallet_id)
            assert wallet is not None
            start.wait(timeout=5)
            consumed, _item = consume_automation_credit(
                db,
                settings=wallet,
                related_message_id=message_id,
            )
            db.commit()
            return consumed

    with ThreadPoolExecutor(max_workers=2) as executor:
        results = list(executor.map(consume, message_ids))
    assert sorted(results) == [False, True]
    with factory() as db:
        wallet = db.get(ConversationAutomationSettings, wallet_id)
        assert wallet is not None
        assert wallet.included_credits_used == 1
        assert wallet.additional_credits_balance == 0
        assert db.query(AutomationCreditTransaction).count() == 1


def test_concurrent_booking_writes_are_serialized_per_business(
    postgresql_engine: Engine,
) -> None:
    factory = sessionmaker(postgresql_engine, expire_on_commit=False)
    with factory.begin() as db:
        business = Business(slug="booking-lock", name="Booking lock")
        db.add(business)
        db.flush()
        customer = Customer(business_id=business.id, name="Customer")
        service = BusinessService(
            business_id=business.id,
            name="Service",
            duration_minutes=30,
        )
        db.add_all([customer, service])
        db.flush()
        business_id = business.id
        customer_id = customer.id
        service_id = service.id

    start_at = datetime(2026, 8, 1, 10, 0)
    end_at = start_at + timedelta(minutes=30)
    start = Barrier(2)

    def book(index: int) -> bool:
        with factory() as db:
            business = db.get(Business, business_id)
            assert business is not None
            start.wait(timeout=5)
            lock_business_schedule(db, business)
            try:
                ensure_no_booking_overlap(
                    db,
                    business_id=business_id,
                    staff_business_user_id=None,
                    start_datetime=start_at,
                    end_datetime=end_at,
                )
            except ValueError:
                db.rollback()
                return False
            db.add(
                Booking(
                    business_id=business_id,
                    customer_id=customer_id,
                    service_id=service_id,
                    service_name="Service",
                    duration_minutes=30,
                    start_datetime=start_at,
                    end_datetime=end_at,
                    preferred_time="10:00",
                    source=f"test-{index}",
                )
            )
            db.commit()
            return True

    with ThreadPoolExecutor(max_workers=2) as executor:
        results = list(executor.map(book, range(2)))
    assert sorted(results) == [False, True]
    with factory() as db:
        assert db.query(Booking).count() == 1


def test_sqlite_to_postgresql_copy_preserves_ids_ciphertext_and_sequences(
    postgresql_engine: Engine,
    tmp_path: Path,
) -> None:
    source_path = tmp_path / "migration-source.db"
    source_url = f"sqlite:///{source_path.as_posix()}"
    config = alembic_config()
    config.attributes["database_url"] = source_url
    command.upgrade(config, "head")
    source = create_engine(source_url)
    with Session(source) as db:
        business = Business(id=42, slug="migrated", name="Migrated")
        second_business = Business(id=43, slug="migrated-two", name="Migrated Two")
        first_user = User(id=10, email="admin@migration.test", email_verified=True)
        second_user = User(id=11, email="staff@migration.test", email_verified=True)
        db.add_all([business, second_business, first_user, second_user])
        db.flush()
        member = BusinessUser(
            id=20,
            business_id=business.id,
            user_id=first_user.id,
            role="business_admin",
            bookable=True,
        )
        service = BusinessService(
            id=30,
            business_id=business.id,
            name="Migration service",
            duration_minutes=30,
        )
        customer = Customer(id=40, business_id=business.id, name="Migration customer")
        settings = AvailabilitySettings(
            id=50,
            business_id=business.id,
            weekly_schedule_json="{}",
        )
        wallet = ConversationAutomationSettings(
            id=60,
            business_id=business.id,
            period_yyyymm="2026-07",
            included_credits_per_period=10,
            included_credits_used=1,
            additional_credits_balance=2,
        )
        integration = BusinessChannelIntegration(
            id=77,
            business_id=business.id,
            channel="instagram",
            provider="instagram",
            external_account_id="account-77",
            encrypted_access_token="ciphertext-not-plaintext",
            encryption_key_version="v1",
            integration_status="connected",
        )
        db.add_all([member, service, customer, settings, wallet, integration])
        db.flush()
        booking = Booking(
            id=80,
            business_id=business.id,
            customer_id=customer.id,
            service_id=service.id,
            staff_business_user_id=member.id,
            service_name=service.name,
            duration_minutes=30,
            start_datetime=datetime(2026, 8, 4, 10),
            end_datetime=datetime(2026, 8, 4, 10, 30),
            preferred_time="10:00",
        )
        conversation = Conversation(
            id=90,
            business_id=business.id,
            channel="instagram",
            external_user_id="migration-user",
        )
        db.add_all([booking, conversation])
        db.flush()
        message = ConversationMessage(
            id=100,
            conversation_id=conversation.id,
            direction="outbound",
            sender_type="automation",
            body="representative message",
        )
        db.add(message)
        db.flush()
        db.add_all(
            [
                AutomationCreditTransaction(
                    id=110,
                    business_id=business.id,
                    transaction_type="automatic_message_consumed",
                    amount=1,
                    included_delta=-1,
                    additional_delta=0,
                    included_balance_after=9,
                    additional_balance_after=2,
                    total_balance_after=11,
                    reason="migration test",
                    related_message_id=message.id,
                    idempotency_key="migration-credit-100",
                ),
                SystemIncident(
                    id=120,
                    incident_key="migration-incident",
                    severity="medium",
                    category="provider_timeout",
                    business_id=business.id,
                    integration_id=integration.id,
                    channel="instagram",
                    provider="instagram",
                    operation="migration_test",
                    first_occurred_at=datetime(2026, 7, 30, 10),
                    last_occurred_at=datetime(2026, 7, 30, 10),
                ),
                WebhookInboxEvent(
                    id=130,
                    provider="instagram",
                    channel="instagram",
                    idempotency_key="migration-inbox",
                    payload_hash="5" * 64,
                    payload_json='{"safe":true}',
                    payload_size_bytes=13,
                    status="retry",
                    max_attempts=5,
                    next_retry_at=datetime(2026, 7, 30, 11),
                    business_id=business.id,
                    integration_id=integration.id,
                ),
                ChannelOutboxMessage(
                    id=140,
                    business_id=business.id,
                    integration_id=integration.id,
                    conversation_id=conversation.id,
                    conversation_message_id=message.id,
                    channel="instagram",
                    provider="instagram",
                    recipient_external_id="migration-recipient",
                    payload_json='{"text":"representative"}',
                    idempotency_key="migration-outbox",
                    status="pending",
                    max_attempts=5,
                ),
                WorkerHeartbeat(
                    id=150,
                    worker_id="migration-worker",
                    worker_type="channel",
                    status="idle",
                ),
            ]
        )
        db.commit()

    require_complete_source(source)
    require_empty_destination(postgresql_engine)
    report = copy_and_validate_atomic(source, postgresql_engine)
    assert report["ciphertext_exact_match"] is True
    assert report["source"]["businesses"]["rows"] == 2
    assert report["source"]["bookings"]["rows"] == 1
    assert report["source"]["automation_credit_transactions"]["rows"] == 1
    with postgresql_engine.connect() as connection:
        assert (
            connection.execute(select(func.count()).select_from(Business.__table__)).scalar_one()
            == 2
        )
        migrated = connection.execute(
            select(
                BusinessChannelIntegration.id,
                BusinessChannelIntegration.encrypted_access_token,
            )
        ).one()
        assert migrated == (77, "ciphertext-not-plaintext")
        connection.rollback()
        transaction = connection.begin()
        next_business_id = connection.execute(
            Business.__table__.insert()
            .values(slug="sequence-probe", name="Sequence probe")
            .returning(Business.id)
        ).scalar_one()
        assert next_business_id > 43
        transaction.rollback()
    source.dispose()


def test_live_logical_lock_is_not_stolen(postgresql_engine: Engine) -> None:
    factory = sessionmaker(postgresql_engine, expire_on_commit=False)
    now = datetime.utcnow()
    with factory.begin() as db:
        db.add(
            WebhookInboxEvent(
                provider="instagram",
                channel="instagram",
                idempotency_key="live-lock",
                payload_hash="1" * 64,
                payload_json="{}",
                payload_size_bytes=2,
                status="processing",
                locked_by="live-worker",
                lock_expires_at=now + timedelta(minutes=5),
                max_attempts=5,
            )
        )
    with factory() as db:
        assert (
            claim_inbox_jobs(db, worker_id="other", limit=1, lock_timeout_seconds=60, now=now) == []
        )


def test_expired_logical_lock_is_recovered(postgresql_engine: Engine) -> None:
    factory = sessionmaker(postgresql_engine, expire_on_commit=False)
    now = datetime.utcnow()
    with factory.begin() as db:
        row = WebhookInboxEvent(
            provider="instagram",
            channel="instagram",
            idempotency_key="expired-lock",
            payload_hash="2" * 64,
            payload_json="{}",
            payload_size_bytes=2,
            status="processing",
            locked_by="dead-worker",
            lock_expires_at=now - timedelta(seconds=1),
            max_attempts=5,
        )
        db.add(row)
        db.flush()
        row_id = row.id
    with factory.begin() as db:
        assert claim_inbox_jobs(
            db, worker_id="recovery", limit=1, lock_timeout_seconds=60, now=now
        ) == [row_id]


def test_two_workers_cannot_claim_the_same_inbox_row(postgresql_engine: Engine) -> None:
    factory = sessionmaker(postgresql_engine, expire_on_commit=False)
    with factory.begin() as db:
        db.add(
            WebhookInboxEvent(
                provider="instagram",
                channel="instagram",
                idempotency_key="single-inbox",
                payload_hash="3" * 64,
                payload_json="{}",
                payload_size_bytes=2,
                status="pending",
                max_attempts=5,
            )
        )
    start = Barrier(2)
    claimed = Barrier(2)

    def worker(index: int) -> list[int]:
        with factory() as db:
            start.wait(timeout=5)
            ids = claim_inbox_jobs(db, worker_id=f"inbox-{index}", limit=1, lock_timeout_seconds=60)
            claimed.wait(timeout=5)
            db.commit()
            return ids

    with ThreadPoolExecutor(max_workers=2) as executor:
        results = list(executor.map(worker, range(2)))
    assert sorted(len(result) for result in results) == [0, 1]


def _seed_outbox(factory: sessionmaker[Session]) -> int:
    with factory.begin() as db:
        business = Business(slug="outbox-lock", name="Outbox lock")
        db.add(business)
        db.flush()
        integration = BusinessChannelIntegration(
            business_id=business.id,
            channel="instagram",
            provider="instagram",
            external_account_id="outbox-account",
            encrypted_access_token="ciphertext",
            encryption_key_version="v1",
            integration_status="connected",
        )
        conversation = Conversation(
            business_id=business.id,
            channel="instagram",
            external_user_id="outbox-user",
        )
        db.add_all([integration, conversation])
        db.flush()
        row = ChannelOutboxMessage(
            business_id=business.id,
            integration_id=integration.id,
            conversation_id=conversation.id,
            channel="instagram",
            provider="instagram",
            recipient_external_id="recipient",
            payload_json='{"text":"safe"}',
            idempotency_key="single-outbox",
            status="pending",
            max_attempts=5,
        )
        db.add(row)
        db.flush()
        return row.id


def test_two_workers_cannot_claim_the_same_outbox_row(postgresql_engine: Engine) -> None:
    factory = sessionmaker(postgresql_engine, expire_on_commit=False)
    _seed_outbox(factory)
    start = Barrier(2)
    claimed = Barrier(2)

    def worker(index: int) -> list[int]:
        with factory() as db:
            start.wait(timeout=5)
            ids = claim_outbox_jobs(
                db, worker_id=f"outbox-{index}", limit=1, lock_timeout_seconds=60
            )
            claimed.wait(timeout=5)
            db.commit()
            return ids

    with ThreadPoolExecutor(max_workers=2) as executor:
        results = list(executor.map(worker, range(2)))
    assert sorted(len(result) for result in results) == [0, 1]


def test_repeated_credit_idempotency_key_does_not_duplicate_consumption(
    postgresql_engine: Engine,
) -> None:
    factory = sessionmaker(postgresql_engine, expire_on_commit=False)
    with factory.begin() as db:
        business = Business(slug="credit-idempotent", name="Credit idempotent")
        db.add(business)
        db.flush()
        wallet = ConversationAutomationSettings(
            business_id=business.id,
            period_yyyymm="2026-07",
            included_credits_per_period=2,
        )
        conversation = Conversation(
            business_id=business.id,
            channel="instagram",
            external_user_id="idempotent-user",
        )
        db.add_all([wallet, conversation])
        db.flush()
        message = ConversationMessage(
            conversation_id=conversation.id,
            direction="outbound",
            sender_type="automation",
            body="idempotent",
        )
        db.add(message)
        db.flush()
        wallet_id, message_id = wallet.id, message.id
    start = Barrier(2)

    def consume() -> bool:
        with factory() as db:
            wallet = db.get(ConversationAutomationSettings, wallet_id)
            assert wallet is not None
            start.wait(timeout=5)
            result, _ = consume_automation_credit(
                db, settings=wallet, related_message_id=message_id
            )
            db.commit()
            return result

    with ThreadPoolExecutor(max_workers=2) as executor:
        results = [
            future.result(timeout=10) for future in [executor.submit(consume) for _ in range(2)]
        ]
    assert sorted(results) == [False, True]
    with factory() as db:
        assert db.query(AutomationCreditTransaction).count() == 1


def test_wallets_from_different_businesses_lock_in_parallel(postgresql_engine: Engine) -> None:
    factory = sessionmaker(postgresql_engine, expire_on_commit=False)
    pairs: list[tuple[int, int]] = []
    with factory.begin() as db:
        for index in range(2):
            business = Business(slug=f"wallet-{index}", name=f"Wallet {index}")
            db.add(business)
            db.flush()
            wallet = ConversationAutomationSettings(
                business_id=business.id,
                period_yyyymm="2026-07",
                included_credits_per_period=1,
            )
            conversation = Conversation(
                business_id=business.id,
                channel="instagram",
                external_user_id=f"wallet-user-{index}",
            )
            db.add_all([wallet, conversation])
            db.flush()
            message = ConversationMessage(
                conversation_id=conversation.id,
                direction="outbound",
                sender_type="automation",
                body="parallel",
            )
            db.add(message)
            db.flush()
            pairs.append((wallet.id, message.id))
    acquired = Barrier(2)

    def consume(pair: tuple[int, int]) -> bool:
        with factory() as db:
            wallet = db.get(ConversationAutomationSettings, pair[0])
            assert wallet is not None
            lock_credit_wallet(db, wallet)
            acquired.wait(timeout=5)
            result, _ = consume_automation_credit(db, settings=wallet, related_message_id=pair[1])
            db.commit()
            return result

    with ThreadPoolExecutor(max_workers=2) as executor:
        assert list(executor.map(consume, pairs)) == [True, True]


def test_bookings_for_different_businesses_advance_in_parallel(
    postgresql_engine: Engine,
) -> None:
    factory = sessionmaker(postgresql_engine, expire_on_commit=False)
    resources: list[tuple[int, int, int]] = []
    with factory.begin() as db:
        for index in range(2):
            business = Business(slug=f"booking-parallel-{index}", name=f"B {index}")
            db.add(business)
            db.flush()
            customer = Customer(business_id=business.id, name="Customer")
            service = BusinessService(business_id=business.id, name="Service", duration_minutes=30)
            db.add_all([customer, service])
            db.flush()
            resources.append((business.id, customer.id, service.id))
    acquired = Barrier(2)

    def book(resource: tuple[int, int, int]) -> bool:
        with factory() as db:
            business = db.get(Business, resource[0])
            assert business is not None
            lock_business_schedule(db, business)
            acquired.wait(timeout=5)
            db.add(
                Booking(
                    business_id=resource[0],
                    customer_id=resource[1],
                    service_id=resource[2],
                    service_name="Service",
                    duration_minutes=30,
                    start_datetime=datetime(2026, 8, 2, 10),
                    end_datetime=datetime(2026, 8, 2, 10, 30),
                    preferred_time="10:00",
                )
            )
            db.commit()
            return True

    with ThreadPoolExecutor(max_workers=2) as executor:
        assert list(executor.map(book, resources)) == [True, True]


def test_concurrent_reschedule_updates_one_booking_without_duplication(
    postgresql_engine: Engine,
) -> None:
    factory = sessionmaker(postgresql_engine, expire_on_commit=False)
    with factory.begin() as db:
        business = Business(slug="reschedule-lock", name="Reschedule")
        db.add(business)
        db.flush()
        customer = Customer(business_id=business.id, name="Customer")
        service = BusinessService(business_id=business.id, name="Service", duration_minutes=30)
        db.add_all([customer, service])
        db.flush()
        booking = Booking(
            business_id=business.id,
            customer_id=customer.id,
            service_id=service.id,
            service_name="Service",
            duration_minutes=30,
            start_datetime=datetime(2026, 8, 3, 10),
            end_datetime=datetime(2026, 8, 3, 10, 30),
            preferred_time="10:00",
        )
        db.add(booking)
        db.flush()
        booking_id, business_id = booking.id, business.id
    start = Barrier(2)

    def reschedule(hour: int) -> None:
        with factory() as db:
            business = db.get(Business, business_id)
            row = db.get(Booking, booking_id)
            assert business is not None and row is not None
            start.wait(timeout=5)
            lock_business_schedule(db, business)
            row = (
                db.query(Booking)
                .filter(Booking.id == booking_id)
                .populate_existing()
                .with_for_update()
                .one()
            )
            row.start_datetime = datetime(2026, 8, 3, hour)
            row.end_datetime = datetime(2026, 8, 3, hour, 30)
            row.preferred_time = f"{hour:02d}:00"
            db.commit()

    with ThreadPoolExecutor(max_workers=2) as executor:
        list(executor.map(reschedule, (11, 12)))
    with factory() as db:
        assert db.query(Booking).count() == 1
        assert db.get(Booking, booking_id).preferred_time in {"11:00", "12:00"}


def test_concurrent_integration_updates_keep_credentials_consistent(
    postgresql_engine: Engine,
) -> None:
    factory = sessionmaker(postgresql_engine, expire_on_commit=False)
    with factory.begin() as db:
        business = Business(slug="integration-lock", name="Integration")
        db.add(business)
        db.flush()
        integration = BusinessChannelIntegration(
            business_id=business.id,
            channel="instagram",
            provider="instagram",
            external_account_id="integration-account",
            encrypted_access_token="old",
            encryption_key_version="v0",
            integration_status="connected",
        )
        db.add(integration)
        db.flush()
        integration_id = integration.id
    start = Barrier(2)
    pairs = (("cipher-one", "v1"), ("cipher-two", "v2"))

    def update(pair: tuple[str, str]) -> None:
        with factory() as db:
            row = db.get(BusinessChannelIntegration, integration_id)
            assert row is not None
            start.wait(timeout=5)
            row = lock_instagram_integration(db, row)
            row.encrypted_access_token, row.encryption_key_version = pair
            row.integration_status = "connected"
            db.commit()

    with ThreadPoolExecutor(max_workers=2) as executor:
        list(executor.map(update, pairs))
    with factory() as db:
        row = db.get(BusinessChannelIntegration, integration_id)
        assert row is not None
        assert (row.encrypted_access_token, row.encryption_key_version) in pairs


def test_late_oauth_190_does_not_overwrite_new_credentials(
    postgresql_engine: Engine, monkeypatch
) -> None:
    factory = sessionmaker(postgresql_engine, expire_on_commit=False)
    with factory.begin() as db:
        business = Business(slug="oauth-race", name="OAuth race")
        db.add(business)
        db.flush()
        integration = BusinessChannelIntegration(
            business_id=business.id,
            channel="instagram",
            provider="instagram",
            external_account_id="oauth-account",
            encrypted_access_token="old-cipher",
            encryption_key_version="v1",
            integration_status="connected",
        )
        db.add(integration)
        db.flush()
        integration_id = integration.id
    provider_started = Event()
    provider_release = Event()

    def delayed_failure(*_args, **_kwargs) -> InstagramVerificationResult:
        provider_started.set()
        assert provider_release.wait(timeout=5)
        return InstagramVerificationResult(ok=False, error_code="190", error_subcode="463")

    monkeypatch.setattr(
        "app.services.instagram_integration_service.verify_instagram_access_token",
        delayed_failure,
    )

    def verify_old_token() -> None:
        with factory() as db:
            row = db.get(BusinessChannelIntegration, integration_id)
            assert row is not None
            verify_instagram_integration(db, row, access_token="old-token")
            db.commit()

    with ThreadPoolExecutor(max_workers=1) as executor:
        future = executor.submit(verify_old_token)
        assert provider_started.wait(timeout=5)
        with factory.begin() as db:
            row = db.get(BusinessChannelIntegration, integration_id)
            assert row is not None
            row.encrypted_access_token = "new-cipher"
            row.encryption_key_version = "v2"
            row.token_last_refreshed_at = datetime.utcnow()
            row.integration_status = "connected"
        provider_release.set()
        future.result(timeout=10)
    with factory() as db:
        row = db.get(BusinessChannelIntegration, integration_id)
        assert row is not None
        assert row.integration_status == "connected"
        assert row.encrypted_access_token == "new-cipher"


def test_deadlock_is_detected_and_classified(postgresql_engine: Engine) -> None:
    factory = sessionmaker(postgresql_engine, expire_on_commit=False)
    with factory.begin() as db:
        first = Business(slug="deadlock-one", name="One")
        second = Business(slug="deadlock-two", name="Two")
        db.add_all([first, second])
        db.flush()
        ids = (first.id, second.id)
    locked_first = Barrier(2)

    def lock_opposite(order: tuple[int, int]) -> str:
        with factory() as db:
            db.execute(select(Business).where(Business.id == order[0]).with_for_update()).one()
            locked_first.wait(timeout=5)
            try:
                db.execute(select(Business).where(Business.id == order[1]).with_for_update()).one()
                db.commit()
                return "completed"
            except DBAPIError as exc:
                classification = classify_database_error(exc)
                db.rollback()
                return classification.code

    with ThreadPoolExecutor(max_workers=2) as executor:
        results = list(executor.map(lock_opposite, (ids, tuple(reversed(ids)))))
    assert "deadlock_detected" in results
    assert "completed" in results


def test_lock_timeout_is_classified_from_real_postgresql_error(
    postgresql_engine: Engine,
) -> None:
    factory = sessionmaker(postgresql_engine, expire_on_commit=False)
    with factory.begin() as db:
        business = Business(slug="timeout-lock", name="Timeout")
        db.add(business)
        db.flush()
        business_id = business.id
    first = factory()
    second = factory()
    try:
        first.execute(select(Business).where(Business.id == business_id).with_for_update()).one()
        second.execute(text("SET LOCAL lock_timeout = '200ms'"))
        with pytest.raises(DBAPIError) as caught:
            second.execute(
                select(Business).where(Business.id == business_id).with_for_update()
            ).one()
        assert classify_database_error(caught.value).code == "lock_timeout"
        second.rollback()
    finally:
        first.rollback()
        first.close()
        second.close()


def test_worker_rollback_releases_claimed_row(postgresql_engine: Engine) -> None:
    factory = sessionmaker(postgresql_engine, expire_on_commit=False)
    with factory.begin() as db:
        row = WebhookInboxEvent(
            provider="instagram",
            channel="instagram",
            idempotency_key="rollback-claim",
            payload_hash="4" * 64,
            payload_json="{}",
            payload_size_bytes=2,
            status="pending",
            max_attempts=5,
        )
        db.add(row)
        db.flush()
        row_id = row.id
    first = factory()
    try:
        assert claim_inbox_jobs(
            first, worker_id="rollback-worker", limit=1, lock_timeout_seconds=60
        ) == [row_id]
        first.rollback()
    finally:
        first.close()
    with factory.begin() as second:
        assert claim_inbox_jobs(
            second, worker_id="next-worker", limit=1, lock_timeout_seconds=60
        ) == [row_id]


def test_sessions_do_not_share_uncommitted_state(postgresql_engine: Engine) -> None:
    factory = sessionmaker(postgresql_engine, expire_on_commit=False)
    with factory.begin() as db:
        business = Business(slug="session-isolation", name="Original")
        db.add(business)
        db.flush()
        business_id = business.id
    first = factory()
    second = factory()
    try:
        first_row = first.get(Business, business_id)
        assert first_row is not None
        first_row.name = "Uncommitted"
        first.flush()
        second_row = second.get(Business, business_id)
        assert second_row is not None
        assert second_row.name == "Original"
        first.rollback()
    finally:
        first.close()
        second.close()


def test_migration_rejects_nonempty_or_partial_destination(postgresql_engine: Engine) -> None:
    with postgresql_engine.begin() as connection:
        connection.execute(Business.__table__.insert().values(slug="partial", name="Partial"))
    with pytest.raises(RuntimeError, match="partially migrated"):
        require_empty_destination(postgresql_engine)


def test_migration_rejects_destination_without_alembic_head(
    postgresql_engine: Engine,
) -> None:
    system_url = postgresql_engine.url.set(database="postgres")
    system_engine = create_engine(system_url)
    try:
        with pytest.raises(RuntimeError, match="not at the single Alembic head"):
            require_destination_at_head(system_engine)
    finally:
        system_engine.dispose()


def test_migration_rejects_invalid_foreign_keys_and_missing_ciphertext(
    postgresql_engine: Engine,
    tmp_path: Path,
) -> None:
    del postgresql_engine
    invalid_fk_path = tmp_path / "invalid-fk.db"
    invalid_fk_url = f"sqlite:///{invalid_fk_path.as_posix()}"
    config = alembic_config()
    config.attributes["database_url"] = invalid_fk_url
    command.upgrade(config, "head")
    invalid_fk_engine = create_engine(invalid_fk_url)
    with invalid_fk_engine.begin() as connection:
        connection.execute(
            BusinessChannelIntegration.__table__.insert().values(
                business_id=99999,
                channel="instagram",
                provider="instagram",
                external_account_id="orphan",
                encrypted_access_token="cipher",
                encryption_key_version="v1",
                integration_status="connected",
            )
        )
    with pytest.raises(RuntimeError, match="foreign-key validation failed"):
        require_complete_source(invalid_fk_engine)
    invalid_fk_engine.dispose()

    missing_cipher_path = tmp_path / "missing-cipher.db"
    missing_cipher_url = f"sqlite:///{missing_cipher_path.as_posix()}"
    config = alembic_config()
    config.attributes["database_url"] = missing_cipher_url
    command.upgrade(config, "head")
    missing_cipher_engine = create_engine(missing_cipher_url)
    with missing_cipher_engine.begin() as connection:
        business_id = connection.execute(
            Business.__table__.insert()
            .values(slug="missing-cipher", name="Missing cipher")
            .returning(Business.id)
        ).scalar_one()
        connection.execute(
            BusinessChannelIntegration.__table__.insert().values(
                business_id=business_id,
                channel="instagram",
                provider="instagram",
                external_account_id="missing-cipher-account",
                integration_status="connected",
            )
        )
    with pytest.raises(RuntimeError, match="without complete ciphertext"):
        require_complete_source(missing_cipher_engine)
    missing_cipher_engine.dispose()
