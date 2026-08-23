import hashlib
import logging
import re
from datetime import datetime
from pathlib import Path
from typing import Annotated
from uuid import uuid4

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, Request, UploadFile
from fastapi.responses import FileResponse
from sqlalchemy import or_
from sqlalchemy.orm import Session, selectinload

from app.core.audit import record_audit
from app.core.config import get_settings, get_uploads_dir
from app.core.database import get_db
from app.core.security import get_business_membership, get_current_user, require_owner
from app.models import (
    Business,
    InstagramContent,
    InstagramContentRawAsset,
    InstagramContentVersion,
    InstagramContentVersionAsset,
    InstagramFinalAsset,
    InstagramPublishJob,
    InstagramRawAsset,
    User,
)
from app.schemas.instagram_content import (
    InstagramCommentCreate,
    InstagramContentCreate,
    InstagramEditorialReviewCreate,
    InstagramMaterialUpdate,
    InstagramPlannedDateUpdate,
    InstagramPublishJobHistory,
    InstagramPublishJobRead,
    InstagramRawContentTarget,
    InstagramServiceUpdate,
    InstagramTitleUpdate,
    InstagramValidationCreate,
    InstagramValidationDelegationUpdate,
)
from app.services.capability_service import require_module_available
from app.services.instagram_content_service import (
    add_admin_comment,
    associate_raw_asset,
    cancel_content,
    content_or_404,
    create_content,
    current_version,
    disassociate_permitted_raw_asset_associations,
    disassociate_raw_asset,
    get_or_create_settings,
    prepare_content_removal,
    prepare_raw_asset_as_final,
    prepare_raw_asset_removal,
    raw_asset_association_manager,
    raw_asset_or_404,
    require_service_enabled,
    schedule_content,
    serialize_comment,
    serialize_content,
    serialize_final_asset,
    serialize_raw_asset,
    serialize_settings,
    submit_for_review,
    update_material,
    validate_content,
)
from app.services.instagram_publish_service import (
    cancel_business_jobs,
    cancel_publish_job,
    normalize_planned_datetime,
    publication_history_events,
    publication_metrics,
    retry_publish_job,
    serialize_publish_job,
    sync_publish_job,
    utc_now,
)

owner_router = APIRouter(
    prefix="/api/owner/businesses/{business_id}/instagram-content",
    tags=["owner-instagram-content"],
    dependencies=[Depends(require_owner)],
)
admin_router = APIRouter(
    prefix="/api/admin/businesses/{business_slug}/instagram-content",
    tags=["admin-instagram-content"],
)

ALLOWED_MEDIA = {
    "image/jpeg": ".jpg",
    "image/png": ".png",
    "image/webp": ".webp",
    "video/mp4": ".mp4",
}
SETTINGS = get_settings()

MAX_IMAGE_ASSET_MB = SETTINGS.upload_max_size_mb
MAX_IMAGE_ASSET_BYTES = MAX_IMAGE_ASSET_MB * 1024 * 1024

# Backwards-compatible aliases used by existing tests and image upload behavior.
MAX_ASSET_MB = MAX_IMAGE_ASSET_MB
MAX_ASSET_BYTES = MAX_IMAGE_ASSET_BYTES

MAX_VIDEO_ASSET_MB = SETTINGS.instagram_video_upload_max_size_mb
MAX_VIDEO_ASSET_BYTES = MAX_VIDEO_ASSET_MB * 1024 * 1024

logger = logging.getLogger(__name__)


def _owner_business(db: Session, business_id: int) -> Business:
    business = db.get(Business, business_id)
    if business is None:
        raise HTTPException(status_code=404, detail="Business not found")
    require_module_available(db, business.id, "social")
    return business


def _admin_business(db: Session, business_slug: str) -> Business:
    business = db.query(Business).filter(Business.slug == business_slug).first()
    if business is None:
        raise HTTPException(status_code=404, detail="Business not found")
    require_module_available(db, business.id, "social")
    return business


def require_instagram_business_admin(
    business_slug: str,
    actor: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> User:
    _admin_business(db, business_slug)
    if actor.is_owner:
        raise HTTPException(status_code=403, detail="Business administrator access required")
    membership = get_business_membership(
        db,
        business_slug=business_slug,
        user_id=actor.id,
    )
    if membership is None or membership.role != "business_admin":
        raise HTTPException(status_code=403, detail="Business administrator access required")
    return actor


def _owner_prefix(business_id: int) -> str:
    return f"/api/owner/businesses/{business_id}/instagram-content"


def _admin_prefix(business_slug: str) -> str:
    return f"/api/admin/businesses/{business_slug}/instagram-content"


def _business_timezone(business: Business) -> str:
    return business.timezone.strip() or get_settings().instagram_default_timezone


def _audit(
    db: Session,
    *,
    request: Request,
    actor: User,
    business_id: int,
    action: str,
    resource_type: str,
    resource_id: int,
    metadata: dict | None = None,
) -> None:
    record_audit(
        db,
        action=action,
        request=request,
        actor=actor,
        business_id=business_id,
        resource_type=resource_type,
        resource_id=resource_id,
        metadata=metadata,
        commit=False,
    )


async def _read_media(file: UploadFile) -> tuple[bytes, str, str]:
    content_type = (file.content_type or "").lower()
    extension = ALLOWED_MEDIA.get(content_type)
    if extension is None:
        raise HTTPException(
            status_code=400,
            detail={
                "code": "unsupported_file_type",
                "message": "Este tipo de archivo no está permitido. Usa JPG, PNG, WEBP o MP4.",
            },
        )

    if content_type == "video/mp4":
        max_mb = MAX_VIDEO_ASSET_MB
        max_bytes = MAX_VIDEO_ASSET_BYTES
    else:
        max_mb = MAX_ASSET_MB
        max_bytes = MAX_ASSET_BYTES

    content = await file.read(max_bytes + 1)
    if not content:
        raise HTTPException(
            status_code=400,
            detail={"code": "empty_file", "message": "El archivo está vacío."},
        )
    if len(content) > max_bytes:
        raise HTTPException(
            status_code=413,
            detail={
                "code": "upload_too_large",
                "message": (f"El archivo supera el tamaño máximo permitido de {max_mb} MB."),
            },
        )
    _validate_media_content(content, content_type)
    return content, content_type, extension


def _validate_media_content(content: bytes, media_type: str) -> None:
    if media_type == "video/mp4":
        _validate_mp4_content(content)
        return
    _validate_image_content(content, media_type)


def _validate_image_content(content: bytes, media_type: str) -> None:
    signatures = {
        "image/jpeg": content.startswith(b"\xff\xd8\xff"),
        "image/png": content.startswith(b"\x89PNG\r\n\x1a\n"),
        "image/webp": len(content) >= 12
        and content.startswith(b"RIFF")
        and content[8:12] == b"WEBP",
    }
    if media_type not in signatures or not signatures[media_type]:
        raise HTTPException(
            status_code=400,
            detail={
                "code": "invalid_image_content",
                "message": "El contenido del archivo no corresponde a una imagen válida.",
            },
        )


def _validate_mp4_content(content: bytes) -> None:
    if len(content) < 12 or content[4:8] != b"ftyp":
        raise HTTPException(
            status_code=400,
            detail={
                "code": "invalid_video_content",
                "message": "El contenido del archivo no corresponde a un vídeo MP4 válido.",
            },
        )


def _safe_download_filename(value: str, asset_id: int, media_type: str) -> str:
    extension = ALLOWED_MEDIA.get(media_type, "")
    normalized = re.sub(r'[\x00-\x1f\x7f/\\"]', "_", Path(value).name).strip(" .")
    return normalized[:255] or f"material-{asset_id}{extension}"


def _write_private_asset(
    content: bytes, *, business_id: int, collection: str, extension: str
) -> str:
    relative = (
        Path("_instagram_content") / str(business_id) / collection / f"{uuid4().hex}{extension}"
    )
    path = get_uploads_dir() / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        path.write_bytes(content)
    except OSError:
        path.unlink(missing_ok=True)
        raise
    return relative.as_posix()


def _private_file(storage_key: str) -> Path:
    path = _private_storage_path(storage_key)
    if not path.is_file():
        raise HTTPException(status_code=404, detail="Asset file not found")
    return path


def _private_storage_path(storage_key: str) -> Path:
    root = (get_uploads_dir() / "_instagram_content").resolve()
    path = (get_uploads_dir() / storage_key).resolve()
    if root != path and root not in path.parents:
        raise HTTPException(status_code=404, detail="Asset not found")
    return path


def _restore_staged_files(staged: list[tuple[Path, Path]]) -> None:
    for original, temporary in reversed(staged):
        try:
            if temporary.exists():
                original.parent.mkdir(parents=True, exist_ok=True)
                temporary.replace(original)
        except OSError:
            logger.exception("Could not restore a staged Instagram asset")


def _stage_private_files(storage_keys: list[str]) -> list[tuple[Path, Path]]:
    staged: list[tuple[Path, Path]] = []
    staging_dir = (get_uploads_dir() / "_instagram_content" / "_delete_staging").resolve()
    try:
        for storage_key in storage_keys:
            original = _private_storage_path(storage_key)
            if not original.exists():
                continue
            staging_dir.mkdir(parents=True, exist_ok=True)
            temporary = staging_dir / f"{uuid4().hex}{original.suffix}"
            original.replace(temporary)
            staged.append((original, temporary))
    except OSError as error:
        _restore_staged_files(staged)
        raise HTTPException(
            status_code=500,
            detail="No se pudo retirar el archivo de forma segura. Inténtalo de nuevo.",
        ) from error
    return staged


def _commit_with_staged_files(
    db: Session,
    storage_keys: list[str],
) -> None:
    try:
        staged = _stage_private_files(storage_keys)
    except HTTPException:
        db.rollback()
        raise
    try:
        db.commit()
    except Exception:
        db.rollback()
        _restore_staged_files(staged)
        raise
    for _original, temporary in staged:
        try:
            temporary.unlink(missing_ok=True)
        except OSError:
            logger.exception("Could not purge a staged Instagram asset")


def _list_raw(
    db: Session,
    business_id: int,
    api_prefix: str,
    *,
    limit: int,
    offset: int,
) -> dict:
    require_service_enabled(db, business_id)
    assets = (
        db.query(InstagramRawAsset)
        .options(
            selectinload(InstagramRawAsset.content_links).selectinload(
                InstagramContentRawAsset.content
            )
        )
        .filter(InstagramRawAsset.business_id == business_id)
        .order_by(InstagramRawAsset.created_at.desc(), InstagramRawAsset.id.desc())
        .offset(offset)
        .limit(limit)
        .all()
    )
    return {"assets": [serialize_raw_asset(asset, api_prefix) for asset in assets]}


async def _upload_raw(
    db: Session,
    *,
    business_id: int,
    actor: User,
    file: UploadFile,
    label: str | None,
) -> InstagramRawAsset:
    require_service_enabled(db, business_id)
    content, media_type, extension = await _read_media(file)
    storage_key = _write_private_asset(
        content,
        business_id=business_id,
        collection="raw",
        extension=extension,
    )
    asset = InstagramRawAsset(
        business_id=business_id,
        uploaded_by_user_id=actor.id,
        original_filename=Path(file.filename or f"asset{extension}").name[:255],
        storage_key=storage_key,
        media_type=media_type,
        size_bytes=len(content),
        label=label.strip()[:240] if label and label.strip() else None,
    )
    db.add(asset)
    db.flush()
    return asset


def _raw_or_404(db: Session, business_id: int, asset_id: int) -> InstagramRawAsset:
    require_service_enabled(db, business_id)
    asset = (
        db.query(InstagramRawAsset)
        .filter(
            InstagramRawAsset.id == asset_id,
            InstagramRawAsset.business_id == business_id,
        )
        .first()
    )
    if asset is None:
        raise HTTPException(status_code=404, detail="Raw asset not found")
    return asset


def _list_content(
    db: Session,
    business_id: int,
    api_prefix: str,
    *,
    detailed: bool = False,
    owner_technical: bool = True,
    from_datetime: datetime | None = None,
    to_datetime: datetime | None = None,
    include_unscheduled: bool = True,
    limit: int = 200,
    offset: int = 0,
) -> dict:
    require_service_enabled(db, business_id)
    query = (
        db.query(InstagramContent)
        .options(
            selectinload(InstagramContent.source_asset_links).selectinload(
                InstagramContentRawAsset.raw_asset
            ),
            selectinload(InstagramContent.business),
            selectinload(InstagramContent.publish_jobs),
            selectinload(InstagramContent.versions).selectinload(
                InstagramContentVersion.validation
            ),
            selectinload(InstagramContent.versions)
            .selectinload(InstagramContentVersion.asset_links)
            .selectinload(InstagramContentVersionAsset.asset),
        )
        .filter(
            InstagramContent.business_id == business_id,
            InstagramContent.archived_at.is_(None),
        )
    )
    range_filters = []
    if from_datetime is not None:
        range_filters.append(InstagramContent.planned_publish_at >= from_datetime)
    if to_datetime is not None:
        range_filters.append(InstagramContent.planned_publish_at < to_datetime)
    if range_filters:
        planned_in_range = range_filters[0]
        for condition in range_filters[1:]:
            planned_in_range = planned_in_range & condition
        query = query.filter(
            or_(InstagramContent.planned_publish_at.is_(None), planned_in_range)
            if include_unscheduled
            else planned_in_range
        )
    items = query.order_by(
        InstagramContent.planned_publish_at.asc(), InstagramContent.updated_at.desc()
    ).offset(offset).limit(limit).all()
    contents = []
    for item in items:
        setattr(
            item,
            "_prefetched_current_version",
            max(item.versions, key=lambda version: version.version_number, default=None),
        )
        payload = serialize_content(
            db,
            item,
            api_prefix,
            detailed=detailed,
            owner_technical=owner_technical,
        )
        delattr(item, "_prefetched_current_version")
        if not detailed:
            latest_job = max(item.publish_jobs, key=lambda job: job.created_at, default=None)
            payload["publish_jobs"] = (
                [serialize_publish_job(latest_job, owner_technical=owner_technical)]
                if latest_job
                else []
            )
        contents.append(payload)
    return {"contents": contents}


def _validate_content_range(from_datetime: datetime | None, to_datetime: datetime | None) -> None:
    if from_datetime is None or to_datetime is None:
        return
    if (from_datetime.tzinfo is None) != (to_datetime.tzinfo is None):
        raise HTTPException(status_code=422, detail="Content range offsets must match")
    if to_datetime <= from_datetime or (to_datetime - from_datetime).days > 62:
        raise HTTPException(
            status_code=422,
            detail="Content range must span between 1 and 62 days",
        )


def _raw_content_payload(
    db: Session,
    *,
    business_id: int,
    asset_id: int,
    content_id: int,
) -> dict:
    db.expire_all()
    api_prefix = _owner_prefix(business_id)
    asset = raw_asset_or_404(db, business_id, asset_id)
    content = content_or_404(db, business_id, content_id)
    return {
        "raw_asset": serialize_raw_asset(asset, api_prefix),
        "content": serialize_content(db, content, api_prefix, detailed=True),
    }


@owner_router.get("/settings")
def owner_get_settings(business_id: int, db: Session = Depends(get_db)):
    _owner_business(db, business_id)
    settings = get_or_create_settings(db, business_id)
    db.commit()
    return serialize_settings(settings)


@owner_router.patch("/settings")
def owner_update_settings(
    business_id: int,
    payload: InstagramServiceUpdate,
    request: Request,
    actor: User = Depends(require_owner),
    db: Session = Depends(get_db),
):
    _owner_business(db, business_id)
    settings = get_or_create_settings(db, business_id)
    old_enabled = settings.enabled
    settings.enabled = payload.enabled
    settings.enabled_by_user_id = actor.id
    cancelled_jobs = 0
    if old_enabled and not settings.enabled:
        cancelled_jobs = cancel_business_jobs(
            db, business_id, "instagram_content_service_disabled", actor
        )
        if cancelled_jobs:
            _audit(
                db,
                request=request,
                actor=actor,
                business_id=business_id,
                action="service_disabled_with_pending_jobs",
                resource_type="instagram_content_settings",
                resource_id=business_id,
                metadata={"cancelled_or_blocked_jobs": cancelled_jobs},
            )
    _audit(
        db,
        request=request,
        actor=actor,
        business_id=business_id,
        action="instagram_content_service_updated",
        resource_type="instagram_content_settings",
        resource_id=business_id,
        metadata={"old_enabled": old_enabled, "new_enabled": settings.enabled},
    )
    db.commit()
    db.refresh(settings)
    return serialize_settings(settings)


@admin_router.get("/settings")
def admin_get_settings(
    business_slug: str,
    actor: User = Depends(require_instagram_business_admin),
    db: Session = Depends(get_db),
):
    del actor
    business = _admin_business(db, business_slug)
    settings = get_or_create_settings(db, business.id)
    db.commit()
    return serialize_settings(settings)


@admin_router.get("/publication-metrics")
def admin_get_publication_metrics(
    business_slug: str,
    actor: User = Depends(require_instagram_business_admin),
    db: Session = Depends(get_db),
):
    del actor
    business = _admin_business(db, business_slug)
    require_service_enabled(db, business.id)
    return publication_metrics(db, business.id)


@admin_router.patch("/settings/validation-delegation")
def admin_update_validation_delegation(
    business_slug: str,
    payload: InstagramValidationDelegationUpdate,
    request: Request,
    actor: User = Depends(require_owner),
    db: Session = Depends(get_db),
):
    business = _admin_business(db, business_slug)
    settings = get_or_create_settings(db, business.id)
    old_value = settings.owner_can_validate_instagram_content
    settings.owner_can_validate_instagram_content = payload.owner_can_validate_instagram_content
    settings.validation_delegated_by_user_id = actor.id
    _audit(
        db,
        request=request,
        actor=actor,
        business_id=business.id,
        action="instagram_owner_validation_delegation_updated",
        resource_type="instagram_content_settings",
        resource_id=business.id,
        metadata={
            "old_value": old_value,
            "new_value": settings.owner_can_validate_instagram_content,
        },
    )
    db.commit()
    db.refresh(settings)
    return serialize_settings(settings)


@owner_router.get("/raw-assets")
def owner_list_raw_assets(
    business_id: int,
    limit: Annotated[int, Query(ge=1, le=200)] = 100,
    offset: Annotated[int, Query(ge=0)] = 0,
    db: Session = Depends(get_db),
):
    _owner_business(db, business_id)
    return _list_raw(
        db, business_id, _owner_prefix(business_id), limit=limit, offset=offset
    )


@admin_router.get("/raw-assets")
def admin_list_raw_assets(
    business_slug: str,
    limit: Annotated[int, Query(ge=1, le=200)] = 100,
    offset: Annotated[int, Query(ge=0)] = 0,
    actor: User = Depends(require_instagram_business_admin),
    db: Session = Depends(get_db),
):
    del actor
    business = _admin_business(db, business_slug)
    return _list_raw(
        db, business.id, _admin_prefix(business_slug), limit=limit, offset=offset
    )


@owner_router.post("/raw-assets", status_code=201)
async def owner_upload_raw_asset(
    business_id: int,
    request: Request,
    file: UploadFile = File(...),
    label: str | None = Form(default=None),
    actor: User = Depends(require_owner),
    db: Session = Depends(get_db),
):
    _owner_business(db, business_id)
    asset = await _upload_raw(db, business_id=business_id, actor=actor, file=file, label=label)
    _audit(
        db,
        request=request,
        actor=actor,
        business_id=business_id,
        action="instagram_raw_asset_uploaded",
        resource_type="instagram_raw_asset",
        resource_id=asset.id,
    )
    db.commit()
    db.refresh(asset)
    return serialize_raw_asset(asset, _owner_prefix(business_id))


@admin_router.post("/raw-assets", status_code=201)
async def admin_upload_raw_asset(
    business_slug: str,
    request: Request,
    file: UploadFile = File(...),
    label: str | None = Form(default=None),
    actor: User = Depends(require_instagram_business_admin),
    db: Session = Depends(get_db),
):
    business = _admin_business(db, business_slug)
    asset = await _upload_raw(db, business_id=business.id, actor=actor, file=file, label=label)
    _audit(
        db,
        request=request,
        actor=actor,
        business_id=business.id,
        action="instagram_raw_asset_uploaded",
        resource_type="instagram_raw_asset",
        resource_id=asset.id,
    )
    db.commit()
    db.refresh(asset)
    return serialize_raw_asset(asset, _admin_prefix(business_slug))


@owner_router.delete("/raw-assets/{asset_id}")
def owner_delete_raw_asset(
    business_id: int,
    asset_id: int,
    request: Request,
    actor: User = Depends(require_owner),
    db: Session = Depends(get_db),
):
    _owner_business(db, business_id)
    result = prepare_raw_asset_removal(db, business_id=business_id, asset_id=asset_id)
    _audit(
        db,
        request=request,
        actor=actor,
        business_id=business_id,
        action="raw_asset_deleted",
        resource_type="instagram_raw_asset",
        resource_id=asset_id,
    )
    _commit_with_staged_files(db, result["storage_keys"])
    return {"id": asset_id, "disposition": "deleted"}


@owner_router.get("/raw-assets/{asset_id}/associations")
def owner_get_raw_asset_associations(
    business_id: int,
    asset_id: int,
    db: Session = Depends(get_db),
):
    _owner_business(db, business_id)
    return raw_asset_association_manager(db, business_id=business_id, asset_id=asset_id)


@admin_router.delete("/raw-assets/{asset_id}")
def admin_delete_raw_asset_forbidden(
    business_slug: str,
    asset_id: int,
    actor: User = Depends(require_instagram_business_admin),
):
    del business_slug, asset_id, actor
    raise HTTPException(status_code=403, detail="Owner access required")


@owner_router.get("/raw-assets/{asset_id}/file", response_class=FileResponse)
def owner_get_raw_file(business_id: int, asset_id: int, db: Session = Depends(get_db)):
    _owner_business(db, business_id)
    asset = _raw_or_404(db, business_id, asset_id)
    return FileResponse(_private_file(asset.storage_key), media_type=asset.media_type)


@owner_router.get("/raw-assets/{asset_id}/download", response_class=FileResponse)
def owner_download_raw_file(
    business_id: int,
    asset_id: int,
    db: Session = Depends(get_db),
):
    _owner_business(db, business_id)
    asset = _raw_or_404(db, business_id, asset_id)
    return FileResponse(
        _private_file(asset.storage_key),
        media_type=asset.media_type,
        filename=_safe_download_filename(
            asset.original_filename,
            asset.id,
            asset.media_type,
        ),
        content_disposition_type="attachment",
    )


@owner_router.post("/raw-assets/{asset_id}/associations")
def owner_associate_raw_asset(
    business_id: int,
    asset_id: int,
    payload: InstagramRawContentTarget,
    request: Request,
    actor: User = Depends(require_owner),
    db: Session = Depends(get_db),
):
    _owner_business(db, business_id)
    content, _asset, link, created = associate_raw_asset(
        db,
        business_id=business_id,
        content_id=payload.content_id,
        asset_id=asset_id,
        actor=actor,
    )
    if created:
        _audit(
            db,
            request=request,
            actor=actor,
            business_id=business_id,
            action="raw_asset_associated",
            resource_type="instagram_content_raw_asset",
            resource_id=link.id,
            metadata={"content_id": content.id, "raw_asset_id": asset_id},
        )
    db.commit()
    return _raw_content_payload(
        db,
        business_id=business_id,
        asset_id=asset_id,
        content_id=content.id,
    )


@owner_router.delete("/raw-assets/{asset_id}/associations/{content_id}")
def owner_disassociate_raw_asset(
    business_id: int,
    asset_id: int,
    content_id: int,
    request: Request,
    actor: User = Depends(require_owner),
    db: Session = Depends(get_db),
):
    _owner_business(db, business_id)
    content, _asset = disassociate_raw_asset(
        db,
        business_id=business_id,
        content_id=content_id,
        asset_id=asset_id,
    )
    _audit(
        db,
        request=request,
        actor=actor,
        business_id=business_id,
        action="raw_asset_disassociated",
        resource_type="instagram_raw_asset",
        resource_id=asset_id,
        metadata={"content_id": content.id},
    )
    db.commit()
    return _raw_content_payload(
        db,
        business_id=business_id,
        asset_id=asset_id,
        content_id=content.id,
    )


@owner_router.delete("/raw-assets/{asset_id}/associations")
def owner_disassociate_permitted_raw_asset_associations(
    business_id: int,
    asset_id: int,
    request: Request,
    actor: User = Depends(require_owner),
    db: Session = Depends(get_db),
):
    _owner_business(db, business_id)
    content_ids = disassociate_permitted_raw_asset_associations(
        db,
        business_id=business_id,
        asset_id=asset_id,
    )
    if content_ids:
        _audit(
            db,
            request=request,
            actor=actor,
            business_id=business_id,
            action="raw_asset_associations_disassociated",
            resource_type="instagram_raw_asset",
            resource_id=asset_id,
            metadata={"content_ids": content_ids},
        )
    db.commit()
    db.expire_all()
    api_prefix = _owner_prefix(business_id)
    asset = raw_asset_or_404(db, business_id, asset_id)
    contents = [content_or_404(db, business_id, content_id) for content_id in content_ids]
    return {
        "association_manager": raw_asset_association_manager(
            db,
            business_id=business_id,
            asset_id=asset_id,
        ),
        "raw_asset": serialize_raw_asset(asset, api_prefix),
        "contents": [
            serialize_content(db, content, api_prefix, detailed=True) for content in contents
        ],
    }


@owner_router.post("/raw-assets/{asset_id}/create-content", status_code=201)
def owner_create_content_from_raw_asset(
    business_id: int,
    asset_id: int,
    request: Request,
    actor: User = Depends(require_owner),
    db: Session = Depends(get_db),
):
    _owner_business(db, business_id)
    asset = raw_asset_or_404(db, business_id, asset_id, for_update=True)
    source_name = (asset.label or Path(asset.original_filename).stem).strip()
    title = f"Contenido desde {source_name or 'material bruto'}"[:200]
    content = create_content(
        db,
        business_id=business_id,
        actor=actor,
        title=title,
        caption="",
        format="reel" if asset.media_type == "video/mp4" else "single_image",
        planned_publish_at=None,
    )
    _content, _asset, link, _created = associate_raw_asset(
        db,
        business_id=business_id,
        content_id=content.id,
        asset_id=asset_id,
        actor=actor,
    )
    _audit(
        db,
        request=request,
        actor=actor,
        business_id=business_id,
        action="instagram_content_created",
        resource_type="instagram_content",
        resource_id=content.id,
        metadata={"version_number": 1, "source_raw_asset_id": asset_id},
    )
    _audit(
        db,
        request=request,
        actor=actor,
        business_id=business_id,
        action="raw_asset_associated",
        resource_type="instagram_content_raw_asset",
        resource_id=link.id,
        metadata={"content_id": content.id, "raw_asset_id": asset_id},
    )
    db.commit()
    return _raw_content_payload(
        db,
        business_id=business_id,
        asset_id=asset_id,
        content_id=content.id,
    )


@owner_router.post("/raw-assets/{asset_id}/use-as-final", status_code=201)
def owner_use_raw_asset_as_final(
    business_id: int,
    asset_id: int,
    payload: InstagramRawContentTarget,
    request: Request,
    actor: User = Depends(require_owner),
    db: Session = Depends(get_db),
):
    _owner_business(db, business_id)
    content, raw_asset, existing, associated = prepare_raw_asset_as_final(
        db,
        business_id=business_id,
        content_id=payload.content_id,
        asset_id=asset_id,
        actor=actor,
    )
    storage_key: str | None = None
    try:
        if existing is None:
            extension = ALLOWED_MEDIA.get(raw_asset.media_type)
            if extension is None:
                raise HTTPException(
                    status_code=400,
                    detail="El tipo de material no es válido como asset final.",
                )
            raw_content = _private_file(raw_asset.storage_key).read_bytes()
            max_bytes = (
                MAX_VIDEO_ASSET_BYTES
                if raw_asset.media_type == "video/mp4"
                else MAX_ASSET_BYTES
            )
            if not raw_content or len(raw_content) > max_bytes:
                raise HTTPException(
                    status_code=400,
                    detail="El material no cumple el tamaño permitido para un asset final.",
                )
            _validate_media_content(raw_content, raw_asset.media_type)
            storage_key = _write_private_asset(
                raw_content,
                business_id=business_id,
                collection=f"final/{content.id}",
                extension=extension,
            )
            final_asset = InstagramFinalAsset(
                business_id=business_id,
                content_id=content.id,
                uploaded_by_user_id=actor.id,
                source_raw_asset_id=raw_asset.id,
                original_filename=raw_asset.original_filename,
                storage_key=storage_key,
                media_type=raw_asset.media_type,
                size_bytes=len(raw_content),
                sha256=hashlib.sha256(raw_content).hexdigest(),
            )
            db.add(final_asset)
            db.flush()
            _audit(
                db,
                request=request,
                actor=actor,
                business_id=business_id,
                action="raw_asset_used_as_final",
                resource_type="instagram_final_asset",
                resource_id=final_asset.id,
                metadata={
                    "content_id": content.id,
                    "source_raw_asset_id": raw_asset.id,
                },
            )
        if associated:
            link = (
                db.query(InstagramContentRawAsset)
                .filter_by(content_id=content.id, raw_asset_id=raw_asset.id)
                .one()
            )
            _audit(
                db,
                request=request,
                actor=actor,
                business_id=business_id,
                action="raw_asset_associated",
                resource_type="instagram_content_raw_asset",
                resource_id=link.id,
                metadata={"content_id": content.id, "raw_asset_id": raw_asset.id},
            )
        db.commit()
    except Exception:
        db.rollback()
        if storage_key is not None:
            try:
                _private_storage_path(storage_key).unlink(missing_ok=True)
            except OSError:
                logger.exception("Could not remove a failed final asset copy")
        raise
    return _raw_content_payload(
        db,
        business_id=business_id,
        asset_id=asset_id,
        content_id=content.id,
    )


@admin_router.get("/raw-assets/{asset_id}/file", response_class=FileResponse)
def admin_get_raw_file(
    business_slug: str,
    asset_id: int,
    actor: User = Depends(require_instagram_business_admin),
    db: Session = Depends(get_db),
):
    del actor
    business = _admin_business(db, business_slug)
    asset = _raw_or_404(db, business.id, asset_id)
    return FileResponse(_private_file(asset.storage_key), media_type=asset.media_type)


@admin_router.post("/raw-assets/{asset_id}/associations")
@admin_router.post("/raw-assets/{asset_id}/create-content")
@admin_router.post("/raw-assets/{asset_id}/use-as-final")
def admin_raw_asset_owner_operation_forbidden(
    business_slug: str,
    asset_id: int,
    actor: User = Depends(require_instagram_business_admin),
):
    del business_slug, asset_id, actor
    raise HTTPException(status_code=403, detail="Owner access required")


@admin_router.delete("/raw-assets/{asset_id}/associations/{content_id}")
@admin_router.delete("/raw-assets/{asset_id}/associations")
@admin_router.get("/raw-assets/{asset_id}/associations")
def admin_disassociate_raw_asset_forbidden(
    business_slug: str,
    asset_id: int,
    content_id: int | None = None,
    actor: User = Depends(require_instagram_business_admin),
):
    del business_slug, asset_id, content_id, actor
    raise HTTPException(status_code=403, detail="Owner access required")


@owner_router.get("/contents")
def owner_list_contents(
    business_id: int,
    from_datetime: datetime | None = Query(default=None, alias="from"),
    to_datetime: datetime | None = Query(default=None, alias="to"),
    include_unscheduled: bool = True,
    limit: Annotated[int, Query(ge=1, le=500)] = 200,
    offset: Annotated[int, Query(ge=0)] = 0,
    db: Session = Depends(get_db),
):
    _owner_business(db, business_id)
    _validate_content_range(from_datetime, to_datetime)
    return _list_content(
        db,
        business_id,
        _owner_prefix(business_id),
        detailed=False,
        from_datetime=from_datetime,
        to_datetime=to_datetime,
        include_unscheduled=include_unscheduled,
        limit=limit,
        offset=offset,
    )


@admin_router.get("/contents")
def admin_list_contents(
    business_slug: str,
    from_datetime: datetime | None = Query(default=None, alias="from"),
    to_datetime: datetime | None = Query(default=None, alias="to"),
    include_unscheduled: bool = True,
    limit: Annotated[int, Query(ge=1, le=500)] = 200,
    offset: Annotated[int, Query(ge=0)] = 0,
    actor: User = Depends(require_instagram_business_admin),
    db: Session = Depends(get_db),
):
    del actor
    business = _admin_business(db, business_slug)
    _validate_content_range(from_datetime, to_datetime)
    return _list_content(
        db,
        business.id,
        _admin_prefix(business_slug),
        detailed=False,
        owner_technical=False,
        from_datetime=from_datetime,
        to_datetime=to_datetime,
        include_unscheduled=include_unscheduled,
        limit=limit,
        offset=offset,
    )


@owner_router.post("/contents", status_code=201)
def owner_create_content(
    business_id: int,
    payload: InstagramContentCreate,
    request: Request,
    actor: User = Depends(require_owner),
    db: Session = Depends(get_db),
):
    business = _owner_business(db, business_id)
    planned = normalize_planned_datetime(payload.planned_publish_at, _business_timezone(business))
    content = create_content(
        db,
        business_id=business_id,
        actor=actor,
        title=payload.title,
        caption=payload.caption,
        format=payload.format,
        planned_publish_at=planned,
    )
    _audit(
        db,
        request=request,
        actor=actor,
        business_id=business_id,
        action="instagram_content_created",
        resource_type="instagram_content",
        resource_id=content.id,
        metadata={"version_number": 1},
    )
    db.commit()
    db.refresh(content)
    return serialize_content(db, content, _owner_prefix(business_id), detailed=True)


def _content_detail(
    db: Session,
    business_id: int,
    content_id: int,
    api_prefix: str,
    *,
    owner_technical: bool = True,
) -> dict:
    require_service_enabled(db, business_id)
    return serialize_content(
        db,
        content_or_404(db, business_id, content_id),
        api_prefix,
        detailed=True,
        owner_technical=owner_technical,
    )


@owner_router.get("/contents/{content_id}")
def owner_get_content(business_id: int, content_id: int, db: Session = Depends(get_db)):
    _owner_business(db, business_id)
    return _content_detail(db, business_id, content_id, _owner_prefix(business_id))


@admin_router.get("/contents/{content_id}")
def admin_get_content(
    business_slug: str,
    content_id: int,
    actor: User = Depends(require_instagram_business_admin),
    db: Session = Depends(get_db),
):
    del actor
    business = _admin_business(db, business_slug)
    return _content_detail(
        db,
        business.id,
        content_id,
        _admin_prefix(business_slug),
        owner_technical=False,
    )


@owner_router.delete("/contents/{content_id}")
def owner_remove_content(
    business_id: int,
    content_id: int,
    request: Request,
    actor: User = Depends(require_owner),
    db: Session = Depends(get_db),
):
    _owner_business(db, business_id)
    result = prepare_content_removal(
        db,
        business_id=business_id,
        content_id=content_id,
        actor=actor,
    )
    cancelled_job_id = result["cancelled_job_id"]
    if cancelled_job_id is not None:
        _audit(
            db,
            request=request,
            actor=actor,
            business_id=business_id,
            action="publish_job_cancelled_by_delete",
            resource_type="instagram_publish_job",
            resource_id=cancelled_job_id,
            metadata={"content_id": content_id},
        )
    previous_status = result["previous_status"]
    if previous_status == "scheduled":
        action = "scheduled_content_removed"
    elif previous_status == "published":
        action = "content_archived"
    elif result["disposition"] == "archived":
        action = "content_removed"
    else:
        action = "content_deleted"
    _audit(
        db,
        request=request,
        actor=actor,
        business_id=business_id,
        action=action,
        resource_type="instagram_content",
        resource_id=content_id,
        metadata={
            "previous_status": previous_status,
            "disposition": result["disposition"],
            "review_cancelled": previous_status == "ready_for_review",
        },
    )
    _commit_with_staged_files(db, result["storage_keys"])
    return {
        "id": content_id,
        "disposition": result["disposition"],
        "previous_status": previous_status,
    }


@admin_router.delete("/contents/{content_id}")
def admin_remove_content_forbidden(
    business_slug: str,
    content_id: int,
    actor: User = Depends(require_instagram_business_admin),
):
    del business_slug, content_id, actor
    raise HTTPException(status_code=403, detail="Owner access required")


@owner_router.post("/contents/{content_id}/final-assets", status_code=201)
async def owner_upload_final_asset(
    business_id: int,
    content_id: int,
    request: Request,
    file: UploadFile = File(...),
    actor: User = Depends(require_owner),
    db: Session = Depends(get_db),
):
    _owner_business(db, business_id)
    require_service_enabled(db, business_id)
    content_or_404(db, business_id, content_id)
    file_content, media_type, extension = await _read_media(file)
    storage_key = _write_private_asset(
        file_content,
        business_id=business_id,
        collection=f"final/{content_id}",
        extension=extension,
    )
    asset = InstagramFinalAsset(
        business_id=business_id,
        content_id=content_id,
        uploaded_by_user_id=actor.id,
        original_filename=Path(file.filename or f"asset{extension}").name[:255],
        storage_key=storage_key,
        media_type=media_type,
        size_bytes=len(file_content),
        sha256=hashlib.sha256(file_content).hexdigest(),
    )
    db.add(asset)
    db.flush()
    _audit(
        db,
        request=request,
        actor=actor,
        business_id=business_id,
        action="instagram_final_asset_uploaded",
        resource_type="instagram_final_asset",
        resource_id=asset.id,
        metadata={"content_id": content_id},
    )
    db.commit()
    db.refresh(asset)
    return serialize_final_asset(asset, _owner_prefix(business_id))


def _final_asset_or_404(
    db: Session, business_id: int, content_id: int, asset_id: int
) -> InstagramFinalAsset:
    require_service_enabled(db, business_id)
    asset = (
        db.query(InstagramFinalAsset)
        .filter(
            InstagramFinalAsset.id == asset_id,
            InstagramFinalAsset.content_id == content_id,
            InstagramFinalAsset.business_id == business_id,
        )
        .first()
    )
    if asset is None:
        raise HTTPException(status_code=404, detail="Final asset not found")
    return asset


@owner_router.get(
    "/contents/{content_id}/final-assets/{asset_id}/file", response_class=FileResponse
)
def owner_get_final_file(
    business_id: int, content_id: int, asset_id: int, db: Session = Depends(get_db)
):
    _owner_business(db, business_id)
    asset = _final_asset_or_404(db, business_id, content_id, asset_id)
    return FileResponse(_private_file(asset.storage_key), media_type=asset.media_type)


@admin_router.post("/contents/{content_id}/final-assets", status_code=201)
async def admin_upload_final_asset_forbidden(
    business_slug: str,
    content_id: int,
    file: UploadFile = File(...),
    actor: User = Depends(require_owner),
):
    del business_slug, content_id, file, actor
    raise HTTPException(status_code=403, detail="Final assets must use an Owner operation")


@admin_router.get(
    "/contents/{content_id}/final-assets/{asset_id}/file", response_class=FileResponse
)
def admin_get_final_file(
    business_slug: str,
    content_id: int,
    asset_id: int,
    actor: User = Depends(require_instagram_business_admin),
    db: Session = Depends(get_db),
):
    del actor
    business = _admin_business(db, business_slug)
    asset = _final_asset_or_404(db, business.id, content_id, asset_id)
    return FileResponse(_private_file(asset.storage_key), media_type=asset.media_type)


@owner_router.put("/contents/{content_id}/material")
def owner_update_material(
    business_id: int,
    content_id: int,
    payload: InstagramMaterialUpdate,
    request: Request,
    actor: User = Depends(require_owner),
    db: Session = Depends(get_db),
):
    _owner_business(db, business_id)
    content, version, changed = update_material(
        db,
        business_id=business_id,
        content_id=content_id,
        actor=actor,
        caption=payload.caption,
        format=payload.format,
        asset_ids=payload.asset_ids,
        cover_asset_id=payload.cover_asset_id,
    )
    if changed:
        _audit(
            db,
            request=request,
            actor=actor,
            business_id=business_id,
            action="instagram_content_version_created",
            resource_type="instagram_content_version",
            resource_id=version.id,
            metadata={"content_id": content.id, "version_number": version.version_number},
        )
    db.commit()
    db.refresh(content)
    return serialize_content(db, content, _owner_prefix(business_id), detailed=True)


@owner_router.patch("/contents/{content_id}/planned-date")
@owner_router.patch("/contents/{content_id}/publish-job/reschedule")
def owner_update_planned_date(
    business_id: int,
    content_id: int,
    payload: InstagramPlannedDateUpdate,
    request: Request,
    actor: User = Depends(require_owner),
    db: Session = Depends(get_db),
):
    business = _owner_business(db, business_id)
    require_service_enabled(db, business_id)
    content = content_or_404(db, business_id, content_id)
    if content.status in {"cancelled", "published"}:
        raise HTTPException(status_code=409, detail="Terminal content cannot be edited")
    planned = normalize_planned_datetime(payload.planned_publish_at, _business_timezone(business))
    old_value = content.planned_publish_at
    content.planned_publish_at = planned
    if content.status == "scheduled":
        if planned is None:
            cancel_publish_job(db, content, reason="planned_date_removed", actor=actor)
            content.status = "validated"
        else:
            job = sync_publish_job(db, content, actor=actor)
            if job.status != "queued":
                raise HTTPException(
                    status_code=409,
                    detail=job.safe_error_message or "Publishing preflight failed",
                )
    _audit(
        db,
        request=request,
        actor=actor,
        business_id=business_id,
        action="instagram_content_planned_date_updated",
        resource_type="instagram_content",
        resource_id=content.id,
        metadata={
            "old_value": old_value.isoformat() if old_value else None,
            "new_value": planned.isoformat() if planned else None,
        },
    )
    db.commit()
    db.refresh(content)
    return serialize_content(db, content, _owner_prefix(business_id), detailed=True)


@admin_router.patch("/contents/{content_id}/planned-date")
@admin_router.patch("/contents/{content_id}/publish-job/reschedule")
def admin_update_planned_date(
    business_slug: str,
    content_id: int,
    payload: InstagramPlannedDateUpdate,
    request: Request,
    actor: User = Depends(require_owner),
    db: Session = Depends(get_db),
):
    business = _admin_business(db, business_slug)
    require_service_enabled(db, business.id)
    content = content_or_404(db, business.id, content_id, for_update=True)
    if content.status in {"cancelled", "published"}:
        raise HTTPException(status_code=409, detail="Terminal content cannot be edited")
    planned = normalize_planned_datetime(
        payload.planned_publish_at,
        _business_timezone(business),
    )
    old_value = content.planned_publish_at
    content.planned_publish_at = planned
    if content.status == "scheduled":
        if planned is None:
            cancel_publish_job(db, content, reason="planned_date_removed", actor=actor)
            content.status = "validated"
        else:
            job = sync_publish_job(db, content, actor=actor)
            if job.status != "queued":
                raise HTTPException(
                    status_code=409,
                    detail=job.safe_error_message or "Publishing preflight failed",
                )
    _audit(
        db,
        request=request,
        actor=actor,
        business_id=business.id,
        action="instagram_content_planned_date_updated",
        resource_type="instagram_content",
        resource_id=content.id,
        metadata={
            "old_value": old_value.isoformat() if old_value else None,
            "new_value": planned.isoformat() if planned else None,
        },
    )
    db.commit()
    db.refresh(content)
    return serialize_content(
        db,
        content,
        _admin_prefix(business_slug),
        detailed=True,
        owner_technical=False,
    )


@owner_router.patch("/contents/{content_id}/title")
def owner_update_title(
    business_id: int,
    content_id: int,
    payload: InstagramTitleUpdate,
    request: Request,
    actor: User = Depends(require_owner),
    db: Session = Depends(get_db),
):
    _owner_business(db, business_id)
    require_service_enabled(db, business_id)
    content = content_or_404(db, business_id, content_id)
    if content.status == "cancelled":
        raise HTTPException(status_code=409, detail="Cancelled content cannot be edited")
    content.title = payload.title
    _audit(
        db,
        request=request,
        actor=actor,
        business_id=business_id,
        action="instagram_content_title_updated",
        resource_type="instagram_content",
        resource_id=content.id,
    )
    db.commit()
    return serialize_content(db, content, _owner_prefix(business_id), detailed=True)


def _owner_transition_and_commit(
    db: Session,
    *,
    business_id: int,
    content_id: int,
    action: str,
    request: Request,
    actor: User,
) -> dict:
    if action == "submit-for-review":
        content = submit_for_review(db, business_id, content_id)
    elif action == "schedule":
        content = schedule_content(db, business_id, content_id, actor)
    elif action == "cancel":
        content = cancel_content(db, business_id, content_id, actor)
    else:
        raise HTTPException(status_code=404, detail="Unknown editorial transition")
    _audit(
        db,
        request=request,
        actor=actor,
        business_id=business_id,
        action=f"instagram_content_{action.replace('-', '_')}",
        resource_type="instagram_content",
        resource_id=content.id,
        metadata={"new_status": content.status},
    )
    db.commit()
    db.refresh(content)
    return serialize_content(db, content, _owner_prefix(business_id), detailed=True)


@owner_router.post("/contents/{content_id}/submit-for-review")
def owner_submit_content(
    business_id: int,
    content_id: int,
    request: Request,
    actor: User = Depends(require_owner),
    db: Session = Depends(get_db),
):
    _owner_business(db, business_id)
    return _owner_transition_and_commit(
        db,
        business_id=business_id,
        content_id=content_id,
        action="submit-for-review",
        request=request,
        actor=actor,
    )


@owner_router.post("/contents/{content_id}/schedule")
def owner_schedule_content(
    business_id: int,
    content_id: int,
    request: Request,
    actor: User = Depends(require_owner),
    db: Session = Depends(get_db),
):
    _owner_business(db, business_id)
    return _owner_transition_and_commit(
        db,
        business_id=business_id,
        content_id=content_id,
        action="schedule",
        request=request,
        actor=actor,
    )


@owner_router.post("/contents/{content_id}/cancel")
def owner_cancel_content(
    business_id: int,
    content_id: int,
    request: Request,
    actor: User = Depends(require_owner),
    db: Session = Depends(get_db),
):
    _owner_business(db, business_id)
    return _owner_transition_and_commit(
        db,
        business_id=business_id,
        content_id=content_id,
        action="cancel",
        request=request,
        actor=actor,
    )


def _publish_job_history(
    db: Session,
    business_id: int,
    content_id: int,
    *,
    owner_technical: bool = True,
    limit: int,
) -> dict:
    content_or_404(db, business_id, content_id)
    jobs = (
        db.query(InstagramPublishJob)
        .filter(
            InstagramPublishJob.business_id == business_id,
            InstagramPublishJob.content_item_id == content_id,
        )
        .order_by(InstagramPublishJob.created_at.desc(), InstagramPublishJob.id.desc())
        .limit(limit)
        .all()
    )
    return {
        "jobs": [serialize_publish_job(job, owner_technical=owner_technical) for job in jobs],
        "events": publication_history_events(
            db,
            business_id,
            content_id,
            owner_technical=owner_technical,
            limit=limit,
        ),
    }


@owner_router.get("/contents/{content_id}/publish-jobs", response_model=InstagramPublishJobHistory)
def owner_publish_job_history(
    business_id: int,
    content_id: int,
    limit: Annotated[int, Query(ge=1, le=200)] = 100,
    db: Session = Depends(get_db),
):
    _owner_business(db, business_id)
    return _publish_job_history(db, business_id, content_id, limit=limit)


@admin_router.get("/contents/{content_id}/publish-jobs", response_model=InstagramPublishJobHistory)
def admin_publish_job_history(
    business_slug: str,
    content_id: int,
    limit: Annotated[int, Query(ge=1, le=200)] = 100,
    actor: User = Depends(require_instagram_business_admin),
    db: Session = Depends(get_db),
):
    del actor
    business = _admin_business(db, business_slug)
    return _publish_job_history(
        db, business.id, content_id, owner_technical=False, limit=limit
    )


@owner_router.post("/contents/{content_id}/publish-now", response_model=InstagramPublishJobRead)
def owner_publish_now(
    business_id: int,
    content_id: int,
    request: Request,
    actor: User = Depends(require_owner),
    db: Session = Depends(get_db),
):
    _owner_business(db, business_id)
    require_service_enabled(db, business_id)
    content = content_or_404(db, business_id, content_id, for_update=True)
    job = sync_publish_job(db, content, actor=actor, now=utc_now(), force_now=True)
    if job.status != "queued":
        raise HTTPException(
            status_code=409,
            detail=job.safe_error_message or "Publishing preflight failed",
        )
    _audit(
        db,
        request=request,
        actor=actor,
        business_id=business_id,
        action="publish_now_requested",
        resource_type="instagram_publish_job",
        resource_id=job.id,
        metadata={"content_id": content_id, "version_id": job.content_version_id},
    )
    db.commit()
    return serialize_publish_job(job)


@owner_router.post(
    "/contents/{content_id}/publish-job/cancel", response_model=InstagramPublishJobRead
)
def owner_cancel_publish_job(
    business_id: int,
    content_id: int,
    actor: User = Depends(require_owner),
    db: Session = Depends(get_db),
):
    _owner_business(db, business_id)
    require_service_enabled(db, business_id)
    content = content_or_404(db, business_id, content_id, for_update=True)
    job = cancel_publish_job(db, content, reason="cancelled_by_owner", actor=actor)
    if job is None:
        raise HTTPException(status_code=409, detail="No active publish job is available")
    if content.status == "scheduled":
        content.status = "validated"
    db.commit()
    return serialize_publish_job(job)


@owner_router.post(
    "/contents/{content_id}/publish-job/retry", response_model=InstagramPublishJobRead
)
def owner_retry_publish_job(
    business_id: int,
    content_id: int,
    actor: User = Depends(require_owner),
    db: Session = Depends(get_db),
):
    _owner_business(db, business_id)
    require_service_enabled(db, business_id)
    content = content_or_404(db, business_id, content_id, for_update=True)
    job = retry_publish_job(db, content, actor)
    db.commit()
    return serialize_publish_job(job)


@admin_router.post("/contents/{content_id}/schedule")
def admin_schedule_content(
    business_slug: str,
    content_id: int,
    request: Request,
    actor: User = Depends(require_owner),
    db: Session = Depends(get_db),
):
    business = _admin_business(db, business_slug)
    content = schedule_content(db, business.id, content_id, actor)
    _audit(
        db,
        request=request,
        actor=actor,
        business_id=business.id,
        action="instagram_content_schedule",
        resource_type="instagram_content",
        resource_id=content.id,
        metadata={"new_status": content.status},
    )
    db.commit()
    db.refresh(content)
    return serialize_content(
        db,
        content,
        _admin_prefix(business_slug),
        detailed=True,
        owner_technical=False,
    )


@admin_router.post("/contents/{content_id}/publish-now", response_model=InstagramPublishJobRead)
def admin_publish_now(
    business_slug: str,
    content_id: int,
    request: Request,
    actor: User = Depends(require_owner),
    db: Session = Depends(get_db),
):
    business = _admin_business(db, business_slug)
    require_service_enabled(db, business.id)
    content = content_or_404(db, business.id, content_id, for_update=True)
    job = sync_publish_job(db, content, actor=actor, now=utc_now(), force_now=True)
    if job.status != "queued":
        raise HTTPException(
            status_code=409,
            detail=job.safe_error_message or "Publishing preflight failed",
        )
    _audit(
        db,
        request=request,
        actor=actor,
        business_id=business.id,
        action="publish_now_requested",
        resource_type="instagram_publish_job",
        resource_id=job.id,
        metadata={"content_id": content_id, "version_id": job.content_version_id},
    )
    db.commit()
    return serialize_publish_job(job, owner_technical=False)


@admin_router.post(
    "/contents/{content_id}/publish-job/cancel",
    response_model=InstagramPublishJobRead,
)
def admin_cancel_publish_job(
    business_slug: str,
    content_id: int,
    actor: User = Depends(require_owner),
    db: Session = Depends(get_db),
):
    business = _admin_business(db, business_slug)
    require_service_enabled(db, business.id)
    content = content_or_404(db, business.id, content_id, for_update=True)
    job = cancel_publish_job(db, content, reason="cancelled_by_business_admin", actor=actor)
    if job is None:
        raise HTTPException(status_code=409, detail="No active publish job is available")
    if content.status == "scheduled":
        content.status = "validated"
    db.commit()
    return serialize_publish_job(job, owner_technical=False)


@admin_router.post(
    "/contents/{content_id}/publish-job/retry",
    response_model=InstagramPublishJobRead,
)
def admin_retry_publish_job(
    business_slug: str,
    content_id: int,
    actor: User = Depends(require_owner),
    db: Session = Depends(get_db),
):
    business = _admin_business(db, business_slug)
    require_service_enabled(db, business.id)
    content = content_or_404(db, business.id, content_id, for_update=True)
    job = retry_publish_job(db, content, actor)
    db.commit()
    return serialize_publish_job(job, owner_technical=False)


@admin_router.post("/contents/{content_id}/comments", status_code=201)
def admin_create_comment(
    business_slug: str,
    content_id: int,
    payload: InstagramCommentCreate,
    request: Request,
    actor: User = Depends(require_instagram_business_admin),
    db: Session = Depends(get_db),
):
    business = _admin_business(db, business_slug)
    comment = add_admin_comment(
        db,
        business_id=business.id,
        content_id=content_id,
        version_id=payload.version_id,
        actor=actor,
        kind=payload.kind,
        body=payload.body,
    )
    _audit(
        db,
        request=request,
        actor=actor,
        business_id=business.id,
        action="instagram_content_changes_requested"
        if payload.kind == "change_request"
        else "instagram_content_commented",
        resource_type="instagram_content_comment",
        resource_id=comment.id,
        metadata={
            "content_id": content_id,
            "version_id": payload.version_id,
            "kind": payload.kind,
        },
    )
    db.commit()
    db.refresh(comment)
    return serialize_comment(comment)


@admin_router.post("/contents/{content_id}/editorial-review", status_code=201)
def admin_review_content(
    business_slug: str,
    content_id: int,
    payload: InstagramEditorialReviewCreate,
    request: Request,
    actor: User = Depends(require_instagram_business_admin),
    db: Session = Depends(get_db),
):
    business = _admin_business(db, business_slug)
    content = content_or_404(db, business.id, content_id, for_update=True)
    version = current_version(db, content)
    if version.id != payload.version_id:
        raise HTTPException(status_code=409, detail="Review must target the current version")
    if content.status != "ready_for_review":
        raise HTTPException(status_code=409, detail="Content is not ready for editorial review")
    if payload.decision == "reject" and payload.note is None:
        raise HTTPException(status_code=422, detail="A rejection note is required")

    approved = payload.decision == "approve"
    comment = add_admin_comment(
        db,
        business_id=business.id,
        content_id=content_id,
        version_id=version.id,
        actor=actor,
        kind="comment" if approved else "change_request",
        body=(
            f"Aprobación editorial: {payload.note}"
            if payload.note
            else "Aprobación editorial registrada."
        )
        if approved
        else payload.note or "",
    )
    _audit(
        db,
        request=request,
        actor=actor,
        business_id=business.id,
        action=(
            "instagram_content_editorially_approved"
            if approved
            else "instagram_content_editorially_rejected"
        ),
        resource_type="instagram_content_comment",
        resource_id=comment.id,
        metadata={
            "content_id": content_id,
            "version_id": version.id,
            "decision": payload.decision,
        },
    )
    db.commit()
    db.refresh(comment)
    return {
        "decision": payload.decision,
        "content_status": content.status,
        "comment": serialize_comment(comment),
    }


def _validate_and_commit(
    db: Session,
    *,
    business_id: int,
    content_id: int,
    version_id: int,
    actor: User,
    role: str,
    request: Request,
    api_prefix: str,
) -> dict:
    validation = validate_content(
        db,
        business_id=business_id,
        content_id=content_id,
        version_id=version_id,
        actor=actor,
        validator_role=role,
    )
    _audit(
        db,
        request=request,
        actor=actor,
        business_id=business_id,
        action="instagram_content_validated",
        resource_type="instagram_content_validation",
        resource_id=validation.id,
        metadata={
            "content_id": content_id,
            "version_id": version_id,
            "validator_role": role,
            "approved_asset_ids": [
                link.asset_id
                for link in sorted(
                    validation.version.asset_links,
                    key=lambda item: item.position,
                )
            ],
        },
    )
    db.commit()
    content = content_or_404(db, business_id, content_id)
    return serialize_content(
        db,
        content,
        api_prefix,
        detailed=True,
        owner_technical=role == "owner_delegate",
    )


@admin_router.post("/contents/{content_id}/validate")
def admin_validate_content(
    business_slug: str,
    content_id: int,
    payload: InstagramValidationCreate,
    request: Request,
    actor: User = Depends(require_owner),
    db: Session = Depends(get_db),
):
    business = _admin_business(db, business_slug)
    return _validate_and_commit(
        db,
        business_id=business.id,
        content_id=content_id,
        version_id=payload.version_id,
        actor=actor,
        role="business_admin",
        request=request,
        api_prefix=_admin_prefix(business_slug),
    )


@owner_router.post("/contents/{content_id}/validate")
def owner_validate_content(
    business_id: int,
    content_id: int,
    payload: InstagramValidationCreate,
    request: Request,
    actor: User = Depends(require_owner),
    db: Session = Depends(get_db),
):
    _owner_business(db, business_id)
    return _validate_and_commit(
        db,
        business_id=business_id,
        content_id=content_id,
        version_id=payload.version_id,
        actor=actor,
        role="owner_delegate",
        request=request,
        api_prefix=_owner_prefix(business_id),
    )
