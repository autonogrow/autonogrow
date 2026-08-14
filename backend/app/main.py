import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles

from app.core.config import get_settings, get_uploads_dir, migrate_legacy_uploads
from app.core.database import initialize_database
from app.core.observability import configure_logging
from app.middleware.audit import FailedAccessAuditMiddleware
from app.middleware.csrf import CSRFMiddleware
from app.middleware.maintenance import MaintenanceMiddleware
from app.middleware.rate_limit import RateLimitMiddleware
from app.middleware.request_context import RequestContextMiddleware
from app.middleware.security_headers import SecurityHeadersMiddleware
from app.routers.admin import router as admin_router
from app.routers.admin_availability import router as admin_availability_router
from app.routers.attachments import router as attachments_router
from app.routers.auth import router as auth_router
from app.routers.availability import router as availability_router
from app.routers.bookings import router as bookings_router
from app.routers.businesses import router as businesses_router
from app.routers.channel_onboarding import admin_router as channel_onboarding_router
from app.routers.channel_onboarding import owner_router as owner_channel_controls_router
from app.routers.config import router as config_router
from app.routers.conversations import (
    admin_router as conversations_router,
)
from app.routers.conversations import (
    webhook_router as test_webhook_router,
)
from app.routers.customer import router as customer_router
from app.routers.customer_memory import router as customer_memory_router
from app.routers.customers import router as customers_router
from app.routers.growth_actions import router as growth_actions_router
from app.routers.growth_opportunities import router as growth_opportunities_router
from app.routers.growth_signals import router as growth_signals_router
from app.routers.health import router as health_router
from app.routers.instagram_asset_delivery import router as instagram_asset_delivery_router
from app.routers.instagram_content import admin_router as instagram_content_admin_router
from app.routers.instagram_content import owner_router as instagram_content_owner_router
from app.routers.instagram_oauth import admin_router as instagram_oauth_admin_router
from app.routers.instagram_oauth import callback_router as instagram_oauth_callback_router
from app.routers.instagram_oauth import owner_router as instagram_oauth_owner_router
from app.routers.instagram_webhook import router as instagram_webhook_router
from app.routers.media import router as media_router
from app.routers.meta_integration_health import admin_router as meta_health_admin_router
from app.routers.meta_integration_health import owner_router as meta_health_owner_router
from app.routers.owner import router as owner_router
from app.routers.owner_onboarding import router as owner_onboarding_router
from app.routers.services import router as services_router
from app.routers.social_content import router as social_content_router
from app.routers.social_content_generation import router as social_content_generation_router
from app.routers.staff import (
    admin_router as admin_staff_router,
)
from app.routers.staff import (
    member_router as member_staff_router,
)
from app.routers.staff import (
    public_router as public_staff_router,
)
from app.routers.whatsapp_embedded_signup import (
    admin_router as whatsapp_embedded_signup_admin_router,
)
from app.routers.whatsapp_embedded_signup import (
    owner_router as whatsapp_embedded_signup_owner_router,
)
from app.routers.whatsapp_webhook import router as whatsapp_webhook_router


@asynccontextmanager
async def lifespan(app: FastAPI):
    migrate_legacy_uploads()
    initialize_database()
    yield


settings = get_settings()
configure_logging(settings)
logger = logging.getLogger(__name__)

app = FastAPI(
    title=settings.app_name,
    version=settings.app_version,
    lifespan=lifespan,
)


@app.exception_handler(Exception)
async def unexpected_exception_handler(request: Request, exc: Exception):
    request_id = getattr(request.state, "request_id", None)
    logger.exception(
        "unexpected request failure",
        exc_info=exc,
        extra={"event": "unexpected_exception", "request_id": request_id, "result": "error"},
    )
    return JSONResponse(
        status_code=500,
        content={"detail": "Internal server error", "request_id": request_id},
        headers={"X-Request-ID": request_id} if request_id else None,
    )


app.add_middleware(SecurityHeadersMiddleware)
app.add_middleware(RateLimitMiddleware)
app.add_middleware(CSRFMiddleware)
app.add_middleware(FailedAccessAuditMiddleware)
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.frontend_origin_list,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=[
        "Content-Type",
        "X-CSRF-Token",
        "X-Booking-Token",
        "Idempotency-Key",
        "X-Request-ID",
    ],
)
app.add_middleware(MaintenanceMiddleware)
app.add_middleware(RequestContextMiddleware)

uploads_dir = get_uploads_dir()
public_uploads_dir = uploads_dir / "businesses"
public_uploads_dir.mkdir(parents=True, exist_ok=True)

app.mount("/uploads/businesses", StaticFiles(directory=public_uploads_dir), name="public-uploads")

app.include_router(health_router)
app.include_router(config_router)
app.include_router(auth_router)
app.include_router(businesses_router)
app.include_router(services_router)
app.include_router(availability_router)
app.include_router(bookings_router)
app.include_router(attachments_router)
app.include_router(customers_router)
app.include_router(customer_memory_router)
app.include_router(admin_availability_router)
app.include_router(admin_router)
app.include_router(growth_opportunities_router)
app.include_router(growth_actions_router)
app.include_router(growth_signals_router)
app.include_router(social_content_router)
app.include_router(social_content_generation_router)
app.include_router(channel_onboarding_router)
app.include_router(owner_router)
app.include_router(owner_channel_controls_router)
app.include_router(meta_health_owner_router)
app.include_router(meta_health_admin_router)
app.include_router(owner_onboarding_router)
app.include_router(media_router)
app.include_router(customer_router)
app.include_router(public_staff_router)
app.include_router(admin_staff_router)
app.include_router(member_staff_router)
app.include_router(conversations_router)
app.include_router(test_webhook_router)
app.include_router(instagram_webhook_router)
app.include_router(instagram_oauth_callback_router)
app.include_router(instagram_oauth_admin_router)
app.include_router(instagram_oauth_owner_router)
app.include_router(instagram_content_admin_router)
app.include_router(instagram_content_owner_router)
app.include_router(instagram_asset_delivery_router)
app.include_router(whatsapp_webhook_router)
app.include_router(whatsapp_embedded_signup_admin_router)
app.include_router(whatsapp_embedded_signup_owner_router)
