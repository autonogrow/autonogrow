from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse, PlainTextResponse

from app.core.config import get_settings
from app.services.metrics_service import render_metrics, require_metrics_access
from app.services.operational_health_service import readiness_checks

router = APIRouter(tags=["health"])


@router.get("/health")
def health_check() -> dict:
    return {"status": "ok"}


@router.get("/ready")
def readiness_check():
    ready, _checks = readiness_checks()
    return JSONResponse(
        status_code=200 if ready else 503,
        content={"status": "ready" if ready else "not_ready"},
    )


async def metrics_check(request: Request):
    require_metrics_access(request)
    return PlainTextResponse(render_metrics(), media_type="text/plain; version=0.0.4")


router.add_api_route(
    get_settings().metrics_path,
    metrics_check,
    methods=["GET"],
    include_in_schema=False,
)
