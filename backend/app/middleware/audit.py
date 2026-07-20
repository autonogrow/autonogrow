from starlette.middleware.base import BaseHTTPMiddleware

from app.core.audit import record_audit
from app.core.database import SessionLocal


class FailedAccessAuditMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request, call_next):
        response = await call_next(request)
        if response.status_code != 403 or not request.url.path.startswith("/api/"):
            return response
        db = SessionLocal()
        try:
            record_audit(
                db,
                action="failed_access_403",
                request=request,
                actor=getattr(request.state, "current_user", None),
                metadata={"method": request.method, "scope": request.url.path.split("/")[2] if len(request.url.path.split("/")) > 2 else "api"},
            )
        except Exception:
            db.rollback()
        finally:
            db.close()
        return response
