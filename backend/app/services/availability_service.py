import json
from datetime import date as date_cls
from datetime import datetime, time, timedelta
from datetime import timezone as datetime_timezone
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from sqlalchemy import or_
from sqlalchemy.orm import Session

from app.models import (
    AvailabilityException,
    AvailabilitySettings,
    Booking,
    Business,
    BusinessService,
    BusinessUser,
    BusinessUserAvailability,
    BusinessUserAvailabilityException,
    WeeklyAvailability,
)

BLOCKING_STATUSES = {"requested", "pending", "confirmed"}
DEFAULT_TIMEZONE = "Europe/Madrid"
DEFAULT_SLOT_INTERVAL_MINUTES = 15
DEFAULT_BUFFER_BETWEEN_BOOKINGS_MINUTES = 0
DEFAULT_MIN_NOTICE_MINUTES = 120
DEFAULT_MAX_DAYS_AHEAD = 30
DEFAULT_WINDOWS = {
    0: [],
    1: [{"start": "10:00", "end": "20:00"}],
    2: [{"start": "10:00", "end": "20:00"}],
    3: [{"start": "10:00", "end": "20:00"}],
    4: [{"start": "10:00", "end": "20:00"}],
    5: [{"start": "10:00", "end": "20:00"}],
    6: [{"start": "10:00", "end": "14:00"}],
}

SPANISH_WEEKDAYS = {
    0: "lun.",
    1: "mar.",
    2: "mie.",
    3: "jue.",
    4: "vie.",
    5: "sab.",
    6: "dom.",
}

SPANISH_MONTHS = {
    1: "ene.",
    2: "feb.",
    3: "mar.",
    4: "abr.",
    5: "may.",
    6: "jun.",
    7: "jul.",
    8: "ago.",
    9: "sep.",
    10: "oct.",
    11: "nov.",
    12: "dic.",
}


def default_weekly_schedule() -> dict[str, list[dict[str, str]]]:
    return {str(weekday): list(windows) for weekday, windows in DEFAULT_WINDOWS.items()}


def format_day_label(day: date_cls) -> str:
    return f"{SPANISH_WEEKDAYS[day.weekday()]} {day.day:02d} {SPANISH_MONTHS[day.month]}"


def business_weekday(day: date_cls) -> int:
    return (day.weekday() + 1) % 7


def get_business_or_none(db: Session, business_slug: str) -> Business | None:
    return (
        db.query(Business)
        .filter(
            Business.slug == business_slug,
            Business.status == "active",
        )
        .first()
    )


def parse_time(value: str) -> time:
    return datetime.strptime(value, "%H:%M").time()


def combine(day: date_cls, value: str | time) -> datetime:
    parsed_time = parse_time(value) if isinstance(value, str) else value
    return datetime.combine(day, parsed_time)


def get_timezone(name: str | None) -> ZoneInfo | None:
    try:
        return ZoneInfo(name or DEFAULT_TIMEZONE)
    except ZoneInfoNotFoundError:
        return None


def get_operational_business_now(
    db: Session,
    business_id: int,
    *,
    now: datetime | None = None,
) -> datetime:
    """Return the business civil time used by booking availability rules."""
    settings = (
        db.query(AvailabilitySettings)
        .filter(AvailabilitySettings.business_id == business_id)
        .first()
    )
    timezone = get_timezone(settings.timezone if settings else DEFAULT_TIMEZONE)
    if timezone is None:
        return datetime.now() if now is None else now.replace(tzinfo=None)
    if now is None:
        return datetime.now(timezone).replace(tzinfo=None)
    aware_now = now if now.tzinfo is not None else now.replace(tzinfo=datetime_timezone.utc)
    return aware_now.astimezone(timezone).replace(tzinfo=None)


def parse_windows(value: Any) -> list[dict[str, str]]:
    if not isinstance(value, list):
        return []

    windows = []

    for item in value:
        if isinstance(item, dict) and item.get("start") and item.get("end"):
            windows.append({"start": str(item["start"]), "end": str(item["end"])})
        elif isinstance(item, str) and "-" in item:
            start, end = item.split("-", 1)
            windows.append({"start": start.strip(), "end": end.strip()})

    return windows


def parse_windows_from_json(raw_value: str | None) -> list[dict[str, str]]:
    if not raw_value:
        return []

    try:
        values = json.loads(raw_value)
    except json.JSONDecodeError:
        return []

    if isinstance(values, list):
        windows = parse_windows(values)
        legacy_times = sorted(item for item in values if isinstance(item, str) and "-" not in item)

        if windows:
            return windows

        if legacy_times:
            return [{"start": legacy_times[0], "end": legacy_times[-1]}]

    return []


def parse_weekly_schedule(raw_value: str | None) -> dict[int, list[dict[str, str]]]:
    if not raw_value:
        return {}

    try:
        values = json.loads(raw_value)
    except json.JSONDecodeError:
        return {}

    if not isinstance(values, dict):
        return {}

    schedule: dict[int, list[dict[str, str]]] = {}

    for weekday_key, windows in values.items():
        try:
            weekday = int(weekday_key)
        except (TypeError, ValueError):
            continue

        if 0 <= weekday <= 6:
            schedule[weekday] = parse_windows(windows)

    return schedule


def normalize_weekly_schedule(value: dict[str, Any] | None) -> dict[str, list[dict[str, str]]]:
    source: dict[Any, Any] = value or default_weekly_schedule()
    result = {}

    for weekday in range(7):
        result[str(weekday)] = parse_windows(source.get(str(weekday), source.get(weekday, [])))

    return result


def get_weekly_windows(db: Session, business_id: int) -> dict[int, list[dict[str, str]]]:
    rows = (
        db.query(WeeklyAvailability)
        .filter(
            WeeklyAvailability.business_id == business_id,
            WeeklyAvailability.active == True,  # noqa: E712
        )
        .all()
    )

    result: dict[int, list[dict[str, str]]] = {}

    for row in rows:
        result[row.weekday] = parse_windows_from_json(row.slots_json)

    return result


def get_or_create_availability_settings(
    db: Session,
    business: Business,
) -> AvailabilitySettings:
    settings = (
        db.query(AvailabilitySettings)
        .filter(AvailabilitySettings.business_id == business.id)
        .first()
    )

    if settings:
        return settings

    legacy_weekly = get_weekly_windows(db, business.id)
    weekly_schedule = legacy_weekly or DEFAULT_WINDOWS
    settings = AvailabilitySettings(
        business_id=business.id,
        timezone=DEFAULT_TIMEZONE,
        slot_interval_minutes=DEFAULT_SLOT_INTERVAL_MINUTES,
        buffer_between_bookings_minutes=DEFAULT_BUFFER_BETWEEN_BOOKINGS_MINUTES,
        min_notice_minutes=DEFAULT_MIN_NOTICE_MINUTES,
        max_days_ahead=DEFAULT_MAX_DAYS_AHEAD,
        weekly_schedule_json=json.dumps(
            {str(day): windows for day, windows in weekly_schedule.items()},
            ensure_ascii=False,
        ),
    )
    db.add(settings)
    db.flush()
    return settings


def serialize_settings(business: Business, settings: AvailabilitySettings) -> dict[str, Any]:
    return {
        "business_slug": business.slug,
        "timezone": settings.timezone,
        "slot_interval_minutes": settings.slot_interval_minutes,
        "buffer_between_bookings_minutes": settings.buffer_between_bookings_minutes,
        "min_notice_minutes": settings.min_notice_minutes,
        "max_days_ahead": settings.max_days_ahead,
        "weekly_schedule": normalize_weekly_schedule(
            {
                str(day): windows
                for day, windows in parse_weekly_schedule(settings.weekly_schedule_json).items()
            }
        ),
    }


def get_service_or_none(
    db: Session,
    *,
    business_id: int,
    service_id: int,
) -> BusinessService | None:
    return (
        db.query(BusinessService)
        .filter(
            BusinessService.id == service_id,
            BusinessService.business_id == business_id,
            BusinessService.active == True,  # noqa: E712
        )
        .first()
    )


def get_public_bookable_staff(
    db: Session,
    business_id: int,
    service_id: int | None = None,
) -> list[BusinessUser]:
    query = (
        db.query(BusinessUser)
        .join(BusinessUser.services)
        .filter(
            BusinessUser.business_id == business_id,
            BusinessUser.active.is_(True),
            BusinessUser.bookable.is_(True),
            BusinessUser.show_schedule.is_(True),
            BusinessUser.removed_at.is_(None),
            BusinessService.business_id == business_id,
            BusinessService.active.is_(True),
        )
    )
    if service_id is not None:
        query = query.filter(BusinessService.id == service_id)
    return query.distinct().order_by(BusinessUser.id.asc()).all()


def serialize_public_staff(member: BusinessUser) -> dict[str, Any]:
    return {
        "id": member.id,
        "public_name": member.public_name
        or member.user.preferred_name
        or member.user.name
        or "Profesional",
        "bio": member.bio,
        "avatar_url": member.avatar_url or member.user.picture_url,
    }


def get_public_staff_or_none(
    db: Session,
    *,
    business_id: int,
    business_user_id: int,
    service_id: int | None = None,
) -> BusinessUser | None:
    query = (
        db.query(BusinessUser)
        .join(BusinessUser.services)
        .filter(
            BusinessUser.id == business_user_id,
            BusinessUser.business_id == business_id,
            BusinessUser.active.is_(True),
            BusinessUser.bookable.is_(True),
            BusinessUser.show_schedule.is_(True),
            BusinessUser.removed_at.is_(None),
            BusinessService.business_id == business_id,
            BusinessService.active.is_(True),
        )
    )
    if service_id is not None:
        query = query.filter(BusinessService.id == service_id)
    return query.first()


def get_exception_for_date(
    db: Session,
    *,
    business_id: int,
    target_date: date_cls,
) -> AvailabilityException | None:
    return (
        db.query(AvailabilityException)
        .filter(
            AvailabilityException.business_id == business_id,
            AvailabilityException.date == target_date.isoformat(),
        )
        .order_by(AvailabilityException.id.desc())
        .first()
    )


def serialize_exception(exception: AvailabilityException, business: Business) -> dict[str, Any]:
    return {
        "id": exception.id,
        "business_slug": business.slug,
        "date": exception.date,
        "type": exception.type,
        "windows": parse_windows_from_json(exception.windows_json),
        "reason": exception.reason,
        "created_at": exception.created_at.isoformat() if exception.created_at else None,
    }


def get_booking_interval(booking: Booking) -> tuple[datetime, datetime] | None:
    if booking.start_datetime:
        start = booking.start_datetime
        if booking.end_datetime:
            return start, booking.end_datetime
    else:
        if not booking.preferred_date or not booking.preferred_time:
            return None
        try:
            start = datetime.fromisoformat(f"{booking.preferred_date}T{booking.preferred_time}:00")
        except ValueError:
            return None

    duration = booking.duration_minutes

    if duration is None and booking.service and booking.service.duration_minutes:
        duration = booking.service.duration_minutes

    if duration is None:
        duration = 30

    return start, start + timedelta(minutes=duration)


def intervals_overlap(
    first_start: datetime,
    first_end: datetime,
    second_start: datetime,
    second_end: datetime,
) -> bool:
    return first_start < second_end and first_end > second_start


def get_blocking_bookings(
    db: Session,
    *,
    business_id: int,
    target_date: date_cls,
    exclude_booking_id: int | None = None,
    staff_business_user_id: int | None = None,
) -> list[Booking]:
    query = db.query(Booking).filter(
        Booking.business_id == business_id,
        Booking.status.in_(BLOCKING_STATUSES),
    )

    if exclude_booking_id is not None:
        query = query.filter(Booking.id != exclude_booking_id)

    if staff_business_user_id is not None:
        # Legacy unassigned reservations conservatively block every professional.
        query = query.filter(
            or_(
                Booking.staff_business_user_id == staff_business_user_id,
                Booking.staff_business_user_id.is_(None),
            )
        )

    rows = query.all()
    result = []

    for booking in rows:
        interval = get_booking_interval(booking)
        if not interval:
            continue

        starts_at, ends_at = interval
        if starts_at.date() <= target_date <= ends_at.date():
            result.append(booking)

    return result


def get_windows_for_date(
    db: Session,
    *,
    business: Business,
    settings: AvailabilitySettings | None,
    target_date: date_cls,
) -> list[dict[str, str]]:
    exception = get_exception_for_date(db, business_id=business.id, target_date=target_date)

    if exception and exception.type == "closed":
        return []

    if exception and exception.type == "custom_hours":
        return parse_windows_from_json(exception.windows_json)

    if settings:
        schedule = parse_weekly_schedule(settings.weekly_schedule_json)
        return schedule.get(business_weekday(target_date), [])

    weekly_windows = get_weekly_windows(db, business.id)
    windows = weekly_windows.get(business_weekday(target_date))

    if windows is None:
        return DEFAULT_WINDOWS[business_weekday(target_date)]

    return windows


def get_staff_windows_for_date(
    db: Session,
    *,
    business: Business,
    settings: AvailabilitySettings | None,
    staff: BusinessUser,
    target_date: date_cls,
) -> list[dict[str, str]]:
    exception = (
        db.query(BusinessUserAvailabilityException)
        .filter(
            BusinessUserAvailabilityException.business_user_id == staff.id,
            BusinessUserAvailabilityException.date == target_date.isoformat(),
        )
        .first()
    )
    if exception and exception.type == "closed":
        return []
    if exception and exception.type == "custom_hours":
        return parse_windows_from_json(exception.windows_json)

    row = (
        db.query(BusinessUserAvailability)
        .filter(
            BusinessUserAvailability.business_user_id == staff.id,
            BusinessUserAvailability.weekday == business_weekday(target_date),
            BusinessUserAvailability.active.is_(True),
        )
        .first()
    )
    if row is not None:
        return parse_windows_from_json(row.windows_json)
    return get_windows_for_date(db, business=business, settings=settings, target_date=target_date)


def get_available_slots(
    db: Session,
    *,
    business_slug: str,
    service_id: int,
    date: str,
    exclude_booking_id: int | None = None,
    staff_business_user_id: int | None = None,
    allow_nonpublic_staff: bool = False,
) -> list[dict[str, Any]]:
    business = get_business_or_none(db, business_slug)

    if business is None:
        raise ValueError("business_not_found")

    service = get_service_or_none(db, business_id=business.id, service_id=service_id)

    if service is None:
        raise ValueError("service_not_found")

    public_staff = get_public_bookable_staff(db, business.id, service.id)
    if not public_staff and not allow_nonpublic_staff:
        raise ValueError("no_staff_available_for_service")
    if staff_business_user_id is None:
        slots_by_start: dict[str, dict[str, Any]] = {}
        for member in public_staff:
            member_slots = get_available_slots(
                db,
                business_slug=business_slug,
                service_id=service_id,
                date=date,
                exclude_booking_id=exclude_booking_id,
                staff_business_user_id=member.id,
            )
            for slot in member_slots:
                key = slot["start"]
                aggregate = slots_by_start.setdefault(
                    key,
                    {**slot, "staff_business_user_id": None, "available_staff_ids": []},
                )
                aggregate["available_staff_ids"].append(member.id)
        return [slots_by_start[key] for key in sorted(slots_by_start)]

    selected_staff = None
    if staff_business_user_id is not None:
        if allow_nonpublic_staff:
            selected_staff = (
                db.query(BusinessUser)
                .filter(
                    BusinessUser.id == staff_business_user_id,
                    BusinessUser.business_id == business.id,
                    BusinessUser.active.is_(True),
                    BusinessUser.removed_at.is_(None),
                )
                .first()
            )
        else:
            selected_staff = get_public_staff_or_none(
                db,
                business_id=business.id,
                business_user_id=staff_business_user_id,
                service_id=service.id,
            )
        if selected_staff is None:
            raise ValueError("staff_not_available_for_service")

    try:
        target_date = datetime.strptime(date, "%Y-%m-%d").date()
    except ValueError as exc:
        raise ValueError("invalid_date") from exc

    settings = (
        db.query(AvailabilitySettings)
        .filter(AvailabilitySettings.business_id == business.id)
        .first()
    )

    now = get_operational_business_now(db, business.id)
    today = now.date()
    max_days_ahead = settings.max_days_ahead if settings else DEFAULT_MAX_DAYS_AHEAD

    if target_date > today + timedelta(days=max_days_ahead):
        return []

    service_duration = service.duration_minutes or 30
    slot_interval = settings.slot_interval_minutes if settings else DEFAULT_SLOT_INTERVAL_MINUTES
    min_notice = settings.min_notice_minutes if settings else DEFAULT_MIN_NOTICE_MINUTES
    buffer_minutes = (
        settings.buffer_between_bookings_minutes
        if settings
        else DEFAULT_BUFFER_BETWEEN_BOOKINGS_MINUTES
    )
    if selected_staff is not None:
        windows = get_staff_windows_for_date(
            db,
            business=business,
            settings=settings,
            staff=selected_staff,
            target_date=target_date,
        )
    else:
        windows = get_windows_for_date(
            db,
            business=business,
            settings=settings,
            target_date=target_date,
        )

    blocking_bookings = get_blocking_bookings(
        db,
        business_id=business.id,
        target_date=target_date,
        exclude_booking_id=exclude_booking_id,
        staff_business_user_id=selected_staff.id if selected_staff else None,
    )

    earliest_allowed_start = now + timedelta(minutes=min_notice)
    slots = []

    for window in windows:
        window_start = combine(target_date, window["start"])
        window_end = combine(target_date, window["end"])
        current_start = window_start

        while current_start + timedelta(minutes=service_duration) <= window_end:
            current_end = current_start + timedelta(minutes=service_duration)
            is_too_soon = current_start < earliest_allowed_start
            overlaps = False

            for booking in blocking_bookings:
                interval = get_booking_interval(booking)
                if interval is None:
                    continue

                blocked_start = interval[0] - timedelta(minutes=buffer_minutes)
                blocked_end = interval[1] + timedelta(minutes=buffer_minutes)

                if intervals_overlap(current_start, current_end, blocked_start, blocked_end):
                    overlaps = True
                    break

            if not is_too_soon and not overlaps:
                slots.append(
                    {
                        "start": current_start.isoformat(),
                        "end": current_end.isoformat(),
                        "label": current_start.strftime("%H:%M"),
                        "staff_business_user_id": selected_staff.id if selected_staff else None,
                        "available_staff_ids": [selected_staff.id] if selected_staff else [],
                    }
                )

            current_start += timedelta(minutes=slot_interval)

    return slots


def build_calendar_days(
    db: Session,
    *,
    business_slug: str,
    date_from: str,
    date_to: str,
    service_id: int | None = None,
    staff_business_user_id: int | None = None,
) -> list[dict[str, Any]]:
    business = get_business_or_none(db, business_slug)

    if business is None:
        raise ValueError("business_not_found")

    try:
        start_date = datetime.strptime(date_from, "%Y-%m-%d").date()
        end_date = datetime.strptime(date_to, "%Y-%m-%d").date()
    except ValueError as exc:
        raise ValueError("invalid_date") from exc

    if end_date < start_date:
        raise ValueError("invalid_date_range")

    if service_id is not None:
        service = get_service_or_none(db, business_id=business.id, service_id=service_id)
        if service is None:
            raise ValueError("service_not_found")
        if not get_public_bookable_staff(db, business.id, service_id):
            raise ValueError("no_staff_available_for_service")
    if (
        staff_business_user_id is not None
        and get_public_staff_or_none(
            db,
            business_id=business.id,
            business_user_id=staff_business_user_id,
            service_id=service_id,
        )
        is None
    ):
        raise ValueError("staff_not_available_for_service")

    settings = (
        db.query(AvailabilitySettings)
        .filter(AvailabilitySettings.business_id == business.id)
        .first()
    )
    now = get_operational_business_now(db, business.id)
    today = now.date()
    days = []
    current_day = start_date

    while current_day <= end_date:
        exception = get_exception_for_date(
            db,
            business_id=business.id,
            target_date=current_day,
        )
        windows = get_windows_for_date(
            db,
            business=business,
            settings=settings,
            target_date=current_day,
        )
        exception_type = exception.type if exception else None
        reason = exception.reason if exception else None
        slots = []

        if service_id is not None and current_day >= today:
            slots = get_available_slots(
                db,
                business_slug=business_slug,
                service_id=service_id,
                date=current_day.isoformat(),
                staff_business_user_id=staff_business_user_id,
            )

        has_slots = len(slots) > 0

        if current_day < today:
            status = "past"
        elif service_id is not None:
            if has_slots:
                status = "special" if exception_type == "custom_hours" else "available"
            elif exception_type == "closed":
                status = "closed"
            else:
                status = "full"
        elif exception_type == "closed" or not windows:
            status = "closed"
        elif exception_type == "custom_hours":
            status = "special"
        else:
            status = "available"

        days.append(
            {
                "date": current_day.isoformat(),
                "status": status,
                "label": format_day_label(current_day),
                "reason": reason,
                "has_slots": has_slots,
                "exception_type": exception_type,
            }
        )

        current_day += timedelta(days=1)

    return days


def get_booked_slots_by_date(
    db: Session,
    business_id: int,
    start_date: date_cls,
    end_date: date_cls,
) -> dict[str, list[str]]:
    rows = (
        db.query(Booking)
        .filter(
            Booking.business_id == business_id,
            Booking.preferred_date >= start_date.isoformat(),
            Booking.preferred_date <= end_date.isoformat(),
            Booking.status.in_(BLOCKING_STATUSES),
        )
        .all()
    )

    result: dict[str, list[str]] = {}

    for booking in rows:
        if not booking.preferred_date:
            continue

        if booking.preferred_date not in result:
            result[booking.preferred_date] = []

        result[booking.preferred_date].append(booking.preferred_time)

    return result


def build_availability(
    db: Session,
    *,
    business_slug: str,
    days_ahead: int = 14,
    service_id: int | None = None,
    staff_business_user_id: int | None = None,
) -> dict[str, Any]:
    business = get_business_or_none(db, business_slug)

    if business is None:
        raise ValueError("business_not_found")

    if service_id is not None:
        service = get_service_or_none(db, business_id=business.id, service_id=service_id)
        if service is None:
            raise ValueError("service_not_found")
        if not get_public_bookable_staff(db, business.id, service_id):
            raise ValueError("no_staff_available_for_service")
    if (
        staff_business_user_id is not None
        and get_public_staff_or_none(
            db,
            business_id=business.id,
            business_user_id=staff_business_user_id,
            service_id=service_id,
        )
        is None
    ):
        raise ValueError("staff_not_available_for_service")

    has_bookable_staff = bool(get_public_bookable_staff(db, business.id, service_id))

    settings = (
        db.query(AvailabilitySettings)
        .filter(AvailabilitySettings.business_id == business.id)
        .first()
    )
    today = date_cls.today()
    end_date = today + timedelta(days=days_ahead - 1)
    booked_by_date = get_booked_slots_by_date(
        db,
        business.id,
        today,
        end_date,
    )

    availability = []

    for offset in range(days_ahead):
        current_day = today + timedelta(days=offset)
        iso_date = current_day.isoformat()
        if service_id is not None and has_bookable_staff:
            service_slots = get_available_slots(
                db,
                business_slug=business_slug,
                service_id=service_id,
                date=iso_date,
                staff_business_user_id=staff_business_user_id,
            )
            day_windows = service_slots
            labels = [slot["label"] for slot in service_slots]
        else:
            day_windows = (
                get_windows_for_date(
                    db,
                    business=business,
                    settings=settings,
                    target_date=current_day,
                )
                if has_bookable_staff
                else []
            )
            labels = [window["start"] for window in day_windows]
        booked_slots = booked_by_date.get(iso_date, [])
        available_slots = (
            labels
            if service_id is not None
            else [slot for slot in labels if slot not in booked_slots]
        )

        availability.append(
            {
                "date": iso_date,
                "day_label": format_day_label(current_day),
                "weekday": business_weekday(current_day),
                "slots": available_slots,
                "booked_slots": booked_slots,
                "is_available": len(day_windows) > 0,
            }
        )

    return {
        "business_slug": business.slug,
        "business_name": business.name,
        "days_ahead": days_ahead,
        "availability": availability,
    }
