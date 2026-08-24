from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from uuid import uuid4

from sqlalchemy import or_
from sqlalchemy.orm import Session

from app.core.audit import record_audit
from app.core.config import Settings, get_settings
from app.models import (
    BusinessChannelIntegration,
    InstagramMediaSyncState,
    InstagramPublishJob,
    InstagramRemoteMedia,
    MetaIntegrationJob,
)
from app.services.instagram_integration_service import get_instagram_integration
from app.services.instagram_meta_client import InstagramRemoteMediaItem
from app.services.meta_integration_job_service import enqueue_meta_integration_job

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class SyncPersistResult:
    discovered: int
    created: int
    updated: int
    restored: int


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _state_for_integration(
    db: Session,
    *,
    integration: BusinessChannelIntegration,
    for_update: bool = False,
) -> InstagramMediaSyncState:
    query = db.query(InstagramMediaSyncState).filter(
        InstagramMediaSyncState.integration_id == integration.id,
        InstagramMediaSyncState.business_id == integration.business_id,
    )
    if for_update and db.get_bind().dialect.name == "postgresql":
        query = query.with_for_update()
    state = query.first()
    if state is None:
        state = InstagramMediaSyncState(
            business_id=integration.business_id,
            integration_id=integration.id,
            status="idle",
        )
        db.add(state)
        db.flush()
    return state


def enqueue_instagram_media_sync(
    db: Session,
    *,
    business_id: int,
    origin: str,
    actor_user_id: int | None = None,
    settings: Settings | None = None,
) -> tuple[MetaIntegrationJob, bool, InstagramMediaSyncState]:
    config = settings or get_settings()
    integration = get_instagram_integration(db, business_id=business_id)
    if (
        integration is None
        or integration.integration_status not in {"connected", "degraded"}
        or not integration.encrypted_access_token
        or not integration.encryption_key_version
    ):
        raise ValueError("Instagram integration is unavailable")
    state = _state_for_integration(db, integration=integration, for_update=True)
    active_job = (
        db.query(MetaIntegrationJob.id)
        .filter(
            MetaIntegrationJob.integration_id == integration.id,
            MetaIntegrationJob.job_type == "instagram_media_sync",
            MetaIntegrationJob.status.in_(("queued", "processing", "retry")),
        )
        .first()
    )
    if (
        not state.run_id
        or state.status in {"idle", "succeeded"}
        or (state.status == "failed" and active_job is None)
    ):
        state.run_id = uuid4().hex
        state.after_cursor = None
    state.updated_at = _now()
    cursor_key = state.after_cursor or "first"
    job, created = enqueue_meta_integration_job(
        db,
        business_id=business_id,
        integration_id=integration.id,
        job_type="instagram_media_sync",
        origin=origin,
        actor_user_id=actor_user_id,
        idempotency_key=f"instagram-media-sync:{state.run_id}:{cursor_key}",
        max_attempts=config.meta_integration_failure_threshold,
    )
    state.status = "failed" if job.status == "retry" and not created else "queued"
    if state.status == "queued":
        state.last_error_code = None
        state.safe_error_message = None
    db.flush()
    return job, created, state


def mark_sync_started(
    db: Session,
    *,
    state: InstagramMediaSyncState,
    job: MetaIntegrationJob,
) -> None:
    current = _now()
    state.status = "running"
    state.last_attempt_at = current
    state.last_error_code = None
    state.safe_error_message = None
    state.updated_at = current
    record_audit(
        db,
        action="instagram_media_sync_started",
        business_id=state.business_id,
        resource_type="instagram_media_sync_state",
        resource_id=state.id,
        metadata={"integration_id": state.integration_id, "job_id": job.id},
        commit=False,
    )
    db.flush()


def mark_sync_failed(
    db: Session,
    *,
    state: InstagramMediaSyncState,
    job_id: int,
    error_code: str,
    safe_message: str,
) -> None:
    state.status = "failed"
    state.last_error_code = error_code[:120]
    state.safe_error_message = safe_message[:500]
    state.updated_at = _now()
    record_audit(
        db,
        action="instagram_media_sync_failed",
        business_id=state.business_id,
        resource_type="instagram_media_sync_state",
        resource_id=state.id,
        metadata={
            "integration_id": state.integration_id,
            "job_id": job_id,
            "safe_error_code": error_code[:120],
        },
        commit=False,
    )
    logger.warning(
        "instagram_media_sync_failed business_id=%s integration_id=%s job_id=%s error_code=%s",
        state.business_id,
        state.integration_id,
        job_id,
        error_code[:120],
    )


def _known_content_id(
    db: Session,
    *,
    business_id: int,
    integration_id: int,
    provider_media_id: str,
) -> int | None:
    row = (
        db.query(InstagramPublishJob.content_item_id)
        .filter(
            InstagramPublishJob.business_id == business_id,
            InstagramPublishJob.integration_id == integration_id,
            InstagramPublishJob.provider_media_id == provider_media_id,
            InstagramPublishJob.status == "published",
        )
        .order_by(InstagramPublishJob.id.desc())
        .first()
    )
    return row[0] if row else None


def _upsert_item(
    db: Session,
    *,
    business_id: int,
    integration_id: int,
    run_id: str,
    item: InstagramRemoteMediaItem,
    parent_id: int | None,
    position: int | None,
) -> tuple[InstagramRemoteMedia, bool, bool]:
    current = _now()
    media = (
        db.query(InstagramRemoteMedia)
        .filter(
            InstagramRemoteMedia.integration_id == integration_id,
            InstagramRemoteMedia.provider_media_id == item.provider_media_id,
        )
        .first()
    )
    created = media is None
    restored = media is not None and media.remote_status == "unavailable"
    internal_content_id = _known_content_id(
        db,
        business_id=business_id,
        integration_id=integration_id,
        provider_media_id=item.provider_media_id,
    )
    if media is None:
        media = InstagramRemoteMedia(
            business_id=business_id,
            integration_id=integration_id,
            provider_media_id=item.provider_media_id,
            first_seen_at=current,
            created_at=current,
        )
        db.add(media)
    media.parent_id = parent_id
    media.position = position
    media.origin = "autonogrow" if internal_content_id is not None else "instagram"
    media.media_type = item.media_type
    media.media_product_type = item.media_product_type
    media.caption = item.caption
    media.provider_timestamp = item.timestamp
    media.permalink = item.permalink
    media.provider_preview_url = item.thumbnail_url or item.media_url
    media.remote_status = "available"
    media.last_seen_at = current
    media.last_checked_at = current
    media.unavailable_at = None
    media.last_error_code = None
    media.last_seen_sync_id = run_id
    media.internal_content_id = internal_content_id
    media.updated_at = current
    db.flush()
    if restored:
        record_audit(
            db,
            action="instagram_media_restored",
            business_id=business_id,
            resource_type="instagram_remote_media",
            resource_id=media.id,
            metadata={"integration_id": integration_id},
            commit=False,
        )
    return media, created, restored


def persist_media_page(
    db: Session,
    *,
    business_id: int,
    integration_id: int,
    run_id: str,
    items: tuple[tuple[InstagramRemoteMediaItem, tuple[InstagramRemoteMediaItem, ...]], ...],
) -> SyncPersistResult:
    created = 0
    updated = 0
    restored = 0
    discovered = 0
    for item, children in items:
        parent, was_created, was_restored = _upsert_item(
            db,
            business_id=business_id,
            integration_id=integration_id,
            run_id=run_id,
            item=item,
            parent_id=None,
            position=None,
        )
        discovered += 1
        created += int(was_created)
        updated += int(not was_created)
        restored += int(was_restored)
        for position, child in enumerate(children):
            _, child_created, child_restored = _upsert_item(
                db,
                business_id=business_id,
                integration_id=integration_id,
                run_id=run_id,
                item=child,
                parent_id=parent.id,
                position=position,
            )
            discovered += 1
            created += int(child_created)
            updated += int(not child_created)
            restored += int(child_restored)
        if item.media_type == "CAROUSEL_ALBUM":
            seen_child_ids = {child.provider_media_id for child in children}
            stale_children = db.query(InstagramRemoteMedia).filter(
                InstagramRemoteMedia.parent_id == parent.id,
                InstagramRemoteMedia.remote_status == "available",
            )
            if seen_child_ids:
                stale_children = stale_children.filter(
                    InstagramRemoteMedia.provider_media_id.notin_(seen_child_ids)
                )
            for stale_child in stale_children.all():
                mark_media_unavailable(
                    db,
                    business_id=business_id,
                    integration_id=integration_id,
                    media_id=stale_child.id,
                    error_code="not_in_current_carousel",
                )
    return SyncPersistResult(discovered, created, updated, restored)


def unavailable_probe_candidates(
    db: Session,
    *,
    integration_id: int,
    run_id: str,
    limit: int,
) -> list[tuple[int, str]]:
    return [
        (row.id, row.provider_media_id)
        for row in db.query(InstagramRemoteMedia)
        .filter(
            InstagramRemoteMedia.integration_id == integration_id,
            InstagramRemoteMedia.parent_id.is_(None),
            InstagramRemoteMedia.remote_status == "available",
            or_(
                InstagramRemoteMedia.last_seen_sync_id.is_(None),
                InstagramRemoteMedia.last_seen_sync_id != run_id,
            ),
        )
        .order_by(
            InstagramRemoteMedia.last_checked_at.asc(), InstagramRemoteMedia.id.asc()
        )
        .limit(limit)
        .all()
    ]


def mark_media_unavailable(
    db: Session,
    *,
    business_id: int,
    integration_id: int,
    media_id: int,
    error_code: str | None,
) -> bool:
    media = (
        db.query(InstagramRemoteMedia)
        .filter(
            InstagramRemoteMedia.id == media_id,
            InstagramRemoteMedia.business_id == business_id,
            InstagramRemoteMedia.integration_id == integration_id,
        )
        .first()
    )
    if media is None:
        return False
    current = _now()
    changed = media.remote_status != "unavailable"
    media.remote_status = "unavailable"
    media.unavailable_at = media.unavailable_at or current
    media.last_checked_at = current
    media.last_error_code = (error_code or "provider_media_unavailable")[:120]
    media.updated_at = current
    for child in media.children:
        child.remote_status = "unavailable"
        child.unavailable_at = child.unavailable_at or current
        child.last_checked_at = current
        child.last_error_code = media.last_error_code
    if changed:
        record_audit(
            db,
            action="instagram_media_became_unavailable",
            business_id=business_id,
            resource_type="instagram_remote_media",
            resource_id=media.id,
            metadata={"integration_id": integration_id},
            commit=False,
        )
    return changed


def mark_probe_available(
    db: Session,
    *,
    business_id: int,
    integration_id: int,
    media_id: int,
    item: InstagramRemoteMediaItem,
) -> None:
    media = (
        db.query(InstagramRemoteMedia)
        .filter(
            InstagramRemoteMedia.id == media_id,
            InstagramRemoteMedia.business_id == business_id,
            InstagramRemoteMedia.integration_id == integration_id,
        )
        .first()
    )
    if media is None:
        return
    media.last_checked_at = _now()
    media.media_product_type = item.media_product_type
    media.caption = item.caption
    media.provider_timestamp = item.timestamp
    media.permalink = item.permalink
    media.provider_preview_url = item.thumbnail_url or item.media_url
    media.last_error_code = None
    media.updated_at = _now()


def advance_or_finish_sync(
    db: Session,
    *,
    state: InstagramMediaSyncState,
    job_id: int,
    after_cursor: str | None,
    result: SyncPersistResult,
    unavailable_count: int,
) -> bool:
    current = _now()
    state.after_cursor = after_cursor
    state.updated_at = current
    completed = after_cursor is None
    if completed:
        state.status = "succeeded"
        state.last_success_at = current
        state.last_completed_at = current
        state.run_id = None
        state.last_error_code = None
        state.safe_error_message = None
        action = "instagram_media_sync_completed"
    else:
        state.status = "queued"
        action = "instagram_media_sync_page_completed"
    record_audit(
        db,
        action=action,
        business_id=state.business_id,
        resource_type="instagram_media_sync_state",
        resource_id=state.id,
        metadata={
            "integration_id": state.integration_id,
            "job_id": job_id,
            "discovered": result.discovered,
            "created": result.created,
            "updated": result.updated,
            "restored": result.restored,
            "unavailable": unavailable_count,
            "has_more": not completed,
        },
        commit=False,
    )
    logger.info(
        "instagram_media_sync_progress business_id=%s integration_id=%s job_id=%s "
        "discovered=%s created=%s updated=%s restored=%s unavailable=%s has_more=%s",
        state.business_id,
        state.integration_id,
        job_id,
        result.discovered,
        result.created,
        result.updated,
        result.restored,
        unavailable_count,
        not completed,
    )
    return completed


def serialize_remote_media(media: InstagramRemoteMedia, api_prefix: str) -> dict:
    return {
        "id": media.id,
        "origin": media.origin,
        "media_type": media.media_type,
        "media_product_type": media.media_product_type,
        "caption": media.caption,
        "published_at": media.provider_timestamp.isoformat()
        if media.provider_timestamp
        else None,
        "permalink": media.permalink if media.remote_status == "available" else None,
        "remote_status": media.remote_status,
        "internal_content_id": media.internal_content_id,
        "preview_url": f"{api_prefix}/instagram-media/{media.id}/preview",
        "child_count": len(media.children),
        "children": [
            {
                "id": child.id,
                "media_type": child.media_type,
                "position": child.position,
                "remote_status": child.remote_status,
                "preview_url": f"{api_prefix}/instagram-media/{child.id}/preview",
            }
            for child in media.children
            if child.remote_status == "available"
        ],
    }


def serialize_sync_state(state: InstagramMediaSyncState | None) -> dict:
    if state is None:
        return {
            "status": "idle",
            "last_attempt_at": None,
            "last_success_at": None,
            "last_completed_at": None,
            "safe_error_code": None,
            "safe_error_message": None,
        }
    return {
        "status": state.status,
        "last_attempt_at": state.last_attempt_at,
        "last_success_at": state.last_success_at,
        "last_completed_at": state.last_completed_at,
        "safe_error_code": state.last_error_code,
        "safe_error_message": state.safe_error_message,
    }
