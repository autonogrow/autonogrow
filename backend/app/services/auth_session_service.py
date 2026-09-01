from datetime import datetime, timedelta
from hashlib import sha256
from hmac import compare_digest
from secrets import token_urlsafe

from sqlalchemy.orm import Session

from app.models import AuthSession

SESSION_MAX_AGE = 7 * 24 * 60 * 60


def session_token_hash(token: str) -> str:
    return sha256(token.encode("utf-8")).hexdigest()


def create_auth_session(
    db: Session,
    *,
    user_id: int,
    now: datetime | None = None,
) -> tuple[AuthSession, str]:
    current = now or datetime.utcnow()
    token = token_urlsafe(48)
    row = AuthSession(
        user_id=user_id,
        token_hash=session_token_hash(token),
        created_at=current,
        expires_at=current + timedelta(seconds=SESSION_MAX_AGE),
    )
    db.add(row)
    db.flush()
    return row, token


def find_auth_session(db: Session, token: str) -> AuthSession | None:
    candidate_hash = session_token_hash(token)
    row = db.query(AuthSession).filter(AuthSession.token_hash == candidate_hash).first()
    if row is None or not compare_digest(row.token_hash, candidate_hash):
        return None
    return row


def resolve_auth_session(
    db: Session,
    token: str,
    *,
    now: datetime | None = None,
) -> AuthSession | None:
    current = now or datetime.utcnow()
    row = find_auth_session(db, token)
    if row is None or row.revoked_at is not None:
        return None
    if row.expires_at <= current:
        row.revoked_at = current
        db.commit()
        return None
    return row


def revoke_auth_session(
    db: Session,
    token: str,
    *,
    now: datetime | None = None,
) -> tuple[AuthSession | None, bool]:
    row = find_auth_session(db, token)
    if row is None or row.revoked_at is not None:
        return row, False
    row.revoked_at = now or datetime.utcnow()
    db.flush()
    return row, True


def revoke_all_user_sessions(
    db: Session,
    *,
    user_id: int,
    now: datetime | None = None,
) -> int:
    current = now or datetime.utcnow()
    rows = (
        db.query(AuthSession)
        .filter(AuthSession.user_id == user_id, AuthSession.revoked_at.is_(None))
        .all()
    )
    for row in rows:
        row.revoked_at = current
    db.flush()
    return len(rows)


def delete_expired_auth_sessions(
    db: Session,
    *,
    user_id: int,
    now: datetime | None = None,
) -> int:
    return (
        db.query(AuthSession)
        .filter(
            AuthSession.user_id == user_id,
            AuthSession.expires_at <= (now or datetime.utcnow()),
        )
        .delete(synchronize_session=False)
    )
