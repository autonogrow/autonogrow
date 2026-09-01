from fastapi import Depends, HTTPException, Request
from itsdangerous import BadSignature, SignatureExpired, URLSafeTimedSerializer
from sqlalchemy.orm import Session

from app.core.config import get_owner_allowed_emails, get_settings
from app.core.database import get_db
from app.models import Booking, Business, BusinessUser, User
from app.services.business_status_service import ensure_business_operational

SESSION_COOKIE = "autonogrow_session"
SESSION_MAX_AGE = 7 * 24 * 60 * 60
SAFE_BUSINESS_METHODS = frozenset({"GET", "HEAD", "OPTIONS"})


def has_owner_access(user: User) -> bool:
    """Return the effective global Owner permission for the current configuration.

    Staging and production always require a non-empty OWNER_ALLOWED_EMAILS value, so the
    allowlist is authoritative there.  The database flag remains a compatibility fallback only
    for local/test fixtures that intentionally run without an allowlist.
    """

    if user.is_active is False:
        return False
    allowed_emails = get_owner_allowed_emails()
    if allowed_emails:
        return user.email.strip().lower() in allowed_emails
    return get_settings().app_env in {"local", "test"} and bool(user.is_owner)


def sync_effective_owner_access(user: User) -> User:
    """Expose the effective permission to downstream code that still reads ``is_owner``."""

    user.is_owner = has_owner_access(user)
    return user


def _serializer() -> URLSafeTimedSerializer:
    secret = get_settings().session_secret
    if not secret:
        raise RuntimeError("SESSION_SECRET no está configurado")
    return URLSafeTimedSerializer(secret, salt="autonogrow-session-v1")


def create_session_token(user_id: int) -> str:
    return _serializer().dumps({"user_id": user_id})


def read_session_user_id(token: str) -> int | None:
    try:
        payload = _serializer().loads(token, max_age=SESSION_MAX_AGE)
        return int(payload["user_id"])
    except (BadSignature, SignatureExpired, KeyError, TypeError, ValueError, RuntimeError):
        return None


def get_optional_current_user(request: Request, db: Session = Depends(get_db)) -> User | None:
    token = request.cookies.get(SESSION_COOKIE)
    if not token:
        return None
    user_id = read_session_user_id(token)
    if user_id is None:
        return None
    user = db.query(User).filter(User.id == user_id).first()
    if user is not None:
        sync_effective_owner_access(user)
    request.state.current_user = user
    return user


def get_current_user(user: User | None = Depends(get_optional_current_user)) -> User:
    if user is None:
        raise HTTPException(status_code=401, detail="Authentication required")
    if not user.is_active:
        raise HTTPException(status_code=403, detail="User is inactive")
    sync_effective_owner_access(user)
    return user


def require_owner(user: User = Depends(get_current_user)) -> User:
    sync_effective_owner_access(user)
    if not user.is_owner:
        raise HTTPException(status_code=403, detail="Owner access required")
    return user


def require_business_operational_status(
    business_slug: str,
    request: Request,
    db: Session = Depends(get_db),
) -> None:
    """Allow historical reads but reject every normal business mutation when inactive."""

    if request.method.upper() in SAFE_BUSINESS_METHODS:
        return
    business = db.query(Business).filter(Business.slug == business_slug).first()
    if business is None:
        raise HTTPException(status_code=404, detail="Business not found")
    ensure_business_operational(business)


def require_business_operational_status_by_id(
    business_id: int,
    request: Request,
    db: Session = Depends(get_db),
) -> None:
    """Owner operational routes use numeric tenant ids instead of slugs."""

    if request.method.upper() in SAFE_BUSINESS_METHODS:
        return
    business = db.get(Business, business_id)
    if business is None:
        raise HTTPException(status_code=404, detail="Business not found")
    ensure_business_operational(business)


def require_business_access(
    business_slug: str,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
    _operational_status: None = Depends(require_business_operational_status),
) -> User:
    sync_effective_owner_access(user)
    if user.is_owner:
        return user
    membership = (
        db.query(BusinessUser)
        .join(Business, Business.id == BusinessUser.business_id)
        .filter(
            Business.slug == business_slug,
            BusinessUser.user_id == user.id,
            BusinessUser.active.is_(True),
            BusinessUser.role.in_(("business_admin", "business_staff")),
        )
        .first()
    )
    if membership is None:
        raise HTTPException(status_code=403, detail="You do not have access to this business")
    if membership.business.status == "archived":
        ensure_business_operational(membership.business)
    return user


def get_business_membership(
    db: Session,
    *,
    business_slug: str,
    user_id: int,
) -> BusinessUser | None:
    return (
        db.query(BusinessUser)
        .join(Business, Business.id == BusinessUser.business_id)
        .filter(
            Business.slug == business_slug,
            BusinessUser.user_id == user_id,
            BusinessUser.active.is_(True),
            BusinessUser.role.in_(("business_admin", "business_staff")),
        )
        .first()
    )


def require_business_admin(
    business_slug: str,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
    _operational_status: None = Depends(require_business_operational_status),
) -> User:
    sync_effective_owner_access(user)
    if user.is_owner:
        return user
    membership = get_business_membership(db, business_slug=business_slug, user_id=user.id)
    if membership is None:
        raise HTTPException(status_code=403, detail="You do not have access to this business")
    if membership.business.status == "archived":
        ensure_business_operational(membership.business)
    if membership.role != "business_admin":
        raise HTTPException(status_code=403, detail="Business administrator access required")
    return user


def require_tenant_business_admin(
    business_slug: str,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
    _operational_status: None = Depends(require_business_operational_status),
) -> User:
    """Require the tenant Business Owner, never the global AutonoGrow operator."""
    sync_effective_owner_access(user)
    if user.is_owner:
        raise HTTPException(status_code=403, detail="Business owner access required")
    membership = get_business_membership(db, business_slug=business_slug, user_id=user.id)
    if membership is None or membership.role != "business_admin":
        raise HTTPException(status_code=403, detail="Business owner access required")
    if membership.business.status == "archived":
        ensure_business_operational(membership.business)
    return user


require_business_member = require_business_access
require_business_staff_or_admin = require_business_access
require_can_manage_business_settings = require_business_admin


def ensure_can_manage_booking(
    db: Session,
    *,
    business_slug: str,
    booking: Booking,
    user: User,
) -> BusinessUser | None:
    sync_effective_owner_access(user)
    if user.is_owner:
        return None
    membership = get_business_membership(db, business_slug=business_slug, user_id=user.id)
    if membership is None:
        raise HTTPException(status_code=403, detail="You do not have access to this booking")
    if membership.role == "business_staff" and booking.staff_business_user_id != membership.id:
        raise HTTPException(status_code=403, detail="This booking is not assigned to you")
    return membership


def require_booking_business_access(
    booking_id: int,
    request: Request,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> User:
    booking = db.query(Booking).filter(Booking.id == booking_id).first()
    if booking is None:
        raise HTTPException(status_code=404, detail="Booking not found")
    business = db.query(Business).filter(Business.id == booking.business_id).first()
    if business is None:
        raise HTTPException(status_code=404, detail="Business not found")
    if request.method.upper() not in SAFE_BUSINESS_METHODS:
        ensure_business_operational(business)
    ensure_can_manage_booking(db, business_slug=business.slug, booking=booking, user=user)
    return user
