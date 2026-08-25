from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta, timezone
from statistics import mean
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.models import (
    AvailabilityException,
    AvailabilitySettings,
    Booking,
    Business,
    BusinessCalendarEvent,
    BusinessGrowthSignal,
    BusinessService,
    BusinessUser,
    BusinessUserAvailability,
    BusinessUserAvailabilityException,
    CustomerOpportunity,
    WeeklyAvailability,
)
from app.services.availability_service import (
    DEFAULT_WINDOWS,
    business_weekday,
    parse_weekly_schedule,
    parse_windows_from_json,
)
from app.services.capability_service import module_is_available
from app.services.growth_opportunity_service import as_utc

# Centralized V1 policy. These are product rules, not opaque scores.
OCCUPANCY_HORIZON_DAYS = 7
OCCUPANCY_BASELINE_WEEKS = 6
OCCUPANCY_MIN_COMPARABLE_WEEKS = 4
OCCUPANCY_MIN_BASELINE_BOOKINGS = 8
OCCUPANCY_MAX_RATE = 0.45
OCCUPANCY_MIN_DROP_POINTS = 0.20
DUE_POOL_HORIZON_DAYS = 7
DUE_POOL_BUSINESS_MINIMUM = 5
DUE_POOL_SERVICE_MINIMUM = 4
RETURN_PERIOD_DAYS = 30
RETURN_BASELINE_PERIODS = 3
RETURN_MIN_CURRENT_SAMPLE = 10
RETURN_MIN_BASELINE_SAMPLE = 30
RETURN_MAX_RATE = 0.50
RETURN_MIN_DROP_POINTS = 0.15
DEMAND_PERIOD_DAYS = 30
DEMAND_BASELINE_PERIODS = 3
DEMAND_MIN_BASELINE_AVERAGE = 5
DEMAND_MAX_RATIO = 0.60
DEMAND_MIN_ABSOLUTE_DROP = 3
DEMAND_MIN_CAPACITY_RATIO = 0.70
SEASONAL_HORIZON_DAYS = 30
SIGNAL_HISTORY_EXPIRY_DAYS = 14
NEW_SERVICE_WINDOW_DAYS = 21

OCCUPANCY_BOOKING_STATUSES = {"requested", "pending", "confirmed", "completed"}
DEMAND_BOOKING_STATUSES = {"requested", "pending", "confirmed", "completed"}
OPEN_OPPORTUNITY_STATUSES = {"pending", "actioned"}


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _json(value: dict[str, Any] | None) -> str | None:
    if value is None:
        return None
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _read_json(value: str | None) -> dict[str, Any] | None:
    if not value:
        return None
    try:
        parsed = json.loads(value)
    except (TypeError, json.JSONDecodeError):
        return None
    return parsed if isinstance(parsed, dict) else None


def _aware(value: datetime) -> datetime:
    normalized = as_utc(value)
    assert normalized is not None
    return normalized


def _naive(value: datetime) -> datetime:
    return value.astimezone(timezone.utc).replace(tzinfo=None) if value.tzinfo else value


def _period(start: date, days: int) -> tuple[datetime, datetime]:
    period_start = datetime.combine(start, time.min, tzinfo=timezone.utc)
    return period_start, period_start + timedelta(days=days)


def _week_bucket(day: date) -> str:
    iso = day.isocalendar()
    return f"{iso.year}-W{iso.week:02d}"


def _month_bucket(day: date) -> str:
    return day.strftime("%Y-%m")


def _rate(value: float) -> float:
    return round(max(0.0, min(1.0, value)), 4)


def _window_minutes(windows: list[dict[str, str]]) -> int:
    total = 0
    for window in windows:
        try:
            starts = datetime.strptime(window["start"], "%H:%M")
            ends = datetime.strptime(window["end"], "%H:%M")
        except (KeyError, ValueError):
            continue
        if ends > starts:
            total += int((ends - starts).total_seconds() // 60)
    return total


def _intersect_windows(
    first: list[dict[str, str]], second: list[dict[str, str]]
) -> list[dict[str, str]]:
    result: list[dict[str, str]] = []
    for left in first:
        for right in second:
            start = max(left.get("start", ""), right.get("start", ""))
            end = min(left.get("end", ""), right.get("end", ""))
            if start and end and start < end:
                result.append({"start": start, "end": end})
    return result


@dataclass(frozen=True)
class CapacitySnapshot:
    capacity_minutes: int
    booked_minutes: int
    available_minutes: int
    booking_count: int
    staff_count: int

    @property
    def occupancy_rate(self) -> float:
        if self.capacity_minutes <= 0:
            return 0.0
        return _rate(self.booked_minutes / self.capacity_minutes)


@dataclass
class SignalEvaluationResult:
    created: int = 0
    updated: int = 0
    resolved: int = 0
    expired: int = 0
    suppressed: int = 0


class BusinessGrowthSignalService:
    def __init__(self, db: Session, *, now: datetime | None = None):
        self.db = db
        self.now = _aware(now or utc_now())
        self.result = SignalEvaluationResult()

    def evaluate_business(self, business_id: int) -> SignalEvaluationResult:
        business = self.db.get(Business, business_id)
        if business is None:
            raise ValueError("business_not_found")
        if not module_is_available(self.db, business_id, "growth"):
            return self.result
        self._expire(business.id)
        self._evaluate_low_future_occupancy(business)
        self._evaluate_high_due_customer_pool(business)
        self._evaluate_low_return_rate(business)
        self._evaluate_service_demand_drop(business)
        self._evaluate_new_services(business)
        self._evaluate_seasonal_windows(business)
        return self.result

    def _evaluate_new_services(self, business: Business) -> None:
        cutoff = self.now - timedelta(days=NEW_SERVICE_WINDOW_DAYS)
        services = (
            self.db.query(BusinessService)
            .filter(
                BusinessService.business_id == business.id,
                BusinessService.active.is_(True),
                BusinessService.archived_at.is_(None),
                BusinessService.created_at >= _naive(cutoff),
            )
            .order_by(BusinessService.created_at.asc(), BusinessService.id.asc())
            .all()
        )
        touched: set[str] = set()
        for service in services:
            created_at = _aware(service.created_at)
            expires_at = created_at + timedelta(days=NEW_SERVICE_WINDOW_DAYS)
            if expires_at <= self.now:
                continue
            dedupe = f"new_service:service:{service.id}"
            touched.add(dedupe)
            age_days = max(0, (self.now.date() - created_at.date()).days)
            self._upsert(
                dedupe_key=dedupe,
                values={
                    "business_id": business.id,
                    "type": "new_service",
                    "status": "active",
                    "severity": "info",
                    "scope_type": "service",
                    "service_id": service.id,
                    "calendar_event_id": None,
                    "detected_at": self.now,
                    "period_start": created_at,
                    "period_end": expires_at,
                    "expires_at": expires_at,
                    "resolved_at": None,
                    "dismissed_at": None,
                    "last_evaluated_at": self.now,
                    "reason_code": "active_service_recently_created",
                    "explanation_json": _json(
                        self._explanation(
                            title="Servicio nuevo",
                            what=f"{service.name} se añadió hace {age_days} días.",
                            comparison="La señal usa exclusivamente la fecha real de alta del servicio.",
                            importance="Es posible que parte de la clientela todavía no lo conozca.",
                            action="Valorar una presentación del nuevo servicio.",
                        )
                    ),
                    "observed_json": _json(
                        {"schema_version": 1, "service_age_days": age_days}
                    ),
                    "baseline_json": None,
                    "recommendation_code": "introduce_new_service",
                },
            )
        self._resolve_untouched(business.id, "new_service", touched)

    def capacity_snapshot(
        self, business: Business, *, start: date, end: date
    ) -> CapacitySnapshot:
        """Return real staffed minutes and occupied minutes for [start, end)."""
        if end <= start:
            return CapacitySnapshot(0, 0, 0, 0, 0)
        settings = (
            self.db.query(AvailabilitySettings)
            .filter(AvailabilitySettings.business_id == business.id)
            .first()
        )
        weekly = {
            row.weekday: parse_windows_from_json(row.slots_json)
            for row in self.db.query(WeeklyAvailability)
            .filter(
                WeeklyAvailability.business_id == business.id,
                WeeklyAvailability.active.is_(True),
            )
            .all()
        }
        configured_schedule = (
            parse_weekly_schedule(settings.weekly_schedule_json) if settings else {}
        )
        business_exceptions = {
            row.date: row
            for row in self.db.query(AvailabilityException)
            .filter(
                AvailabilityException.business_id == business.id,
                AvailabilityException.date >= start.isoformat(),
                AvailabilityException.date < end.isoformat(),
            )
            .order_by(AvailabilityException.id.asc())
            .all()
        }
        staff = (
            self.db.query(BusinessUser)
            .join(BusinessUser.services)
            .filter(
                BusinessUser.business_id == business.id,
                BusinessUser.active.is_(True),
                BusinessUser.bookable.is_(True),
                BusinessUser.show_schedule.is_(True),
                BusinessUser.removed_at.is_(None),
                BusinessService.business_id == business.id,
                BusinessService.active.is_(True),
                BusinessService.bookable.is_(True),
                BusinessService.archived_at.is_(None),
            )
            .distinct()
            .all()
        )
        staff_ids = [row.id for row in staff]
        staff_weekly: dict[tuple[int, int], list[dict[str, str]]] = {}
        staff_exceptions: dict[tuple[int, str], BusinessUserAvailabilityException] = {}
        if staff_ids:
            for availability_row in self.db.query(BusinessUserAvailability).filter(
                BusinessUserAvailability.business_user_id.in_(staff_ids),
                BusinessUserAvailability.active.is_(True),
            ):
                staff_weekly[(availability_row.business_user_id, availability_row.weekday)] = parse_windows_from_json(
                    availability_row.windows_json
                )
            for exception_row in self.db.query(BusinessUserAvailabilityException).filter(
                BusinessUserAvailabilityException.business_user_id.in_(staff_ids),
                BusinessUserAvailabilityException.date >= start.isoformat(),
                BusinessUserAvailabilityException.date < end.isoformat(),
            ):
                staff_exceptions[(exception_row.business_user_id, exception_row.date)] = exception_row

        daily_capacity: dict[date, int] = {}
        current = start
        while current < end:
            weekday = business_weekday(current)
            business_windows = configured_schedule.get(
                weekday, weekly.get(weekday, DEFAULT_WINDOWS[weekday])
            )
            exception = business_exceptions.get(current.isoformat())
            if exception and exception.type == "closed":
                business_windows = []
            elif exception and exception.type == "custom_hours":
                business_windows = parse_windows_from_json(exception.windows_json)
            capacity = 0
            for member in staff:
                member_exception = staff_exceptions.get((member.id, current.isoformat()))
                if member_exception and member_exception.type == "closed":
                    member_windows: list[dict[str, str]] = []
                elif member_exception and member_exception.type == "custom_hours":
                    member_windows = parse_windows_from_json(member_exception.windows_json)
                else:
                    member_windows = staff_weekly.get((member.id, weekday), business_windows)
                capacity += _window_minutes(
                    _intersect_windows(business_windows, member_windows)
                )
            daily_capacity[current] = capacity
            current += timedelta(days=1)

        start_dt = datetime.combine(start, time.min)
        end_dt = datetime.combine(end, time.min)
        bookings = (
            self.db.query(Booking)
            .filter(
                Booking.business_id == business.id,
                Booking.status.in_(OCCUPANCY_BOOKING_STATUSES),
            )
            .all()
        )
        eligible_staff_ids = set(staff_ids)
        booked_by_day = {day: 0 for day in daily_capacity}
        counted = 0
        buffer_minutes = settings.buffer_between_bookings_minutes if settings else 0
        for booking in bookings:
            starts_at = booking.start_datetime
            ends_at = booking.end_datetime
            if starts_at is None and booking.preferred_date and booking.preferred_time:
                try:
                    starts_at = datetime.fromisoformat(
                        f"{booking.preferred_date}T{booking.preferred_time}:00"
                    )
                except ValueError:
                    continue
                ends_at = starts_at + timedelta(minutes=booking.duration_minutes or 30)
            if starts_at is None:
                continue
            ends_at = ends_at or starts_at + timedelta(minutes=booking.duration_minutes or 30)
            starts_at = _naive(starts_at) - timedelta(minutes=buffer_minutes)
            ends_at = _naive(ends_at) + timedelta(minutes=buffer_minutes)
            if starts_at >= end_dt or ends_at <= start_dt:
                continue
            multiplier = 1
            if booking.staff_business_user_id is None:
                # Legacy unassigned reservations block every professional in the live scheduler.
                multiplier = max(1, len(staff_ids))
            elif booking.staff_business_user_id not in eligible_staff_ids:
                continue
            counted += 1
            day = max(starts_at.date(), start)
            last_day = min(ends_at.date(), end - timedelta(days=1))
            while day <= last_day:
                day_start = datetime.combine(day, time.min)
                day_end = day_start + timedelta(days=1)
                overlap_start = max(starts_at, day_start)
                overlap_end = min(ends_at, day_end)
                if overlap_end > overlap_start:
                    booked_by_day[day] += (
                        int((overlap_end - overlap_start).total_seconds() // 60) * multiplier
                    )
                day += timedelta(days=1)
        capacity_minutes = sum(daily_capacity.values())
        booked_minutes = sum(
            min(daily_capacity[day], minutes) for day, minutes in booked_by_day.items()
        )
        return CapacitySnapshot(
            capacity_minutes=capacity_minutes,
            booked_minutes=booked_minutes,
            available_minutes=max(0, capacity_minutes - booked_minutes),
            booking_count=counted,
            staff_count=len(staff),
        )

    def _upsert(
        self,
        *,
        dedupe_key: str,
        values: dict[str, Any],
    ) -> BusinessGrowthSignal | None:
        existing = (
            self.db.query(BusinessGrowthSignal)
            .filter(
                BusinessGrowthSignal.business_id == values["business_id"],
                BusinessGrowthSignal.dedupe_key == dedupe_key,
            )
            .first()
        )
        if existing is not None:
            existing.last_evaluated_at = self.now
            if existing.status != "active":
                self.result.suppressed += 1
                return None
            for key, value in values.items():
                if key not in {"business_id", "detected_at"}:
                    setattr(existing, key, value)
            self.result.updated += 1
            return existing
        row = BusinessGrowthSignal(dedupe_key=dedupe_key, **values)
        try:
            with self.db.begin_nested():
                self.db.add(row)
                self.db.flush()
            self.result.created += 1
            return row
        except IntegrityError:
            self.result.suppressed += 1
            return None

    def _resolve_untouched(self, business_id: int, signal_type: str, touched: set[str]) -> None:
        rows = (
            self.db.query(BusinessGrowthSignal)
            .filter(
                BusinessGrowthSignal.business_id == business_id,
                BusinessGrowthSignal.type == signal_type,
                BusinessGrowthSignal.status == "active",
            )
            .all()
        )
        for row in rows:
            if row.dedupe_key in touched:
                continue
            row.status = "resolved"
            row.resolved_at = self.now
            row.last_evaluated_at = self.now
            self.result.resolved += 1

    def _expire(self, business_id: int) -> None:
        rows = (
            self.db.query(BusinessGrowthSignal)
            .filter(
                BusinessGrowthSignal.business_id == business_id,
                BusinessGrowthSignal.status == "active",
                BusinessGrowthSignal.expires_at.is_not(None),
                BusinessGrowthSignal.expires_at <= self.now,
            )
            .all()
        )
        for row in rows:
            row.status = "expired"
            row.last_evaluated_at = self.now
            self.result.expired += 1

    @staticmethod
    def _explanation(
        *, title: str, what: str, comparison: str, importance: str, action: str
    ) -> dict[str, Any]:
        return {
            "schema_version": 1,
            "title": title,
            "what_happened": what,
            "comparison": comparison,
            "why_it_matters": importance,
            "suggested_action": action,
        }

    def _evaluate_low_future_occupancy(self, business: Business) -> None:
        local_today = self._business_today(business)
        future_start = local_today + timedelta(days=1)
        future_end = future_start + timedelta(days=OCCUPANCY_HORIZON_DAYS)
        current = self.capacity_snapshot(business, start=future_start, end=future_end)
        comparable: list[CapacitySnapshot] = []
        for weeks_ago in range(1, OCCUPANCY_BASELINE_WEEKS + 1):
            baseline_start = future_start - timedelta(weeks=weeks_ago)
            snapshot = self.capacity_snapshot(
                business,
                start=baseline_start,
                end=baseline_start + timedelta(days=OCCUPANCY_HORIZON_DAYS),
            )
            if snapshot.capacity_minutes > 0:
                comparable.append(snapshot)
        baseline_booking_count = sum(item.booking_count for item in comparable)
        touched: set[str] = set()
        if (
            current.capacity_minutes > 0
            and len(comparable) >= OCCUPANCY_MIN_COMPARABLE_WEEKS
            and baseline_booking_count >= OCCUPANCY_MIN_BASELINE_BOOKINGS
        ):
            baseline_rate = mean(item.occupancy_rate for item in comparable)
            drop = baseline_rate - current.occupancy_rate
            if current.occupancy_rate <= OCCUPANCY_MAX_RATE and drop >= OCCUPANCY_MIN_DROP_POINTS:
                severity = "high" if current.occupancy_rate <= 0.25 and drop >= 0.30 else (
                    "medium" if current.occupancy_rate <= 0.35 or drop >= 0.25 else "low"
                )
                dedupe = f"low_future_occupancy:business:{_week_bucket(local_today)}"
                touched.add(dedupe)
                period_start, period_end = _period(
                    future_start, OCCUPANCY_HORIZON_DAYS
                )
                observed = {
                    "schema_version": 1,
                    "occupancy_rate": current.occupancy_rate,
                    "capacity_minutes": current.capacity_minutes,
                    "booked_minutes": current.booked_minutes,
                    "available_minutes": current.available_minutes,
                    "booking_count": current.booking_count,
                    "staff_count": current.staff_count,
                }
                baseline = {
                    "schema_version": 1,
                    "occupancy_rate": _rate(baseline_rate),
                    "weeks_used": len(comparable),
                    "booking_count": baseline_booking_count,
                    "drop_points": round(drop, 4),
                }
                percent = round(current.occupancy_rate * 100)
                normal = round(baseline_rate * 100)
                self._upsert(
                    dedupe_key=dedupe,
                    values={
                        "business_id": business.id,
                        "type": "low_future_occupancy",
                        "status": "active",
                        "severity": severity,
                        "scope_type": "business",
                        "service_id": None,
                        "calendar_event_id": None,
                        "detected_at": self.now,
                        "period_start": period_start,
                        "period_end": period_end,
                        "expires_at": period_end + timedelta(days=SIGNAL_HISTORY_EXPIRY_DAYS),
                        "resolved_at": None,
                        "dismissed_at": None,
                        "last_evaluated_at": self.now,
                        "reason_code": "future_occupancy_below_comparable_weeks",
                        "explanation_json": _json(
                            self._explanation(
                                title="Agenda con ocupación baja",
                                what=f"La ocupación prevista para los próximos 7 días es del {percent}%.",
                                comparison=f"La media de {len(comparable)} semanas comparables fue del {normal}%.",
                                importance="Hay capacidad real disponible que todavía podría llenarse.",
                                action="Revisar oportunidades o dar más visibilidad a la disponibilidad.",
                            )
                        ),
                        "observed_json": _json(observed),
                        "baseline_json": _json(baseline),
                        "recommendation_code": "increase_booking_visibility",
                    },
                )
        self._resolve_untouched(business.id, "low_future_occupancy", touched)

    def _evaluate_high_due_customer_pool(self, business: Business) -> None:
        horizon = self.now + timedelta(days=DUE_POOL_HORIZON_DAYS)
        rows = (
            self.db.query(CustomerOpportunity)
            .filter(
                CustomerOpportunity.business_id == business.id,
                CustomerOpportunity.type == "service_due",
                CustomerOpportunity.status.in_(OPEN_OPPORTUNITY_STATUSES),
                CustomerOpportunity.due_at <= horizon,
                (
                    CustomerOpportunity.expires_at.is_(None)
                    | (CustomerOpportunity.expires_at > self.now)
                ),
            )
            .all()
        )
        unique_business = {row.customer_id: row for row in rows}
        by_service: dict[int, dict[int, CustomerOpportunity]] = {}
        for row in rows:
            if row.source_service_id is not None:
                by_service.setdefault(row.source_service_id, {})[row.customer_id] = row
        period_start, period_end = _period(
            self._business_today(business), DUE_POOL_HORIZON_DAYS + 1
        )
        bucket = _week_bucket(self._business_today(business))
        touched: set[str] = set()

        def create_pool(service_id: int | None, count: int, minimum: int) -> None:
            if count < minimum:
                return
            service = self.db.get(BusinessService, service_id) if service_id else None
            if service_id is not None and (
                service is None or service.business_id != business.id
            ):
                return
            scope = "service" if service_id else "business"
            dedupe = f"high_due_customer_pool:{scope}:{service_id or 'all'}:{bucket}"
            touched.add(dedupe)
            severity = "high" if count >= 12 else ("medium" if count >= 8 else "low")
            service_text = f" de {service.name}" if service else ""
            observed = {
                "schema_version": 1,
                "customers_due": count,
                "window_days": DUE_POOL_HORIZON_DAYS,
            }
            self._upsert(
                dedupe_key=dedupe,
                values={
                    "business_id": business.id,
                    "type": "high_due_customer_pool",
                    "status": "active",
                    "severity": severity,
                    "scope_type": scope,
                    "service_id": service_id,
                    "calendar_event_id": None,
                    "detected_at": self.now,
                    "period_start": period_start,
                    "period_end": period_end,
                    "expires_at": period_end + timedelta(days=SIGNAL_HISTORY_EXPIRY_DAYS),
                    "resolved_at": None,
                    "dismissed_at": None,
                    "last_evaluated_at": self.now,
                    "reason_code": "active_service_due_pool_threshold",
                    "explanation_json": _json(
                        self._explanation(
                            title="Clientes en periodo de retorno",
                            what=f"{count} clientes{service_text} están en su periodo recomendado de retorno.",
                            comparison=f"El mínimo operativo para esta señal es {minimum} clientes únicos.",
                            importance="El grupo es suficientemente amplio para justificar una revisión comercial.",
                            action="Abrir las oportunidades relacionadas y decidir a quién contactar.",
                        )
                    ),
                    "observed_json": _json(observed),
                    "baseline_json": _json(
                        {"schema_version": 1, "minimum_customers": minimum}
                    ),
                    "recommendation_code": "contact_due_customers",
                },
            )

        create_pool(None, len(unique_business), DUE_POOL_BUSINESS_MINIMUM)
        for service_id, customers in by_service.items():
            create_pool(service_id, len(customers), DUE_POOL_SERVICE_MINIMUM)
        self._resolve_untouched(business.id, "high_due_customer_pool", touched)

    @staticmethod
    def _booking_point(booking: Booking) -> datetime:
        return _aware(booking.start_datetime or booking.end_datetime or booking.created_at)

    def _return_cohort(
        self,
        bookings: list[Booking],
        *,
        deadline_start: datetime,
        deadline_end: datetime,
    ) -> tuple[int, int]:
        candidates_by_customer_service: dict[tuple[int, int], list[Booking]] = {}
        for candidate in bookings:
            if candidate.service_id is not None and candidate.status in DEMAND_BOOKING_STATUSES:
                candidates_by_customer_service.setdefault(
                    (candidate.customer_id, candidate.service_id), []
                ).append(candidate)
        sources: list[tuple[Booking, datetime, datetime]] = []
        for booking in bookings:
            if (
                booking.status != "completed"
                or not booking.follow_up_enabled_snapshot
                or booking.follow_up_interval_days_snapshot is None
                or booking.service_id is None
            ):
                continue
            occurred = _aware(booking.end_datetime or booking.updated_at)
            deadline = occurred + timedelta(
                days=booking.follow_up_interval_days_snapshot
                + (booking.follow_up_window_days_snapshot or 0)
            )
            if deadline_start <= deadline < deadline_end:
                sources.append((booking, occurred, deadline))
        returned = 0
        for source, occurred, deadline in sources:
            assert source.service_id is not None
            found = any(
                candidate.id != source.id
                and occurred < self._booking_point(candidate) <= deadline
                for candidate in candidates_by_customer_service.get(
                    (source.customer_id, source.service_id), []
                )
            )
            returned += int(found)
        return len(sources), returned

    def _evaluate_low_return_rate(self, business: Business) -> None:
        bookings = self.db.query(Booking).filter(Booking.business_id == business.id).all()
        current_end = self.now
        current_start = current_end - timedelta(days=RETURN_PERIOD_DAYS)
        current_sample, current_returned = self._return_cohort(
            bookings, deadline_start=current_start, deadline_end=current_end
        )
        baseline_sample = 0
        baseline_returned = 0
        periods_used = 0
        for index in range(RETURN_BASELINE_PERIODS):
            end = current_start - timedelta(days=RETURN_PERIOD_DAYS * index)
            start = end - timedelta(days=RETURN_PERIOD_DAYS)
            sample, returned = self._return_cohort(
                bookings, deadline_start=start, deadline_end=end
            )
            if sample:
                periods_used += 1
                baseline_sample += sample
                baseline_returned += returned
        touched: set[str] = set()
        if (
            current_sample >= RETURN_MIN_CURRENT_SAMPLE
            and baseline_sample >= RETURN_MIN_BASELINE_SAMPLE
        ):
            current_rate = current_returned / current_sample
            baseline_rate = baseline_returned / baseline_sample
            drop = baseline_rate - current_rate
            if current_rate <= RETURN_MAX_RATE and drop >= RETURN_MIN_DROP_POINTS:
                severity = "high" if current_rate <= 0.30 and drop >= 0.30 else (
                    "medium" if current_rate <= 0.40 or drop >= 0.22 else "low"
                )
                today = self._business_today(business)
                dedupe = f"low_return_rate:business:{_month_bucket(today)}"
                touched.add(dedupe)
                self._upsert(
                    dedupe_key=dedupe,
                    values={
                        "business_id": business.id,
                        "type": "low_return_rate",
                        "status": "active",
                        "severity": severity,
                        "scope_type": "business",
                        "service_id": None,
                        "calendar_event_id": None,
                        "detected_at": self.now,
                        "period_start": current_start,
                        "period_end": current_end,
                        "expires_at": current_end + timedelta(days=SIGNAL_HISTORY_EXPIRY_DAYS),
                        "resolved_at": None,
                        "dismissed_at": None,
                        "last_evaluated_at": self.now,
                        "reason_code": "configured_recurrence_return_rate_drop",
                        "explanation_json": _json(
                            self._explanation(
                                title="Menor retorno observable",
                                what=f"Volvió el {round(current_rate * 100)}% de la cohorte recurrente reciente.",
                                comparison=f"La referencia observable fue del {round(baseline_rate * 100)}% sobre {baseline_sample} casos.",
                                importance="Está regresando una proporción menor de clientes con recurrencia configurada.",
                                action="Revisar oportunidades de retorno; no se genera ninguna recomendación clínica.",
                            )
                        ),
                        "observed_json": _json(
                            {
                                "schema_version": 1,
                                "return_rate": _rate(current_rate),
                                "sample_size": current_sample,
                                "returned": current_returned,
                                "period_days": RETURN_PERIOD_DAYS,
                            }
                        ),
                        "baseline_json": _json(
                            {
                                "schema_version": 1,
                                "return_rate": _rate(baseline_rate),
                                "sample_size": baseline_sample,
                                "returned": baseline_returned,
                                "periods_used": periods_used,
                                "drop_points": round(drop, 4),
                            }
                        ),
                        "recommendation_code": "contact_due_customers",
                    },
                )
        self._resolve_untouched(business.id, "low_return_rate", touched)

    def _evaluate_service_demand_drop(self, business: Business) -> None:
        today = self._business_today(business)
        current_end = self.now
        current_start = current_end - timedelta(days=DEMAND_PERIOD_DAYS)
        oldest_start = current_start - timedelta(
            days=DEMAND_PERIOD_DAYS * DEMAND_BASELINE_PERIODS
        )
        bookings = (
            self.db.query(Booking)
            .filter(
                Booking.business_id == business.id,
                Booking.status.in_(DEMAND_BOOKING_STATUSES),
                Booking.created_at >= oldest_start.replace(tzinfo=None),
                Booking.created_at < current_end.replace(tzinfo=None),
            )
            .all()
        )
        current_capacity = self.capacity_snapshot(
            business,
            start=(current_start.date()),
            end=current_end.date() + timedelta(days=1),
        ).capacity_minutes
        historical_capacity = self.capacity_snapshot(
            business,
            start=oldest_start.date(),
            end=current_start.date(),
        ).capacity_minutes
        normalized_historical_capacity = historical_capacity / DEMAND_BASELINE_PERIODS
        capacity_ratio = (
            current_capacity / normalized_historical_capacity
            if normalized_historical_capacity > 0
            else 0.0
        )
        touched: set[str] = set()
        services = (
            self.db.query(BusinessService)
            .filter(
                BusinessService.business_id == business.id,
                BusinessService.active.is_(True),
                BusinessService.bookable.is_(True),
                BusinessService.archived_at.is_(None),
            )
            .all()
        )
        for service in services:
            created_at = _aware(service.created_at)
            if created_at > oldest_start or capacity_ratio < DEMAND_MIN_CAPACITY_RATIO:
                continue
            service_bookings = [row for row in bookings if row.service_id == service.id]
            current_count = sum(
                1 for row in service_bookings if _aware(row.created_at) >= current_start
            )
            baseline_counts: list[int] = []
            for index in range(DEMAND_BASELINE_PERIODS):
                end = current_start - timedelta(days=DEMAND_PERIOD_DAYS * index)
                start = end - timedelta(days=DEMAND_PERIOD_DAYS)
                baseline_counts.append(
                    sum(
                        1
                        for row in service_bookings
                        if start <= _aware(row.created_at) < end
                    )
                )
            baseline_average = mean(baseline_counts)
            absolute_drop = baseline_average - current_count
            ratio = current_count / baseline_average if baseline_average else 1.0
            if (
                baseline_average < DEMAND_MIN_BASELINE_AVERAGE
                or ratio > DEMAND_MAX_RATIO
                or absolute_drop < DEMAND_MIN_ABSOLUTE_DROP
            ):
                continue
            severity = "high" if ratio <= 0.35 else ("medium" if ratio <= 0.50 else "low")
            dedupe = f"service_demand_drop:service:{service.id}:{_month_bucket(today)}"
            touched.add(dedupe)
            self._upsert(
                dedupe_key=dedupe,
                values={
                    "business_id": business.id,
                    "type": "service_demand_drop",
                    "status": "active",
                    "severity": severity,
                    "scope_type": "service",
                    "service_id": service.id,
                    "calendar_event_id": None,
                    "detected_at": self.now,
                    "period_start": current_start,
                    "period_end": current_end,
                    "expires_at": current_end + timedelta(days=SIGNAL_HISTORY_EXPIRY_DAYS),
                    "resolved_at": None,
                    "dismissed_at": None,
                    "last_evaluated_at": self.now,
                    "reason_code": "service_bookings_below_comparable_periods",
                    "explanation_json": _json(
                        self._explanation(
                            title="Servicio con menor demanda",
                            what=f"{service.name} recibió {current_count} reservas en los últimos 30 días.",
                            comparison=f"La media de los 3 periodos anteriores fue {baseline_average:.1f}.",
                            importance="La demanda reciente está por debajo de su patrón observable.",
                            action="Revisar la demanda del servicio o darle mayor visibilidad.",
                        )
                    ),
                    "observed_json": _json(
                        {
                            "schema_version": 1,
                            "booking_count": current_count,
                            "period_days": DEMAND_PERIOD_DAYS,
                            "capacity_ratio": round(capacity_ratio, 4),
                        }
                    ),
                    "baseline_json": _json(
                        {
                            "schema_version": 1,
                            "average_booking_count": round(baseline_average, 2),
                            "period_counts": baseline_counts,
                            "periods_used": DEMAND_BASELINE_PERIODS,
                            "relative_ratio": round(ratio, 4),
                        }
                    ),
                    "recommendation_code": "review_service_demand",
                },
            )
        self._resolve_untouched(business.id, "service_demand_drop", touched)

    def _event_occurrence(
        self, event: BusinessCalendarEvent
    ) -> tuple[datetime, datetime] | None:
        if not event.enabled:
            return None
        start = _aware(event.starts_at)
        end = _aware(event.ends_at)
        if event.yearly_recurrence:
            duration = end - start
            candidates = []
            for year in (self.now.year, self.now.year + 1):
                try:
                    occurrence = start.replace(year=year)
                except ValueError:
                    occurrence = start.replace(year=year, day=28)
                candidates.append((occurrence, occurrence + duration))
            return next((item for item in candidates if item[1] >= self.now), None)
        return (start, end) if end >= self.now else None

    def _evaluate_seasonal_windows(self, business: Business) -> None:
        horizon = self.now + timedelta(days=SEASONAL_HORIZON_DAYS)
        events = (
            self.db.query(BusinessCalendarEvent)
            .filter(
                BusinessCalendarEvent.business_id == business.id,
                BusinessCalendarEvent.enabled.is_(True),
            )
            .all()
        )
        touched: set[str] = set()
        for event in events:
            occurrence = self._event_occurrence(event)
            if occurrence is None:
                continue
            starts_at, ends_at = occurrence
            if starts_at > horizon:
                continue
            days_until = max(0, (starts_at.date() - self.now.date()).days)
            dedupe = f"seasonal_window:event:{event.id}:{starts_at.year}"
            touched.add(dedupe)
            service_name = event.service.name if event.service else None
            self._upsert(
                dedupe_key=dedupe,
                values={
                    "business_id": business.id,
                    "type": "seasonal_window",
                    "status": "active",
                    "severity": "info",
                    "scope_type": "service" if event.service_id else "business",
                    "service_id": event.service_id,
                    "calendar_event_id": event.id,
                    "detected_at": self.now,
                    "period_start": starts_at,
                    "period_end": ends_at,
                    "expires_at": ends_at,
                    "resolved_at": None,
                    "dismissed_at": None,
                    "last_evaluated_at": self.now,
                    "reason_code": "configured_business_calendar_event_upcoming",
                    "explanation_json": _json(
                        self._explanation(
                            title="Ventana comercial próxima",
                            what=f"Se aproxima “{event.title}” en {days_until} días.",
                            comparison="Es un evento configurado por este negocio, no una temporada inferida.",
                            importance="Prepararlo con antelación permite decidir si conviene comunicarlo.",
                            action=(
                                f"Revisar la visibilidad de {service_name}."
                                if service_name
                                else "Valorar una comunicación comercial genérica."
                            ),
                        )
                    ),
                    "observed_json": _json(
                        {
                            "schema_version": 1,
                            "days_until_start": days_until,
                            "event_title": event.title,
                            "event_category": event.category,
                        }
                    ),
                    "baseline_json": None,
                    "recommendation_code": "consider_campaign",
                },
            )
        self._resolve_untouched(business.id, "seasonal_window", touched)

    def _business_today(self, business: Business) -> date:
        try:
            zone: ZoneInfo | timezone = ZoneInfo(business.timezone or "Europe/Madrid")
        except ZoneInfoNotFoundError:
            zone = timezone.utc
        return self.now.astimezone(zone).date()


def serialize_growth_signal(row: BusinessGrowthSignal) -> dict[str, Any]:
    related = None
    if row.type == "high_due_customer_pool":
        related = {
            "type": "service_due",
            "status": "pending",
            "service_id": row.service_id,
        }
    return {
        "id": row.id,
        "business_id": row.business_id,
        "type": row.type,
        "status": row.status,
        "severity": row.severity,
        "scope_type": row.scope_type,
        "service": (
            {"id": row.service.id, "name": row.service.name} if row.service else None
        ),
        "calendar_event_id": row.calendar_event_id,
        "detected_at": row.detected_at.isoformat(),
        "period_start": row.period_start.isoformat(),
        "period_end": row.period_end.isoformat(),
        "expires_at": row.expires_at.isoformat() if row.expires_at else None,
        "resolved_at": row.resolved_at.isoformat() if row.resolved_at else None,
        "dismissed_at": row.dismissed_at.isoformat() if row.dismissed_at else None,
        "last_evaluated_at": row.last_evaluated_at.isoformat(),
        "reason_code": row.reason_code,
        "explanation": _read_json(row.explanation_json),
        "observed": _read_json(row.observed_json) or {},
        "baseline": _read_json(row.baseline_json),
        "recommendation_code": row.recommendation_code,
        "related_opportunities": related,
        "created_at": row.created_at.isoformat(),
        "updated_at": row.updated_at.isoformat(),
    }


def serialize_calendar_event(row: BusinessCalendarEvent) -> dict[str, Any]:
    return {
        "id": row.id,
        "business_id": row.business_id,
        "title": row.title,
        "starts_at": row.starts_at.isoformat(),
        "ends_at": row.ends_at.isoformat(),
        "category": row.category,
        "service": (
            {"id": row.service.id, "name": row.service.name} if row.service else None
        ),
        "enabled": row.enabled,
        "yearly_recurrence": row.yearly_recurrence,
        "created_at": row.created_at.isoformat(),
        "updated_at": row.updated_at.isoformat(),
    }
