from secrets import compare_digest

from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware

from app.core.config import get_settings
from app.core.csrf import CSRF_COOKIE, CSRF_HEADER, is_valid_csrf_token
from app.core.security import SESSION_COOKIE

SAFE_METHODS = {"GET", "HEAD", "OPTIONS"}
EXEMPT_PATHS = {"/api/auth/google", "/api/auth/logout"}


class CSRFMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request, call_next):
        settings = get_settings()
        if (
            not settings.csrf_enabled
            or request.method in SAFE_METHODS
            or request.url.path in EXEMPT_PATHS
            or not request.cookies.get(SESSION_COOKIE)
        ):
            return await call_next(request)

        cookie_token = request.cookies.get(CSRF_COOKIE, "")
        header_token = request.headers.get(CSRF_HEADER, "")
        if (
            not cookie_token
            or not header_token
            or not compare_digest(cookie_token, header_token)
            or not is_valid_csrf_token(cookie_token)
        ):
            return JSONResponse(
                status_code=403, content={"detail": "CSRF token missing or invalid"}
            )
        return await call_next(request)
