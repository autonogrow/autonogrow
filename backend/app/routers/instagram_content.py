import hashlib
import logging
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Annotated
from uuid import uuid4

import requests
from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, Request, UploadFile
from fastapi.responses import FileResponse, Response
from sqlalchemy import and_, or_
from sqlalchemy.orm import Session, selectinload

from app.core.audit import record_audit
from app.core.config import get_settings, get_uploads_dir
from app.core.database import get_db
from app.core.security import (
    get_business_membership,
    get_current_user,
    require_business_operational_status,
    require_business_operational_status_by_id,
    require_owner,
    require_tenant_business_admin,
)
from app.models import (
    Business,
    InstagramContent,
    InstagramContentEditorialReview,
    InstagramContentPublicationHold,
    InstagramContentRawAsset,
    InstagramContentVersion,
    InstagramContentVersionAsset,
    InstagramFinalAsset,
    InstagramMediaSyncState,
    InstagramPublishJob,
    InstagramRawAsset,
    InstagramRemoteMedia,
    User,
)
from app.schemas.instagram_content import (
    InstagramCommentCreate,
    InstagramContentCreate,
    InstagramEditorialReviewCreate,
    InstagramMaterialUpdate,
    InstagramPlannedDateUpdate,
    InstagramPublicationHoldCreate,
    InstagramPublicationHoldRelease,
    InstagramPublishJobHistory,
    InstagramPublishJobRead,
    InstagramRawContentTarget,
    InstagramServiceUpdate,
    InstagramTitleUpdate,
    InstagramValidationCreate,
    InstagramValidationDelegationUpdate,
)
from app.services.capability_service import require_module_available
from app.services.instagram_calendar_service import (
    calendar_datetime,
    calendar_semantics,
    latest_publish_job,
    load_calendar_contexts,
    operational_week_summary,
)
from app.services.instagram_content_service import (
    active_publication_hold,
    add_admin_comment,
    associate_raw_asset,
    cancel_content,
    content_dependency_or_404,
    content_or_404,
    create_content,
    current_version,
    disassociate_permitted_raw_asset_associations,
    disassociate_raw_asset,
    ensure_owner_operational_validation,
    get_or_create_settings,
    prepare_content_removal,
    prepare_raw_asset_as_final,
    prepare_raw_asset_removal,
    prepare_raw_asset_retirement,
    prepare_raw_asset_storage_purge,
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
from app.services.instagram_integration_service import get_instagram_integration
from app.services.instagram_media_sync_service import (
    enqueue_instagram_media_sync,
    mark_media_unavailable,
    serialize_remote_media,
    serialize_sync_state,
)
from app.services.instagram_meta_client import MetaHTTPError
from app.services.instagram_publish_service import (
    ACTIVE_JOB_STATUSES,
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
from app.services.instagram_remote_asset_service import (
    RemoteAssetError,
    download_remote_image,
    materialize_remote_image,
    refresh_remote_media_item,
    remote_media_for_business,
)
from app.services.instagram_story_renderer import StoryRenderError, StoryTransform
from app.services.instagram_story_service import (
    create_uploaded_story_raw,
    render_story_version,
)

owner_router = APIRouter(
    prefix="/api/owner/businesses/{business_id}/instagram-content",
    tags=["owner-instagram-content"],
    dependencies=[Depends(require_owner), Depends(require_business_operational_status_by_id)],
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
    _operational_status: None = Depends(require_business_operational_status),
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
    include_instagram: bool = False,
) -> dict:
    require_service_enabled(db, business_id)
    query = (
        db.query(InstagramRawAsset)
        .options(
            selectinload(InstagramRawAsset.uploaded_by),
            selectinload(InstagramRawAsset.content_links).selectinload(
                InstagramContentRawAsset.content
            ),
        )
        .filter(
            InstagramRawAsset.business_id == business_id,
            InstagramRawAsset.active.is_(True),
        )
    )
    if not include_instagram:
        query = query.filter(InstagramRawAsset.source_kind == "business_upload")
    assets = (
        query.order_by(InstagramRawAsset.created_at.desc(), InstagramRawAsset.id.desc())
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
        sha256=hashlib.sha256(content).hexdigest(),
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
            InstagramRawAsset.source_kind == "business_upload",
        )
        .first()
    )
    if asset is None:
        raise HTTPException(status_code=404, detail="Raw asset not found")
    return asset


def _ensure_raw_storage_available(asset: InstagramRawAsset) -> None:
    if asset.storage_deleted_at is not None:
        raise HTTPException(
            status_code=410,
            detail="El material original fue retirado y su archivo ya no está disponible.",
        )


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
            or_(
                InstagramContent.status == "published",
                and_(
                    InstagramContent.status != "published",
                    or_(InstagramContent.planned_publish_at.is_(None), planned_in_range),
                ),
            )
        )
    candidates = query.all()
    contexts = load_calendar_contexts(db, candidates)
    for item in candidates:
        setattr(item, "_calendar_context", contexts.get(item.id))

    def in_requested_range(item: InstagramContent) -> bool:
        if not range_filters:
            return True
        value, _source = calendar_datetime(item, contexts.get(item.id))
        if value is None:
            bucket = calendar_semantics(item, contexts.get(item.id))["calendar_bucket"]
            job = latest_publish_job(item)
            return (include_unscheduled and bucket == "unscheduled") or (
                job is not None and job.status in ACTIVE_JOB_STATUSES
            )
        normalized_from = (
            from_datetime.replace(tzinfo=timezone.utc)
            if from_datetime is not None and from_datetime.tzinfo is None
            else from_datetime
        )
        normalized_to = (
            to_datetime.replace(tzinfo=timezone.utc)
            if to_datetime is not None and to_datetime.tzinfo is None
            else to_datetime
        )
        return (normalized_from is None or value >= normalized_from) and (
            normalized_to is None or value < normalized_to
        )

    items = [item for item in candidates if in_requested_range(item)]
    items.sort(
        key=lambda item: (
            calendar_datetime(item, contexts.get(item.id))[0] is None,
            calendar_datetime(item, contexts.get(item.id))[0]
            or datetime.max.replace(tzinfo=timezone.utc),
            -item.id,
        )
    )
    items = items[offset : offset + limit]
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
        delattr(item, "_calendar_context")
        if not detailed:
            latest_job = latest_publish_job(item)
            payload["publish_jobs"] = (
                [serialize_publish_job(latest_job, owner_technical=owner_technical)]
                if latest_job
                else []
            )
        contents.append(payload)

    for candidate in candidates:
        if hasattr(candidate, "_calendar_context"):
            delattr(candidate, "_calendar_context")

    attention_query = (
        db.query(InstagramContent)
        .options(
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
    all_operational = attention_query.all()
    all_contexts = load_calendar_contexts(db, all_operational)
    attention_rows: list[tuple[InstagramContent, dict]] = []
    for item in all_operational:
        semantics = calendar_semantics(item, all_contexts.get(item.id))
        if semantics["attention_required"]:
            attention_rows.append((item, semantics))
    attention_rows.sort(
        key=lambda row: (
            row[1]["attention_datetime"] is None,
            row[1]["attention_datetime"] or "",
            row[0].created_at,
        )
    )
    attention_items = []
    for item, _semantics in attention_rows:
        setattr(
            item,
            "_prefetched_current_version",
            max(item.versions, key=lambda version: version.version_number, default=None),
        )
        setattr(item, "_calendar_context", all_contexts.get(item.id))
        payload = serialize_content(
            db,
            item,
            api_prefix,
            detailed=False,
            owner_technical=owner_technical,
        )
        latest_job = latest_publish_job(item)
        payload["publish_jobs"] = (
            [serialize_publish_job(latest_job, owner_technical=owner_technical)]
            if latest_job
            else []
        )
        attention_items.append(payload)
        delattr(item, "_prefetched_current_version")
        delattr(item, "_calendar_context")

    timezone_name = (
        all_operational[0].business.timezone.strip()
        if all_operational and all_operational[0].business.timezone.strip()
        else get_settings().instagram_default_timezone
    )
    return {
        "contents": contents,
        "attention": {"count": len(attention_items), "items": attention_items},
        "summary": operational_week_summary(
            all_operational, now=utc_now(), timezone_name=timezone_name
        ),
    }


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
    content = content_dependency_or_404(db, business_id, content_id)
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


@admin_router.patch(
    "/settings/validation-delegation",
    dependencies=[Depends(require_business_operational_status)],
)
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
        db,
        business_id,
        _owner_prefix(business_id),
        limit=limit,
        offset=offset,
        include_instagram=True,
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
    return _list_raw(db, business.id, _admin_prefix(business_slug), limit=limit, offset=offset)


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


@owner_router.post("/raw-assets/{asset_id}/retire")
def owner_retire_raw_asset(
    business_id: int,
    asset_id: int,
    request: Request,
    actor: User = Depends(require_owner),
    db: Session = Depends(get_db),
):
    _owner_business(db, business_id)
    result = prepare_raw_asset_retirement(
        db,
        business_id=business_id,
        asset_id=asset_id,
        actor_user_id=actor.id,
    )
    if result["retired"]:
        _audit(
            db,
            request=request,
            actor=actor,
            business_id=business_id,
            action="raw_asset_retired",
            resource_type="instagram_raw_asset",
            resource_id=asset_id,
            metadata={
                "raw_asset_id": asset_id,
                "storage_retained": not result["purged"],
            },
        )
    if result["purged"]:
        _audit(
            db,
            request=request,
            actor=actor,
            business_id=business_id,
            action="raw_asset_storage_purged",
            resource_type="instagram_raw_asset",
            resource_id=asset_id,
            metadata={"raw_asset_id": asset_id},
        )
    _commit_with_staged_files(db, result["storage_keys"])
    return {
        "id": asset_id,
        "disposition": "retired",
        "storage_purged": result["purged"],
        "storage_retained_for_current_content": result["has_current_physical_dependency"],
    }


@owner_router.post("/raw-assets/{asset_id}/purge-storage")
def owner_purge_retired_raw_asset_storage(
    business_id: int,
    asset_id: int,
    request: Request,
    actor: User = Depends(require_owner),
    db: Session = Depends(get_db),
):
    _owner_business(db, business_id)
    result = prepare_raw_asset_storage_purge(
        db,
        business_id=business_id,
        asset_id=asset_id,
    )
    if result["purged"]:
        _audit(
            db,
            request=request,
            actor=actor,
            business_id=business_id,
            action="raw_asset_storage_purged",
            resource_type="instagram_raw_asset",
            resource_id=asset_id,
            metadata={"raw_asset_id": asset_id},
        )
    _commit_with_staged_files(db, result["storage_keys"])
    return {
        "id": asset_id,
        "disposition": "storage_purged" if result["purged"] else "already_purged",
    }


@owner_router.get("/raw-assets/{asset_id}/associations")
def owner_get_raw_asset_associations(
    business_id: int,
    asset_id: int,
    db: Session = Depends(get_db),
):
    _owner_business(db, business_id)
    return raw_asset_association_manager(db, business_id=business_id, asset_id=asset_id)


@admin_router.delete("/raw-assets/{asset_id}")
@admin_router.post("/raw-assets/{asset_id}/retire")
@admin_router.post("/raw-assets/{asset_id}/purge-storage")
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
    _ensure_raw_storage_available(asset)
    return FileResponse(_private_file(asset.storage_key), media_type=asset.media_type)


@owner_router.get("/raw-assets/{asset_id}/download", response_class=FileResponse)
def owner_download_raw_file(
    business_id: int,
    asset_id: int,
    db: Session = Depends(get_db),
):
    _owner_business(db, business_id)
    asset = _raw_or_404(db, business_id, asset_id)
    _ensure_raw_storage_available(asset)
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
        metadata={"content_id": content.id, "raw_asset_id": asset_id},
    )
    storage_keys: list[str] = []
    if not _asset.active and _asset.storage_deleted_at is None:
        purge = prepare_raw_asset_storage_purge(db, business_id=business_id, asset_id=asset_id)
        storage_keys = purge["storage_keys"]
        if purge["purged"]:
            _audit(
                db,
                request=request,
                actor=actor,
                business_id=business_id,
                action="raw_asset_storage_purged",
                resource_type="instagram_raw_asset",
                resource_id=asset_id,
                metadata={"raw_asset_id": asset_id},
            )
    _commit_with_staged_files(db, storage_keys)
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
    for content_id in content_ids:
        _audit(
            db,
            request=request,
            actor=actor,
            business_id=business_id,
            action="raw_asset_disassociated",
            resource_type="instagram_raw_asset",
            resource_id=asset_id,
            metadata={"content_id": content_id, "raw_asset_id": asset_id},
        )
    storage_keys: list[str] = []
    asset_before_commit = raw_asset_or_404(db, business_id, asset_id)
    if not asset_before_commit.active and asset_before_commit.storage_deleted_at is None:
        purge = prepare_raw_asset_storage_purge(db, business_id=business_id, asset_id=asset_id)
        storage_keys = purge["storage_keys"]
        if purge["purged"]:
            _audit(
                db,
                request=request,
                actor=actor,
                business_id=business_id,
                action="raw_asset_storage_purged",
                resource_type="instagram_raw_asset",
                resource_id=asset_id,
                metadata={"raw_asset_id": asset_id},
            )
    _commit_with_staged_files(db, storage_keys)
    db.expire_all()
    api_prefix = _owner_prefix(business_id)
    asset = raw_asset_or_404(db, business_id, asset_id)
    contents = [
        content_dependency_or_404(db, business_id, content_id) for content_id in content_ids
    ]
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
    asset = raw_asset_or_404(db, business_id, asset_id, for_update=True, active_only=True)
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
                MAX_VIDEO_ASSET_BYTES if raw_asset.media_type == "video/mp4" else MAX_ASSET_BYTES
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
                derivation_fingerprint="copy",
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
    _ensure_raw_storage_available(asset)
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


@owner_router.get("/publication-history")
def owner_publication_history(
    business_id: int,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
    db: Session = Depends(get_db),
):
    _owner_business(db, business_id)
    require_service_enabled(db, business_id)
    published = (
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
            InstagramContent.status == "published",
        )
        .all()
    )
    contexts = load_calendar_contexts(db, published)

    def history_sort_key(item: InstagramContent) -> tuple[bool, float]:
        value, _source = calendar_datetime(item, contexts.get(item.id))
        return value is None, -(value.timestamp() if value else 0)

    published.sort(key=history_sort_key)
    page = published[offset : offset + limit]
    items = []
    for item in page:
        setattr(
            item,
            "_prefetched_current_version",
            max(item.versions, key=lambda version: version.version_number, default=None),
        )
        setattr(item, "_calendar_context", contexts.get(item.id))
        payload = serialize_content(
            db, item, _owner_prefix(business_id), detailed=False, owner_technical=True
        )
        latest_job = max(item.publish_jobs, key=lambda job: job.created_at, default=None)
        payload["publish_jobs"] = (
            [serialize_publish_job(latest_job, owner_technical=True)] if latest_job else []
        )
        payload["history_read_only"] = True
        items.append(payload)
        delattr(item, "_prefetched_current_version")
        delattr(item, "_calendar_context")
    return {"items": items, "total": len(published), "limit": limit, "offset": offset}


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
    if result["historically_published"]:
        action = "content_archived"
    elif previous_status == "scheduled":
        action = "scheduled_content_removed"
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
    actor: User = Depends(require_tenant_business_admin),
    db: Session = Depends(get_db),
):
    business = _admin_business(db, business_slug)
    require_service_enabled(db, business.id)
    content = content_or_404(db, business.id, content_id, for_update=True)
    if content.status in {"cancelled", "published"}:
        raise HTTPException(status_code=409, detail="Terminal content cannot be edited")
    if content.status not in {"validated", "scheduled"}:
        raise HTTPException(
            status_code=409,
            detail="Planning is available after Business Owner final approval",
        )
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
        action=(
            "content_scheduled_by_owner"
            if action == "schedule"
            else f"instagram_content_{action.replace('-', '_')}"
        ),
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
    return _publish_job_history(db, business.id, content_id, owner_technical=False, limit=limit)


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
    ensure_owner_operational_validation(db, content, actor)
    job = sync_publish_job(db, content, actor=actor, now=utc_now(), force_now=True)
    if job.status not in ACTIVE_JOB_STATUSES:
        raise HTTPException(
            status_code=409,
            detail=job.safe_error_message or "Publishing preflight failed",
        )
    _audit(
        db,
        request=request,
        actor=actor,
        business_id=business_id,
        action=(
            "content_publish_now_by_owner"
            if job.status == "queued"
            else "publish_now_already_active"
        ),
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
    actor: User = Depends(require_tenant_business_admin),
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
    actor: User = Depends(require_tenant_business_admin),
    db: Session = Depends(get_db),
):
    business = _admin_business(db, business_slug)
    require_service_enabled(db, business.id)
    content = content_or_404(db, business.id, content_id, for_update=True)
    job = sync_publish_job(db, content, actor=actor, now=utc_now(), force_now=True)
    if job.status not in ACTIVE_JOB_STATUSES:
        raise HTTPException(
            status_code=409,
            detail=job.safe_error_message or "Publishing preflight failed",
        )
    _audit(
        db,
        request=request,
        actor=actor,
        business_id=business.id,
        action=(
            "publish_now_requested" if job.status == "queued" else "publish_now_already_active"
        ),
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
    actor: User = Depends(require_tenant_business_admin),
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
    actor: User = Depends(require_tenant_business_admin),
    db: Session = Depends(get_db),
):
    business = _admin_business(db, business_slug)
    require_service_enabled(db, business.id)
    content = content_or_404(db, business.id, content_id, for_update=True)
    job = retry_publish_job(db, content, actor)
    db.commit()
    return serialize_publish_job(job, owner_technical=False)


@admin_router.post("/contents/{content_id}/publication-hold", status_code=201)
def admin_hold_publication(
    business_slug: str,
    content_id: int,
    payload: InstagramPublicationHoldCreate,
    request: Request,
    actor: User = Depends(require_tenant_business_admin),
    db: Session = Depends(get_db),
):
    business = _admin_business(db, business_slug)
    content = content_or_404(db, business.id, content_id, for_update=True)
    if content.status in {"cancelled", "published"}:
        raise HTTPException(status_code=409, detail="Terminal content cannot be stopped")
    existing = active_publication_hold(db, content, lock=True)
    if existing is not None:
        latest_job = (
            db.query(InstagramPublishJob)
            .filter(
                InstagramPublishJob.business_id == business.id,
                InstagramPublishJob.content_item_id == content.id,
            )
            .order_by(InstagramPublishJob.created_at.desc())
            .first()
        )
        return {
            "ok": True,
            "idempotent": True,
            "hold_id": existing.id,
            "outcome_requires_review": bool(
                latest_job is not None
                and latest_job.status == "action_required"
                and latest_job.provider_status == "outcome_requires_review"
            ),
        }
    now = datetime.now(timezone.utc)
    hold = InstagramContentPublicationHold(
        business_id=business.id,
        content_id=content.id,
        reason=payload.reason,
        held_by_user_id=actor.id,
        held_at=now,
    )
    db.add(hold)
    db.flush()
    job = cancel_publish_job(
        db,
        content,
        reason="publication_hold_activated_by_business",
        actor=actor,
    )
    outcome_requires_review = bool(
        job is not None
        and job.status == "action_required"
        and job.provider_status == "outcome_requires_review"
    )
    if content.status == "scheduled":
        content.status = "validated"
    _audit(
        db,
        request=request,
        actor=actor,
        business_id=business.id,
        action="content_admin_publication_hold",
        resource_type="instagram_content_publication_hold",
        resource_id=hold.id,
        metadata={
            "content_id": content.id,
            "version_id": current_version(db, content).id,
            "job_id": job.id if job else None,
            "outcome_requires_review": outcome_requires_review,
        },
    )
    db.commit()
    return {
        "ok": True,
        "idempotent": False,
        "hold_id": hold.id,
        "outcome_requires_review": outcome_requires_review,
    }


@admin_router.post("/contents/{content_id}/publication-hold/release")
def admin_release_publication_hold(
    business_slug: str,
    content_id: int,
    payload: InstagramPublicationHoldRelease,
    request: Request,
    actor: User = Depends(require_tenant_business_admin),
    db: Session = Depends(get_db),
):
    business = _admin_business(db, business_slug)
    content = content_or_404(db, business.id, content_id, for_update=True)
    hold = active_publication_hold(db, content, lock=True)
    if hold is None:
        return {"ok": True, "idempotent": True, "hold_id": None}
    hold.released_by_user_id = actor.id
    hold.released_at = datetime.now(timezone.utc)
    hold.release_note = payload.note
    _audit(
        db,
        request=request,
        actor=actor,
        business_id=business.id,
        action="content_admin_publication_resumed",
        resource_type="instagram_content_publication_hold",
        resource_id=hold.id,
        metadata={"content_id": content.id},
    )
    db.commit()
    return {"ok": True, "idempotent": False, "hold_id": hold.id}


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
    actor: User = Depends(require_tenant_business_admin),
    db: Session = Depends(get_db),
):
    business = _admin_business(db, business_slug)
    content = content_or_404(db, business.id, content_id, for_update=True)
    version = current_version(db, content)
    if version.id != payload.version_id:
        raise HTTPException(status_code=409, detail="Review must target the current version")
    if content.status not in {"ready_for_review", "validated", "scheduled"}:
        raise HTTPException(status_code=409, detail="Content is not available for business review")
    if payload.decision != "approve" and payload.note is None:
        raise HTTPException(status_code=422, detail="A review note is required")

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
    editorial_review = (
        db.query(InstagramContentEditorialReview)
        .filter(InstagramContentEditorialReview.version_id == version.id)
        .first()
    )
    if editorial_review is None:
        editorial_review = InstagramContentEditorialReview(
            business_id=business.id,
            content_id=content.id,
            version_id=version.id,
            status="pending",
            submitted_at=datetime.now(timezone.utc),
        )
        db.add(editorial_review)
    editorial_review.status = (
        "approved"
        if approved
        else "changes_requested"
        if payload.decision == "changes_requested"
        else "rejected"
    )
    editorial_review.reviewed_by_user_id = actor.id
    editorial_review.reviewed_at = datetime.now(timezone.utc)
    editorial_review.note = payload.note
    db.flush()
    _audit(
        db,
        request=request,
        actor=actor,
        business_id=business.id,
        action=(
            "content_admin_approved_optional"
            if approved
            else "content_admin_changes_requested"
            if payload.decision == "changes_requested"
            else "content_admin_version_rejected"
        ),
        resource_type="instagram_content_editorial_review",
        resource_id=editorial_review.id,
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
        "editorial_review": {
            "id": editorial_review.id,
            "status": editorial_review.status,
            "version_id": editorial_review.version_id,
        },
    }


@owner_router.post("/contents/{content_id}/editorial-review", status_code=201)
def owner_review_content(
    business_id: int,
    content_id: int,
    payload: InstagramEditorialReviewCreate,
    request: Request,
    actor: User = Depends(require_owner),
    db: Session = Depends(get_db),
):
    _owner_business(db, business_id)
    del content_id, payload, request, actor, db
    raise HTTPException(
        status_code=403,
        detail="Optional business review belongs to the business administrator",
    )


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
        action=(
            "instagram_content_business_owner_final_approved"
            if role == "business_admin"
            else "instagram_content_validated"
        ),
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
    actor: User = Depends(require_tenant_business_admin),
    db: Session = Depends(get_db),
):
    _admin_business(db, business_slug)
    del content_id, payload, request, actor
    raise HTTPException(
        status_code=409,
        detail="Business approval is optional; publication selection belongs to AutonoGrow",
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
    del content_id, payload, request, actor
    raise HTTPException(
        status_code=403,
        detail="Scheduling or publishing records the AutonoGrow operational selection",
    )


@owner_router.get("/instagram-media")
def owner_list_instagram_media(
    business_id: int,
    media_filter: str = Query("recent", alias="filter"),
    limit: int = Query(48, ge=1, le=100),
    offset: int = Query(0, ge=0),
    actor: User = Depends(require_owner),
    db: Session = Depends(get_db),
):
    del actor
    _owner_business(db, business_id)
    require_service_enabled(db, business_id)
    query = (
        db.query(InstagramRemoteMedia)
        .options(selectinload(InstagramRemoteMedia.children))
        .filter(
            InstagramRemoteMedia.business_id == business_id,
            InstagramRemoteMedia.parent_id.is_(None),
            InstagramRemoteMedia.remote_status == "available",
        )
    )
    if media_filter == "photos":
        query = query.filter(InstagramRemoteMedia.media_type == "IMAGE")
    elif media_filter == "carousels":
        query = query.filter(InstagramRemoteMedia.media_type == "CAROUSEL_ALBUM")
    elif media_filter == "reels":
        query = query.filter(
            InstagramRemoteMedia.media_type == "VIDEO",
            InstagramRemoteMedia.media_product_type == "REELS",
        )
    elif media_filter != "recent":
        raise HTTPException(status_code=422, detail="Unsupported Instagram media filter")
    media = (
        query.order_by(
            InstagramRemoteMedia.provider_timestamp.desc(), InstagramRemoteMedia.id.desc()
        )
        .offset(offset)
        .limit(limit + 1)
        .all()
    )
    prefix = _owner_prefix(business_id)
    return {
        "items": [serialize_remote_media(item, prefix) for item in media[:limit]],
        "has_more": len(media) > limit,
        "next_offset": offset + limit if len(media) > limit else None,
    }


@owner_router.get("/instagram-media/sync")
def owner_instagram_media_sync_status(
    business_id: int,
    actor: User = Depends(require_owner),
    db: Session = Depends(get_db),
):
    del actor
    _owner_business(db, business_id)
    integration = get_instagram_integration(db, business_id=business_id)
    state = (
        db.query(InstagramMediaSyncState)
        .filter(InstagramMediaSyncState.integration_id == integration.id)
        .first()
        if integration is not None
        else None
    )
    return serialize_sync_state(state)


@owner_router.post("/instagram-media/sync", status_code=202)
def owner_refresh_instagram_media(
    business_id: int,
    actor: User = Depends(require_owner),
    db: Session = Depends(get_db),
):
    _owner_business(db, business_id)
    require_service_enabled(db, business_id)
    try:
        job, created, state = enqueue_instagram_media_sync(
            db,
            business_id=business_id,
            origin="owner",
            actor_user_id=actor.id,
        )
    except ValueError as error:
        raise HTTPException(status_code=409, detail="Instagram is not connected") from error
    db.commit()
    return {
        "accepted": True,
        "created": created,
        "job_id": job.id,
        "sync": serialize_sync_state(state),
    }


@owner_router.get("/instagram-media/{media_id}")
def owner_instagram_media_detail(
    business_id: int,
    media_id: int,
    actor: User = Depends(require_owner),
    db: Session = Depends(get_db),
):
    del actor
    _owner_business(db, business_id)
    media = (
        db.query(InstagramRemoteMedia)
        .options(selectinload(InstagramRemoteMedia.children))
        .filter(
            InstagramRemoteMedia.id == media_id,
            InstagramRemoteMedia.business_id == business_id,
        )
        .first()
    )
    if media is None:
        raise HTTPException(status_code=404, detail="Instagram media not found")
    return serialize_remote_media(media, _owner_prefix(business_id))


@owner_router.get("/instagram-media/{media_id}/preview")
def owner_instagram_media_preview(
    business_id: int,
    media_id: int,
    actor: User = Depends(require_owner),
    db: Session = Depends(get_db),
):
    del actor
    _owner_business(db, business_id)
    try:
        media, integration = remote_media_for_business(
            db,
            business_id=business_id,
            media_id=media_id,
        )
        url = media.provider_preview_url
        try:
            if not url:
                raise RemoteAssetError("Instagram preview URL must be refreshed")
            downloaded = download_remote_image(url)
        except RemoteAssetError:
            refreshed = refresh_remote_media_item(media, integration)
            url = refreshed.thumbnail_url if media.media_type == "VIDEO" else refreshed.media_url
            url = url or refreshed.thumbnail_url
            if not url:
                raise RemoteAssetError("Instagram preview is unavailable")
            downloaded = download_remote_image(url)
        media.provider_preview_url = url
        media.last_checked_at = datetime.now(timezone.utc)
        media.last_error_code = None
        db.commit()
    except MetaHTTPError as error:
        if error.unavailable:
            mark_media_unavailable(
                db,
                business_id=business_id,
                integration_id=media.integration_id,
                media_id=media.id,
                error_code=error.error_code,
            )
            db.commit()
            raise HTTPException(status_code=404, detail="Instagram media is unavailable") from error
        raise HTTPException(
            status_code=502, detail="Instagram preview could not be updated"
        ) from error
    except requests.RequestException as error:
        raise HTTPException(
            status_code=502, detail="Instagram preview could not be updated"
        ) from error
    except RemoteAssetError as error:
        raise HTTPException(status_code=502, detail=str(error)) from error
    return Response(
        content=downloaded.content,
        media_type=downloaded.media_type,
        headers={
            "Cache-Control": "private, max-age=300",
            "X-Content-Type-Options": "nosniff",
        },
    )


@owner_router.post("/contents/{content_id}/story-image", status_code=201)
async def owner_render_story_image(
    business_id: int,
    content_id: int,
    request: Request,
    transform_json: str = Form("{}", alias="transform"),
    file: UploadFile | None = File(None),
    remote_media_id: int | None = Form(None),
    source_raw_asset_id: int | None = Form(None),
    actor: User = Depends(require_owner),
    db: Session = Depends(get_db),
):
    _owner_business(db, business_id)
    require_service_enabled(db, business_id)
    content_or_404(db, business_id, content_id)
    try:
        transform = StoryTransform.from_json(transform_json)
    except StoryRenderError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error
    selected = sum(
        (
            file is not None,
            remote_media_id is not None,
            source_raw_asset_id is not None,
        )
    )
    if selected != 1:
        raise HTTPException(status_code=422, detail="Choose exactly one Story image source")

    source_remote: InstagramRemoteMedia | None = None
    raw_asset: InstagramRawAsset | None = None
    if file is not None:
        maximum = get_settings().upload_max_size_mb * 1024 * 1024
        content = await file.read(maximum + 1)
        raw_asset = create_uploaded_story_raw(
            db,
            business_id=business_id,
            actor=actor,
            filename=file.filename or "story-image",
            media_type=(file.content_type or "").lower(),
            content=content,
        )
    elif remote_media_id is not None:
        try:
            source_remote, integration = remote_media_for_business(
                db,
                business_id=business_id,
                media_id=remote_media_id,
            )
            if source_remote.media_type != "IMAGE":
                raise HTTPException(
                    status_code=422,
                    detail="P1 supports Instagram images and carousel image children",
                )
            refreshed = refresh_remote_media_item(source_remote, integration)
            if not refreshed.media_url:
                raise RemoteAssetError("Instagram image URL is unavailable")
            downloaded = download_remote_image(refreshed.media_url)
            source_remote.provider_preview_url = refreshed.media_url
            source_remote.last_checked_at = datetime.now(timezone.utc)
            raw_asset, _ = materialize_remote_image(
                db,
                media=source_remote,
                downloaded=downloaded,
            )
        except MetaHTTPError as error:
            if error.unavailable and source_remote is not None:
                mark_media_unavailable(
                    db,
                    business_id=business_id,
                    integration_id=source_remote.integration_id,
                    media_id=source_remote.id,
                    error_code=error.error_code,
                )
                db.commit()
                raise HTTPException(
                    status_code=409, detail="Instagram media is no longer available"
                ) from error
            raise HTTPException(
                status_code=502, detail="Instagram media could not be read"
            ) from error
        except requests.RequestException as error:
            raise HTTPException(
                status_code=502, detail="Instagram media could not be read"
            ) from error
        except RemoteAssetError as error:
            raise HTTPException(status_code=502, detail=str(error)) from error
    else:
        raw_asset = (
            db.query(InstagramRawAsset)
            .filter(
                InstagramRawAsset.id == source_raw_asset_id,
                InstagramRawAsset.business_id == business_id,
                InstagramRawAsset.active.is_(True),
                InstagramRawAsset.media_type.in_(("image/jpeg", "image/png", "image/webp")),
            )
            .first()
        )
        if raw_asset is None:
            raise HTTPException(status_code=404, detail="Story source not found")
        source_remote = raw_asset.source_remote_media

    if raw_asset is None:
        raise HTTPException(status_code=404, detail="Story source not found")

    final_asset, created = render_story_version(
        db,
        business_id=business_id,
        content_id=content_id,
        raw_asset=raw_asset,
        actor=actor,
        transform=transform,
        source_remote_media=source_remote,
    )
    _audit(
        db,
        request=request,
        actor=actor,
        business_id=business_id,
        action="instagram_raw_asset_reused",
        resource_type="instagram_raw_asset",
        resource_id=raw_asset.id,
        metadata={"content_id": content_id, "final_asset_id": final_asset.id},
    )
    db.commit()
    return {
        "created": created,
        "asset": serialize_final_asset(final_asset, _owner_prefix(business_id)),
        "content": serialize_content(
            db,
            content_or_404(db, business_id, content_id),
            _owner_prefix(business_id),
            detailed=True,
        ),
    }
