import json
import re
from datetime import datetime, timezone

from fastapi import HTTPException
from sqlalchemy import func
from sqlalchemy.orm import Session, joinedload

from app.core.config import get_settings
from app.models import (
    InstagramContent,
    InstagramContentComment,
    InstagramContentEditorialReview,
    InstagramContentPublicationHold,
    InstagramContentRawAsset,
    InstagramContentSettings,
    InstagramContentValidation,
    InstagramContentVersion,
    InstagramContentVersionAsset,
    InstagramFinalAsset,
    InstagramPublishJob,
    InstagramRawAsset,
    InstagramRemoteMedia,
    User,
)
from app.services.capability_service import require_module_available

_UNSET = object()


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def get_or_create_settings(db: Session, business_id: int) -> InstagramContentSettings:
    settings = db.get(InstagramContentSettings, business_id)
    if settings is None:
        settings = InstagramContentSettings(business_id=business_id)
        db.add(settings)
        db.flush()
    return settings


def require_service_enabled(db: Session, business_id: int) -> InstagramContentSettings:
    require_module_available(db, business_id, "social")
    settings = db.get(InstagramContentSettings, business_id)
    if settings is None or not settings.enabled:
        raise HTTPException(status_code=409, detail="Instagram content management is not enabled")
    return settings


def content_or_404(
    db: Session, business_id: int, content_id: int, *, for_update: bool = False
) -> InstagramContent:
    query = db.query(InstagramContent).filter(
        InstagramContent.id == content_id,
        InstagramContent.business_id == business_id,
        InstagramContent.archived_at.is_(None),
    )
    if for_update:
        query = query.with_for_update()
    content = query.first()
    if content is None:
        raise HTTPException(status_code=404, detail="Instagram content not found")
    return content


def current_version(db: Session, content: InstagramContent) -> InstagramContentVersion:
    version = getattr(content, "_prefetched_current_version", None)
    if version is None:
        version = (
            db.query(InstagramContentVersion)
            .filter(
                InstagramContentVersion.content_id == content.id,
                InstagramContentVersion.business_id == content.business_id,
            )
            .order_by(InstagramContentVersion.version_number.desc())
            .first()
        )
    if version is None:
        raise HTTPException(status_code=409, detail="Instagram content has no version")
    return version


def _active_validation(db: Session, content: InstagramContent) -> InstagramContentValidation | None:
    return (
        db.query(InstagramContentValidation)
        .filter(
            InstagramContentValidation.business_id == content.business_id,
            InstagramContentValidation.content_id == content.id,
            InstagramContentValidation.invalidated_at.is_(None),
        )
        .order_by(InstagramContentValidation.validated_at.desc())
        .first()
    )


def invalidate_validation(db: Session, content: InstagramContent, reason: str) -> bool:
    validation = _active_validation(db, content)
    if validation is None:
        return False
    validation.invalidated_at = utc_now()
    validation.invalidation_reason = reason[:240]
    return True


def active_publication_hold(
    db: Session, content: InstagramContent, *, lock: bool = False
) -> InstagramContentPublicationHold | None:
    query = db.query(InstagramContentPublicationHold).filter(
        InstagramContentPublicationHold.business_id == content.business_id,
        InstagramContentPublicationHold.content_id == content.id,
        InstagramContentPublicationHold.released_at.is_(None),
    )
    if lock:
        query = query.with_for_update()
    return query.order_by(InstagramContentPublicationHold.held_at.desc()).first()


def current_version_review_blocker(
    db: Session, content: InstagramContent, version: InstagramContentVersion
) -> InstagramContentEditorialReview | None:
    return (
        db.query(InstagramContentEditorialReview)
        .filter(
            InstagramContentEditorialReview.business_id == content.business_id,
            InstagramContentEditorialReview.content_id == content.id,
            InstagramContentEditorialReview.version_id == version.id,
            InstagramContentEditorialReview.status.in_({"changes_requested", "rejected"}),
        )
        .first()
    )


def ensure_owner_operational_validation(
    db: Session, content: InstagramContent, actor: User
) -> InstagramContentValidation:
    version = current_version(db, content)
    blocker = current_version_review_blocker(db, content, version)
    if blocker is not None:
        raise HTTPException(
            status_code=409,
            detail="The business requested changes to the current version",
        )
    if active_publication_hold(db, content) is not None:
        raise HTTPException(status_code=409, detail="Publication is stopped by the business")
    existing = _active_validation(db, content)
    if existing is not None and existing.version_id == version.id:
        return existing
    if not actor.is_owner:
        raise HTTPException(
            status_code=409,
            detail="AutonoGrow must select the current version for publication",
        )
    if content.status not in {"ready_for_review", "validated", "scheduled"}:
        raise HTTPException(
            status_code=409,
            detail="Content must be ready before it can be selected for publication",
        )
    validation = InstagramContentValidation(
        business_id=content.business_id,
        content_id=content.id,
        version_id=version.id,
        validated_by_user_id=actor.id,
        validator_role="owner_delegate",
        validated_at=utc_now(),
    )
    db.add(validation)
    content.status = "validated"
    db.flush()
    return validation


def create_content(
    db: Session,
    *,
    business_id: int,
    actor: User,
    title: str,
    caption: str,
    format: str,
    planned_publish_at: datetime | None,
) -> InstagramContent:
    require_service_enabled(db, business_id)
    content = InstagramContent(
        business_id=business_id,
        title=title,
        status="draft",
        planned_publish_at=planned_publish_at,
        created_by_user_id=actor.id,
    )
    db.add(content)
    db.flush()
    db.add(
        InstagramContentVersion(
            business_id=business_id,
            content_id=content.id,
            version_number=1,
            caption=caption,
            format=format,
            created_by_user_id=actor.id,
        )
    )
    db.flush()
    return content


def _validated_assets(
    db: Session,
    *,
    business_id: int,
    content_id: int,
    asset_ids: list[int],
) -> list[InstagramFinalAsset]:
    if len(asset_ids) != len(set(asset_ids)):
        raise HTTPException(status_code=422, detail="Final assets cannot be repeated")
    if not asset_ids:
        return []
    assets = (
        db.query(InstagramFinalAsset)
        .filter(
            InstagramFinalAsset.business_id == business_id,
            InstagramFinalAsset.content_id == content_id,
            InstagramFinalAsset.id.in_(asset_ids),
        )
        .all()
    )
    by_id = {item.id: item for item in assets}
    if len(by_id) != len(asset_ids):
        raise HTTPException(status_code=422, detail="A final asset does not belong to this content")
    return [by_id[item_id] for item_id in asset_ids]


def update_material(
    db: Session,
    *,
    business_id: int,
    content_id: int,
    actor: User,
    caption: str,
    format: str,
    asset_ids: list[int],
    cover_asset_id: int | None,
    story_transform_json: str | None | object = _UNSET,
    story_renderer_version: str | None | object = _UNSET,
) -> tuple[InstagramContent, InstagramContentVersion, bool]:
    require_service_enabled(db, business_id)
    content = content_or_404(db, business_id, content_id, for_update=True)
    if content.status in {"cancelled", "published"}:
        raise HTTPException(status_code=409, detail="Terminal content cannot be edited")
    if format == "single_image" and len(asset_ids) > 1:
        raise HTTPException(status_code=422, detail="single_image accepts at most one asset")
    if format == "carousel" and len(asset_ids) == 1:
        raise HTTPException(status_code=422, detail="carousel requires zero or at least two assets")
    _validated_assets(
        db,
        business_id=business_id,
        content_id=content_id,
        asset_ids=asset_ids,
    )
    if cover_asset_id is not None and cover_asset_id not in asset_ids:
        raise HTTPException(status_code=422, detail="Cover must be one of the ordered final assets")

    previous = current_version(db, content)
    previous_ids = [link.asset_id for link in previous.asset_links]
    previous_cover = next((link.asset_id for link in previous.asset_links if link.is_cover), None)
    normalized_cover = (
        cover_asset_id if cover_asset_id is not None else (asset_ids[0] if asset_ids else None)
    )
    effective_story_transform = (
        previous.story_transform_json if story_transform_json is _UNSET else story_transform_json
    )
    effective_story_renderer = (
        previous.story_renderer_version
        if story_renderer_version is _UNSET
        else story_renderer_version
    )
    changed = (
        previous.caption != caption
        or previous.format != format
        or previous_ids != asset_ids
        or previous_cover != normalized_cover
        or previous.story_transform_json != effective_story_transform
        or previous.story_renderer_version != effective_story_renderer
    )
    if not changed:
        return content, previous, False

    version = InstagramContentVersion(
        business_id=business_id,
        content_id=content.id,
        version_number=previous.version_number + 1,
        caption=caption,
        format=format,
        created_by_user_id=actor.id,
        editorial_package_json=(
            _updated_editorial_package(previous.editorial_package_json, caption, format)
            if previous.editorial_package_json
            else None
        ),
        generation_source="manual_edit" if previous.editorial_package_json else None,
        generator_version=previous.generator_version,
        promotion_revision_id=previous.promotion_revision_id,
        story_transform_json=effective_story_transform,
        story_renderer_version=effective_story_renderer,
    )
    db.add(version)
    db.flush()
    for position, asset_id in enumerate(asset_ids):
        db.add(
            InstagramContentVersionAsset(
                version_id=version.id,
                asset_id=asset_id,
                position=position,
                is_cover=asset_id == normalized_cover,
            )
        )
    invalidate_validation(db, content, "material_content_changed")
    from app.services.instagram_publish_service import cancel_publish_job

    cancelled_job = cancel_publish_job(db, content, reason="material_content_changed", actor=actor)
    if cancelled_job is not None:
        from app.core.audit import record_audit

        record_audit(
            db,
            action="material_change_cancelled_publish_job",
            actor=actor,
            business_id=business_id,
            resource_type="instagram_publish_job",
            resource_id=cancelled_job.id,
            metadata={"content_id": content.id, "new_version_id": version.id},
            commit=False,
        )
    content.status = "draft"
    db.flush()
    return content, version, True


def _updated_editorial_package(raw: str, caption: str, format: str) -> str:
    import json

    package = json.loads(raw)
    package["caption"] = caption
    package["editorial_format"] = "static_post" if format == "single_image" else format
    return json.dumps(package, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def submit_for_review(db: Session, business_id: int, content_id: int) -> InstagramContent:
    require_service_enabled(db, business_id)
    content = content_or_404(db, business_id, content_id, for_update=True)
    if content.status not in {"draft", "changes_requested"}:
        raise HTTPException(status_code=409, detail="Only draft or changed content can be reviewed")
    version = current_version(db, content)
    requested_on_version = (
        db.query(InstagramContentComment.id)
        .filter(
            InstagramContentComment.business_id == business_id,
            InstagramContentComment.content_id == content.id,
            InstagramContentComment.version_id == version.id,
            InstagramContentComment.kind == "change_request",
        )
        .first()
    )
    if content.status == "changes_requested" and requested_on_version is not None:
        raise HTTPException(
            status_code=409,
            detail="A new material version is required after a change request",
        )
    asset_count = len(version.asset_links)
    if asset_count == 0:
        raise HTTPException(status_code=409, detail="At least one final asset is required")
    if version.format == "single_image" and asset_count != 1:
        raise HTTPException(status_code=409, detail="single_image requires one final asset")
    if version.format == "carousel" and not 2 <= asset_count <= 10:
        raise HTTPException(
            status_code=409,
            detail="carousel requires between two and ten final assets",
        )
    if version.format == "reel" and asset_count != 1:
        raise HTTPException(
            status_code=409,
            detail="reel requires one final video asset",
        )
    if version.format == "story" and asset_count != 1:
        raise HTTPException(
            status_code=409,
            detail="story requires one final image or video asset",
        )
    editorial_review = (
        db.query(InstagramContentEditorialReview)
        .filter(InstagramContentEditorialReview.version_id == version.id)
        .first()
    )
    if editorial_review is None:
        db.add(
            InstagramContentEditorialReview(
                business_id=business_id,
                content_id=content.id,
                version_id=version.id,
                status="pending",
                submitted_at=utc_now(),
            )
        )
    elif editorial_review.status != "pending":
        editorial_review.status = "pending"
        editorial_review.submitted_at = utc_now()
        editorial_review.reviewed_by_user_id = None
        editorial_review.reviewed_at = None
        editorial_review.note = None
    content.status = "ready_for_review"
    db.flush()
    return content


def add_admin_comment(
    db: Session,
    *,
    business_id: int,
    content_id: int,
    version_id: int,
    actor: User,
    kind: str,
    body: str,
) -> InstagramContentComment:
    require_service_enabled(db, business_id)
    content = content_or_404(db, business_id, content_id, for_update=True)
    version = (
        db.query(InstagramContentVersion)
        .filter(
            InstagramContentVersion.id == version_id,
            InstagramContentVersion.content_id == content.id,
            InstagramContentVersion.business_id == business_id,
        )
        .first()
    )
    if version is None:
        raise HTTPException(status_code=422, detail="Version does not belong to this content")
    if content.status == "cancelled":
        raise HTTPException(status_code=409, detail="Cancelled content cannot be commented")
    if kind == "change_request":
        if version.id != current_version(db, content).id:
            raise HTTPException(status_code=409, detail="Changes must target the current version")
        if content.status not in {"ready_for_review", "validated", "scheduled"}:
            raise HTTPException(status_code=409, detail="Current version cannot be reviewed")
        invalidate_validation(db, content, "changes_requested_by_admin")
        from app.services.instagram_publish_service import cancel_publish_job

        cancel_publish_job(db, content, reason="validation_revoked_by_change_request", actor=actor)
        content.status = "changes_requested"
        editorial_review = (
            db.query(InstagramContentEditorialReview)
            .filter(InstagramContentEditorialReview.version_id == version.id)
            .first()
        )
        if editorial_review is not None:
            editorial_review.status = "changes_requested"
            editorial_review.reviewed_by_user_id = actor.id
            editorial_review.reviewed_at = utc_now()
            editorial_review.note = body
    comment = InstagramContentComment(
        business_id=business_id,
        content_id=content.id,
        version_id=version.id,
        author_user_id=actor.id,
        kind=kind,
        body=body,
    )
    db.add(comment)
    db.flush()
    return comment


def validate_content(
    db: Session,
    *,
    business_id: int,
    content_id: int,
    version_id: int,
    actor: User,
    validator_role: str,
) -> InstagramContentValidation:
    require_service_enabled(db, business_id)
    content = content_or_404(db, business_id, content_id, for_update=True)
    version = current_version(db, content)
    if version.id != version_id:
        raise HTTPException(status_code=409, detail="Validation must target the current version")
    if content.status != "ready_for_review":
        raise HTTPException(status_code=409, detail="Content is not ready for validation")
    if current_version_review_blocker(db, content, version) is not None:
        raise HTTPException(status_code=409, detail="Current version is blocked by the business")
    if active_publication_hold(db, content) is not None:
        raise HTTPException(status_code=409, detail="Publication is stopped by the business")
    existing = _active_validation(db, content)
    if existing is not None:
        raise HTTPException(status_code=409, detail="Current version is already validated")
    validation = InstagramContentValidation(
        business_id=business_id,
        content_id=content.id,
        version_id=version.id,
        validated_by_user_id=actor.id,
        validator_role=validator_role,
        validated_at=utc_now(),
    )
    db.add(validation)
    content.status = "validated"
    db.flush()
    if content.planned_publish_at is not None:
        from app.services.instagram_publish_service import sync_publish_job

        job = sync_publish_job(db, content, actor=actor)
        if job.status == "action_required" and job.provider_error_code == "planned_date_in_past":
            from app.core.audit import record_audit

            record_audit(
                db,
                action="validated_too_late",
                actor=actor,
                business_id=business_id,
                resource_type="instagram_publish_job",
                resource_id=job.id,
                metadata={"content_id": content.id, "version_id": version.id},
                commit=False,
            )
    return validation


def schedule_content(
    db: Session, business_id: int, content_id: int, actor: User | None = None
) -> InstagramContent:
    require_service_enabled(db, business_id)
    content = content_or_404(db, business_id, content_id, for_update=True)
    if actor is None:
        raise HTTPException(status_code=409, detail="A publication actor is required")
    ensure_owner_operational_validation(db, content, actor)
    if content.planned_publish_at is None:
        raise HTTPException(status_code=409, detail="A planned date is required")
    from app.services.instagram_publish_service import sync_publish_job

    job = sync_publish_job(db, content, actor=actor)
    if job.status != "queued":
        raise HTTPException(
            status_code=409, detail=job.safe_error_message or "Publishing requires action"
        )
    return content


def ensure_promotion_window(db: Session, content: InstagramContent, planned_at: datetime) -> None:
    from app.services.instagram_publish_service import promotion_preflight

    error = promotion_preflight(db, current_version(db, content), planned_at)
    if error is not None:
        raise HTTPException(status_code=409, detail=error[1])


def cancel_content(
    db: Session, business_id: int, content_id: int, actor: User | None = None
) -> InstagramContent:
    require_service_enabled(db, business_id)
    content = content_or_404(db, business_id, content_id, for_update=True)
    if content.status == "cancelled":
        raise HTTPException(status_code=409, detail="Content is already cancelled")
    if content.status == "published":
        raise HTTPException(status_code=409, detail="Published content cannot be cancelled")
    content.status = "cancelled"
    from app.services.instagram_publish_service import cancel_publish_job

    cancel_publish_job(db, content, reason="editorial_content_cancelled", actor=actor)
    db.flush()
    return content


def _package_references_raw_asset(package_json: str | None, asset_id: int) -> bool:
    if not package_json:
        return False
    try:
        package = json.loads(package_json)
    except (TypeError, ValueError):
        return False
    recommended = package.get("asset_plan", {}).get("recommended", [])
    return any(
        isinstance(item, dict)
        and item.get("source") == "instagram_raw_asset"
        and item.get("id") == asset_id
        for item in recommended
    )


def _package_raw_asset_ids(package_json: str | None) -> set[int]:
    if not package_json:
        return set()
    try:
        package = json.loads(package_json)
    except (TypeError, ValueError):
        return set()
    recommended = package.get("asset_plan", {}).get("recommended", [])
    return {
        item["id"]
        for item in recommended
        if isinstance(item, dict)
        and item.get("source") == "instagram_raw_asset"
        and isinstance(item.get("id"), int)
    }


def _package_may_reference_raw_asset(package_json: str | None, asset_id: int) -> bool:
    """Conservative delete-only fallback for malformed legacy snapshots."""
    if _package_references_raw_asset(package_json, asset_id):
        return True
    if not package_json:
        return False
    compact = "".join(package_json.split())
    return bool(
        re.search(r"""["']source["']:["']instagram_raw_asset["']""", compact)
        and re.search(rf"""["']id["']:{asset_id}(?!\d)""", compact)
    )


def _version_has_usable_final_assets(version: InstagramContentVersion) -> bool:
    links = sorted(version.asset_links, key=lambda item: item.position)
    assets = [link.asset for link in links]
    if not assets or any(not asset.storage_key or asset.size_bytes <= 0 for asset in assets):
        return False
    if version.format == "single_image":
        return len(assets) == 1 and assets[0].media_type.startswith("image/")
    if version.format == "carousel":
        return 2 <= len(assets) <= 10 and all(
            asset.media_type.startswith("image/") for asset in assets
        )
    if version.format == "reel":
        return len(assets) == 1 and assets[0].media_type == "video/mp4"
    if version.format == "story":
        return len(assets) == 1 and (
            assets[0].media_type.startswith("image/") or assets[0].media_type == "video/mp4"
        )
    return False


def content_dependency_or_404(
    db: Session, business_id: int, content_id: int, *, for_update: bool = False
) -> InstagramContent:
    """Owner-scoped dependency lookup that intentionally includes archived content."""
    query = db.query(InstagramContent).filter(
        InstagramContent.id == content_id,
        InstagramContent.business_id == business_id,
    )
    if for_update:
        query = query.with_for_update()
    content = query.first()
    if content is None:
        raise HTTPException(status_code=404, detail="Instagram content not found")
    return content


def classify_raw_asset_dependencies(
    db: Session,
    *,
    business_id: int,
    asset_id: int,
    for_update: bool = False,
) -> dict:
    """Classify operational, current, historical, and physical dependencies once."""
    asset = raw_asset_or_404(db, business_id, asset_id, for_update=for_update)
    direct_content_ids = {
        content_id
        for (content_id,) in db.query(InstagramContentRawAsset.content_id)
        .filter(
            InstagramContentRawAsset.business_id == business_id,
            InstagramContentRawAsset.raw_asset_id == asset_id,
        )
        .all()
    }
    final_content_ids = {
        content_id
        for (content_id,) in db.query(InstagramFinalAsset.content_id)
        .filter(
            InstagramFinalAsset.business_id == business_id,
            InstagramFinalAsset.source_raw_asset_id == asset_id,
        )
        .all()
    }
    latest_version_numbers: dict[int, int] = {
        content_id: version_number
        for content_id, version_number in db.query(
            InstagramContentVersion.content_id,
            func.max(InstagramContentVersion.version_number),
        )
        .filter(InstagramContentVersion.business_id == business_id)
        .group_by(InstagramContentVersion.content_id)
        .all()
    }
    version_rows = (
        db.query(InstagramContentVersion)
        .options(
            joinedload(InstagramContentVersion.asset_links).joinedload(
                InstagramContentVersionAsset.asset
            )
        )
        .filter(
            InstagramContentVersion.business_id == business_id,
            InstagramContentVersion.editorial_package_json.is_not(None),
        )
        .all()
    )
    references: dict[int, dict[str, object]] = {}
    malformed_reference_content_ids: set[int] = set()
    for version in version_rows:
        strict_reference = _package_references_raw_asset(version.editorial_package_json, asset_id)
        if not strict_reference:
            if _package_may_reference_raw_asset(version.editorial_package_json, asset_id):
                malformed_reference_content_ids.add(version.content_id)
            continue
        entry = references.setdefault(
            version.content_id,
            {
                "current": False,
                "historical": False,
                "current_version": None,
                "version_ids": [],
            },
        )
        is_current = version.version_number == latest_version_numbers.get(version.content_id)
        entry["current"] = bool(entry["current"] or is_current)
        entry["historical"] = bool(entry["historical"] or not is_current)
        if is_current:
            entry["current_version"] = version
        version_ids = entry["version_ids"]
        assert isinstance(version_ids, list)
        version_ids.append(version.id)

    content_ids = direct_content_ids | final_content_ids | set(references)
    contents = (
        db.query(InstagramContent)
        .filter(
            InstagramContent.business_id == business_id,
            InstagramContent.id.in_(content_ids),
        )
        .all()
        if content_ids
        else []
    )
    content_by_id = {content.id: content for content in contents}
    associations: list[dict] = []
    for content_id in sorted(content_ids):
        content = content_by_id[content_id]
        reference = references.get(content_id, {})
        current_reference = bool(reference.get("current"))
        current_version_row = reference.get("current_version")
        current_has_final = bool(
            isinstance(current_version_row, InstagramContentVersion)
            and _version_has_usable_final_assets(current_version_row)
        )
        current_physical_dependency = current_reference and not current_has_final
        direct_association = content_id in direct_content_ids
        historical_reference = bool(reference.get("historical"))
        final_provenance = content_id in final_content_ids
        can_disassociate = direct_association and not current_physical_dependency
        version_ids = reference.get("version_ids", [])
        associations.append(
            {
                "content_id": content.id,
                "content_title": content.title,
                "content_status": content.status,
                "content_archived": content.archived_at is not None,
                "direct_association": direct_association,
                "current_version_reference": current_reference,
                "historical_version_reference": historical_reference,
                "final_asset_provenance": final_provenance,
                "current_physical_dependency": current_physical_dependency,
                "current_version_has_usable_final": current_has_final,
                "historical_only": bool(
                    not current_reference and (historical_reference or final_provenance)
                ),
                "can_disassociate": can_disassociate,
                "protected_reason": (
                    "Este material todavÃ­a se utiliza para preparar la versiÃ³n actual."
                    if direct_association and current_physical_dependency
                    else None
                ),
                "version_ids": list(version_ids) if isinstance(version_ids, list) else [],
                "is_source_material": direct_association,
                "has_final_derivative": final_provenance,
                "has_historical_reference": historical_reference or current_reference,
                "modifiable": can_disassociate,
            }
        )
    has_current_physical_dependency = any(
        item["current_physical_dependency"] for item in associations
    )
    has_version_provenance = bool(references or malformed_reference_content_ids)
    has_any_dependency = bool(direct_content_ids or final_content_ids or has_version_provenance)
    return {
        "asset": asset,
        "associations": associations,
        "direct_association_count": len(direct_content_ids),
        "has_current_physical_dependency": has_current_physical_dependency,
        "has_historical_provenance": bool(final_content_ids or has_version_provenance),
        "has_malformed_legacy_reference": bool(malformed_reference_content_ids),
        "can_retire": asset.active,
        "can_purge_storage": (
            not has_current_physical_dependency and asset.storage_deleted_at is None
        ),
        "can_delete": not has_any_dependency,
    }


def raw_asset_reference_content_ids(db: Session, business_id: int, asset_id: int) -> list[int]:
    classification = classify_raw_asset_dependencies(db, business_id=business_id, asset_id=asset_id)
    return [item["content_id"] for item in classification["associations"]]


def raw_asset_association_manager(
    db: Session,
    *,
    business_id: int,
    asset_id: int,
    for_update: bool = False,
) -> dict:
    classification = classify_raw_asset_dependencies(
        db,
        business_id=business_id,
        asset_id=asset_id,
        for_update=for_update,
    )
    asset = classification["asset"]
    serialized = classification["associations"]
    serialized.sort(key=lambda item: (item["content_title"].casefold(), item["content_id"]))
    return {
        "raw_asset": {
            "id": asset.id,
            "original_filename": asset.original_filename,
            "media_type": asset.media_type,
            "size_bytes": asset.size_bytes,
            "label": asset.label,
            "created_at": asset.created_at.isoformat(),
            "active": asset.active,
            "removed_at": asset.removed_at.isoformat() if asset.removed_at else None,
            "storage_deleted_at": (
                asset.storage_deleted_at.isoformat() if asset.storage_deleted_at else None
            ),
        },
        "association_count": len(serialized),
        "direct_association_count": classification["direct_association_count"],
        "modifiable_count": sum(item["can_disassociate"] for item in serialized),
        "has_historical_provenance": classification["has_historical_provenance"],
        "has_current_physical_dependency": classification["has_current_physical_dependency"],
        "can_retire": classification["can_retire"],
        "can_purge_storage": classification["can_purge_storage"],
        "can_delete": classification["can_delete"],
        "associations": serialized,
    }


def raw_asset_or_404(
    db: Session,
    business_id: int,
    asset_id: int,
    *,
    for_update: bool = False,
    active_only: bool = False,
) -> InstagramRawAsset:
    require_service_enabled(db, business_id)
    query = db.query(InstagramRawAsset).filter(
        InstagramRawAsset.id == asset_id,
        InstagramRawAsset.business_id == business_id,
        InstagramRawAsset.source_kind == "business_upload",
    )
    if active_only:
        query = query.filter(InstagramRawAsset.active.is_(True))
    if for_update:
        query = query.with_for_update()
    asset = query.first()
    if asset is None:
        raise HTTPException(status_code=404, detail="Material bruto no encontrado.")
    return asset


def _require_mutable_source_content(content: InstagramContent) -> None:
    if content.status not in {"draft", "changes_requested"}:
        raise HTTPException(
            status_code=409,
            detail=(
                "El material de origen solo puede cambiarse en borradores o contenidos con "
                "cambios solicitados."
            ),
        )


def associate_raw_asset(
    db: Session,
    *,
    business_id: int,
    content_id: int,
    asset_id: int,
    actor: User,
) -> tuple[InstagramContent, InstagramRawAsset, InstagramContentRawAsset, bool]:
    content = content_or_404(db, business_id, content_id, for_update=True)
    _require_mutable_source_content(content)
    existing = (
        db.query(InstagramContentRawAsset)
        .filter(
            InstagramContentRawAsset.business_id == business_id,
            InstagramContentRawAsset.content_id == content_id,
            InstagramContentRawAsset.raw_asset_id == asset_id,
        )
        .first()
    )
    if existing is not None:
        asset = raw_asset_or_404(db, business_id, asset_id, for_update=True)
        if asset.storage_deleted_at is not None:
            raise HTTPException(status_code=410, detail="El archivo original ya fue purgado.")
        return content, asset, existing, False
    asset = raw_asset_or_404(db, business_id, asset_id, for_update=True, active_only=True)
    link = InstagramContentRawAsset(
        business_id=business_id,
        content_id=content_id,
        raw_asset_id=asset_id,
        associated_by_user_id=actor.id,
    )
    db.add(link)
    db.flush()
    return content, asset, link, True


def disassociate_raw_asset(
    db: Session,
    *,
    business_id: int,
    content_id: int,
    asset_id: int,
) -> tuple[InstagramContent, InstagramRawAsset]:
    content = content_dependency_or_404(db, business_id, content_id, for_update=True)
    asset = raw_asset_or_404(db, business_id, asset_id, for_update=True)
    classification = classify_raw_asset_dependencies(db, business_id=business_id, asset_id=asset_id)
    association = next(
        (item for item in classification["associations"] if item["content_id"] == content_id),
        None,
    )
    if association is not None and association["current_physical_dependency"]:
        raise HTTPException(
            status_code=409,
            detail="Este material todavía se utiliza para preparar la versión actual.",
        )
    link = (
        db.query(InstagramContentRawAsset)
        .filter(
            InstagramContentRawAsset.business_id == business_id,
            InstagramContentRawAsset.content_id == content_id,
            InstagramContentRawAsset.raw_asset_id == asset_id,
        )
        .first()
    )
    if link is None:
        raise HTTPException(status_code=404, detail="La asociación no existe.")
    db.delete(link)
    db.flush()
    return content, asset


def disassociate_permitted_raw_asset_associations(
    db: Session,
    *,
    business_id: int,
    asset_id: int,
) -> list[int]:
    manager = raw_asset_association_manager(
        db,
        business_id=business_id,
        asset_id=asset_id,
        for_update=True,
    )
    content_ids = [
        association["content_id"]
        for association in manager["associations"]
        if association["can_disassociate"]
    ]
    if not content_ids:
        return []
    links = (
        db.query(InstagramContentRawAsset)
        .filter(
            InstagramContentRawAsset.business_id == business_id,
            InstagramContentRawAsset.raw_asset_id == asset_id,
            InstagramContentRawAsset.content_id.in_(content_ids),
        )
        .with_for_update()
        .all()
    )
    removed_content_ids = sorted(link.content_id for link in links)
    for link in links:
        db.delete(link)
    db.flush()
    return removed_content_ids


def prepare_raw_asset_as_final(
    db: Session,
    *,
    business_id: int,
    content_id: int,
    asset_id: int,
    actor: User,
) -> tuple[InstagramContent, InstagramRawAsset, InstagramFinalAsset | None, bool]:
    content, asset, _link, associated = associate_raw_asset(
        db,
        business_id=business_id,
        content_id=content_id,
        asset_id=asset_id,
        actor=actor,
    )
    existing = (
        db.query(InstagramFinalAsset)
        .filter(
            InstagramFinalAsset.business_id == business_id,
            InstagramFinalAsset.content_id == content_id,
            InstagramFinalAsset.source_raw_asset_id == asset_id,
        )
        .first()
    )
    return content, asset, existing, associated


def content_has_cross_content_asset_references(db: Session, content: InstagramContent) -> bool:
    asset_ids = [asset.id for asset in content.final_assets]
    if not asset_ids:
        return False
    return (
        db.query(InstagramContentVersionAsset.id)
        .join(
            InstagramContentVersion,
            InstagramContentVersion.id == InstagramContentVersionAsset.version_id,
        )
        .filter(
            InstagramContentVersionAsset.asset_id.in_(asset_ids),
            InstagramContentVersion.content_id != content.id,
        )
        .first()
        is not None
    )


def prepare_content_removal(
    db: Session,
    *,
    business_id: int,
    content_id: int,
    actor: User,
) -> dict:
    require_service_enabled(db, business_id)
    content = content_or_404(db, business_id, content_id, for_update=True)
    previous_status = content.status
    cancelled_job_id: int | None = None

    if previous_status != "published":
        from app.services.instagram_publish_service import cancel_publish_job

        cancelled_job = cancel_publish_job(
            db,
            content,
            reason="content_removed_by_owner",
            actor=actor,
        )
        if cancelled_job is not None:
            if cancelled_job.status != "cancelled":
                db.rollback()
                raise HTTPException(
                    status_code=409,
                    detail=(
                        "La publicación ya había comenzado. Revisa su resultado antes de retirar "
                        "el contenido."
                    ),
                )
            cancelled_job_id = cancelled_job.id

    has_publish_history = (
        db.query(InstagramPublishJob.id)
        .filter(
            InstagramPublishJob.business_id == business_id,
            InstagramPublishJob.content_item_id == content.id,
        )
        .first()
        is not None
    )
    has_cross_references = content_has_cross_content_asset_references(db, content)
    must_archive = (
        previous_status in {"scheduled", "published"} or has_publish_history or has_cross_references
    )

    storage_keys: list[str] = []
    if must_archive:
        content.archived_at = utc_now()
        if previous_status != "published":
            content.status = "cancelled"
        db.flush()
        disposition = "archived"
    else:
        storage_keys = [asset.storage_key for asset in content.final_assets]
        db.delete(content)
        db.flush()
        disposition = "deleted"

    return {
        "id": content_id,
        "disposition": disposition,
        "previous_status": previous_status,
        "cancelled_job_id": cancelled_job_id,
        "storage_keys": storage_keys,
        "shared_asset_references": has_cross_references,
    }


def prepare_raw_asset_retirement(
    db: Session, *, business_id: int, asset_id: int, actor_user_id: int
) -> dict:
    require_service_enabled(db, business_id)
    classification = classify_raw_asset_dependencies(
        db,
        business_id=business_id,
        asset_id=asset_id,
        for_update=True,
    )
    asset = classification["asset"]
    retired = asset.active
    if retired:
        asset.active = False
        asset.removed_at = utc_now()
        asset.removed_by_user_id = actor_user_id
    purged = bool(classification["can_purge_storage"])
    storage_keys: list[str] = []
    if purged:
        asset.storage_deleted_at = utc_now()
        storage_keys.append(asset.storage_key)
    db.flush()
    return {
        "id": asset.id,
        "retired": retired,
        "purged": purged,
        "storage_keys": storage_keys,
        "has_current_physical_dependency": classification["has_current_physical_dependency"],
    }


def prepare_raw_asset_storage_purge(db: Session, *, business_id: int, asset_id: int) -> dict:
    require_service_enabled(db, business_id)
    classification = classify_raw_asset_dependencies(
        db,
        business_id=business_id,
        asset_id=asset_id,
        for_update=True,
    )
    asset = classification["asset"]
    if asset.active:
        raise HTTPException(
            status_code=409,
            detail="Retira primero el material de la biblioteca.",
        )
    if asset.storage_deleted_at is not None:
        return {"id": asset.id, "purged": False, "storage_keys": []}
    if not classification["can_purge_storage"]:
        raise HTTPException(
            status_code=409,
            detail="La versión actual todavía necesita el archivo original.",
        )
    asset.storage_deleted_at = utc_now()
    db.flush()
    return {"id": asset.id, "purged": True, "storage_keys": [asset.storage_key]}


def prepare_raw_asset_removal(db: Session, *, business_id: int, asset_id: int) -> dict:
    require_service_enabled(db, business_id)
    classification = classify_raw_asset_dependencies(
        db,
        business_id=business_id,
        asset_id=asset_id,
        for_update=True,
    )
    asset = classification["asset"]
    if not classification["can_delete"]:
        manager = raw_asset_association_manager(db, business_id=business_id, asset_id=asset_id)
        detail = {
            "code": "raw_asset_in_use",
            "message": (
                "Este material conserva dependencias. Retíralo de la biblioteca para mantener "
                "la trazabilidad."
            ),
            **manager,
        }
        raise HTTPException(
            status_code=409,
            detail=detail,
        )
    storage_keys = [] if asset.storage_deleted_at is not None else [asset.storage_key]
    db.delete(asset)
    db.flush()
    return {"id": asset_id, "storage_keys": storage_keys}


def serialize_settings(settings: InstagramContentSettings) -> dict:
    return {
        "business_id": settings.business_id,
        "enabled": settings.enabled,
        "owner_can_validate_instagram_content": (settings.owner_can_validate_instagram_content),
        "publishing_mode": get_settings().instagram_publishing_mode,
        "updated_at": settings.updated_at.isoformat() if settings.updated_at else None,
    }


def serialize_raw_asset(
    asset: InstagramRawAsset,
    api_prefix: str,
    *,
    include_associations: bool = True,
) -> dict:
    payload = {
        "id": asset.id,
        "source_kind": asset.source_kind,
        "origin": (
            "instagram"
            if asset.source_kind == "instagram"
            else "autonogrow_admin"
            if asset.uploaded_by is not None and asset.uploaded_by.is_owner
            else "business_owner"
        ),
        "original_filename": asset.original_filename,
        "media_type": asset.media_type,
        "size_bytes": asset.size_bytes,
        "label": asset.label,
        "active": asset.active,
        "removed_at": asset.removed_at.isoformat() if asset.removed_at else None,
        "removed_by_user_id": asset.removed_by_user_id,
        "storage_deleted_at": (
            asset.storage_deleted_at.isoformat() if asset.storage_deleted_at else None
        ),
        "storage_available": asset.storage_deleted_at is None,
        "created_at": asset.created_at.isoformat(),
    }
    if asset.storage_deleted_at is None:
        payload.update(
            {
                "file_url": f"{api_prefix}/raw-assets/{asset.id}/file",
                "preview_url": f"{api_prefix}/raw-assets/{asset.id}/file",
                "download_url": f"{api_prefix}/raw-assets/{asset.id}/download",
            }
        )
    else:
        payload.update({"file_url": None, "preview_url": None, "download_url": None})
    if include_associations:
        payload["associations"] = [
            {
                "content_id": link.content_id,
                "content_title": link.content.title,
                "content_status": link.content.status,
                "content_archived": link.content.archived_at is not None,
                "associated_by_user_id": link.associated_by_user_id,
                "created_at": link.created_at.isoformat(),
            }
            for link in sorted(asset.content_links, key=lambda item: item.created_at)
        ]
    return payload


def serialize_final_asset(asset: InstagramFinalAsset, api_prefix: str) -> dict:
    source = asset.source_raw_asset
    return {
        "id": asset.id,
        "original_filename": asset.original_filename,
        "media_type": asset.media_type,
        "size_bytes": asset.size_bytes,
        "created_at": asset.created_at.isoformat(),
        "source_raw_asset_id": asset.source_raw_asset_id,
        "source_raw_asset": (
            {
                "id": source.id,
                "original_filename": source.original_filename,
                "sha256": source.sha256,
                "source_kind": source.source_kind,
                "active": source.active,
                "removed": not source.active,
                "storage_available": source.storage_deleted_at is None,
                "display_status": (
                    "Material original retirado" if not source.active else "Material original"
                ),
            }
            if source is not None
            else None
        ),
        "file_url": f"{api_prefix}/contents/{asset.content_id}/final-assets/{asset.id}/file",
    }


def serialize_validation(validation: InstagramContentValidation) -> dict:
    return {
        "id": validation.id,
        "version_id": validation.version_id,
        "validated_by_user_id": validation.validated_by_user_id,
        "validator_role": validation.validator_role,
        "validated_at": validation.validated_at.isoformat(),
        "invalidated_at": (
            validation.invalidated_at.isoformat() if validation.invalidated_at else None
        ),
        "invalidation_reason": validation.invalidation_reason,
        "approved_asset_ids": [
            link.asset_id
            for link in sorted(validation.version.asset_links, key=lambda item: item.position)
        ],
    }


def serialize_version(version: InstagramContentVersion, api_prefix: str) -> dict:
    import json

    links = sorted(version.asset_links, key=lambda item: item.position)
    return {
        "id": version.id,
        "version_number": version.version_number,
        "caption": version.caption,
        "format": version.format,
        "editorial_package": (
            json.loads(version.editorial_package_json) if version.editorial_package_json else None
        ),
        "generation_source": version.generation_source,
        "generator_version": version.generator_version,
        "promotion_revision": (
            {
                "id": version.promotion_revision.id,
                "revision_number": version.promotion_revision.revision_number,
                "status": (
                    "business_approved"
                    if version.promotion_revision.status == "owner_approved"
                    else "business_rejected"
                    if version.promotion_revision.status == "owner_rejected"
                    else version.promotion_revision.status
                ),
                "discount_type": version.promotion_revision.discount_type,
                "discount_value": str(version.promotion_revision.discount_value),
                "regular_price": str(version.promotion_revision.regular_price),
                "promotional_price": str(version.promotion_revision.promotional_price),
                "currency": version.promotion_revision.currency,
                "valid_from": version.promotion_revision.valid_from.isoformat(),
                "valid_until": version.promotion_revision.valid_until.isoformat(),
                "days": json.loads(version.promotion_revision.days_json),
                "scope": version.promotion_revision.scope,
            }
            if version.promotion_revision
            else None
        ),
        "story_transform": (
            json.loads(version.story_transform_json) if version.story_transform_json else None
        ),
        "story_renderer_version": version.story_renderer_version,
        "created_by_user_id": version.created_by_user_id,
        "created_at": version.created_at.isoformat(),
        "assets": [
            {
                **serialize_final_asset(link.asset, api_prefix),
                "position": link.position,
                "is_cover": link.is_cover,
            }
            for link in links
        ],
        "validation": serialize_validation(version.validation) if version.validation else None,
        "editorial_review": (
            {
                "id": version.editorial_review.id,
                "status": version.editorial_review.status,
                "submitted_at": version.editorial_review.submitted_at.isoformat(),
                "reviewed_at": (
                    version.editorial_review.reviewed_at.isoformat()
                    if version.editorial_review.reviewed_at
                    else None
                ),
                "note": version.editorial_review.note,
            }
            if version.editorial_review
            else None
        ),
    }


def serialize_comment(comment: InstagramContentComment) -> dict:
    return {
        "id": comment.id,
        "version_id": comment.version_id,
        "author_user_id": comment.author_user_id,
        "kind": comment.kind,
        "body": comment.body,
        "created_at": comment.created_at.isoformat(),
    }


def serialize_content(
    db: Session,
    content: InstagramContent,
    api_prefix: str,
    *,
    detailed: bool = False,
    owner_technical: bool = True,
) -> dict:
    version = current_version(db, content)
    published_remote = (
        db.query(InstagramRemoteMedia)
        .filter(
            InstagramRemoteMedia.business_id == content.business_id,
            InstagramRemoteMedia.internal_content_id == content.id,
            InstagramRemoteMedia.parent_id.is_(None),
        )
        .order_by(InstagramRemoteMedia.id.desc())
        .first()
    )
    source_remote = next(
        (
            link.asset.source_raw_asset.source_remote_media
            for link in sorted(version.asset_links, key=lambda item: item.position)
            if link.asset.source_raw_asset is not None
            and link.asset.source_raw_asset.source_remote_media is not None
        ),
        None,
    )
    publication_hold = active_publication_hold(db, content)
    payload = {
        "id": content.id,
        "business_id": content.business_id,
        "business_timezone": (
            content.business.timezone.strip() or get_settings().instagram_default_timezone
        ),
        "title": content.title,
        "source_proposal_id": content.source_proposal_id,
        "status": content.status,
        "planned_publish_at": (
            content.planned_publish_at.isoformat() if content.planned_publish_at else None
        ),
        "current_version": serialize_version(version, api_prefix),
        "created_at": content.created_at.isoformat(),
        "updated_at": content.updated_at.isoformat(),
        "publication_hold": (
            {
                "id": publication_hold.id,
                "reason": publication_hold.reason,
                "held_by_user_id": publication_hold.held_by_user_id,
                "held_at": publication_hold.held_at.isoformat(),
            }
            if publication_hold
            else None
        ),
        "instagram_remote": (
            {
                "id": published_remote.id,
                "remote_status": published_remote.remote_status,
                "last_checked_at": published_remote.last_checked_at.isoformat()
                if published_remote.last_checked_at
                else None,
                "unavailable_at": published_remote.unavailable_at.isoformat()
                if published_remote.unavailable_at
                else None,
            }
            if published_remote
            else None
        ),
        "source_instagram_media": (
            {
                "id": source_remote.id,
                "origin": source_remote.origin,
                "remote_status": source_remote.remote_status,
                "source_internal_content_id": source_remote.internal_content_id,
            }
            if source_remote
            else None
        ),
    }
    if detailed:
        payload["versions"] = [serialize_version(item, api_prefix) for item in content.versions]
        payload["comments"] = [serialize_comment(item) for item in content.comments]
        referenced_versions: dict[int, list[int]] = {}
        for historical_version in content.versions:
            for raw_asset_id in _package_raw_asset_ids(historical_version.editorial_package_json):
                referenced_versions.setdefault(raw_asset_id, []).append(
                    historical_version.version_number
                )
        historical_assets = (
            db.query(InstagramRawAsset)
            .filter(
                InstagramRawAsset.business_id == content.business_id,
                InstagramRawAsset.id.in_(referenced_versions),
            )
            .all()
            if referenced_versions
            else []
        )
        payload["raw_asset_history"] = [
            {
                "id": asset.id,
                "original_filename": asset.original_filename,
                "sha256": asset.sha256,
                "source_kind": asset.source_kind,
                "version_numbers": sorted(referenced_versions[asset.id]),
                "active": asset.active,
                "removed": not asset.active,
                "storage_available": asset.storage_deleted_at is None,
                "display_status": (
                    "Material original retirado" if not asset.active else "Material original"
                ),
                "preview_url": (
                    f"{api_prefix}/raw-assets/{asset.id}/file"
                    if asset.storage_deleted_at is None and asset.source_kind == "business_upload"
                    else None
                ),
            }
            for asset in sorted(historical_assets, key=lambda item: item.id)
        ]
        payload["publication_hold_history"] = [
            {
                "id": item.id,
                "reason": item.reason,
                "held_by_user_id": item.held_by_user_id,
                "held_at": item.held_at.isoformat(),
                "released_by_user_id": item.released_by_user_id,
                "released_at": item.released_at.isoformat() if item.released_at else None,
                "release_note": item.release_note,
            }
            for item in content.publication_holds
        ]
        payload["final_assets"] = [
            serialize_final_asset(item, api_prefix) for item in content.final_assets
        ]
        payload["source_assets"] = [
            {
                **serialize_raw_asset(
                    link.raw_asset,
                    api_prefix,
                    include_associations=False,
                ),
                "association_created_at": link.created_at.isoformat(),
            }
            for link in sorted(content.source_asset_links, key=lambda item: item.created_at)
            if link.raw_asset.source_kind == "business_upload"
        ]
        from app.services.instagram_publish_service import (
            publication_history_events,
            serialize_publish_job,
        )

        payload["publish_jobs"] = [
            serialize_publish_job(item, owner_technical=owner_technical)
            for item in sorted(content.publish_jobs, key=lambda item: item.created_at, reverse=True)
        ]
        payload["publication_events"] = publication_history_events(
            db,
            content.business_id,
            content.id,
            owner_technical=owner_technical,
        )
    return payload
