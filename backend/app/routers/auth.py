from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import BaseModel, model_validator
from sqlalchemy.orm import Session

from app.core.config import get_owner_allowed_emails, get_settings
from app.core.database import get_db
from app.core.audit import record_audit
from app.core.csrf import CSRF_COOKIE, CSRF_MAX_AGE, create_csrf_token
from app.core.security import (
    SESSION_COOKIE,
    SESSION_MAX_AGE,
    create_session_token,
    get_current_user,
)
from app.models import BusinessUser, User


router = APIRouter(prefix="/api/auth", tags=["auth"])


class GoogleLoginRequest(BaseModel):
    credential: str | None = None
    id_token: str | None = None

    @model_validator(mode="after")
    def require_token(self):
        if not (self.credential or self.id_token):
            raise ValueError("credential or id_token is required")
        return self


def serialize_user(db: Session, user: User) -> dict:
    memberships = (
        db.query(BusinessUser)
        .filter(BusinessUser.user_id == user.id, BusinessUser.active.is_(True))
        .all()
    )
    businesses = [
        {"slug": item.business.slug, "name": item.business.name, "role": item.role}
        for item in memberships
        if item.business is not None
    ]
    return {
        "id": user.id,
        "email": user.email,
        "name": user.name,
        "preferred_name": user.preferred_name,
        "picture_url": user.picture_url,
        "is_owner": user.is_owner,
        "businesses": businesses,
        "can_access_owner": user.is_owner,
        "can_access_customer_portal": True,
    }


@router.post("/google")
def google_login(payload: GoogleLoginRequest, response: Response, request: Request, db: Session = Depends(get_db)):
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
        user = User(email=email)
        db.add(user)
    elif not user.is_active:
        raise HTTPException(status_code=403, detail="El usuario está desactivado")
    if user.google_sub and user.google_sub != google_sub:
        raise HTTPException(status_code=409, detail="El usuario ya está vinculado a otra cuenta Google")

    user.email = email
    user.google_sub = google_sub
    user.name = claims.get("name") or user.name
    user.picture_url = claims.get("picture") or user.picture_url
    user.email_verified = True
    user.is_owner = email in get_owner_allowed_emails()
    user.last_login_at = datetime.utcnow()
    db.commit()
    db.refresh(user)

    response.set_cookie(
        key=SESSION_COOKIE,
        value=create_session_token(user.id),
        max_age=SESSION_MAX_AGE,
        httponly=True,
        secure=settings.cookie_secure,
        samesite="lax",
        path="/",
    )
    record_audit(db, action="login_success", request=request, actor=user, resource_type="user", resource_id=user.id)
    return {"ok": True, "user": serialize_user(db, user)}


@router.get("/me")
def auth_me(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
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
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    settings = get_settings()
    record_audit(db, action="logout", request=request, actor=user, resource_type="user", resource_id=user.id)
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
    return {"ok": True}
