from fastapi import Depends, HTTPException, Request
from itsdangerous import BadSignature, SignatureExpired, URLSafeTimedSerializer
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.database import get_db
from app.models import Booking, Business, BusinessUser, User


SESSION_COOKIE = "autonogrow_session"
SESSION_MAX_AGE = 7 * 24 * 60 * 60


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
    request.state.current_user = user
    return user


def get_current_user(user: User | None = Depends(get_optional_current_user)) -> User:
    if user is None:
        raise HTTPException(status_code=401, detail="Authentication required")
    if not user.is_active:
        raise HTTPException(status_code=403, detail="User is inactive")
    return user


def require_owner(user: User = Depends(get_current_user)) -> User:
    if not user.is_owner:
        raise HTTPException(status_code=403, detail="Owner access required")
    return user


def require_business_access(
    business_slug: str,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> User:
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
    return user


def require_business_admin(
    business_slug: str,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> User:
    """Business roles currently share permissions; kept separate for future refinement."""
    return require_business_access(business_slug=business_slug, user=user, db=db)


def require_booking_business_access(
    booking_id: int,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> User:
    booking = db.query(Booking).filter(Booking.id == booking_id).first()
    if booking is None:
        raise HTTPException(status_code=404, detail="Booking not found")
    business = db.query(Business).filter(Business.id == booking.business_id).first()
    if business is None:
        raise HTTPException(status_code=404, detail="Business not found")
    if user.is_owner:
        return user
    membership = db.query(BusinessUser).filter(
        BusinessUser.business_id == business.id,
        BusinessUser.user_id == user.id,
        BusinessUser.active.is_(True),
    ).first()
    if membership is None:
        raise HTTPException(status_code=403, detail="You do not have access to this booking")
    return user
