from __future__ import annotations

import asyncio
import hashlib
import json
from datetime import datetime, timedelta
from io import BytesIO

import pytest
from alembic import command
from fastapi import HTTPException, UploadFile
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.orm import Session, sessionmaker
from starlette.datastructures import Headers
from starlette.requests import Request

from app.core.audit import record_audit
from app.core.migration_state import alembic_config
from app.middleware.rate_limit import RateLimitMiddleware
from app.models import AuditLog, Booking, Business, Customer, CustomerAccountLink, User
from app.models.registry import register_models
from app.routers.attachments import (
    can_access_booking_attachments,
    get_booking_attachment_content,
    list_booking_attachments,
    upload_booking_attachments,
)
from app.routers.customer import BookingClaimRequest, claim_guest_booking
from app.services.booking_manage_token_service import (
    TOKEN_MAX_AGE,
    as_utc_naive,
    booking_manage_token_is_valid,
    create_booking_manage_token,
    refresh_booking_manage_token_expiry,
    revoke_booking_manage_token,
)


@pytest.fixture
def db() -> Session:
    register_models()
    engine = create_engine("sqlite:///:memory:")
    from app.core.database import Base

    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine, expire_on_commit=False)()
    try:
        yield session
    finally:
        session.close()
        engine.dispose()


def seed_booking(
    db: Session,
    *,
    slug: str,
    start: datetime,
    status: str = "confirmed",
    customer_user: User | None = None,
) -> Booking:
    business = Business(slug=slug, name=slug, status="active")
    customer = Customer(business=business, name=f"Customer {slug}")
    booking = Booking(
        business=business,
        customer=customer,
        customer_user=customer_user,
        service_name="Service",
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


def claim_request() -> Request:
    return Request(
        {
            "type": "http",
            "method": "POST",
            "path": "/api/customer/claim-booking",
            "headers": [],
            "client": ("test", 50000),
        }
    )


def test_generation_hashes_random_guest_bearers_and_caps_expiry(db: Session) -> None:
    now = datetime(2026, 9, 1, 12)
    first = seed_booking(db, slug="first", start=now + timedelta(days=300))
    second = seed_booking(db, slug="second", start=now + timedelta(days=1))

    first_token = create_booking_manage_token(first, now=now)
    second_token = create_booking_manage_token(second, now=now)

    assert first_token != second_token
    assert len(first_token) >= 40
    assert first.public_manage_token_hash == hashlib.sha256(first_token.encode()).hexdigest()
    assert first.public_manage_token_hash != first_token
    assert len(first.public_manage_token_hash) == 64
    assert first.public_manage_token_expires_at == now + TOKEN_MAX_AGE
    assert second.public_manage_token_expires_at == as_utc_naive(
        second.end_datetime, second.business.timezone
    ) + timedelta(days=7)


def test_validation_is_expiring_revocable_and_booking_and_business_scoped(db: Session) -> None:
    now = datetime(2026, 9, 1, 12)
    first = seed_booking(db, slug="business-a", start=now + timedelta(days=1))
    second = seed_booking(db, slug="business-b", start=now + timedelta(days=1))
    first_token = create_booking_manage_token(first, now=now)
    second_token = create_booking_manage_token(second, now=now)

    assert booking_manage_token_is_valid(first, first_token, now=now)
    assert not booking_manage_token_is_valid(first, second_token, now=now)
    assert not booking_manage_token_is_valid(second, first_token, now=now)
    assert not booking_manage_token_is_valid(first, "wrong-token-that-is-long-enough", now=now)

    first.public_manage_token_expires_at = now
    assert not booking_manage_token_is_valid(first, first_token, now=now)
    first.public_manage_token_expires_at = now + timedelta(days=1)
    assert revoke_booking_manage_token(first, now=now)
    assert not revoke_booking_manage_token(first, now=now)
    assert not booking_manage_token_is_valid(first, first_token, now=now)

    second.business.status = "archived"
    assert not booking_manage_token_is_valid(second, second_token, now=now)


def test_reschedule_refresh_never_resurrects_an_expired_token(db: Session) -> None:
    now = datetime(2026, 9, 1, 12)
    booking = seed_booking(db, slug="expired-reschedule", start=now + timedelta(days=1))
    create_booking_manage_token(booking, now=now - timedelta(days=10))
    expired_at = now - timedelta(seconds=1)
    booking.public_manage_token_expires_at = expired_at
    booking.end_datetime = now + timedelta(days=30)

    refresh_booking_manage_token_expiry(booking, now=now)

    assert booking.public_manage_token_expires_at == expired_at


@pytest.mark.parametrize("status", ["rejected", "cancelled", "completed", "no_show"])
def test_terminal_booking_states_reject_guest_token(db: Session, status: str) -> None:
    now = datetime(2026, 9, 1, 12)
    booking = seed_booking(db, slug=f"terminal-{status}", start=now, status=status)
    token = create_booking_manage_token(booking, now=now - timedelta(hours=1))
    assert not booking_manage_token_is_valid(booking, token, now=now)


def test_claim_revokes_guest_bearer_preserves_strong_ownership_and_sanitizes_audit(
    db: Session,
) -> None:
    now = datetime.now()
    user = User(email="claim-owner@example.test", email_verified=True, is_active=True)
    stranger = User(email="stranger@example.test", is_active=True)
    db.add_all((user, stranger))
    db.flush()
    booking = seed_booking(db, slug="claim-business", start=now + timedelta(days=1))
    token = create_booking_manage_token(booking, now=now)
    db.commit()

    result = claim_guest_booking(
        BookingClaimRequest(booking_id=booking.id, manage_token=token),
        request=claim_request(),
        user=user,
        db=db,
    )

    assert result == {"ok": True}
    assert booking.customer_user_id == user.id
    assert booking.public_manage_token_revoked_at is not None
    assert not booking_manage_token_is_valid(booking, token, now=now)
    assert (
        db.query(CustomerAccountLink)
        .filter_by(
            user_id=user.id,
            customer_id=booking.customer_id,
            business_id=booking.business_id,
        )
        .one()
    )
    assert can_access_booking_attachments(db, booking=booking, user=user, booking_token=None)
    assert not can_access_booking_attachments(
        db, booking=booking, user=stranger, booking_token=token
    )
    serialized_audits = "\n".join(item.metadata_json or "" for item in db.query(AuditLog))
    assert token not in serialized_audits
    assert booking.public_manage_token_hash not in serialized_audits
    assert {item.action for item in db.query(AuditLog)} >= {
        "manage_token_revoked",
        "customer_booking_claimed",
    }


def test_attachment_authorization_uses_same_guest_lifecycle_and_cross_scope(db: Session) -> None:
    now = datetime(2026, 9, 1, 12)
    booking = seed_booking(db, slug="attachments-a", start=now + timedelta(days=1))
    foreign = seed_booking(db, slug="attachments-b", start=now + timedelta(days=1))
    token = create_booking_manage_token(booking, now=now)
    create_booking_manage_token(foreign, now=now)

    assert can_access_booking_attachments(db, booking=booking, user=None, booking_token=token)
    assert not can_access_booking_attachments(db, booking=foreign, user=None, booking_token=token)
    for booking_id in (foreign.id, 999999):
        with pytest.raises(HTTPException) as hidden:
            list_booking_attachments(
                foreign.business.slug,
                booking_id,
                db=db,
                current_user=None,
                booking_token=token,
            )
        assert (hidden.value.status_code, hidden.value.detail) == (
            404,
            "El enlace ya no es válido.",
        )
    booking.public_manage_token_expires_at = datetime.utcnow() - timedelta(seconds=1)
    assert not can_access_booking_attachments(db, booking=booking, user=None, booking_token=token)


def test_guest_token_controls_attachment_upload_metadata_and_download(
    db: Session, tmp_path, monkeypatch
) -> None:
    now = datetime.now()
    booking = seed_booking(db, slug="attachment-flow", start=now + timedelta(days=1))
    token = create_booking_manage_token(booking, now=now)
    db.commit()
    monkeypatch.setattr("app.routers.attachments.get_uploads_dir", lambda: tmp_path)
    request = Request(
        {
            "type": "http",
            "method": "POST",
            "path": f"/api/businesses/{booking.business.slug}/bookings/{booking.id}/attachments",
            "headers": [],
            "client": ("test", 50000),
        }
    )
    image = UploadFile(
        file=BytesIO(b"\x89PNG\r\n\x1a\nvalid"),
        filename="guest.png",
        headers=Headers({"content-type": "image/png"}),
    )

    uploaded = asyncio.run(
        upload_booking_attachments(
            booking.business.slug,
            booking.id,
            request,
            [image],
            db=db,
            current_user=None,
            booking_token=token,
        )
    )
    attachment_id = uploaded["attachments"][0]["id"]
    metadata = list_booking_attachments(
        booking.business.slug,
        booking.id,
        db=db,
        current_user=None,
        booking_token=token,
    )
    assert metadata["attachments"][0]["id"] == attachment_id
    response = get_booking_attachment_content(
        booking.business.slug,
        booking.id,
        attachment_id,
        db=db,
        current_user=None,
        booking_token=token,
    )
    assert response.path.suffix == ".png"

    db.query(Booking).filter(Booking.id == booking.id).update(
        {Booking.public_manage_token_expires_at: datetime.utcnow() - timedelta(seconds=1)}
    )
    db.commit()
    db.expire_all()
    assert booking.public_manage_token_expires_at <= datetime.utcnow()
    assert not booking_manage_token_is_valid(booking, token)
    with pytest.raises(HTTPException) as expired:
        list_booking_attachments(
            booking.business.slug,
            booking.id,
            db=db,
            current_user=None,
            booking_token=token,
        )
    assert (expired.value.status_code, expired.value.detail) == (
        404,
        "El enlace ya no es válido.",
    )
    booking.public_manage_token_expires_at = now + timedelta(days=1)
    revoke_booking_manage_token(booking, now=now)
    assert not can_access_booking_attachments(db, booking=booking, user=None, booking_token=token)


def test_unknown_booking_and_wrong_token_return_same_claim_response(db: Session) -> None:
    user = User(email="masked@example.test", is_active=True)
    db.add(user)
    db.flush()
    booking = seed_booking(db, slug="masked-booking", start=datetime.now() + timedelta(days=1))
    create_booking_manage_token(booking)
    db.commit()
    payloads = (
        BookingClaimRequest(booking_id=999999, manage_token="unknown-token-that-is-long-enough"),
        BookingClaimRequest(
            booking_id=booking.id,
            manage_token="unknown-token-that-is-long-enough",
        ),
    )
    for payload in payloads:
        with pytest.raises(HTTPException) as hidden:
            claim_guest_booking(payload, request=claim_request(), user=user, db=db)
        assert (hidden.value.status_code, hidden.value.detail) == (
            404,
            "El enlace ya no es válido.",
        )


def test_manage_token_surfaces_use_existing_rate_limit_infrastructure() -> None:
    assert RateLimitMiddleware.policy("/api/customer/claim-booking", "POST") == (
        "booking-manage",
        30,
        60,
    )
    assert RateLimitMiddleware.policy("/api/businesses/demo/bookings/1/attachments", "GET") == (
        "booking-manage",
        60,
        60,
    )
    assert RateLimitMiddleware.policy("/api/businesses/demo/bookings/1/attachments", "POST") == (
        "upload",
        30,
        60,
    )


def test_audit_metadata_defensively_redacts_manage_token_and_hash(db: Session) -> None:
    token = "never-persist-this-guest-bearer"
    item = record_audit(
        db,
        action="manage_token_test",
        metadata={
            "manage_token": token,
            "public_manage_token_hash": hashlib.sha256(token.encode()).hexdigest(),
            "reason": "test",
        },
    )

    assert json.loads(item.metadata_json) == {
        "manage_token": "[REDACTED]",
        "public_manage_token_hash": "[REDACTED]",
        "reason": "test",
    }


def test_legacy_migration_hashes_active_and_revokes_claimed_and_terminal_tokens(
    tmp_path,
) -> None:
    database_url = f"sqlite:///{(tmp_path / 'manage-token-migration.db').as_posix()}"
    config = alembic_config()
    config.attributes["database_url"] = database_url
    command.upgrade(config, "20260901_30")
    engine = create_engine(database_url)
    now = datetime(2026, 9, 1, 12)
    with engine.begin() as connection:
        connection.execute(
            text(
                "INSERT INTO businesses (id, slug, name, status, created_at, updated_at) "
                "VALUES (1, 'legacy', 'Legacy', 'active', :now, :now)"
            ),
            {"now": now},
        )
        connection.execute(
            text(
                "INSERT INTO customers (id, business_id, name, status, created_at, updated_at) "
                "VALUES (1, 1, 'Guest', 'active', :now, :now)"
            ),
            {"now": now},
        )
        connection.execute(
            text(
                "INSERT INTO users (id, email, email_verified, is_active, is_owner, "
                "phone_verified, instagram_verified, created_at, updated_at) "
                "VALUES (1, 'claimed@legacy.test', 1, 1, 0, 0, 0, :now, :now)"
            ),
            {"now": now},
        )
        booking_sql = text(
            "INSERT INTO bookings (id, business_id, customer_id, customer_user_id, "
            "public_manage_token, created_by_user, service_name, start_datetime, end_datetime, "
            "preferred_time, status, source, google_sync_status, created_at, updated_at) "
            "VALUES (:id, 1, 1, :user_id, :token, 0, 'Legacy service', :start, :end, "
            "'12:00', :status, 'legacy', 'pending', :now, :now)"
        )
        for values in (
            {"id": 1, "user_id": None, "token": "active-legacy-token", "status": "confirmed"},
            {"id": 2, "user_id": 1, "token": "claimed-legacy-token", "status": "confirmed"},
            {"id": 3, "user_id": None, "token": "terminal-legacy-token", "status": "completed"},
        ):
            connection.execute(
                booking_sql,
                {
                    **values,
                    "start": now + timedelta(days=1),
                    "end": now + timedelta(days=1, minutes=45),
                    "now": now,
                },
            )
    engine.dispose()

    command.upgrade(config, "20260901_31")
    engine = create_engine(database_url)
    assert "public_manage_token" not in {
        column["name"] for column in inspect(engine).get_columns("bookings")
    }
    with engine.connect() as connection:
        rows = (
            connection.execute(
                text(
                    "SELECT id, public_manage_token_hash, public_manage_token_expires_at, "
                    "public_manage_token_revoked_at FROM bookings ORDER BY id"
                )
            )
            .mappings()
            .all()
        )
    assert rows[0]["public_manage_token_hash"] == hashlib.sha256(b"active-legacy-token").hexdigest()
    assert rows[0]["public_manage_token_revoked_at"] is None
    assert rows[0]["public_manage_token_expires_at"] is not None
    assert rows[1]["public_manage_token_revoked_at"] is not None
    assert rows[2]["public_manage_token_revoked_at"] is not None
    engine.dispose()

    command.downgrade(config, "20260901_30")
    engine = create_engine(database_url)
    downgraded_columns = {column["name"] for column in inspect(engine).get_columns("bookings")}
    assert "public_manage_token" in downgraded_columns
    assert "public_manage_token_hash" not in downgraded_columns
    with engine.connect() as connection:
        assert (
            connection.execute(
                text("SELECT count(*) FROM bookings WHERE public_manage_token IS NOT NULL")
            ).scalar_one()
            == 0
        )
    engine.dispose()
