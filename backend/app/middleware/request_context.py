from __future__ import annotations

import logging
import re
import time
import uuid

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request

from app.core.observability import request_id_context
from app.services.metrics_service import record_http_request

logger = logging.getLogger(__name__)
SAFE_REQUEST_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.:-]{0,63}\Z")


def safe_request_id(value: str | None) -> str:
    candidate = (value or "").strip()
    if candidate and SAFE_REQUEST_ID.fullmatch(candidate):
        return candidate
    return str(uuid.uuid4())


class RequestContextMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        request_id = safe_request_id(request.headers.get("x-request-id"))
        request.state.request_id = request_id
        token = request_id_context.set(request_id)
        started = time.perf_counter()
        status_code = 500
        try:
            response = await call_next(request)
            status_code = response.status_code
            response.headers["X-Request-ID"] = request_id
            return response
        finally:
            duration = time.perf_counter() - started
            route = request.scope.get("route")
            route_path = getattr(route, "path", "unmatched")
            record_http_request(request.method, route_path, status_code, duration)
            logger.info(
                "request completed",
                extra={
                    "event": "http_request_completed",
                    "operation": f"{request.method} {route_path}",
                    "duration_ms": round(duration * 1000, 2),
                    "result": status_code,
                },
            )
            request_id_context.reset(token)
