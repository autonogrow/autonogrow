from __future__ import annotations

import hashlib
import json
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from fastapi import HTTPException
from sqlalchemy import Select, and_, or_, select
from sqlalchemy.orm import Session

from app.core.audit import record_audit
from app.core.config import Settings, get_settings
from app.models import (
    BusinessChannelControl,
    BusinessChannelIntegration,
    InstagramContent,
    InstagramContentValidation,
    InstagramContentVersion,
    InstagramPublishJob,
    User,
)

ACTIVE_JOB_STATUSES = {"queued", "claimed", "simulating_publish", "retry_wait"}
BLOCKING_HEALTH = {"action_required", "revoked", "suspended", "error"}
UNCERTAIN_PROVIDER_STATUSES = {
    "unknown_result",
    "unknown_after_claim_expiry",
    "outcome_requires_review",
}


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
    db: Session, job: InstagramPublishJob, action: str, metadata: dict | None = None
) -> None:
    record_audit(
        db,
        action=action,
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
    integration, eligibility_error = integration_eligibility(db, content.business_id)
    status = "queued"
    safe_error: str | None = None
    if not force_now and planned <= clock:
        status = "action_required"
        safe_error = "Planned date is in the past; choose a new future date"
    elif eligibility_error:
        status = "action_required"
        safe_error = eligibility_error
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
    if job is not None and job.status == "simulating_publish":
        job.status = "action_required"
        job.safe_error_message = "Schedule changed after publishing execution began"
        job.provider_status = "outcome_requires_review"
        _clear_claim(job)
        _audit_job(db, job, "publish_action_required", {"reason": "execution_already_started"})
        db.flush()
        return job
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
    if job.status == "simulating_publish":
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
    _audit_job(db, job, action, {"reason": reason, "actor_user_id": actor.id if actor else None})
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
    integration, error = integration_eligibility(db, content.business_id)
    if error:
        raise HTTPException(status_code=409, detail="Instagram integration requires action")
    clock = as_utc(now) or utc_now()
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
    _audit_job(db, job, "publish_retry_requested", {"actor_user_id": actor.id})
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
            InstagramPublishJob.status == "simulating_publish",
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
        was_expired = job.status == "claimed"
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


def serialize_publish_job(job: InstagramPublishJob) -> dict:
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
        "provider_container_id": job.provider_container_id,
        "provider_media_id": job.provider_media_id,
        "provider_permalink": job.provider_permalink,
        "provider_status": job.provider_status,
        "provider_error_code": job.provider_error_code,
        "safe_error_message": job.safe_error_message,
        "provider_metadata": metadata,
        "created_at": stamp(job.created_at),
        "updated_at": stamp(job.updated_at),
        "published_at": stamp(job.published_at),
        "cancelled_at": stamp(job.cancelled_at),
    }
