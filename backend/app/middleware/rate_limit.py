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
    bucket_ttl_seconds = 60
    cleanup_interval_seconds = 60
    max_buckets = 10_000
    last_cleanup_at = 0.0

    @classmethod
    def prune_buckets(cls, now: float) -> None:
        cutoff = now - cls.bucket_ttl_seconds
        for key, bucket in list(cls.buckets.items()):
            while bucket and bucket[0] <= cutoff:
                bucket.popleft()
            if not bucket:
                cls.buckets.pop(key, None)
        if len(cls.buckets) >= cls.max_buckets:
            overflow = len(cls.buckets) - cls.max_buckets + 1
            oldest = sorted(cls.buckets, key=lambda key: cls.buckets[key][-1])[:overflow]
            for key in oldest:
                cls.buckets.pop(key, None)
        cls.last_cleanup_at = now

    @staticmethod
    def policy(path: str, method: str) -> tuple[str, int, int] | None:
        if path == "/api/integrations/instagram/callback":
            return ("instagram-oauth-callback", 30, 60)
        if path.endswith("/integrations/instagram/oauth/start"):
            return ("instagram-oauth-start", 10, 60)
        if path.endswith("/integrations/whatsapp/embedded-signup/start"):
            return ("whatsapp-signup-start", 10, 60)
        if path.endswith("/integrations/whatsapp/embedded-signup/complete"):
            return ("whatsapp-signup-complete", 20, 60)
        if path.startswith("/api/auth/"):
            return ("auth", 30, 60)
        if method == "POST" and path.endswith(("/bookings", "/booking-requests")):
            return ("public-booking", 12, 60)
        if path == "/api/customer/claim-booking":
            return ("booking-manage", 30, 60)
        if method in {"POST", "PUT", "PATCH", "DELETE"} and (
            "/attachments" in path or "/media/" in path
        ):
            return ("upload", 30, 60)
        if "/attachments" in path:
            return ("booking-manage", 60, 60)
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
            if (
                now - self.last_cleanup_at >= self.cleanup_interval_seconds
                or len(self.buckets) >= self.max_buckets
            ):
                self.prune_buckets(now)
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
