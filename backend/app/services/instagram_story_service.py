from __future__ import annotations

import hashlib
from pathlib import Path
from uuid import uuid4

from fastapi import HTTPException
from sqlalchemy.orm import Session

from app.core.audit import record_audit
from app.core.config import Settings, get_settings, get_uploads_dir
from app.models import (
    InstagramContentRawAsset,
    InstagramFinalAsset,
    InstagramRawAsset,
    InstagramRemoteMedia,
    User,
)
from app.services.instagram_content_service import (
    content_or_404,
    current_version,
    update_material,
)
from app.services.instagram_story_renderer import (
    STORY_RENDERER_VERSION,
    StoryRenderError,
    StoryTransform,
    render_story_jpeg,
    story_derivation_fingerprint,
)

_UPLOAD_MIME = frozenset({"image/jpeg", "image/png", "image/webp"})
_EXTENSION = {"image/jpeg": ".jpg", "image/png": ".png", "image/webp": ".webp"}


def _storage_path(storage_key: str) -> Path:
    root = (get_uploads_dir() / "_instagram_content").resolve()
    path = (get_uploads_dir() / storage_key).resolve()
    if root != path and root not in path.parents:
        raise HTTPException(status_code=404, detail="Story source not found")
    if not path.is_file():
        raise HTTPException(status_code=404, detail="Story source not found")
    return path


def create_uploaded_story_raw(
    db: Session,
    *,
    business_id: int,
    actor: User,
    filename: str,
    media_type: str,
    content: bytes,
    settings: Settings | None = None,
) -> InstagramRawAsset:
    config = settings or get_settings()
    if media_type not in _UPLOAD_MIME:
        raise HTTPException(status_code=400, detail="Story images must be JPEG, PNG, or WebP")
    if not content or len(content) > config.upload_max_size_mb * 1024 * 1024:
        raise HTTPException(status_code=400, detail="Story source exceeds the upload size limit")
    signatures = {
        "image/jpeg": content.startswith(b"\xff\xd8\xff"),
        "image/png": content.startswith(b"\x89PNG\r\n\x1a\n"),
        "image/webp": len(content) >= 12
        and content.startswith(b"RIFF")
        and content[8:12] == b"WEBP",
    }
    if not signatures[media_type]:
        raise HTTPException(status_code=400, detail="Story image MIME does not match its content")
    transform = StoryTransform()
    try:
        render_story_jpeg(
            content,
            transform=transform,
            max_output_bytes=config.instagram_story_render_max_size_mb * 1024 * 1024,
        )
    except StoryRenderError as error:
        raise HTTPException(status_code=400, detail=str(error)) from error
    extension = _EXTENSION[media_type]
    relative = (
        Path("_instagram_content")
        / str(business_id)
        / "raw"
        / f"{uuid4().hex}{extension}"
    )
    path = get_uploads_dir() / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(content)
    asset = InstagramRawAsset(
        business_id=business_id,
        uploaded_by_user_id=actor.id,
        source_kind="business_upload",
        original_filename=Path(filename or f"story{extension}").name[:255],
        storage_key=relative.as_posix(),
        media_type=media_type,
        size_bytes=len(content),
        sha256=hashlib.sha256(content).hexdigest(),
    )
    db.add(asset)
    db.flush()
    return asset


def render_story_version(
    db: Session,
    *,
    business_id: int,
    content_id: int,
    raw_asset: InstagramRawAsset,
    actor: User,
    transform: StoryTransform,
    source_remote_media: InstagramRemoteMedia | None = None,
    settings: Settings | None = None,
) -> tuple[InstagramFinalAsset, bool]:
    config = settings or get_settings()
    content = content_or_404(db, business_id, content_id, for_update=True)
    if content.status in {"cancelled", "published"}:
        raise HTTPException(status_code=409, detail="Terminal content cannot be edited")
    if raw_asset.business_id != business_id:
        raise HTTPException(status_code=404, detail="Story source not found")
    if source_remote_media is not None and (
        source_remote_media.business_id != business_id
        or raw_asset.source_remote_media_id != source_remote_media.id
    ):
        raise HTTPException(status_code=404, detail="Instagram source not found")

    source_bytes = _storage_path(raw_asset.storage_key).read_bytes()
    source_sha = raw_asset.sha256 or hashlib.sha256(source_bytes).hexdigest()
    raw_asset.sha256 = source_sha
    fingerprint = story_derivation_fingerprint(source_sha, transform)
    final_asset = (
        db.query(InstagramFinalAsset)
        .filter(
            InstagramFinalAsset.business_id == business_id,
            InstagramFinalAsset.content_id == content_id,
            InstagramFinalAsset.source_raw_asset_id == raw_asset.id,
            InstagramFinalAsset.derivation_fingerprint == fingerprint,
        )
        .first()
    )
    created = final_asset is None
    if final_asset is None:
        try:
            rendered = render_story_jpeg(
                source_bytes,
                transform=transform,
                max_output_bytes=config.instagram_story_render_max_size_mb * 1024 * 1024,
            )
        except StoryRenderError as error:
            raise HTTPException(status_code=400, detail=str(error)) from error
        relative = (
            Path("_instagram_content")
            / str(business_id)
            / "final"
            / str(content_id)
            / f"{uuid4().hex}.jpg"
        )
        path = get_uploads_dir() / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(rendered)
        final_asset = InstagramFinalAsset(
            business_id=business_id,
            content_id=content_id,
            uploaded_by_user_id=actor.id,
            source_raw_asset_id=raw_asset.id,
            original_filename=f"story-{raw_asset.id}.jpg",
            storage_key=relative.as_posix(),
            media_type="image/jpeg",
            size_bytes=len(rendered),
            sha256=hashlib.sha256(rendered).hexdigest(),
            derivation_fingerprint=fingerprint,
        )
        db.add(final_asset)
        db.flush()

    link = (
        db.query(InstagramContentRawAsset)
        .filter(
            InstagramContentRawAsset.business_id == business_id,
            InstagramContentRawAsset.content_id == content_id,
            InstagramContentRawAsset.raw_asset_id == raw_asset.id,
        )
        .first()
    )
    if link is None:
        db.add(
            InstagramContentRawAsset(
                business_id=business_id,
                content_id=content_id,
                raw_asset_id=raw_asset.id,
                associated_by_user_id=actor.id,
            )
        )
        db.flush()

    previous = current_version(db, content)
    update_material(
        db,
        business_id=business_id,
        content_id=content_id,
        actor=actor,
        caption=previous.caption,
        format="story",
        asset_ids=[final_asset.id],
        cover_asset_id=final_asset.id,
        story_transform_json=transform.to_json(),
        story_renderer_version=STORY_RENDERER_VERSION,
    )
    if created:
        record_audit(
            db,
            action="instagram_story_asset_rendered",
            actor=actor,
            business_id=business_id,
            resource_type="instagram_final_asset",
            resource_id=final_asset.id,
            metadata={
                "content_id": content_id,
                "source_raw_asset_id": raw_asset.id,
                "source_remote_media_id": source_remote_media.id
                if source_remote_media is not None
                else None,
                "renderer_version": STORY_RENDERER_VERSION,
            },
            commit=False,
        )
        if source_remote_media is not None:
            record_audit(
                db,
                action="instagram_story_created_from_existing_media",
                actor=actor,
                business_id=business_id,
                resource_type="instagram_remote_media",
                resource_id=source_remote_media.id,
                metadata={
                    "content_id": content_id,
                    "final_asset_id": final_asset.id,
                    "internal_source_content_id": source_remote_media.internal_content_id,
                },
                commit=False,
            )
    return final_asset, created
