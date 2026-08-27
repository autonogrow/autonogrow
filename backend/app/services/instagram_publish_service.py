from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation
from pathlib import Path
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from fastapi import HTTPException
from sqlalchemy import Select, and_, func, or_, select
from sqlalchemy.orm import Session

from app.core.audit import record_audit
from app.core.config import Settings, get_settings
from app.models import (
    AuditLog,
    BusinessChannelControl,
    BusinessChannelIntegration,
    InstagramContent,
    InstagramContentEditorialReview,
    InstagramContentPublicationHold,
    InstagramContentSettings,
    InstagramContentValidation,
    InstagramContentVersion,
    InstagramPublishJob,
    SocialPromotionRevision,
    User,
)
from app.services.instagram_asset_url_service import resolve_private_asset_path
from app.services.instagram_image_validation import (
    validate_instagram_caption,
    validate_instagram_image,
    validate_instagram_story_image,
)
from app.services.instagram_login_provider import INSTAGRAM_CONTENT_PUBLISH_SCOPE
from app.services.instagram_publishing_adapter import (
    InstagramPublishingError,
    PublishingValidationError,
)

ACTIVE_JOB_STATUSES = {
    "queued",
    "claimed",
    "creating_container",
    "publishing",
    "simulating_publish",
    "retry_wait",
}
EXECUTING_JOB_STATUSES = {
    "claimed",
    "creating_container",
    "publishing",
    "simulating_publish",
    "retry_wait",
}
BLOCKING_HEALTH = {"action_required", "revoked", "suspended", "error"}
UNCERTAIN_PROVIDER_STATUSES = {
    "unknown_result",
    "unknown_after_claim_expiry",
    "outcome_requires_review",
}


@dataclass(frozen=True)
class InstagramPublicationPreflight:
    ok: bool
    code: str | None
    safe_message: str | None
    integration: BusinessChannelIntegration | None


def _granted_scopes(raw: str | None) -> set[str]:
    try:
        values = json.loads(raw or "[]")
    except (TypeError, ValueError):
        return set()
    return {value for value in values if isinstance(value, str)} if isinstance(values, list) else set()


def _validate_instagram_reel_asset(
    asset,
    path: Path,
    config: Settings,
) -> None:
    if asset.media_type != "video/mp4":
        raise PublishingValidationError(
            "instagram_reel_type_unsupported",
            "Instagram Reel publication requires an MP4 video",
        )

    if not path.is_file():
        raise PublishingValidationError(
            "instagram_reel_file_missing",
            "Instagram Reel video file is unavailable",
        )

    try:
        size_bytes = path.stat().st_size
    except OSError as exc:
        raise PublishingValidationError(
            "instagram_reel_file_unavailable",
            "Instagram Reel video file is unavailable",
        ) from exc

    max_bytes = config.instagram_video_upload_max_size_mb * 1024 * 1024

    if size_bytes <= 0 or size_bytes > max_bytes:
        raise PublishingValidationError(
            "instagram_reel_size_invalid",
            "Instagram Reel video does not meet the configured size limit",
        )

    if asset.size_bytes != size_bytes:
        raise PublishingValidationError(
            "instagram_reel_size_mismatch",
            "Instagram Reel video integrity check failed",
        )

    digest = hashlib.sha256()

    try:
        with path.open("rb") as stream:
            header = stream.read(12)

            if len(header) < 12 or header[4:8] != b"ftyp":
                raise PublishingValidationError(
                    "instagram_reel_content_invalid",
                    "Instagram Reel asset is not a valid MP4 container",
                )

            digest.update(header)

            while True:
                chunk = stream.read(1024 * 1024)
                if not chunk:
                    break
                digest.update(chunk)

    except PublishingValidationError:
        raise
    except OSError as exc:
        raise PublishingValidationError(
            "instagram_reel_file_unavailable",
            "Instagram Reel video file is unavailable",
        ) from exc

    if not asset.sha256 or asset.sha256 != digest.hexdigest():
        raise PublishingValidationError(
            "instagram_reel_hash_mismatch",
            "Instagram Reel video integrity check failed",
        )


def publication_preflight(  # noqa: C901
    db: Session,
    content: InstagramContent,
    *,
    version: InstagramContentVersion | None = None,
    settings: Settings | None = None,
    validate_files: bool = False,
    publication_at: datetime | None = None,
) -> InstagramPublicationPreflight:
    """Return the shared, side-effect-free gate used by scheduling and workers."""
    config = settings or get_settings()
    current = version or _current_version(db, content)
    if current is None:
        return InstagramPublicationPreflight(False, "publish_version_missing", "Content has no version", None)
    latest = _current_version(db, content)
    if latest is None or latest.id != current.id:
        return InstagramPublicationPreflight(False, "publish_version_is_not_current", "Only the current version can be published", None)
    if content.status in {"cancelled", "published"}:
        return InstagramPublicationPreflight(
            False,
            "publish_content_not_active",
            "Content is no longer available for publication",
            None,
        )
    hold = (
        db.query(InstagramContentPublicationHold.id)
        .filter(
            InstagramContentPublicationHold.business_id == content.business_id,
            InstagramContentPublicationHold.content_id == content.id,
            InstagramContentPublicationHold.released_at.is_(None),
        )
        .first()
    )
    if hold is not None:
        return InstagramPublicationPreflight(
            False,
            "publish_business_hold_active",
            "Publication is stopped by the business",
            None,
        )
    review_blocker = (
        db.query(InstagramContentEditorialReview.status)
        .filter(
            InstagramContentEditorialReview.business_id == content.business_id,
            InstagramContentEditorialReview.content_id == content.id,
            InstagramContentEditorialReview.version_id == current.id,
            InstagramContentEditorialReview.status.in_({"changes_requested", "rejected"}),
        )
        .first()
    )
    if review_blocker is not None:
        return InstagramPublicationPreflight(
            False,
            "publish_business_review_blocking",
            "The business requested changes to the current version",
            None,
        )
    promotion_error = promotion_preflight(db, current, publication_at)
    if promotion_error is not None:
        return InstagramPublicationPreflight(False, *promotion_error, None)
    service = db.get(InstagramContentSettings, content.business_id)
    if service is None or not service.enabled:
        return InstagramPublicationPreflight(False, "instagram_content_service_disabled", "Instagram content service is disabled", None)
    if _active_validation(db, content, current.id) is None:
        return InstagramPublicationPreflight(False, "publish_validation_revoked", "Current version is not approved", None)
    integration, issue = integration_eligibility(db, content.business_id)
    if issue or integration is None:
        return InstagramPublicationPreflight(False, issue or "instagram_integration_missing", "Instagram integration requires attention", integration)
    links = sorted(current.asset_links, key=lambda item: item.position)
    if not links:
        return InstagramPublicationPreflight(False, "publish_assets_missing", "Approved version has no final assets", integration)
    if any(link.asset.business_id != content.business_id or link.asset.content_id != content.id for link in links):
        return InstagramPublicationPreflight(False, "publish_asset_scope_mismatch", "A final asset does not belong to this content", integration)
    if current.format == "single_image" and len(links) != 1:
        return InstagramPublicationPreflight(False, "publish_assets_do_not_match_format", "single_image requires one final asset", integration)
    if current.format == "carousel" and len(links) < 2:
        return InstagramPublicationPreflight(False, "publish_assets_do_not_match_format", "carousel requires at least two final assets", integration)
    if current.format == "carousel" and len(links) > 10:
        return InstagramPublicationPreflight(
            False,
            "publish_assets_do_not_match_format",
            "carousel supports at most ten final assets",
            integration,
        )
    if current.format == "reel" and len(links) != 1:
        return InstagramPublicationPreflight(
            False,
            "publish_assets_do_not_match_format",
            "reel requires one final video asset",
            integration,
        )
    if current.format == "story" and len(links) != 1:
        return InstagramPublicationPreflight(
            False,
            "publish_assets_do_not_match_format",
            "story requires one final image or video asset",
            integration,
        )
    if config.instagram_publishing_mode == "meta":
        supported_format = (
            current.format == "single_image"
            and len(links) == 1
        ) or (
            current.format == "carousel"
            and 2 <= len(links) <= 10
        ) or (
            current.format == "reel"
            and len(links) == 1
        ) or (
            current.format == "story"
            and len(links) == 1
            and links[0].asset.media_type in {"image/jpeg", "video/mp4"}
        )
        if not supported_format:
            return InstagramPublicationPreflight(
                False,
                "publishing_not_supported_yet",
                "Real publishing currently supports one JPEG image, a carousel of 2 to 10 JPEG images, one MP4 Reel, or one JPEG/MP4 Story",
                integration,
            )
        if not integration.encrypted_access_token or not integration.encryption_key_version:
            return InstagramPublicationPreflight(False, "instagram_credentials_missing", "Instagram needs to be reconnected", integration)
        token_expires_at = as_utc(integration.token_expires_at)
        if token_expires_at is not None and token_expires_at <= utc_now():
            return InstagramPublicationPreflight(
                False,
                "instagram_token_expired",
                "Instagram access has expired; reconnect the account",
                integration,
            )
        if INSTAGRAM_CONTENT_PUBLISH_SCOPE not in _granted_scopes(integration.granted_scopes_json):
            return InstagramPublicationPreflight(False, "instagram_publish_scope_missing", "Instagram publishing permission is missing; reconnect the account", integration)
        if not integration.external_account_id.strip():
            return InstagramPublicationPreflight(False, "instagram_professional_account_missing", "Instagram professional account identifier is missing", integration)
        if validate_files:
            try:
                validate_instagram_caption(current.caption)
                root_setting = config.uploads_dir.strip()
                from app.core.config import get_backend_dir

                root = Path(root_setting) if root_setting else get_backend_dir() / "uploads"
                root = (root if root.is_absolute() else get_backend_dir() / root).resolve()
                for link in links:
                    path = resolve_private_asset_path(
                        link.asset.storage_key,
                        root=root,
                    )
                    if current.format == "reel":
                        _validate_instagram_reel_asset(
                            link.asset,
                            path,
                            config,
                        )
                    elif current.format == "story" and link.asset.media_type == "video/mp4":
                        _validate_instagram_reel_asset(
                            link.asset,
                            path,
                            config,
                        )
                    elif current.format == "story":
                        validate_instagram_story_image(link.asset, path)
                    else:
                        validate_instagram_image(link.asset, path)
            except InstagramPublishingError as exc:
                return InstagramPublicationPreflight(False, exc.code, exc.safe_message, integration)
    return InstagramPublicationPreflight(True, None, None, integration)


def promotion_preflight(
    db: Session,
    version: InstagramContentVersion,
    publication_at: datetime | None,
) -> tuple[str, str] | None:
    try:
        package = json.loads(version.editorial_package_json or "{}")
    except (TypeError, json.JSONDecodeError):
        package = {}
    raw = package.get("promotion") if isinstance(package, dict) else None
    raw_id = raw.get("id") if isinstance(raw, dict) else None
    revision_id = version.promotion_revision_id or raw_id
    if revision_id is None:
        return None
    if not isinstance(revision_id, int):
        return (
            "publish_promotion_revision_missing",
            "Promotion approval is unavailable",
        )
    revision = version.promotion_revision
    if revision is None or revision.id != revision_id:
        revision = db.get(SocialPromotionRevision, revision_id)
    if revision is None or revision.status != "owner_approved":
        return (
            "publish_promotion_not_business_approved",
            "Promotion requires approval by the business",
        )
    if not isinstance(raw, dict) or not _promotion_payload_matches(raw, revision):
        return (
            "publish_promotion_terms_changed",
            "Promotion terms no longer match the approved revision",
        )
    if publication_at is None:
        return None
    value = as_utc(publication_at)
    start = as_utc(revision.valid_from)
    end = as_utc(revision.valid_until)
    if value is None or start is None or end is None or not start <= value <= end:
        return (
            "publish_promotion_outside_window",
            "Publication date is outside the approved promotion window",
        )
    try:
        days = json.loads(revision.days_json)
    except (TypeError, json.JSONDecodeError):
        days = []
    if days and value.weekday() not in days:
        return (
            "publish_promotion_day_not_approved",
            "Publication date does not match the approved promotion days",
        )
    return None


def _promotion_payload_matches(raw: dict, revision: SocialPromotionRevision) -> bool:
    try:
        numeric_matches = all(
            Decimal(str(raw.get(key))) == Decimal(str(expected))
            for key, expected in (
                ("discount_value", revision.discount_value),
                ("regular_price", revision.regular_price),
                ("promotional_price", revision.promotional_price),
            )
        )
    except (InvalidOperation, TypeError, ValueError):
        return False
    try:
        raw_days = sorted(set(int(item) for item in raw.get("days", [])))
        approved_days = sorted(set(int(item) for item in json.loads(revision.days_json)))
        raw_start = as_utc(datetime.fromisoformat(str(raw.get("valid_from"))))
        raw_end = as_utc(datetime.fromisoformat(str(raw.get("valid_until"))))
    except (TypeError, ValueError, json.JSONDecodeError):
        return False
    return (
        raw.get("id") == revision.id
        and raw.get("discount_type") == revision.discount_type
        and numeric_matches
        and str(raw.get("currency", "")).upper() == revision.currency.upper()
        and raw_start == as_utc(revision.valid_from)
        and raw_end == as_utc(revision.valid_until)
        and raw_days == approved_days
        and str(raw.get("scope", "")) == revision.scope
    )


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def as_utc(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    if value.tzinfo is None or value.utcoffset() is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def normalize_planned_datetime(value: datetime | None, timezone_name: str) -> datetime | None:
    if value is None:
        return None
    if value.tzinfo is not None and value.utcoffset() is not None:
        return value.astimezone(timezone.utc)
    try:
        zone = ZoneInfo(timezone_name)
    except (ZoneInfoNotFoundError, ValueError) as exc:
        raise HTTPException(status_code=422, detail="Business timezone is invalid") from exc
    valid: list[datetime] = []
    for fold in (0, 1):
        local = value.replace(tzinfo=zone, fold=fold)
        roundtrip = local.astimezone(timezone.utc).astimezone(zone).replace(tzinfo=None)
        if roundtrip == value:
            valid.append(local)
    if not valid:
        raise HTTPException(status_code=422, detail="Local date does not exist due to DST")
    if len(valid) == 2 and valid[0].utcoffset() != valid[1].utcoffset():
        raise HTTPException(status_code=422, detail="Ambiguous local date requires an UTC offset")
    return valid[0].astimezone(timezone.utc)


def stable_idempotency_key(business_id: int, content_id: int, version_id: int) -> str:
    return f"instagram-publish:{business_id}:{content_id}:{version_id}"


def integration_eligibility(
    db: Session, business_id: int
) -> tuple[BusinessChannelIntegration | None, str | None]:
    control = (
        db.query(BusinessChannelControl)
        .filter(
            BusinessChannelControl.business_id == business_id,
            BusinessChannelControl.channel == "instagram",
        )
        .first()
    )
    if control is None or control.status != "approved" or not control.integrated_delivery_enabled:
        return None, "instagram_delivery_not_approved"
    integration = (
        db.query(BusinessChannelIntegration)
        .filter(
            BusinessChannelIntegration.business_id == business_id,
            BusinessChannelIntegration.channel == "instagram",
            BusinessChannelIntegration.provider == "instagram",
        )
        .first()
    )
    if integration is None:
        return None, "instagram_integration_missing"
    if integration.integration_status not in {"connected", "degraded"}:
        return integration, "instagram_integration_unavailable"
    if integration.health_status in BLOCKING_HEALTH:
        return integration, "instagram_integration_health_blocking"
    return integration, None


def _current_version(db: Session, content: InstagramContent) -> InstagramContentVersion | None:
    return (
        db.query(InstagramContentVersion)
        .filter(
            InstagramContentVersion.business_id == content.business_id,
            InstagramContentVersion.content_id == content.id,
        )
        .order_by(InstagramContentVersion.version_number.desc())
        .first()
    )


def _active_validation(
    db: Session, content: InstagramContent, version_id: int
) -> InstagramContentValidation | None:
    return (
        db.query(InstagramContentValidation)
        .filter(
            InstagramContentValidation.business_id == content.business_id,
            InstagramContentValidation.content_id == content.id,
            InstagramContentValidation.version_id == version_id,
            InstagramContentValidation.invalidated_at.is_(None),
        )
        .first()
    )


def _audit_job(
    db: Session,
    job: InstagramPublishJob,
    action: str,
    metadata: dict | None = None,
    *,
    actor: User | None = None,
) -> None:
    record_audit(
        db,
        action=action,
        actor=actor,
        business_id=job.business_id,
        resource_type="instagram_publish_job",
        resource_id=job.id,
        metadata={
            "content_id": job.content_item_id,
            "version_id": job.content_version_id,
            **(metadata or {}),
        },
        commit=False,
    )


def _clear_claim(job: InstagramPublishJob) -> None:
    job.claimed_at = None
    job.claim_expires_at = None
    job.claimed_by = None


def sync_publish_job(
    db: Session,
    content: InstagramContent,
    *,
    actor: User | None = None,
    now: datetime | None = None,
    force_now: bool = False,
    settings: Settings | None = None,
) -> InstagramPublishJob:
    config = settings or get_settings()
    current = _current_version(db, content)
    if current is None:
        raise HTTPException(status_code=409, detail="Instagram content has no version")
    validation = _active_validation(db, content, current.id)
    if validation is None:
        raise HTTPException(status_code=409, detail="Current version is not validated")
    planned = as_utc(now) if force_now else as_utc(content.planned_publish_at)
    if planned is None:
        raise HTTPException(status_code=409, detail="A planned date is required")
    clock = as_utc(now) or utc_now()
    preflight = publication_preflight(
        db,
        content,
        version=current,
        settings=config,
        validate_files=config.instagram_publishing_mode == "meta",
        publication_at=planned,
    )
    integration = preflight.integration
    eligibility_error = preflight.code if not preflight.ok else None
    status = "queued"
    safe_error: str | None = None
    if not force_now and planned <= clock:
        status = "action_required"
        safe_error = "Planned date is in the past; choose a new future date"
    elif eligibility_error:
        status = "action_required"
        safe_error = preflight.safe_message or eligibility_error
    job = (
        db.query(InstagramPublishJob)
        .filter(
            InstagramPublishJob.business_id == content.business_id,
            InstagramPublishJob.content_item_id == content.id,
            InstagramPublishJob.content_version_id == current.id,
        )
        .with_for_update()
        .first()
    )
    if job is not None and job.status == "published":
        raise HTTPException(status_code=409, detail="This version has already been published")
    if job is not None and job.status == "failed":
        raise HTTPException(status_code=409, detail="Use the explicit retry action for failed jobs")
    if (
        job is not None
        and job.status == "action_required"
        and job.provider_status in UNCERTAIN_PROVIDER_STATUSES
    ):
        raise HTTPException(
            status_code=409, detail="Unknown publish outcomes require manual review"
        )
    if job is not None and job.status in EXECUTING_JOB_STATUSES:
        if force_now:
            return job
        raise HTTPException(
            status_code=409,
            detail="Publication is already in process and cannot be rescheduled",
        )
    created = job is None
    if job is None:
        job = InstagramPublishJob(
            business_id=content.business_id,
            content_item_id=content.id,
            content_version_id=current.id,
            integration_id=integration.id if integration else None,
            status=status,
            scheduled_for=planned,
            next_attempt_at=planned if status == "queued" else None,
            attempt_count=0,
            max_attempts=config.instagram_publishing_max_attempts,
            idempotency_key=stable_idempotency_key(content.business_id, content.id, current.id),
            created_by_user_id=actor.id if actor else None,
        )
        db.add(job)
        db.flush()
    else:
        job.integration_id = integration.id if integration else None
        job.status = status
        job.scheduled_for = planned
        job.next_attempt_at = planned if status == "queued" else None
        job.cancelled_at = None
        _clear_claim(job)
    job.safe_error_message = safe_error
    job.provider_error_code = (
        "planned_date_in_past" if not force_now and planned <= clock else eligibility_error
    )
    content.status = "scheduled" if status == "queued" else "validated"
    _audit_job(
        db,
        job,
        "publish_job_created" if created else "publish_job_rescheduled",
        {"scheduled_for": planned.isoformat(), "status": status, "publish_now": force_now},
        actor=actor,
    )
    db.flush()
    return job


def cancel_publish_job(
    db: Session,
    content: InstagramContent,
    *,
    reason: str,
    actor: User | None = None,
) -> InstagramPublishJob | None:
    job = (
        db.query(InstagramPublishJob)
        .filter(
            InstagramPublishJob.business_id == content.business_id,
            InstagramPublishJob.content_item_id == content.id,
            InstagramPublishJob.status.in_(ACTIVE_JOB_STATUSES),
        )
        .order_by(InstagramPublishJob.created_at.desc())
        .with_for_update()
        .first()
    )
    if job is None:
        return None
    if job.status in {"simulating_publish", "publishing"}:
        job.status = "action_required"
        job.provider_status = "outcome_requires_review"
        job.safe_error_message = "Publishing had started before cancellation"
        _clear_claim(job)
        action = "publish_action_required"
    else:
        job.status = "cancelled"
        job.cancelled_at = utc_now()
        job.safe_error_message = reason[:500]
        _clear_claim(job)
        action = "publish_job_cancelled"
    _audit_job(
        db,
        job,
        action,
        {"reason": reason, "actor_user_id": actor.id if actor else None},
        actor=actor,
    )
    db.flush()
    return job


def cancel_business_jobs(db: Session, business_id: int, reason: str, actor: User | None) -> int:
    contents = db.query(InstagramContent).filter(InstagramContent.business_id == business_id).all()
    affected = 0
    for item in contents:
        if cancel_publish_job(db, item, reason=reason, actor=actor) is not None:
            affected += 1
            if item.status == "scheduled":
                item.status = "validated"
    return affected


def retry_publish_job(
    db: Session, content: InstagramContent, actor: User, now: datetime | None = None
) -> InstagramPublishJob:
    job = (
        db.query(InstagramPublishJob)
        .filter(
            InstagramPublishJob.business_id == content.business_id,
            InstagramPublishJob.content_item_id == content.id,
        )
        .order_by(InstagramPublishJob.created_at.desc())
        .with_for_update()
        .first()
    )
    if job is None or job.status not in {"failed", "action_required", "retry_wait"}:
        raise HTTPException(status_code=409, detail="No recoverable publish job is available")
    if job.status == "failed" and job.provider_status != "attempts_exhausted":
        raise HTTPException(status_code=409, detail="Permanent publish failures cannot be retried")
    if job.provider_status in UNCERTAIN_PROVIDER_STATUSES:
        raise HTTPException(status_code=409, detail="Unknown publish outcomes cannot be retried")
    current = _current_version(db, content)
    if (
        current is None
        or current.id != job.content_version_id
        or _active_validation(db, content, current.id) is None
    ):
        raise HTTPException(status_code=409, detail="The job version is no longer validated")
    clock = as_utc(now) or utc_now()
    preflight = publication_preflight(
        db,
        content,
        version=current,
        validate_files=get_settings().instagram_publishing_mode == "meta",
        publication_at=clock,
    )
    integration = preflight.integration
    if not preflight.ok:
        raise HTTPException(
            status_code=409,
            detail=preflight.safe_message or "Instagram integration requires action",
        )
    job.integration_id = integration.id if integration else None
    job.status = "queued"
    job.scheduled_for = clock
    job.next_attempt_at = clock
    job.provider_error_code = None
    job.safe_error_message = None
    if job.attempt_count >= job.max_attempts:
        job.max_attempts = job.attempt_count + get_settings().instagram_publishing_max_attempts
    _clear_claim(job)
    content.status = "scheduled"
    _audit_job(
        db,
        job,
        "publish_retry_requested",
        {"actor_user_id": actor.id},
        actor=actor,
    )
    db.flush()
    return job


def claim_publish_jobs(
    db: Session,
    *,
    worker_id: str,
    limit: int,
    claim_ttl_seconds: int,
    now: datetime | None = None,
) -> list[InstagramPublishJob]:
    clock = as_utc(now) or utc_now()
    expired_executing = (
        db.query(InstagramPublishJob)
        .filter(
            or_(
                InstagramPublishJob.status == "simulating_publish",
                and_(
                    InstagramPublishJob.status == "publishing",
                    InstagramPublishJob.provider_media_id.is_(None),
                    or_(
                        InstagramPublishJob.provider_status.is_(None),
                        InstagramPublishJob.provider_status != "container_created",
                    ),
                ),
            ),
            InstagramPublishJob.claim_expires_at <= clock,
        )
        .with_for_update()
        .all()
    )
    for job in expired_executing:
        job.status = "action_required"
        job.provider_status = "unknown_after_claim_expiry"
        job.safe_error_message = "Execution claim expired after publishing started"
        _clear_claim(job)
        _audit_job(db, job, "publish_action_required", {"reason": "expired_executing_claim"})
    statement = build_publish_claim_statement(
        clock=clock, limit=limit, dialect_name=db.get_bind().dialect.name
    )
    jobs = list(db.scalars(statement).all())
    for job in jobs:
        was_expired = job.status in {"claimed", "creating_container", "publishing"}
        job.status = "claimed"
        job.claimed_at = clock
        job.claim_expires_at = clock + timedelta(seconds=claim_ttl_seconds)
        job.claimed_by = worker_id[:200]
        job.attempt_count += 1
        if was_expired:
            _audit_job(db, job, "publish_expired_claim_recovered")
        _audit_job(
            db, job, "publish_job_claimed", {"worker_id": worker_id, "attempt": job.attempt_count}
        )
    db.flush()
    return jobs


def build_publish_claim_statement(
    *, clock: datetime, limit: int, dialect_name: str
) -> Select[tuple[InstagramPublishJob]]:
    eligible = or_(
        and_(InstagramPublishJob.status == "queued", InstagramPublishJob.scheduled_for <= clock),
        and_(
            InstagramPublishJob.status == "retry_wait",
            InstagramPublishJob.next_attempt_at.is_not(None),
            InstagramPublishJob.next_attempt_at <= clock,
        ),
        and_(
            InstagramPublishJob.status == "claimed",
            InstagramPublishJob.claim_expires_at <= clock,
        ),
        and_(
            InstagramPublishJob.status == "creating_container",
            InstagramPublishJob.claim_expires_at <= clock,
        ),
        and_(
            InstagramPublishJob.status == "publishing",
            or_(
                InstagramPublishJob.provider_media_id.is_not(None),
                InstagramPublishJob.provider_status == "container_created",
            ),
            InstagramPublishJob.claim_expires_at <= clock,
        ),
    )
    statement = (
        select(InstagramPublishJob)
        .where(eligible)
        .order_by(InstagramPublishJob.scheduled_for, InstagramPublishJob.id)
        .limit(limit)
    )
    if dialect_name == "postgresql":
        statement = statement.with_for_update(skip_locked=True)
    else:
        statement = statement.with_for_update()
    return statement


def retry_delay_seconds(job: InstagramPublishJob, settings: Settings) -> float:
    base = min(
        settings.instagram_publishing_backoff_max_seconds,
        settings.instagram_publishing_backoff_base_seconds * (2 ** max(job.attempt_count - 1, 0)),
    )
    digest = hashlib.sha256(f"{job.idempotency_key}:{job.attempt_count}".encode()).digest()
    jitter = 0.9 + digest[0] / 1275
    return min(settings.instagram_publishing_backoff_max_seconds, base * jitter)


def publication_metrics(db: Session, business_id: int) -> dict[str, int | float]:
    content_counts: dict[str, int] = {
        str(status): int(count)
        for status, count in db.query(
            InstagramContent.status, func.count(InstagramContent.id)
        )
        .filter(InstagramContent.business_id == business_id)
        .group_by(InstagramContent.status)
        .all()
    }
    job_counts: dict[str, int] = {
        str(status): int(count)
        for status, count in db.query(
            InstagramPublishJob.status, func.count(InstagramPublishJob.id)
        )
        .filter(InstagramPublishJob.business_id == business_id)
        .group_by(InstagramPublishJob.status)
        .all()
    }
    published = int(job_counts.get("published", 0))
    failed = int(job_counts.get("failed", 0))
    completed = published + failed
    return {
        "drafts": int(content_counts.get("draft", 0)),
        "approved": int(content_counts.get("validated", 0)),
        "scheduled": int(content_counts.get("scheduled", 0)),
        "published": int(content_counts.get("published", 0)),
        "failed": failed,
        "action_required": int(job_counts.get("action_required", 0)),
        "successful_publishes": published,
        "publish_success_rate": round(published / completed, 4) if completed else 0.0,
    }


def publication_history_events(
    db: Session,
    business_id: int,
    content_id: int,
    *,
    owner_technical: bool,
    limit: int = 100,
) -> list[dict]:
    publication_actions = (
        "publish_job_created",
        "publish_job_rescheduled",
        "publish_job_cancelled",
        "publish_now_requested",
        "publish_retry_requested",
        "publish_attempt_started",
        "publish_carousel_child_created",
        "publish_container_created",
        "publish_provider_call_started",
        "publish_media_id_persisted",
        "publish_succeeded",
        "publish_failed",
        "publish_retry_scheduled",
        "publish_action_required",
        "publish_validation_failed",
        "integration_blocked_publish",
    )
    rows = (
        db.query(AuditLog)
        .filter(
            AuditLog.business_id == business_id,
            AuditLog.action.in_(publication_actions),
        )
        .order_by(AuditLog.created_at.desc(), AuditLog.id.desc())
        .limit(max(limit * 10, 100))
        .all()
    )
    events: list[dict] = []
    for row in rows:
        try:
            metadata = json.loads(row.metadata_json or "{}")
        except (TypeError, ValueError):
            metadata = {}
        if metadata.get("content_id") != content_id:
            continue
        safe_metadata = {
            key: value
            for key, value in metadata.items()
            if key
            in {
                "content_id",
                "version_id",
                "scheduled_for",
                "status",
                "publish_now",
                "attempt",
                "reason",
                "error_code",
                "actor_user_id",
                *(("mode", "worker_id") if owner_technical else ()),
            }
        }
        events.append(
            {
                "id": row.id,
                "action": row.action,
                "actor_user_id": row.actor_user_id,
                "created_at": row.created_at.isoformat(),
                "metadata": safe_metadata,
            }
        )
        if len(events) >= limit:
            break
    return events


def serialize_publish_job(job: InstagramPublishJob, *, owner_technical: bool = True) -> dict:
    def stamp(value: datetime | None) -> str | None:
        normalized = as_utc(value)
        return normalized.isoformat() if normalized else None

    metadata = None
    if job.provider_metadata_json:
        try:
            metadata = json.loads(job.provider_metadata_json)
        except json.JSONDecodeError:
            metadata = None
    return {
        "id": job.id,
        "business_id": job.business_id,
        "content_item_id": job.content_item_id,
        "content_version_id": job.content_version_id,
        "integration_id": job.integration_id,
        "status": job.status,
        "scheduled_for": stamp(job.scheduled_for),
        "attempt_count": job.attempt_count,
        "max_attempts": job.max_attempts,
        "next_attempt_at": stamp(job.next_attempt_at),
        "claimed_at": stamp(job.claimed_at),
        "claim_expires_at": stamp(job.claim_expires_at),
        "provider_container_id": (
            f"...{job.provider_container_id[-8:]}"
            if owner_technical and job.provider_container_id
            else None
        ),
        "provider_media_id": job.provider_media_id,
        "provider_permalink": job.provider_permalink,
        "provider_status": job.provider_status,
        "provider_error_code": job.provider_error_code,
        "safe_error_message": job.safe_error_message,
        "provider_metadata": metadata if owner_technical else None,
        "created_at": stamp(job.created_at),
        "updated_at": stamp(job.updated_at),
        "published_at": stamp(job.published_at),
        "cancelled_at": stamp(job.cancelled_at),
    }
