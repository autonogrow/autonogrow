import json
from datetime import datetime, timezone

from fastapi import HTTPException
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.models import (
    InstagramContent,
    InstagramContentComment,
    InstagramContentRawAsset,
    InstagramContentSettings,
    InstagramContentValidation,
    InstagramContentVersion,
    InstagramContentVersionAsset,
    InstagramFinalAsset,
    InstagramPublishJob,
    InstagramRawAsset,
    User,
)


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
    changed = (
        previous.caption != caption
        or previous.format != format
        or previous_ids != asset_ids
        or previous_cover != normalized_cover
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
    if version.format == "carousel" and asset_count < 2:
        raise HTTPException(status_code=409, detail="carousel requires at least two final assets")
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
        if content.status != "ready_for_review":
            raise HTTPException(status_code=409, detail="Content is not in review")
        invalidate_validation(db, content, "changes_requested_by_admin")
        from app.services.instagram_publish_service import cancel_publish_job

        cancel_publish_job(db, content, reason="validation_revoked_by_change_request", actor=actor)
        content.status = "changes_requested"
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
    if content.status != "validated" or _active_validation(db, content) is None:
        raise HTTPException(status_code=409, detail="Only validated content can be scheduled")
    if content.planned_publish_at is None:
        raise HTTPException(status_code=409, detail="A planned date is required")
    from app.services.instagram_publish_service import sync_publish_job

    job = sync_publish_job(db, content, actor=actor)
    if job.status != "queued":
        raise HTTPException(
            status_code=409, detail=job.safe_error_message or "Publishing requires action"
        )
    return content


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
        return "instagram_raw_asset" in package_json and str(asset_id) in package_json
    recommended = package.get("asset_plan", {}).get("recommended", [])
    return any(
        isinstance(item, dict)
        and item.get("source") == "instagram_raw_asset"
        and item.get("id") == asset_id
        for item in recommended
    )


def raw_asset_reference_content_ids(db: Session, business_id: int, asset_id: int) -> list[int]:
    linked_content_ids = {
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
    rows = (
        db.query(InstagramContentVersion.content_id, InstagramContentVersion.editorial_package_json)
        .filter(
            InstagramContentVersion.business_id == business_id,
            InstagramContentVersion.editorial_package_json.is_not(None),
        )
        .all()
    )
    historical_content_ids = {
        content_id
        for content_id, package_json in rows
        if _package_references_raw_asset(package_json, asset_id)
    }
    return sorted(linked_content_ids | final_content_ids | historical_content_ids)


def raw_asset_or_404(
    db: Session,
    business_id: int,
    asset_id: int,
    *,
    for_update: bool = False,
) -> InstagramRawAsset:
    require_service_enabled(db, business_id)
    query = db.query(InstagramRawAsset).filter(
        InstagramRawAsset.id == asset_id,
        InstagramRawAsset.business_id == business_id,
    )
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
    asset = raw_asset_or_404(db, business_id, asset_id, for_update=True)
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
        return content, asset, existing, False
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
    content = content_or_404(db, business_id, content_id, for_update=True)
    _require_mutable_source_content(content)
    asset = raw_asset_or_404(db, business_id, asset_id, for_update=True)
    if (
        db.query(InstagramFinalAsset.id)
        .filter(
            InstagramFinalAsset.business_id == business_id,
            InstagramFinalAsset.content_id == content_id,
            InstagramFinalAsset.source_raw_asset_id == asset_id,
        )
        .first()
        is not None
    ):
        raise HTTPException(
            status_code=409,
            detail="Este material es el origen de un asset final y debe conservar su trazabilidad.",
        )
    if any(
        _package_references_raw_asset(version.editorial_package_json, asset_id)
        for version in content.versions
    ):
        raise HTTPException(
            status_code=409,
            detail="Este material forma parte de una versión editorial histórica.",
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
        previous_status in {"scheduled", "published"}
        or has_publish_history
        or has_cross_references
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


def prepare_raw_asset_removal(db: Session, *, business_id: int, asset_id: int) -> dict:
    require_service_enabled(db, business_id)
    asset = raw_asset_or_404(db, business_id, asset_id, for_update=True)
    references = raw_asset_reference_content_ids(db, business_id, asset_id)
    if references:
        raise HTTPException(
            status_code=409,
            detail="Este material está siendo utilizado por contenido editorial y no puede borrarse.",
        )
    storage_key = asset.storage_key
    db.delete(asset)
    db.flush()
    return {"id": asset_id, "storage_keys": [storage_key]}


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
        "original_filename": asset.original_filename,
        "media_type": asset.media_type,
        "size_bytes": asset.size_bytes,
        "label": asset.label,
        "created_at": asset.created_at.isoformat(),
        "file_url": f"{api_prefix}/raw-assets/{asset.id}/file",
        "preview_url": f"{api_prefix}/raw-assets/{asset.id}/file",
        "download_url": f"{api_prefix}/raw-assets/{asset.id}/download",
    }
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
    return {
        "id": asset.id,
        "original_filename": asset.original_filename,
        "media_type": asset.media_type,
        "size_bytes": asset.size_bytes,
        "created_at": asset.created_at.isoformat(),
        "source_raw_asset_id": asset.source_raw_asset_id,
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
    }
    if detailed:
        payload["versions"] = [serialize_version(item, api_prefix) for item in content.versions]
        payload["comments"] = [serialize_comment(item) for item in content.comments]
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
