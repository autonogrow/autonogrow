from __future__ import annotations

import hashlib
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.models import (
    Booking,
    Business,
    BusinessService,
    Conversation,
    Customer,
    CustomerOpportunity,
    ScheduledCustomerFollowUp,
)

ACTIVE_BOOKING_STATUSES = {"requested", "pending", "confirmed"}
OPEN_OPPORTUNITY_STATUSES = {"pending", "actioned"}
COMMERCIAL_INTENTS = {"booking_intent", "price_intent", "service_intent"}
MIN_COMMERCIAL_INTENT_CONFIDENCE = 85
CANCELLED_DELAY = timedelta(days=3)
NO_SHOW_DELAY = timedelta(days=3)
LEAD_DELAY = timedelta(hours=48)
DEFAULT_EXPIRY = timedelta(days=45)


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def as_utc(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    if value.tzinfo is None or value.utcoffset() is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def snapshot_booking_follow_up(booking: Booking, service: BusinessService | None) -> None:
    """Capture service recurrence once; later service edits must not rewrite history."""
    # A non-null window is the capture marker. Zero represents an explicitly
    # captured disabled service; NULL is reserved for pre-Sprint-7 bookings.
    if booking.follow_up_window_days_snapshot is not None:
        return
    booking.follow_up_enabled_snapshot = bool(service and service.follow_up_enabled)
    booking.follow_up_interval_days_snapshot = (
        service.follow_up_interval_days if service and service.follow_up_enabled else None
    )
    booking.follow_up_window_days_snapshot = (
        service.follow_up_window_days if service and service.follow_up_enabled else 0
    )


def manual_followup_dedupe_key(
    *, customer_id: int, due_at: datetime, booking_id: int | None, service_id: int | None
) -> str:
    canonical = "|".join(
        (
            str(customer_id),
            as_utc(due_at).isoformat(),  # type: ignore[union-attr]
            str(booking_id or ""),
            str(service_id or ""),
        )
    )
    return "manual:" + hashlib.sha256(canonical.encode("utf-8")).hexdigest()


@dataclass
class EvaluationResult:
    created: int = 0
    updated: int = 0
    resolved: int = 0
    expired: int = 0


class GrowthOpportunityService:
    def __init__(self, db: Session, *, now: datetime | None = None):
        self.db = db
        normalized_now = as_utc(now or utc_now())
        assert normalized_now is not None
        self.now: datetime = normalized_now
        self.result = EvaluationResult()

    def evaluate_business(self, business_id: int) -> EvaluationResult:
        business = self.db.get(Business, business_id)
        if business is None:
            raise ValueError("business_not_found")
        self._resolve_existing(business_id)
        self._detect_booking_recovery(business_id)
        self._detect_service_due(business_id)
        self._detect_leads(business_id)
        self._detect_manual_followups(business_id)
        self._expire(business_id)
        return self.result

    def resolve_for_rebooking(self, booking: Booking) -> int:
        """Resolve open opportunities in the same transaction as a new active booking."""
        if booking.status not in ACTIVE_BOOKING_STATUSES:
            return 0
        rows = (
            self.db.query(CustomerOpportunity)
            .filter(
                CustomerOpportunity.business_id == booking.business_id,
                CustomerOpportunity.customer_id == booking.customer_id,
                CustomerOpportunity.status.in_(OPEN_OPPORTUNITY_STATUSES),
            )
            .all()
        )
        count = 0
        for row in rows:
            if row.type == "service_due" and row.source_service_id != booking.service_id:
                continue
            self._resolve(row)
            count += 1
            if row.scheduled_followup and row.scheduled_followup.status == "scheduled":
                row.scheduled_followup.status = "converted"
                row.scheduled_followup.converted_at = self.now
        return count

    def _bookings(self, business_id: int, customer_id: int) -> list[Booking]:
        return (
            self.db.query(Booking)
            .filter(Booking.business_id == business_id, Booking.customer_id == customer_id)
            .all()
        )

    @staticmethod
    def _booking_time(booking: Booking) -> datetime | None:
        return as_utc(booking.start_datetime or booking.created_at)

    def _has_later_active_booking(
        self, source: Booking | None, *, business_id: int, customer_id: int, after: datetime
    ) -> bool:
        for candidate in self._bookings(business_id, customer_id):
            if source is not None and candidate.id == source.id:
                continue
            if candidate.status not in ACTIVE_BOOKING_STATUSES:
                continue
            candidate_time = self._booking_time(candidate)
            created_at = as_utc(candidate.created_at)
            if (candidate_time and candidate_time > after) or (created_at and created_at > after):
                return True
        return False

    def _has_repeated_service(self, source: Booking, *, occurred_at: datetime) -> bool:
        for candidate in self._bookings(source.business_id, source.customer_id):
            if candidate.id == source.id or candidate.service_id != source.service_id:
                continue
            candidate_time = self._booking_time(candidate)
            if candidate.status in ACTIVE_BOOKING_STATUSES and candidate_time and candidate_time > occurred_at:
                return True
            completed_at = as_utc(candidate.end_datetime or candidate.updated_at)
            if candidate.status == "completed" and completed_at and completed_at > occurred_at:
                return True
        return False

    def _resolve(self, opportunity: CustomerOpportunity) -> None:
        if opportunity.status not in OPEN_OPPORTUNITY_STATUSES:
            return
        opportunity.status = "resolved"
        opportunity.resolved_at = self.now
        self.result.resolved += 1

    def _resolve_existing(self, business_id: int) -> None:
        rows = (
            self.db.query(CustomerOpportunity)
            .filter(
                CustomerOpportunity.business_id == business_id,
                CustomerOpportunity.status.in_(OPEN_OPPORTUNITY_STATUSES),
            )
            .all()
        )
        for row in rows:
            occurred = row.source_occurred_at or row.created_at
            if row.type == "service_due" and row.source_booking:
                should_resolve = self._has_repeated_service(
                    row.source_booking, occurred_at=occurred
                )
            else:
                should_resolve = self._has_later_active_booking(
                    None if row.type == "scheduled_followup" else row.source_booking,
                    business_id=row.business_id,
                    customer_id=row.customer_id,
                    after=occurred,
                )
            if should_resolve:
                self._resolve(row)
                if row.scheduled_followup and row.scheduled_followup.status == "scheduled":
                    row.scheduled_followup.status = "converted"
                    row.scheduled_followup.converted_at = self.now

    def _upsert(self, *, dedupe_key: str, values: dict) -> CustomerOpportunity:
        existing = (
            self.db.query(CustomerOpportunity)
            .filter(
                CustomerOpportunity.business_id == values["business_id"],
                CustomerOpportunity.dedupe_key == dedupe_key,
            )
            .first()
        )
        if existing is not None:
            if existing.status in OPEN_OPPORTUNITY_STATUSES:
                existing.reason_text = values["reason_text"]
                existing.expires_at = values.get("expires_at")
                self.result.updated += 1
            return existing
        row = CustomerOpportunity(dedupe_key=dedupe_key, **values)
        try:
            with self.db.begin_nested():
                self.db.add(row)
                self.db.flush()
            self.result.created += 1
            return row
        except IntegrityError:
            # The unique constraint is the final concurrency guard on PostgreSQL and SQLite.
            existing = (
                self.db.query(CustomerOpportunity)
                .filter(
                    CustomerOpportunity.business_id == values["business_id"],
                    CustomerOpportunity.dedupe_key == dedupe_key,
                )
                .one()
            )
            return existing

    def _detect_booking_recovery(self, business_id: int) -> None:
        bookings = (
            self.db.query(Booking)
            .filter(Booking.business_id == business_id, Booking.status.in_(("cancelled", "no_show")))
            .all()
        )
        for booking in bookings:
            occurred = as_utc(booking.updated_at or booking.end_datetime or booking.created_at)
            if occurred is None:
                continue
            delay = CANCELLED_DELAY if booking.status == "cancelled" else NO_SHOW_DELAY
            due_at = occurred + delay
            if due_at > self.now or self._has_later_active_booking(
                booking,
                business_id=business_id,
                customer_id=booking.customer_id,
                after=occurred,
            ):
                continue
            days = max(0, (self.now - occurred).days)
            kind = "cancelled_not_rebooked" if booking.status == "cancelled" else "no_show_not_rebooked"
            reason = (
                f"Canceló su cita hace {days} días y no tiene otra reserva."
                if booking.status == "cancelled"
                else f"No acudió a su cita hace {days} días y no tiene otra reserva."
            )
            self._upsert(
                dedupe_key=f"{kind}:booking:{booking.id}",
                values={
                    "business_id": business_id,
                    "customer_id": booking.customer_id,
                    "type": kind,
                    "status": "pending",
                    "priority": "high",
                    "detected_at": self.now,
                    "due_at": due_at,
                    "expires_at": due_at + DEFAULT_EXPIRY,
                    "source_booking_id": booking.id,
                    "source_service_id": booking.service_id,
                    "reason_code": kind,
                    "reason_text": reason,
                    "source_occurred_at": occurred,
                },
            )

    def _manual_overrides_service(self, booking: Booking) -> bool:
        return (
            self.db.query(ScheduledCustomerFollowUp.id)
            .filter(
                ScheduledCustomerFollowUp.business_id == booking.business_id,
                ScheduledCustomerFollowUp.customer_id == booking.customer_id,
                ScheduledCustomerFollowUp.status == "scheduled",
                (ScheduledCustomerFollowUp.booking_id == booking.id)
                | (ScheduledCustomerFollowUp.service_id == booking.service_id),
            )
            .first()
            is not None
        )

    def _detect_service_due(self, business_id: int) -> None:
        bookings = (
            self.db.query(Booking)
            .filter(
                Booking.business_id == business_id,
                Booking.status == "completed",
                Booking.follow_up_enabled_snapshot.is_(True),
                Booking.follow_up_interval_days_snapshot.is_not(None),
                Booking.service_id.is_not(None),
            )
            .all()
        )
        for booking in bookings:
            occurred = as_utc(booking.end_datetime or booking.updated_at)
            interval = booking.follow_up_interval_days_snapshot
            window = booking.follow_up_window_days_snapshot or 0
            if occurred is None or interval is None:
                continue
            due_at = occurred + timedelta(days=max(0, interval - window))
            expires_at = (
                occurred + timedelta(days=interval + window)
                if window
                else due_at + timedelta(days=60)
            )
            if (
                due_at > self.now
                or self._has_repeated_service(booking, occurred_at=occurred)
                or self._manual_overrides_service(booking)
            ):
                continue
            days = max(0, (self.now - occurred).days)
            self._upsert(
                dedupe_key=f"service_due:booking:{booking.id}:service:{booking.service_id}",
                values={
                    "business_id": business_id,
                    "customer_id": booking.customer_id,
                    "type": "service_due",
                    "status": "pending",
                    "priority": "normal",
                    "detected_at": self.now,
                    "due_at": due_at,
                    "expires_at": expires_at,
                    "source_booking_id": booking.id,
                    "source_service_id": booking.service_id,
                    "reason_code": "configured_service_return_window",
                    "reason_text": (
                        f"Realizó {booking.service_name} hace {days} días; el servicio está "
                        f"configurado para seguimiento cada {interval} días."
                    ),
                    "source_occurred_at": occurred,
                    "follow_up_interval_days_snapshot": interval,
                    "follow_up_window_days_snapshot": window,
                },
            )

    @staticmethod
    def _normalized_phone(value: str | None) -> str:
        return "".join(character for character in (value or "") if character.isdigit())

    def _conversation_customer(self, conversation: Conversation) -> Customer | None:
        phone = self._normalized_phone(conversation.customer_phone)
        if not phone:
            return None
        for customer in (
            self.db.query(Customer).filter(Customer.business_id == conversation.business_id).all()
        ):
            if self._normalized_phone(customer.phone) == phone:
                return customer
        return None

    def _detect_leads(self, business_id: int) -> None:
        conversations = (
            self.db.query(Conversation)
            .filter(
                Conversation.business_id == business_id,
                Conversation.detected_intent.in_(COMMERCIAL_INTENTS),
                Conversation.intent_confidence >= MIN_COMMERCIAL_INTENT_CONFIDENCE,
                Conversation.status.notin_(("closed", "resolved")),
            )
            .all()
        )
        for conversation in conversations:
            customer = self._conversation_customer(conversation)
            occurred = as_utc(conversation.last_inbound_at or conversation.last_message_at)
            if customer is None or occurred is None:
                continue
            due_at = occurred + LEAD_DELAY
            if due_at > self.now or self._has_later_active_booking(
                None,
                business_id=business_id,
                customer_id=customer.id,
                after=occurred,
            ):
                continue
            hours = max(0, int((self.now - occurred).total_seconds() // 3600))
            self._upsert(
                dedupe_key=f"lead_not_converted:conversation:{conversation.id}",
                values={
                    "business_id": business_id,
                    "customer_id": customer.id,
                    "type": "lead_not_converted",
                    "status": "pending",
                    "priority": "normal",
                    "detected_at": self.now,
                    "due_at": due_at,
                    "expires_at": due_at + timedelta(days=30),
                    "source_conversation_id": conversation.id,
                    "reason_code": f"commercial_{conversation.detected_intent}",
                    "reason_text": (
                        f"Preguntó por una reserva o servicio hace {hours} horas y no existe "
                        "una reserva posterior."
                    ),
                    "source_occurred_at": occurred,
                },
            )

    def _detect_manual_followups(self, business_id: int) -> None:
        rows = (
            self.db.query(ScheduledCustomerFollowUp)
            .filter(
                ScheduledCustomerFollowUp.business_id == business_id,
                ScheduledCustomerFollowUp.status == "scheduled",
                ScheduledCustomerFollowUp.due_at <= self.now,
            )
            .all()
        )
        for row in rows:
            if self._has_later_active_booking(
                None,
                business_id=business_id,
                customer_id=row.customer_id,
                after=row.created_at,
            ):
                row.status = "converted"
                row.converted_at = self.now
                continue
            reason = row.note or "El profesional indicó contactar de nuevo a este cliente."
            self._upsert(
                dedupe_key=f"scheduled_followup:{row.id}",
                values={
                    "business_id": business_id,
                    "customer_id": row.customer_id,
                    "type": "scheduled_followup",
                    "status": "pending",
                    "priority": "high",
                    "detected_at": self.now,
                    "due_at": row.due_at,
                    "expires_at": row.due_at + timedelta(days=30),
                    "source_booking_id": row.booking_id,
                    "source_service_id": row.service_id,
                    "scheduled_followup_id": row.id,
                    "reason_code": "professional_scheduled_followup",
                    "reason_text": reason,
                    "source_occurred_at": row.created_at,
                },
            )

    def _expire(self, business_id: int) -> None:
        rows = (
            self.db.query(CustomerOpportunity)
            .filter(
                CustomerOpportunity.business_id == business_id,
                CustomerOpportunity.status.in_(OPEN_OPPORTUNITY_STATUSES),
                CustomerOpportunity.expires_at.is_not(None),
                CustomerOpportunity.expires_at <= self.now,
            )
            .all()
        )
        for row in rows:
            row.status = "expired"
            self.result.expired += 1


def serialize_opportunity(row: CustomerOpportunity) -> dict:
    return {
        "id": row.id,
        "business_id": row.business_id,
        "customer": {"id": row.customer.id, "name": row.customer.name},
        "type": row.type,
        "status": row.status,
        "priority": row.priority,
        "detected_at": row.detected_at.isoformat(),
        "due_at": row.due_at.isoformat(),
        "expires_at": row.expires_at.isoformat() if row.expires_at else None,
        "actioned_at": row.actioned_at.isoformat() if row.actioned_at else None,
        "resolved_at": row.resolved_at.isoformat() if row.resolved_at else None,
        "dismissed_at": row.dismissed_at.isoformat() if row.dismissed_at else None,
        "source_booking_id": row.source_booking_id,
        "source_service_id": row.source_service_id,
        "source_conversation_id": row.source_conversation_id,
        "scheduled_followup_id": row.scheduled_followup_id,
        "reason_code": row.reason_code,
        "reason_text": row.reason_text,
        "source_occurred_at": (
            row.source_occurred_at.isoformat() if row.source_occurred_at else None
        ),
        "follow_up_interval_days_snapshot": row.follow_up_interval_days_snapshot,
        "follow_up_window_days_snapshot": row.follow_up_window_days_snapshot,
        "created_at": row.created_at.isoformat(),
        "updated_at": row.updated_at.isoformat(),
    }


def serialize_scheduled_followup(row: ScheduledCustomerFollowUp) -> dict:
    return {
        "id": row.id,
        "business_id": row.business_id,
        "customer_id": row.customer_id,
        "booking_id": row.booking_id,
        "service_id": row.service_id,
        "due_at": row.due_at.isoformat(),
        "status": row.status,
        "note": row.note,
        "cancelled_at": row.cancelled_at.isoformat() if row.cancelled_at else None,
        "converted_at": row.converted_at.isoformat() if row.converted_at else None,
        "created_at": row.created_at.isoformat(),
    }
