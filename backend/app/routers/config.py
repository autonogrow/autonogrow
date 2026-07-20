from fastapi import APIRouter

from app.core.config import get_settings


router = APIRouter(prefix="/api/config", tags=["config"])


@router.get("/public")
def public_config():
    settings = get_settings()
    return {"google_client_id": settings.google_client_id, "app_env": settings.app_env}
