from collections import defaultdict, deque
from threading import Lock
from time import monotonic

from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware

from app.core.config import get_settings


class RateLimitMiddleware(BaseHTTPMiddleware):
    """Small single-process limiter. A shared store is still needed for multi-worker deployments."""

    buckets: dict[tuple[str, str], deque[float]] = defaultdict(deque)
    lock = Lock()

    @staticmethod
    def policy(path: str, method: str) -> tuple[str, int, int] | None:
        if path.startswith("/api/auth/"):
            return ("auth", 30, 60)
        if method == "POST" and path.endswith(("/bookings", "/booking-requests")):
            return ("public-booking", 12, 60)
        if method in {"POST", "PUT", "PATCH", "DELETE"} and (
            "/attachments" in path or "/media/" in path
        ):
            return ("upload", 30, 60)
        if path.startswith(("/api/owner/", "/api/admin/", "/api/customer/")):
            return ("authenticated", 180, 60)
        return None

    async def dispatch(self, request, call_next):
        if not get_settings().rate_limit_enabled:
            return await call_next(request)
        policy = self.policy(request.url.path, request.method)
        if policy is None:
            return await call_next(request)
        bucket_name, limit, window = policy
        client_ip = request.client.host if request.client else "unknown"
        key = (client_ip, bucket_name)
        now = monotonic()
        with self.lock:
            bucket = self.buckets[key]
            while bucket and bucket[0] <= now - window:
                bucket.popleft()
            if len(bucket) >= limit:
                retry_after = max(1, int(window - (now - bucket[0])))
                return JSONResponse(
                    status_code=429,
                    headers={"Retry-After": str(retry_after)},
                    content={"detail": "Too many requests"},
                )
            bucket.append(now)
        return await call_next(request)
