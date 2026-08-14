from fastapi import APIRouter

from app.core.config import get_settings

router = APIRouter(prefix="/api/config", tags=["config"])


@router.get("/public")
def public_config():
    settings = get_settings()
    return {"google_client_id": settings.google_client_id, "app_env": settings.app_env}


@router.get("/build")
def build_config():
    """Expose non-sensitive release correlation metadata for operations."""
    settings = get_settings()
    return {
        "app_env": settings.app_env,
        "app_version": settings.app_version,
        "release_id": settings.app_release_id,
        "git_commit": settings.app_git_commit,
        "build_time": settings.app_build_time,
    }
