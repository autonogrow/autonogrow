from __future__ import annotations

import re
from urllib.parse import urlparse

import phonenumbers
from phonenumbers import PhoneNumberFormat
from sqlalchemy.orm import Session

from app.models import Customer, CustomerAccountLink, User
from app.services.idempotent_insert_service import insert_rows_ignore_conflicts

INSTAGRAM_USERNAME = re.compile(r"^[a-z0-9._]{1,30}$")


def normalize_phone(value: str | None, *, region: str = "ES") -> str | None:
    """Return a valid E.164 number; formatting never implies ownership verification."""

    clean = (value or "").strip()
    if not clean:
        return None
    if clean.startswith("00"):
        clean = f"+{clean[2:]}"
    try:
        parsed = phonenumbers.parse(clean, (region or "ES").upper())
    except phonenumbers.NumberParseException:
        return None
    if not phonenumbers.is_valid_number(parsed):
        return None
    return phonenumbers.format_number(parsed, PhoneNumberFormat.E164)


def normalize_email(value: str | None) -> str | None:
    clean = (value or "").strip().lower()
    return clean or None


def normalize_instagram_username(value: str | None) -> str | None:
    clean = (value or "").strip().lower()
    if not clean:
        return None
    if "://" in clean:
        parsed = urlparse(clean)
        if parsed.hostname not in {"instagram.com", "www.instagram.com"}:
            return None
        parts = [part for part in parsed.path.split("/") if part]
        if len(parts) != 1:
            return None
        clean = parts[0]
    clean = clean.removeprefix("@").strip()
    return clean if INSTAGRAM_USERNAME.fullmatch(clean) else None


def linked_customer_for_business(
    db: Session, *, user_id: int, business_id: int
) -> Customer | None:
    return (
        db.query(Customer)
        .join(CustomerAccountLink, CustomerAccountLink.customer_id == Customer.id)
        .filter(
            CustomerAccountLink.user_id == user_id,
            CustomerAccountLink.business_id == business_id,
        )
        .first()
    )


def link_customer_account(
    db: Session,
    *,
    user: User,
    customer: Customer,
    method: str,
) -> CustomerAccountLink:
    db.flush()
    insert_rows_ignore_conflicts(
        db,
        CustomerAccountLink,
        [
            {
                "user_id": user.id,
                "customer_id": customer.id,
                "business_id": customer.business_id,
                "link_method": method,
            }
        ],
    )
    customer_link = (
        db.query(CustomerAccountLink)
        .filter(CustomerAccountLink.customer_id == customer.id)
        .first()
    )
    if customer_link is not None:
        if customer_link.user_id != user.id:
            raise ValueError("identity_conflict")
        return customer_link
    account_link = (
        db.query(CustomerAccountLink)
        .filter(
            CustomerAccountLink.user_id == user.id,
            CustomerAccountLink.business_id == customer.business_id,
        )
        .first()
    )
    if account_link is not None:
        if account_link.customer_id != customer.id:
            raise ValueError("identity_conflict")
        return account_link
    raise RuntimeError("Customer account link upsert did not persist a row")
