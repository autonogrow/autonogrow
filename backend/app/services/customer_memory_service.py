from __future__ import annotations

import re
from collections import Counter, defaultdict
from datetime import datetime, timezone
from statistics import median
from typing import Any

from sqlalchemy.orm import Session

from app.models import Booking, CustomerMemoryItem

FORBIDDEN_SECRET_PATTERN = re.compile(
    r"\b(password|passwd|contrase(?:ñ|n)a|api[ _-]?key|token|bearer|"
    r"credenciales?|secret(?:o|a)?|private key)\b",
    re.IGNORECASE,
)
CARD_CANDIDATE_PATTERN = re.compile(r"(?<!\d)(?:\d[ -]?){13,19}(?!\d)")
MIN_VISITS_FOR_OBSERVED_INTERVAL = 4


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def as_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def _looks_like_payment_card(value: str) -> bool:
    for match in CARD_CANDIDATE_PATTERN.finditer(value):
        digits = re.sub(r"\D", "", match.group(0))
        if not 13 <= len(digits) <= 19:
            continue
        checksum = 0
        parity = len(digits) % 2
        for index, character in enumerate(digits):
            number = int(character)
            if index % 2 == parity:
                number *= 2
                if number > 9:
                    number -= 9
            checksum += number
        if checksum % 10 == 0:
            return True
    return False


def validate_memory_content(value: str) -> str:
    clean = value.strip()
    if not clean:
        raise ValueError("memory_content_required")
    if FORBIDDEN_SECRET_PATTERN.search(clean) or "-----BEGIN" in clean.upper():
        raise ValueError("memory_contains_credentials")
    if _looks_like_payment_card(clean):
        raise ValueError("memory_contains_payment_card")
    return clean


def serialize_memory_item(row: CustomerMemoryItem) -> dict[str, Any]:
    return {
        "id": row.id,
        "business_id": row.business_id,
        "customer_id": row.customer_id,
        "category": row.category,
        "key": row.key,
        "value": row.value,
        "value_type": row.value_type,
        "source_type": row.source_type,
        "source_id": row.source_id,
        "confidence": row.confidence,
        "status": row.status,
        "is_sensitive": row.is_sensitive,
        "created_by_user_id": row.created_by_user_id,
        "created_at": row.created_at.isoformat(),
        "updated_at": row.updated_at.isoformat(),
        "expires_at": row.expires_at.isoformat() if row.expires_at else None,
        "superseded_at": row.superseded_at.isoformat() if row.superseded_at else None,
        "deleted_at": row.deleted_at.isoformat() if row.deleted_at else None,
        "superseded_by_id": row.superseded_by_id,
    }


class CustomerMemoryService:
    def __init__(self, db: Session, *, now: datetime | None = None):
        self.db = db
        self.now = as_utc(now or utc_now())

    def expire_customer(self, *, business_id: int, customer_id: int) -> int:
        rows = (
            self.db.query(CustomerMemoryItem)
            .filter(
                CustomerMemoryItem.business_id == business_id,
                CustomerMemoryItem.customer_id == customer_id,
                CustomerMemoryItem.status == "active",
                CustomerMemoryItem.expires_at.is_not(None),
                CustomerMemoryItem.expires_at <= self.now,
            )
            .all()
        )
        for row in rows:
            row.status = "expired"
            row.updated_at = self.now
        if rows:
            self.db.flush()
        return len(rows)

    def list_items(
        self,
        *,
        business_id: int,
        customer_id: int,
        status: str | None = "active",
    ) -> list[CustomerMemoryItem]:
        self.expire_customer(business_id=business_id, customer_id=customer_id)
        query = self.db.query(CustomerMemoryItem).filter(
            CustomerMemoryItem.business_id == business_id,
            CustomerMemoryItem.customer_id == customer_id,
        )
        if status is not None:
            query = query.filter(CustomerMemoryItem.status == status)
        return query.order_by(
            CustomerMemoryItem.category.asc(),
            CustomerMemoryItem.updated_at.desc(),
            CustomerMemoryItem.id.desc(),
        ).all()

    def create_manual(
        self,
        *,
        business_id: int,
        customer_id: int,
        category: str,
        key: str,
        value: str,
        created_by_user_id: int | None,
        is_sensitive: bool = False,
        expires_at: datetime | None = None,
        supersedes_id: int | None = None,
    ) -> tuple[CustomerMemoryItem, CustomerMemoryItem | None]:
        clean_value = validate_memory_content(value)
        clean_expiration = as_utc(expires_at) if expires_at else None
        if clean_expiration is not None and clean_expiration <= self.now:
            raise ValueError("memory_expiration_must_be_future")

        superseded = None
        if supersedes_id is not None:
            superseded = (
                self.db.query(CustomerMemoryItem)
                .filter(
                    CustomerMemoryItem.id == supersedes_id,
                    CustomerMemoryItem.business_id == business_id,
                    CustomerMemoryItem.customer_id == customer_id,
                )
                .first()
            )
            if superseded is None:
                raise ValueError("memory_to_supersede_not_found")
            if superseded.status != "active":
                raise ValueError("memory_to_supersede_not_active")
            if superseded.category != category or superseded.key != key:
                raise ValueError("memory_replacement_key_mismatch")

        row = CustomerMemoryItem(
            business_id=business_id,
            customer_id=customer_id,
            category=category,
            key=key,
            value=clean_value,
            value_type="text",
            source_type="manual",
            confidence=1.0,
            status="active",
            is_sensitive=is_sensitive,
            created_by_user_id=created_by_user_id,
            created_at=self.now,
            updated_at=self.now,
            expires_at=clean_expiration,
        )
        self.db.add(row)
        self.db.flush()
        if superseded is not None:
            superseded.status = "superseded"
            superseded.superseded_at = self.now
            superseded.superseded_by_id = row.id
            superseded.updated_at = self.now
            self.db.flush()
        return row, superseded

    def update_manual(
        self,
        row: CustomerMemoryItem,
        *,
        value: str | None = None,
        is_sensitive: bool | None = None,
        expires_at: datetime | None = None,
        expires_at_set: bool = False,
    ) -> CustomerMemoryItem:
        if row.status != "active":
            raise ValueError("memory_not_active")
        if value is not None:
            row.value = validate_memory_content(value)
        if is_sensitive is not None:
            row.is_sensitive = is_sensitive
        if expires_at_set:
            clean_expiration = as_utc(expires_at) if expires_at else None
            if clean_expiration is not None and clean_expiration <= self.now:
                row.status = "expired"
            row.expires_at = clean_expiration
        row.updated_at = self.now
        self.db.flush()
        return row

    def mark_obsolete(self, row: CustomerMemoryItem) -> CustomerMemoryItem:
        if row.status != "active":
            raise ValueError("memory_not_active")
        row.status = "superseded"
        row.superseded_at = self.now
        row.updated_at = self.now
        self.db.flush()
        return row

    def soft_delete(self, row: CustomerMemoryItem) -> CustomerMemoryItem:
        if row.status == "deleted":
            raise ValueError("memory_already_deleted")
        row.status = "deleted"
        row.deleted_at = self.now
        row.updated_at = self.now
        self.db.flush()
        return row

    def summary(self, *, business_id: int, customer_id: int) -> dict[str, Any]:
        explicit = self.list_items(
            business_id=business_id, customer_id=customer_id, status="active"
        )
        bookings = (
            self.db.query(Booking)
            .filter(
                Booking.business_id == business_id,
                Booking.customer_id == customer_id,
                Booking.status == "completed",
            )
            .order_by(Booking.end_datetime.asc(), Booking.start_datetime.asc(), Booking.id.asc())
            .all()
        )
        visits: list[tuple[datetime, Booking]] = []
        for booking in bookings:
            occurred_at = booking.end_datetime or booking.start_datetime
            if occurred_at is not None:
                visits.append((as_utc(occurred_at), booking))
        visits.sort(key=lambda item: (item[0], item[1].id))

        last_service = None
        most_frequent_service = None
        configured_recurrence = None
        if visits:
            latest_booking = visits[-1][1]
            last_service = {
                "id": latest_booking.service_id,
                "name": latest_booking.service_name,
            }
            service_counts: Counter[tuple[int | None, str]] = Counter(
                (booking.service_id, booking.service_name) for _, booking in visits
            )
            last_occurrence: dict[tuple[int | None, str], datetime] = {}
            for occurred_at, booking in visits:
                last_occurrence[(booking.service_id, booking.service_name)] = occurred_at
            service_key, service_count = min(
                service_counts.items(),
                key=lambda item: (
                    -item[1],
                    -last_occurrence[item[0]].timestamp(),
                    item[0][1].casefold(),
                    item[0][0] or 0,
                ),
            )
            most_frequent_service = {
                "id": service_key[0],
                "name": service_key[1],
                "visit_count": service_count,
            }
            for _, booking in reversed(visits):
                if (
                    booking.follow_up_enabled_snapshot
                    and booking.follow_up_interval_days_snapshot is not None
                ):
                    configured_recurrence = {
                        "service_id": booking.service_id,
                        "service_name": booking.service_name,
                        "interval_days": booking.follow_up_interval_days_snapshot,
                        "window_days": booking.follow_up_window_days_snapshot,
                        "source": "booking_snapshot",
                    }
                    break

        positive_gaps = [
            (right[0] - left[0]).total_seconds() / 86400
            for left, right in zip(visits, visits[1:], strict=False)
            if right[0] > left[0]
        ]
        observed_interval = None
        if (
            len(visits) >= MIN_VISITS_FOR_OBSERVED_INTERVAL
            and len(positive_gaps) >= MIN_VISITS_FOR_OBSERVED_INTERVAL - 1
        ):
            observed_interval = int(median(positive_gaps) + 0.5)

        return {
            "customer_id": customer_id,
            "explicit": [serialize_memory_item(row) for row in explicit],
            "derived": {
                "visit_count": len(visits),
                "last_visit_at": visits[-1][0].isoformat() if visits else None,
                "last_service": last_service,
                "most_frequent_service": most_frequent_service,
                "observed_return_interval_days": observed_interval,
                "observed_interval_minimum_visits": MIN_VISITS_FOR_OBSERVED_INTERVAL,
                "configured_recurrence": configured_recurrence,
                "return_interval_priority": (
                    "configured_recurrence"
                    if configured_recurrence is not None
                    else ("observed_behavior" if observed_interval is not None else None)
                ),
            },
        }

    def compact_context(self, *, business_id: int, customer_id: int) -> dict[str, Any]:
        summary = self.summary(business_id=business_id, customer_id=customer_id)
        explicit = [item for item in summary["explicit"] if not item["is_sensitive"]]
        derived = summary["derived"]
        return {
            "explicit": [
                {
                    "id": item["id"],
                    "category": item["category"],
                    "value": item["value"],
                    "is_sensitive": item["is_sensitive"],
                }
                for item in explicit[:3]
            ],
            "last_service": derived["last_service"],
            "last_visit_at": derived["last_visit_at"],
            "most_frequent_service": derived["most_frequent_service"],
        }


def group_active_memories_by_customer(
    db: Session, *, business_id: int, customer_ids: set[int], now: datetime | None = None
) -> dict[int, list[dict[str, Any]]]:
    if not customer_ids:
        return {}
    current = as_utc(now or utc_now())
    rows = (
        db.query(CustomerMemoryItem)
        .filter(
            CustomerMemoryItem.business_id == business_id,
            CustomerMemoryItem.customer_id.in_(customer_ids),
            CustomerMemoryItem.status == "active",
            CustomerMemoryItem.is_sensitive.is_(False),
            (
                CustomerMemoryItem.expires_at.is_(None)
                | (CustomerMemoryItem.expires_at > current)
            ),
        )
        .order_by(CustomerMemoryItem.updated_at.desc(), CustomerMemoryItem.id.desc())
        .all()
    )
    grouped: dict[int, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        if len(grouped[row.customer_id]) >= 2:
            continue
        grouped[row.customer_id].append(
            {
                "id": row.id,
                "category": row.category,
                "value": row.value,
                "is_sensitive": row.is_sensitive,
            }
        )
    return dict(grouped)
