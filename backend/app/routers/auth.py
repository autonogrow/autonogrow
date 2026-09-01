from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import BaseModel, model_validator
from sqlalchemy.orm import Session

from app.core.audit import record_audit
from app.core.config import get_settings
from app.core.csrf import CSRF_COOKIE, CSRF_MAX_AGE, create_csrf_token
from app.core.database import get_db
from app.core.security import (
    SESSION_COOKIE,
    SESSION_MAX_AGE,
    create_session_token,
    get_current_user,
    has_owner_access,
    read_session_token,
    require_owner,
    sync_effective_owner_access,
)
from app.models import BusinessUser, User
from app.services.auth_session_service import (
    create_auth_session,
    delete_expired_auth_sessions,
    revoke_all_user_sessions,
    revoke_auth_session,
)

router = APIRouter(prefix="/api/auth", tags=["auth"])


def _clear_auth_cookies(response: Response) -> None:
    settings = get_settings()
    response.delete_cookie(
        SESSION_COOKIE,
        path="/",
        secure=settings.cookie_secure,
        httponly=True,
        samesite="lax",
    )
    response.delete_cookie(
        CSRF_COOKIE,
        path="/",
        secure=settings.cookie_secure,
        httponly=False,
        samesite="lax",
    )


class GoogleLoginRequest(BaseModel):
    credential: str | None = None
    id_token: str | None = None

    @model_validator(mode="after")
    def require_token(self):
        if not (self.credential or self.id_token):
            raise ValueError("credential or id_token is required")
        return self


def serialize_user(db: Session, user: User) -> dict:
    effective_owner = has_owner_access(user)
    memberships = (
        db.query(BusinessUser)
        .filter(BusinessUser.user_id == user.id, BusinessUser.active.is_(True))
        .all()
    )
    businesses = [
        {
            "slug": item.business.slug,
            "name": item.business.name,
            "role": item.role,
            "business_user_id": item.id,
            "bookable": item.bookable,
            "show_schedule": item.show_schedule,
            "public_name": item.public_name,
        }
        for item in memberships
        if item.business is not None
    ]
    return {
        "id": user.id,
        "email": user.email,
        "name": user.name,
        "preferred_name": user.preferred_name,
        "picture_url": user.picture_url,
        "is_owner": effective_owner,
        "businesses": businesses,
        "can_access_owner": effective_owner,
        "can_access_customer_portal": True,
    }


@router.post("/google")
def google_login(
    payload: GoogleLoginRequest, response: Response, request: Request, db: Session = Depends(get_db)
):
    settings = get_settings()
    if not settings.google_client_id:
        raise HTTPException(status_code=503, detail="GOOGLE_CLIENT_ID no está configurado")
    if not settings.session_secret:
        raise HTTPException(status_code=503, detail="SESSION_SECRET no está configurado")
    try:
        from google.auth.exceptions import GoogleAuthError
        from google.auth.transport import requests as google_requests
        from google.oauth2 import id_token as google_id_token

        claims = google_id_token.verify_oauth2_token(
            payload.credential or payload.id_token,
            google_requests.Request(),
            settings.google_client_id,
        )
    except (ValueError, TypeError, GoogleAuthError) as exc:
        raise HTTPException(status_code=400, detail="Google ID token inválido") from exc

    if claims.get("email_verified") is not True:
        raise HTTPException(status_code=400, detail="Google no ha verificado este email")
    email = str(claims.get("email") or "").strip().lower()
    google_sub = str(claims.get("sub") or "").strip()
    if not email or not google_sub:
        raise HTTPException(status_code=400, detail="El token no contiene email o subject")

    user = db.query(User).filter(User.google_sub == google_sub).first()
    email_user = db.query(User).filter(User.email == email).first()
    if user is None:
        user = email_user
    elif email_user is not None and email_user.id != user.id:
        raise HTTPException(status_code=409, detail="El email ya está vinculado a otra cuenta")
    if user is None:
        user = User(email=email, is_active=True)
        db.add(user)
    elif not user.is_active:
        raise HTTPException(status_code=403, detail="El usuario está desactivado")
    if user.google_sub and user.google_sub != google_sub:
        raise HTTPException(
            status_code=409, detail="El usuario ya está vinculado a otra cuenta Google"
        )

    user.email = email
    user.google_sub = google_sub
    if not user.preferred_name:
        user.name = claims.get("name") or user.name
    user.picture_url = claims.get("picture") or user.picture_url
    user.email_verified = True
    user.is_owner = has_owner_access(user)
    user.last_login_at = datetime.utcnow()
    db.flush()
    delete_expired_auth_sessions(db, user_id=user.id)
    auth_session, raw_session_token = create_auth_session(db, user_id=user.id)
    signed_session_token = create_session_token(raw_session_token)
    record_audit(
        db,
        action="login_success",
        request=request,
        actor=user,
        resource_type="user",
        resource_id=user.id,
        commit=False,
    )
    record_audit(
        db,
        action="session_created",
        request=request,
        actor=user,
        resource_type="auth_session",
        resource_id=auth_session.id,
        commit=False,
    )
    db.commit()
    db.refresh(user)

    response.set_cookie(
        key=SESSION_COOKIE,
        value=signed_session_token,
        max_age=SESSION_MAX_AGE,
        httponly=True,
        secure=settings.cookie_secure,
        samesite="lax",
        path="/",
    )
    return {"ok": True, "user": serialize_user(db, user)}


@router.get("/me")
def auth_me(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    sync_effective_owner_access(user)
    return serialize_user(db, user)


@router.get("/csrf")
def csrf_token(response: Response):
    settings = get_settings()
    if not settings.csrf_enabled:
        return {"csrf_token": None}
    token = create_csrf_token()
    response.set_cookie(
        key=CSRF_COOKIE,
        value=token,
        max_age=CSRF_MAX_AGE,
        httponly=False,
        secure=settings.cookie_secure,
        samesite="lax",
        path="/",
    )
    return {"csrf_token": token}


@router.post("/logout")
def logout(
    response: Response,
    request: Request,
    db: Session = Depends(get_db),
):
    cookie = request.cookies.get(SESSION_COOKIE, "")
    session_token = read_session_token(cookie) if cookie else None
    if session_token:
        auth_session, revoked = revoke_auth_session(db, session_token)
        if revoked and auth_session is not None:
            record_audit(
                db,
                action="session_revoked",
                request=request,
                actor=auth_session.user,
                resource_type="auth_session",
                resource_id=auth_session.id,
                commit=False,
            )
            db.commit()
    _clear_auth_cookies(response)
    return {"ok": True}


@router.post("/logout-all")
def logout_all(
    response: Response,
    request: Request,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    revoked = revoke_all_user_sessions(db, user_id=user.id)
    record_audit(
        db,
        action="all_sessions_revoked",
        request=request,
        actor=user,
        resource_type="user",
        resource_id=user.id,
        metadata={"revoked_count": revoked},
        commit=False,
    )
    db.commit()
    _clear_auth_cookies(response)
    return {"ok": True, "revoked_sessions": revoked}


@router.post("/users/{user_id}/sessions/revoke-all")
def owner_revoke_all_user_sessions(
    user_id: int,
    response: Response,
    request: Request,
    actor: User = Depends(require_owner),
    db: Session = Depends(get_db),
):
    target = db.get(User, user_id)
    if target is None:
        raise HTTPException(status_code=404, detail="User not found")
    revoked = revoke_all_user_sessions(db, user_id=target.id)
    record_audit(
        db,
        action="all_sessions_revoked",
        request=request,
        actor=actor,
        resource_type="user",
        resource_id=target.id,
        metadata={"revoked_count": revoked, "revoked_by_owner": True},
        commit=False,
    )
    db.commit()
    if actor.id == target.id:
        _clear_auth_cookies(response)
    return {"ok": True, "user_id": target.id, "revoked_sessions": revoked}
