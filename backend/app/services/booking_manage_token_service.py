from __future__ import annotations

import hashlib
import secrets
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from app.models import Booking

TOKEN_BYTES = 32
TOKEN_MAX_AGE = timedelta(days=90)
TOKEN_AFTER_APPOINTMENT_GRACE = timedelta(days=7)
TERMINAL_BOOKING_STATUSES = frozenset({"rejected", "cancelled", "completed", "no_show"})


def hash_booking_manage_token(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def as_utc_naive(value: datetime, timezone_name: str) -> datetime:
    if value.tzinfo is not None:
        return value.astimezone(timezone.utc).replace(tzinfo=None)
    try:
        local_timezone = ZoneInfo(timezone_name)
    except ZoneInfoNotFoundError:
        local_timezone = timezone.utc
    return value.replace(tzinfo=local_timezone).astimezone(timezone.utc).replace(tzinfo=None)


def booking_manage_token_expiry(booking: Booking, *, now: datetime) -> datetime:
    appointment_value = booking.end_datetime or booking.start_datetime
    appointment_boundary = (
        as_utc_naive(
            appointment_value,
            getattr(booking.business, "timezone", None) or "UTC",
        )
        if appointment_value
        else now
    )
    return min(
        appointment_boundary + TOKEN_AFTER_APPOINTMENT_GRACE,
        now + TOKEN_MAX_AGE,
    )


def create_booking_manage_token(booking: Booking, *, now: datetime | None = None) -> str:
    issued_at = now or datetime.utcnow()
    token = secrets.token_urlsafe(TOKEN_BYTES)
    booking.public_manage_token_hash = hash_booking_manage_token(token)
    booking.public_manage_token_expires_at = booking_manage_token_expiry(booking, now=issued_at)
    booking.public_manage_token_revoked_at = None
    return token


def refresh_booking_manage_token_expiry(booking: Booking, *, now: datetime | None = None) -> None:
    checked_at = now or datetime.utcnow()
    if (
        booking.public_manage_token_hash is None
        or booking.public_manage_token_revoked_at is not None
        or booking.public_manage_token_expires_at is None
        or booking.public_manage_token_expires_at <= checked_at
        or booking.customer_user_id is not None
        or booking.status in TERMINAL_BOOKING_STATUSES
    ):
        return
    issued_at = booking.created_at or checked_at
    booking.public_manage_token_expires_at = booking_manage_token_expiry(booking, now=issued_at)


def revoke_booking_manage_token(booking: Booking, *, now: datetime | None = None) -> bool:
    if booking.public_manage_token_hash is None or booking.public_manage_token_revoked_at:
        return False
    booking.public_manage_token_revoked_at = now or datetime.utcnow()
    return True


def booking_manage_token_is_valid(
    booking: Booking,
    token: str | None,
    *,
    now: datetime | None = None,
) -> bool:
    if not token or not 20 <= len(token) <= 255:
        return False
    if (
        booking.public_manage_token_hash is None
        or booking.public_manage_token_expires_at is None
        or booking.public_manage_token_revoked_at is not None
        or booking.customer_user_id is not None
        or booking.status in TERMINAL_BOOKING_STATUSES
        or getattr(booking.business, "status", None) == "archived"
    ):
        return False
    checked_at = now or datetime.utcnow()
    if booking.public_manage_token_expires_at <= checked_at:
        return False
    incoming_hash = hash_booking_manage_token(token)
    return secrets.compare_digest(booking.public_manage_token_hash, incoming_hash)
