from secrets import token_urlsafe

from itsdangerous import BadSignature, SignatureExpired, URLSafeTimedSerializer

from app.core.config import get_settings

CSRF_COOKIE = "autonogrow_csrf"
CSRF_HEADER = "X-CSRF-Token"
CSRF_MAX_AGE = 7 * 24 * 60 * 60


def _serializer() -> URLSafeTimedSerializer:
    secret = get_settings().session_secret
    if not secret:
        raise RuntimeError("SESSION_SECRET no está configurado")
    return URLSafeTimedSerializer(secret, salt="autonogrow-csrf-v1")


def create_csrf_token() -> str:
    return _serializer().dumps({"nonce": token_urlsafe(32)})


def is_valid_csrf_token(token: str) -> bool:
    try:
        payload = _serializer().loads(token, max_age=CSRF_MAX_AGE)
        return bool(payload.get("nonce"))
    except (BadSignature, SignatureExpired, AttributeError, RuntimeError):
        return False
