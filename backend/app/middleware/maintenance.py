from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse

from app.core.config import get_settings
from app.core.database import SessionLocal
from app.services.maintenance_service import maintenance_enabled

_SAFE_PREFIXES = ("/health", "/ready", "/api/owner", "/webhook", "/api/webhooks")


class MaintenanceMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        if request.method in {"GET", "HEAD", "OPTIONS"}:
            return await call_next(request)
        settings = get_settings()
        if request.url.path == settings.metrics_path or request.url.path.startswith(_SAFE_PREFIXES):
            return await call_next(request)
        try:
            with SessionLocal() as db:
                enabled = maintenance_enabled(db)
        except Exception:
            enabled = False
        if not enabled:
            return await call_next(request)
        return JSONResponse(
            status_code=503,
            content={
                "detail": settings.maintenance_public_message,
                "request_id": getattr(request.state, "request_id", None),
            },
            headers={"Retry-After": "300"},
        )
