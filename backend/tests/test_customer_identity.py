from datetime import date, datetime, timedelta

import pytest
from alembic import command
from fastapi import HTTPException
from sqlalchemy import create_engine, inspect
from sqlalchemy.orm import Session, sessionmaker
from starlette.requests import Request

from app.core.database import Base
from app.core.migration_state import alembic_config
from app.models import Booking, Business, Customer, CustomerAccountLink, User
from app.models.registry import register_models
from app.routers.customer import (
    BookingClaimRequest,
    CustomerProfileUpdate,
    claim_guest_booking,
    customer_home,
    update_customer_profile,
)
from app.services.booking_manage_token_service import hash_booking_manage_token
from app.services.booking_service import get_or_create_customer, serialize_booking
from app.services.customer_identity_service import (
    link_customer_account,
    normalize_instagram_username,
    normalize_phone,
)
from app.services.customer_memory_service import CustomerMemoryService


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


def seed_business(db: Session, slug: str) -> Business:
    business = Business(slug=slug, name=slug.replace("-", " ").title(), status="active")
    db.add(business)
    db.flush()
    return business


def seed_booking(
    db: Session,
    *,
    business: Business,
    customer: Customer,
    start: datetime,
    user: User | None = None,
    token: str = "booking-token-that-is-long-enough",
) -> Booking:
    booking = Booking(
        business_id=business.id,
        customer_id=customer.id,
        customer_user_id=user.id if user else None,
        customer_email=user.email if user else None,
        service_name="Corte",
        duration_minutes=45,
        start_datetime=start,
        end_datetime=start + timedelta(minutes=45),
        preferred_date=start.date().isoformat(),
        preferred_time=start.strftime("%H:%M"),
        status="confirmed",
    )
    if user is None:
        booking.public_manage_token_hash = hash_booking_manage_token(token)
        booking.public_manage_token_expires_at = datetime.now() + timedelta(days=30)
    db.add(booking)
    db.flush()
    return booking


@pytest.mark.parametrize(
    "raw",
    (
        "+34612345678",
        "34612345678",
        "0034612345678",
        "612345678",
        "612 345 678",
        "+34 612 345 678",
        "(612) 345 678",
    ),
)
def test_spanish_phone_formats_converge_to_e164(raw: str) -> None:
    assert normalize_phone(raw, region="ES") == "+34612345678"


def test_international_phone_invalid_input_and_verification_are_separate(db: Session) -> None:
    assert normalize_phone("+4915123456789", region="ES") == "+4915123456789"
    assert normalize_phone("123", region="ES") is None
    user = User(email="phone@example.test", phone="612345678", phone_verified=False)
    db.add(user)
    db.commit()
    updated = update_customer_profile(
        CustomerProfileUpdate(phone="+34 612 345 678"), user=user, db=db
    )
    assert updated["profile"]["phone_normalized"] == "+34612345678"
    assert updated["profile"]["phone_verified"] is False


def test_instagram_normalization_is_optional_and_never_verifies_manually(db: Session) -> None:
    for raw in ("@Maria.Garcia", "maria.garcia", "https://instagram.com/maria.garcia"):
        assert normalize_instagram_username(raw) == "maria.garcia"
    assert normalize_instagram_username("https://evil.test/maria") is None
    user = User(email="ig@example.test", instagram_verified=True)
    db.add(user)
    db.commit()
    result = update_customer_profile(
        CustomerProfileUpdate(instagram_username="@maria.garcia"), user=user, db=db
    )
    assert result["profile"]["instagram_username"] == "maria.garcia"
    assert result["profile"]["instagram_verified"] is False


def test_phone_matching_reuses_customer_but_name_and_instagram_do_not_link(db: Session) -> None:
    business = seed_business(db, "phone-match")
    existing = Customer(business_id=business.id, name="María", phone="612 345 678")
    same_name = Customer(business_id=business.id, name="María", phone=None)
    db.add_all((existing, same_name))
    db.flush()
    resolved = get_or_create_customer(
        db,
        business_id=business.id,
        name="María G.",
        phone="+34612345678",
        notes=None,
        region="ES",
    )
    assert resolved.id == existing.id
    assert resolved.phone_normalized == "+34612345678"
    assert db.query(Customer).filter(Customer.business_id == business.id).count() == 2


def test_name_only_and_ambiguous_phone_never_merge_customers(db: Session) -> None:
    business = seed_business(db, "ambiguous-match")
    same_name = Customer(business_id=business.id, name="María", phone=None)
    first_phone = Customer(
        business_id=business.id,
        name="Primera",
        phone="612 345 678",
        phone_normalized="+34612345678",
    )
    second_phone = Customer(
        business_id=business.id,
        name="Segunda",
        phone=None,
        phone_normalized="+34612345678",
    )
    db.add_all((same_name, first_phone, second_phone))
    db.flush()

    name_only = get_or_create_customer(
        db,
        business_id=business.id,
        name="María",
        phone=None,
        notes=None,
    )
    ambiguous_phone = get_or_create_customer(
        db,
        business_id=business.id,
        name="Otra persona",
        phone="+34 612 345 678",
        notes=None,
    )

    assert name_only.id not in {same_name.id, first_phone.id, second_phone.id}
    assert ambiguous_phone.id not in {same_name.id, first_phone.id, second_phone.id}
    assert name_only.id != ambiguous_phone.id


def test_registered_customer_stays_stable_when_booking_contact_changes(db: Session) -> None:
    business = seed_business(db, "stable-account")
    user = User(email="stable@example.test", name="Nombre de cuenta", email_verified=True)
    db.add(user)
    db.flush()
    customer = get_or_create_customer(
        db,
        business_id=business.id,
        name="Nombre inicial",
        phone="612345678",
        notes=None,
        current_user=user,
    )
    first_booking = seed_booking(
        db,
        business=business,
        customer=customer,
        start=datetime.now(),
        user=user,
    )
    memory, _ = CustomerMemoryService(db).create_manual(
        business_id=business.id,
        customer_id=customer.id,
        category="operational_note",
        key="note",
        value="Historial estable",
        created_by_user_id=user.id,
    )

    resolved = get_or_create_customer(
        db,
        business_id=business.id,
        name="Nombre actualizado",
        phone="611222333",
        notes=None,
        current_user=user,
    )
    second_booking = seed_booking(
        db,
        business=business,
        customer=resolved,
        start=datetime.now() + timedelta(days=1),
        user=user,
        token="second-stable-booking-token-long-enough",
    )
    db.commit()

    assert resolved.id == customer.id
    assert first_booking.customer_id == second_booking.customer_id == customer.id
    assert resolved.name == "Nombre actualizado"
    assert resolved.phone_normalized == "+34611222333"
    assert db.query(Customer).filter_by(business_id=business.id).count() == 1
    assert serialize_booking(first_booking)["customer_memory_eligible"] is True
    assert serialize_booking(second_booking)["customer_memory_eligible"] is True
    assert CustomerMemoryService(db).list_items(
        business_id=business.id,
        customer_id=resolved.id,
        status="active",
    ) == [memory]


def test_unique_phone_reuses_registered_customer_without_replacing_account_link(
    db: Session,
) -> None:
    business = seed_business(db, "registered-phone")
    user = User(email="owner-of-phone@example.test")
    registered = Customer(
        business_id=business.id,
        name="Cliente registrado",
        phone="612345678",
        phone_normalized="+34612345678",
    )
    db.add_all((user, registered))
    db.flush()
    link_customer_account(db, user=user, customer=registered, method="explicit")

    recognized = get_or_create_customer(
        db,
        business_id=business.id,
        name="Reserva sin sesión",
        phone="612 345 678",
        notes=None,
    )
    recognized_booking = seed_booking(
        db,
        business=business,
        customer=recognized,
        start=datetime.now(),
    )

    assert recognized.id == registered.id
    assert registered.account_link.user_id == user.id
    assert db.query(CustomerAccountLink).filter_by(customer_id=registered.id).count() == 1
    assert serialize_booking(recognized_booking)["customer_memory_eligible"] is True

    other_user = User(email="different-account@example.test")
    db.add(other_user)
    db.flush()
    other_customer = get_or_create_customer(
        db,
        business_id=business.id,
        name="Otra cuenta autenticada",
        phone="612345678",
        notes=None,
        current_user=other_user,
    )
    assert other_customer.id != registered.id
    assert other_customer.account_link.user_id == other_user.id
    assert registered.account_link.user_id == user.id


def test_profile_contact_edit_updates_linked_customer_without_replacing_it(db: Session) -> None:
    business = seed_business(db, "profile-sync")
    user = User(
        email="profile-sync@example.test",
        name="Nombre legal",
        preferred_name="Antes",
        phone="612345678",
        phone_normalized="+34612345678",
    )
    customer = Customer(
        business_id=business.id,
        name="Antes",
        phone="612345678",
        phone_normalized="+34612345678",
    )
    db.add_all((user, customer))
    db.flush()
    link_customer_account(db, user=user, customer=customer, method="explicit")
    customer_id = customer.id

    result = update_customer_profile(
        CustomerProfileUpdate(preferred_name="Después", phone="611222333"),
        user=user,
        db=db,
    )

    db.refresh(customer)
    assert result["profile"]["phone_normalized"] == "+34611222333"
    assert customer.id == customer_id
    assert customer.name == "Después"
    assert customer.phone_normalized == "+34611222333"
    assert customer.email == user.email
    assert db.query(Customer).filter_by(business_id=business.id).count() == 1


def test_links_are_one_customer_per_account_and_business_and_reject_conflicts(db: Session) -> None:
    business = seed_business(db, "links")
    first = Customer(business_id=business.id, name="Primera", phone=None)
    second = Customer(business_id=business.id, name="Segunda", phone=None)
    user = User(email="one@example.test")
    other_user = User(email="two@example.test")
    db.add_all((first, second, user, other_user))
    db.flush()
    link = link_customer_account(db, user=user, customer=first, method="explicit_test")
    assert link.business_id == business.id
    with pytest.raises(ValueError, match="identity_conflict"):
        link_customer_account(db, user=user, customer=second, method="weak_name")
    with pytest.raises(ValueError, match="identity_conflict"):
        link_customer_account(db, user=other_user, customer=first, method="manual_instagram")


def test_linked_account_phone_collision_never_merges_or_breaks_unique_customer(db: Session) -> None:
    business = seed_business(db, "phone-conflict")
    linked = Customer(business_id=business.id, name="Cuenta", phone="600000001")
    other = Customer(business_id=business.id, name="Otra", phone="612345678")
    user = User(email="linked@example.test")
    db.add_all((linked, other, user))
    db.flush()
    link_customer_account(db, user=user, customer=linked, method="explicit")
    resolved = get_or_create_customer(
        db,
        business_id=business.id,
        name="Cuenta",
        phone="612345678",
        notes=None,
        region="ES",
        current_user=user,
    )
    db.commit()
    assert resolved.id == linked.id
    assert resolved.phone is None
    assert user.phone_normalized == "+34612345678"
    assert db.query(Customer).filter(Customer.business_id == business.id).count() == 2


def test_explicit_booking_claim_links_guest_booking_and_masks_wrong_token(db: Session) -> None:
    business = seed_business(db, "claim")
    customer = Customer(
        business_id=business.id,
        name="Cliente",
        phone="612345678",
        phone_normalized="+34612345678",
    )
    user = User(email="claim@example.test", email_verified=True)
    db.add_all((customer, user))
    db.flush()
    booking = seed_booking(db, business=business, customer=customer, start=datetime.now())
    request = Request(
        {"type": "http", "method": "POST", "path": "/api/customer/claim-booking", "headers": []}
    )
    with pytest.raises(HTTPException) as hidden:
        claim_guest_booking(
            BookingClaimRequest(booking_id=booking.id, manage_token="wrong-token-that-is-long"),
            request=request,
            user=user,
            db=db,
        )
    assert hidden.value.status_code == 404
    result = claim_guest_booking(
        BookingClaimRequest(
            booking_id=booking.id,
            manage_token="booking-token-that-is-long-enough",
        ),
        request=request,
        user=user,
        db=db,
    )
    assert result == {"ok": True}
    assert booking.customer_user_id == user.id
    assert db.query(CustomerAccountLink).filter_by(customer_id=customer.id).one().user_id == user.id
    assert user.phone_normalized == "+34612345678"
    assert user.phone_verified is False


def test_customer_home_is_cross_business_for_owner_only_and_range_bounded(db: Session) -> None:
    first_business = seed_business(db, "first-place")
    second_business = seed_business(db, "second-place")
    user = User(email="global@example.test", email_verified=True, preferred_name="María García")
    stranger = User(email="stranger@example.test", email_verified=True)
    first_customer = Customer(business_id=first_business.id, name="María", phone=None)
    second_customer = Customer(business_id=second_business.id, name="María", phone=None)
    foreign_customer = Customer(business_id=second_business.id, name="Otra", phone=None)
    db.add_all((user, stranger, first_customer, second_customer, foreign_customer))
    db.flush()
    link_customer_account(db, user=user, customer=first_customer, method="explicit")
    tomorrow = datetime.now() + timedelta(days=1)
    first = seed_booking(db, business=first_business, customer=first_customer, start=tomorrow)
    second = seed_booking(
        db,
        business=second_business,
        customer=second_customer,
        start=tomorrow + timedelta(hours=2),
        user=user,
        token="second-booking-token-long-enough",
    )
    seed_booking(
        db,
        business=second_business,
        customer=foreign_customer,
        start=tomorrow + timedelta(hours=4),
        user=stranger,
        token="foreign-booking-token-long-enough",
    )
    db.commit()
    result = customer_home(
        from_date=date.today(),
        to_date=date.today() + timedelta(days=7),
        user=user,
        db=db,
    )
    assert {item["id"] for item in result["bookings"]} == {first.id, second.id}
    assert result["next_booking"]["business_slug"] == "first-place"
    with pytest.raises(HTTPException) as invalid_range:
        customer_home(
            from_date=date.today(),
            to_date=date.today() + timedelta(days=63),
            user=user,
            db=db,
        )
    assert invalid_range.value.status_code == 422


def test_customer_identity_migration_upgrade_and_downgrade(tmp_path) -> None:
    database_url = f"sqlite:///{(tmp_path / 'customer-identity.db').as_posix()}"
    config = alembic_config()
    config.attributes["database_url"] = database_url
    command.upgrade(config, "20260816_21")
    command.upgrade(config, "20260821_22")
    engine = create_engine(database_url)
    inspector = inspect(engine)
    assert "customer_account_links" in inspector.get_table_names()
    assert {"phone_normalized", "instagram_username", "instagram_verified"} <= {
        item["name"] for item in inspector.get_columns("users")
    }
    engine.dispose()
    command.downgrade(config, "20260816_21")
    engine = create_engine(database_url)
    inspector = inspect(engine)
    assert "customer_account_links" not in inspector.get_table_names()
    assert "phone_normalized" not in {item["name"] for item in inspector.get_columns("users")}
    engine.dispose()
