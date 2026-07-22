import json
from datetime import datetime
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field, field_validator
from sqlalchemy.orm import Session

from app.core.audit import record_audit
from app.core.database import get_db
from app.core.security import get_business_membership, require_business_access, require_business_admin
from app.models import (
    AvailabilitySettings,
    Booking,
    Business,
    BusinessService,
    BusinessUser,
    BusinessUserAvailability,
    BusinessUserAvailabilityException,
    User,
)
from app.services.availability_service import (
    get_public_bookable_staff,
    normalize_weekly_schedule,
    parse_weekly_schedule,
    parse_windows,
    parse_windows_from_json,
    serialize_public_staff,
)


public_router = APIRouter(prefix="/api/businesses/{business_slug}/staff", tags=["staff"])
admin_router = APIRouter(
    prefix="/api/admin/businesses/{business_slug}/staff",
    tags=["admin-staff"],
    dependencies=[Depends(require_business_admin)],
)
member_router = APIRouter(
    prefix="/api/admin/businesses/{business_slug}",
    tags=["member-staff"],
    dependencies=[Depends(require_business_access)],
)


class StaffCreate(BaseModel):
    email: str = Field(min_length=3, max_length=320)
    role: str = "business_staff"
    public_name: str | None = Field(default=None, max_length=200)
    active: bool = True
    bookable: bool = False
    show_schedule: bool = True
    bio: str | None = Field(default=None, max_length=2000)
    avatar_url: str | None = Field(default=None, max_length=2000)

    @field_validator("email")
    @classmethod
    def validate_email(cls, value: str) -> str:
        value = value.strip().lower()
        if "@" not in value or value.startswith("@") or value.endswith("@"):
            raise ValueError("Invalid email")
        return value

    @field_validator("role")
    @classmethod
    def validate_role(cls, value: str) -> str:
        if value not in {"business_admin", "business_staff"}:
            raise ValueError("Invalid business role")
        return value


class StaffUpdate(BaseModel):
    role: str | None = None
    public_name: str | None = Field(default=None, max_length=200)
    active: bool | None = None
    bookable: bool | None = None
    show_schedule: bool | None = None
    bio: str | None = Field(default=None, max_length=2000)
    avatar_url: str | None = Field(default=None, max_length=2000)

    @field_validator("role")
    @classmethod
    def validate_role(cls, value: str | None) -> str | None:
        if value is not None and value not in {"business_admin", "business_staff"}:
            raise ValueError("Invalid business role")
        return value


class StaffScheduleUpdate(BaseModel):
    weekly_schedule: dict[str, list[dict[str, str]]]


class StaffServicesUpdate(BaseModel):
    service_ids: list[int] = Field(default_factory=list)

    @field_validator("service_ids")
    @classmethod
    def validate_service_ids(cls, value: list[int]) -> list[int]:
        if any(service_id < 1 for service_id in value):
            raise ValueError("Invalid service id")
        return list(dict.fromkeys(value))


class StaffExceptionCreate(BaseModel):
    date: str = Field(pattern=r"^\d{4}-\d{2}-\d{2}$")
    type: str = Field(pattern=r"^(closed|custom_hours)$")
    windows: list[dict[str, str]] | None = None
    reason: str | None = Field(default=None, max_length=500)


BLOCKING_BOOKING_STATUSES = {"requested", "pending", "confirmed"}
TERMINAL_BOOKING_STATUSES = {"cancelled", "rejected", "completed", "no_show"}


def get_business_or_404(db: Session, business_slug: str, *, public: bool = False) -> Business:
    query = db.query(Business).filter(Business.slug == business_slug)
    if public:
        query = query.filter(Business.status == "active")
    business = query.first()
    if business is None:
        raise HTTPException(status_code=404, detail="Business not found")
    return business


def get_member_or_404(
    db: Session, *, business_id: int, business_user_id: int
) -> BusinessUser:
    member = (
        db.query(BusinessUser)
        .filter(
            BusinessUser.id == business_user_id,
            BusinessUser.business_id == business_id,
        )
        .first()
    )
    if member is None:
        raise HTTPException(status_code=404, detail="Staff member not found")
    return member


def serialize_member(member: BusinessUser) -> dict:
    return {
        "id": member.id,
        "business_id": member.business_id,
        "user_id": member.user_id,
        "email": member.user.email,
        "name": member.user.name,
        "picture_url": member.user.picture_url,
        "role": member.role,
        "active": member.active,
        "public_name": member.public_name,
        "bookable": member.bookable,
        "show_schedule": member.show_schedule,
        "bio": member.bio,
        "avatar_url": member.avatar_url,
        "removed_at": member.removed_at.isoformat() if member.removed_at else None,
        "pending": member.user.google_sub is None,
        "service_ids": sorted(service.id for service in member.services if service.active),
    }


def get_business_now(db: Session, business_id: int) -> datetime:
    settings = (
        db.query(AvailabilitySettings)
        .filter(AvailabilitySettings.business_id == business_id)
        .first()
    )
    timezone_name = settings.timezone if settings else "Europe/Madrid"
    try:
        return datetime.now(ZoneInfo(timezone_name)).replace(tzinfo=None)
    except ZoneInfoNotFoundError:
        return datetime.utcnow()


def get_booking_start(booking: Booking) -> datetime | None:
    if booking.start_datetime:
        return booking.start_datetime
    if not booking.preferred_date or not booking.preferred_time:
        return None
    try:
        return datetime.fromisoformat(
            f"{booking.preferred_date}T{booking.preferred_time}"
        )
    except ValueError:
        return None


def get_staff_removal_blockers(
    db: Session, *, business_id: int, business_user_id: int
) -> list[Booking]:
    now = get_business_now(db, business_id)
    candidates = (
        db.query(Booking)
        .filter(
            Booking.business_id == business_id,
            Booking.staff_business_user_id == business_user_id,
            ~Booking.status.in_(TERMINAL_BOOKING_STATUSES),
        )
        .all()
    )
    blockers = []
    for booking in candidates:
        starts_at = get_booking_start(booking)
        if booking.status in BLOCKING_BOOKING_STATUSES or bool(
            starts_at and starts_at > now
        ):
            blockers.append(booking)
    return sorted(
        blockers,
        key=lambda booking: (get_booking_start(booking) or datetime.max, booking.id),
    )


def serialize_removal_blocker(booking: Booking) -> dict:
    starts_at = get_booking_start(booking)
    return {
        "id": booking.id,
        "date": starts_at.date().isoformat() if starts_at else booking.preferred_date,
        "start_time": starts_at.strftime("%H:%M") if starts_at else booking.preferred_time,
        "customer_name": booking.customer.name,
        "customer_phone": booking.customer.phone,
        "service_name": booking.service_name,
        "status": booking.status,
    }


def serialize_staff_exception(item: BusinessUserAvailabilityException) -> dict:
    return {
        "id": item.id,
        "date": item.date,
        "type": item.type,
        "windows": parse_windows_from_json(item.windows_json),
        "reason": item.reason,
    }


def validate_windows(windows: list[dict[str, str]]) -> list[dict[str, str]]:
    normalized = parse_windows(windows)
    parsed = []
    for window in normalized:
        try:
            start = datetime.strptime(window["start"], "%H:%M")
            end = datetime.strptime(window["end"], "%H:%M")
        except ValueError as exc:
            raise HTTPException(status_code=422, detail="Hours must use HH:MM") from exc
        if start >= end:
            raise HTTPException(status_code=422, detail="Each availability window must end after it starts")
        parsed.append((start, end, window))
    parsed.sort(key=lambda item: item[0])
    for previous, current in zip(parsed, parsed[1:]):
        if previous[1] > current[0]:
            raise HTTPException(status_code=422, detail="Availability windows cannot overlap")
    return [item[2] for item in parsed]


def member_schedule(db: Session, business: Business, member: BusinessUser) -> dict:
    rows = (
        db.query(BusinessUserAvailability)
        .filter(BusinessUserAvailability.business_user_id == member.id)
        .order_by(BusinessUserAvailability.weekday)
        .all()
    )
    inherits_business_schedule = not rows
    if rows:
        schedule = {str(day): [] for day in range(7)}
        for row in rows:
            schedule[str(row.weekday)] = (
                parse_windows_from_json(row.windows_json) if row.active else []
            )
    else:
        settings = (
            db.query(AvailabilitySettings)
            .filter(AvailabilitySettings.business_id == business.id)
            .first()
        )
        schedule = normalize_weekly_schedule(
            {
                str(day): windows
                for day, windows in parse_weekly_schedule(
                    settings.weekly_schedule_json if settings else None
                ).items()
            }
            if settings
            else None
        )
    exceptions = (
        db.query(BusinessUserAvailabilityException)
        .filter(BusinessUserAvailabilityException.business_user_id == member.id)
        .order_by(BusinessUserAvailabilityException.date, BusinessUserAvailabilityException.id)
        .all()
    )
    return {
        "business_user_id": member.id,
        "inherits_business_schedule": inherits_business_schedule,
        "weekly_schedule": schedule,
        "exceptions": [serialize_staff_exception(item) for item in exceptions],
    }


@public_router.get("")
def list_public_staff(
    business_slug: str,
    service_id: int | None = Query(default=None, ge=1),
    db: Session = Depends(get_db),
):
    business = get_business_or_404(db, business_slug, public=True)
    if service_id is not None:
        service = (
            db.query(BusinessService)
            .filter(
                BusinessService.id == service_id,
                BusinessService.business_id == business.id,
                BusinessService.active.is_(True),
            )
            .first()
        )
        if service is None:
            raise HTTPException(status_code=404, detail="Service not found")
    return {
        "business_slug": business.slug,
        "staff": [
            serialize_public_staff(item)
            for item in get_public_bookable_staff(db, business.id, service_id)
        ],
    }


@member_router.get("/my-staff-availability")
def get_my_staff_availability(
    business_slug: str,
    actor: User = Depends(require_business_access),
    db: Session = Depends(get_db),
):
    if actor.is_owner:
        raise HTTPException(status_code=400, detail="Owner does not have a staff schedule")
    business = get_business_or_404(db, business_slug)
    member = get_business_membership(
        db, business_slug=business_slug, user_id=actor.id
    )
    if member is None:
        raise HTTPException(status_code=403, detail="You do not have access to this business")
    return member_schedule(db, business, member)


@admin_router.get("")
def list_staff(business_slug: str, db: Session = Depends(get_db)):
    business = get_business_or_404(db, business_slug)
    members = (
        db.query(BusinessUser)
        .filter(BusinessUser.business_id == business.id)
        .order_by(BusinessUser.id)
        .all()
    )
    return {"business_slug": business.slug, "staff": [serialize_member(item) for item in members]}


@admin_router.post("", status_code=201)
def create_staff(
    business_slug: str,
    payload: StaffCreate,
    request: Request,
    actor: User = Depends(require_business_admin),
    db: Session = Depends(get_db),
):
    business = get_business_or_404(db, business_slug)
    user = db.query(User).filter(User.email == payload.email).first()
    if user is None:
        user = User(email=payload.email, email_verified=False, is_active=True)
        db.add(user)
        db.flush()
    member = (
        db.query(BusinessUser)
        .filter(BusinessUser.business_id == business.id, BusinessUser.user_id == user.id)
        .first()
    )
    values = payload.model_dump(exclude={"email"})
    is_reactivation = member is not None and not member.active
    if member is None:
        member = BusinessUser(business_id=business.id, user_id=user.id, **values)
        db.add(member)
    elif member.active:
        raise HTTPException(status_code=409, detail="User is already assigned to this business")
    else:
        for field, value in values.items():
            setattr(member, field, value)
        member.bookable = False
        member.show_schedule = False
        member.removed_at = None
    db.commit()
    db.refresh(member)
    record_audit(
        db, action="user_reactivated" if is_reactivation else "user_assigned_to_business", request=request, actor=actor,
        business_id=business.id, resource_type="business_user", resource_id=member.id,
        metadata={"role": member.role, "bookable": member.bookable},
    )
    return {"ok": True, "staff_member": serialize_member(member)}


@admin_router.patch("/{business_user_id}")
def update_staff(
    business_slug: str,
    business_user_id: int,
    payload: StaffUpdate,
    request: Request,
    actor: User = Depends(require_business_admin),
    db: Session = Depends(get_db),
):
    business = get_business_or_404(db, business_slug)
    member = get_member_or_404(
        db, business_id=business.id, business_user_id=business_user_id
    )
    updates = payload.model_dump(exclude_unset=True)
    is_reactivation = not member.active and updates.get("active") is True
    if member.removed_at is not None and updates.get("active") is not True:
        raise HTTPException(
            status_code=409,
            detail="Reactivate the team member before editing their profile",
        )
    if updates.get("active") is False and member.active:
        raise HTTPException(
            status_code=409,
            detail="Use DELETE /staff/{business_user_id} to remove an active team member safely",
        )
    if (
        updates.get("role") == "business_staff"
        and member.role == "business_admin"
        and member.active
    ):
        active_admin_count = (
            db.query(BusinessUser)
            .filter(
                BusinessUser.business_id == business.id,
                BusinessUser.role == "business_admin",
                BusinessUser.active.is_(True),
            )
            .count()
        )
        if active_admin_count <= 1:
            raise HTTPException(status_code=409, detail="last_active_admin")
    for field, value in updates.items():
        setattr(member, field, value.strip() or None if isinstance(value, str) else value)
    if updates.get("active") is True:
        member.removed_at = None
    if is_reactivation:
        member.bookable = False
        member.show_schedule = False
    member.updated_at = datetime.utcnow()
    db.commit()
    db.refresh(member)
    record_audit(
        db, action="user_reactivated" if is_reactivation else "user_role_changed", request=request, actor=actor,
        business_id=business.id, resource_type="business_user", resource_id=member.id,
        metadata={"role": member.role, "active": member.active, "bookable": member.bookable},
    )
    return {"ok": True, "staff_member": serialize_member(member)}


@admin_router.put("/{business_user_id}/services")
def update_staff_services(
    business_slug: str,
    business_user_id: int,
    payload: StaffServicesUpdate,
    request: Request,
    actor: User = Depends(require_business_admin),
    db: Session = Depends(get_db),
):
    business = get_business_or_404(db, business_slug)
    actor_membership = get_business_membership(
        db, business_slug=business_slug, user_id=actor.id
    )
    if actor_membership is None or actor_membership.role != "business_admin":
        raise HTTPException(
            status_code=403, detail="Business administrator access required"
        )
    member = get_member_or_404(
        db, business_id=business.id, business_user_id=business_user_id
    )
    if not member.active or member.removed_at is not None:
        raise HTTPException(status_code=409, detail="Staff member is inactive")
    if not member.bookable:
        raise HTTPException(
            status_code=409,
            detail="Activate Reservable before assigning services",
        )

    services = (
        db.query(BusinessService)
        .filter(
            BusinessService.business_id == business.id,
            BusinessService.active.is_(True),
            BusinessService.id.in_(payload.service_ids),
        )
        .order_by(BusinessService.id)
        .all()
        if payload.service_ids
        else []
    )
    if len(services) != len(payload.service_ids):
        raise HTTPException(
            status_code=422,
            detail="All services must be active and belong to this business",
        )

    member.services = services
    member.updated_at = datetime.utcnow()
    db.commit()
    db.refresh(member)
    record_audit(
        db,
        action="staff_services_changed",
        request=request,
        actor=actor,
        business_id=business.id,
        resource_type="business_user",
        resource_id=member.id,
        metadata={"service_ids": payload.service_ids},
    )
    return {"ok": True, "staff_member": serialize_member(member)}


@admin_router.delete("/{business_user_id}")
def remove_staff(
    business_slug: str,
    business_user_id: int,
    request: Request,
    actor: User = Depends(require_business_admin),
    db: Session = Depends(get_db),
):
    business = get_business_or_404(db, business_slug)
    actor_membership = get_business_membership(
        db, business_slug=business_slug, user_id=actor.id
    )
    if actor_membership is None or actor_membership.role != "business_admin":
        raise HTTPException(
            status_code=403, detail="Business administrator access required"
        )

    member = get_member_or_404(
        db, business_id=business.id, business_user_id=business_user_id
    )

    if member.user_id == actor.id:
        active_admin_count = (
            db.query(BusinessUser)
            .filter(
                BusinessUser.business_id == business.id,
                BusinessUser.role == "business_admin",
                BusinessUser.active.is_(True),
            )
            .count()
        )
        if active_admin_count <= 1:
            return JSONResponse(
                status_code=409,
                content={
                    "detail": "last_active_admin",
                    "message": "No puedes eliminar al único administrador activo del negocio.",
                },
            )

    blockers = get_staff_removal_blockers(
        db, business_id=business.id, business_user_id=member.id
    )
    if blockers:
        return JSONResponse(
            status_code=409,
            content={
                "detail": "member_has_future_bookings",
                "message": (
                    "Reasigna, cancela o completa las citas indicadas antes de "
                    "eliminar a este miembro del equipo."
                ),
                "bookings": [serialize_removal_blocker(item) for item in blockers],
            },
        )

    member.active = False
    member.bookable = False
    member.show_schedule = False
    member.removed_at = datetime.utcnow()
    member.updated_at = datetime.utcnow()
    db.commit()
    db.refresh(member)
    record_audit(
        db,
        action="user_removed_from_business",
        request=request,
        actor=actor,
        business_id=business.id,
        resource_type="business_user",
        resource_id=member.id,
        metadata={"role": member.role, "soft_delete": True},
    )
    return {"ok": True, "staff_member": serialize_member(member)}


@admin_router.get("/{business_user_id}/availability")
def get_staff_availability(
    business_slug: str, business_user_id: int, db: Session = Depends(get_db)
):
    business = get_business_or_404(db, business_slug)
    member = get_member_or_404(
        db, business_id=business.id, business_user_id=business_user_id
    )
    return member_schedule(db, business, member)


@admin_router.put("/{business_user_id}/availability")
def update_staff_availability(
    business_slug: str,
    business_user_id: int,
    payload: StaffScheduleUpdate,
    request: Request,
    actor: User = Depends(require_business_admin),
    db: Session = Depends(get_db),
):
    business = get_business_or_404(db, business_slug)
    member = get_member_or_404(
        db, business_id=business.id, business_user_id=business_user_id
    )
    schedule = normalize_weekly_schedule(payload.weekly_schedule)
    schedule = {
        str(weekday): validate_windows(schedule[str(weekday)]) for weekday in range(7)
    }
    for weekday in range(7):
        row = (
            db.query(BusinessUserAvailability)
            .filter(
                BusinessUserAvailability.business_user_id == member.id,
                BusinessUserAvailability.weekday == weekday,
            )
            .first()
        )
        if row is None:
            row = BusinessUserAvailability(
                business_user_id=member.id, weekday=weekday, windows_json="[]", active=True
            )
            db.add(row)
        row.windows_json = json.dumps(schedule[str(weekday)], ensure_ascii=False)
        row.active = True
    db.commit()
    record_audit(
        db, action="settings_changed", request=request, actor=actor,
        business_id=business.id, resource_type="business_user_availability", resource_id=member.id,
    )
    return {"ok": True, "availability": member_schedule(db, business, member)}


@admin_router.post("/{business_user_id}/availability-exceptions", status_code=201)
def create_staff_exception(
    business_slug: str,
    business_user_id: int,
    payload: StaffExceptionCreate,
    request: Request,
    actor: User = Depends(require_business_admin),
    db: Session = Depends(get_db),
):
    business = get_business_or_404(db, business_slug)
    member = get_member_or_404(
        db, business_id=business.id, business_user_id=business_user_id
    )
    if payload.type == "custom_hours" and not payload.windows:
        raise HTTPException(status_code=400, detail="Custom hours require windows")
    windows_json = (
        json.dumps(validate_windows(payload.windows or []), ensure_ascii=False)
        if payload.type == "custom_hours"
        else None
    )
    item = (
        db.query(BusinessUserAvailabilityException)
        .filter(
            BusinessUserAvailabilityException.business_user_id == member.id,
            BusinessUserAvailabilityException.date == payload.date,
        )
        .first()
    )
    if item is None:
        item = BusinessUserAvailabilityException(
            business_user_id=member.id, date=payload.date, type=payload.type,
            windows_json=windows_json, reason=payload.reason,
        )
        db.add(item)
    else:
        item.type = payload.type
        item.windows_json = windows_json
        item.reason = payload.reason
    db.commit()
    db.refresh(item)
    record_audit(
        db, action="settings_changed", request=request, actor=actor,
        business_id=business.id, resource_type="business_user_availability_exception", resource_id=item.id,
    )
    return {"ok": True, "exception": serialize_staff_exception(item)}


@admin_router.delete("/{business_user_id}/availability-exceptions/{exception_id}")
def delete_staff_exception(
    business_slug: str,
    business_user_id: int,
    exception_id: int,
    request: Request,
    actor: User = Depends(require_business_admin),
    db: Session = Depends(get_db),
):
    business = get_business_or_404(db, business_slug)
    member = get_member_or_404(
        db, business_id=business.id, business_user_id=business_user_id
    )
    item = (
        db.query(BusinessUserAvailabilityException)
        .filter(
            BusinessUserAvailabilityException.id == exception_id,
            BusinessUserAvailabilityException.business_user_id == member.id,
        )
        .first()
    )
    if item is None:
        raise HTTPException(status_code=404, detail="Staff exception not found")
    db.delete(item)
    db.commit()
    record_audit(
        db, action="settings_changed", request=request, actor=actor,
        business_id=business.id, resource_type="business_user_availability_exception", resource_id=exception_id,
    )
    return {"ok": True}
