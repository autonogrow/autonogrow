from __future__ import annotations

import json
from collections.abc import Callable
from datetime import datetime, timedelta, timezone
from hashlib import sha256
from typing import Any

from sqlalchemy import and_, or_
from sqlalchemy.orm import Session

from app.core.audit import record_audit
from app.core.config import Settings, get_settings
from app.models import (
    Business,
    BusinessChannelControl,
    BusinessChannelIntegration,
    InstagramMediaSyncState,
    InstagramOAuthAttempt,
    MetaIntegrationJob,
    User,
    WhatsAppEmbeddedSignupAttempt,
)
from app.services.channel_provider_service import integration_credentials_expired
from app.services.meta_integration_health_contracts import IntegrationHealthResult
from app.services.queue_error_service import calculate_next_retry

ACTIVE_JOB_STATUSES = ("queued", "processing", "retry")
TERMINAL_ATTEMPT_STATUSES = ("expired", "cancelled", "failed", "rejected", "approved")
SAFE_HEALTH_METADATA_KEYS = {
    "account_type",
    "phone_status",
}
EXPIRED_EXPIRY_STATES = frozenset({"expired"})


def _now(value: datetime | None = None) -> datetime:
    return value or datetime.utcnow()


def _bounded_key(value: str) -> str:
    if len(value) <= 255:
        return value
    return f"meta:{sha256(value.encode('utf-8')).hexdigest()}"


def _manual_bucket(now: datetime) -> int:
    return int(now.timestamp()) // 300


def enqueue_meta_integration_job(
    db: Session,
    *,
    business_id: int,
    job_type: str,
    origin: str,
    integration_id: int | None = None,
    actor_user_id: int | None = None,
    idempotency_key: str | None = None,
    max_attempts: int = 5,
    available_at: datetime | None = None,
    now: datetime | None = None,
) -> tuple[MetaIntegrationJob, bool]:
    current = _now(now)
    if job_type in {"health_check", "retry_subscription", "instagram_media_sync"} and integration_id is None:
        raise ValueError("Integration is required for this maintenance job")
    if job_type == "attempt_cleanup" and integration_id is not None:
        raise ValueError("Cleanup jobs cannot target an integration")
    if job_type not in {
        "health_check",
        "retry_subscription",
        "attempt_cleanup",
        "instagram_media_sync",
    }:
        raise ValueError("Unsupported maintenance job")
    if origin not in {"scheduler", "owner", "admin", "system"}:
        raise ValueError("Unsupported maintenance job origin")

    if integration_id is not None:
        integration = (
            db.query(BusinessChannelIntegration)
            .filter(
                BusinessChannelIntegration.id == integration_id,
                BusinessChannelIntegration.business_id == business_id,
            )
            .with_for_update()
            .first()
        )
        if integration is None:
            raise ValueError("Integration is unavailable")
        active = (
            db.query(MetaIntegrationJob)
            .filter(
                MetaIntegrationJob.business_id == business_id,
                MetaIntegrationJob.integration_id == integration_id,
                MetaIntegrationJob.job_type == job_type,
                MetaIntegrationJob.status.in_(ACTIVE_JOB_STATUSES),
            )
            .order_by(MetaIntegrationJob.id.desc())
            .first()
        )
        if active is not None:
            return active, False
    else:
        business = db.query(Business).filter(Business.id == business_id).with_for_update().first()
        if business is None:
            raise ValueError("Business is unavailable")

    key = _bounded_key(
        idempotency_key
        or f"{origin}:{job_type}:{business_id}:{integration_id or 'global'}:{_manual_bucket(current)}"
    )
    existing = (
        db.query(MetaIntegrationJob).filter(MetaIntegrationJob.idempotency_key == key).first()
    )
    if existing is not None:
        return existing, False
    job = MetaIntegrationJob(
        business_id=business_id,
        integration_id=integration_id,
        job_type=job_type,
        status="queued",
        idempotency_key=key,
        actor_user_id=actor_user_id,
        origin=origin,
        attempt_count=0,
        max_attempts=max_attempts,
        available_at=available_at or current,
        created_at=current,
        updated_at=current,
    )
    db.add(job)
    db.flush()
    record_audit(
        db,
        action=(
            "instagram_media_sync_scheduled"
            if job_type == "instagram_media_sync"
            else (
                "integration_health_check_scheduled"
                if job_type == "health_check"
                else (
                    "subscription_retry_started"
                    if job_type == "retry_subscription"
                    else "integration_attempt_cleanup_scheduled"
                )
            )
        ),
        actor=db.get(User, actor_user_id) if actor_user_id else None,
        business_id=business_id,
        resource_type="meta_integration_job",
        resource_id=job.id,
        metadata={
            "integration_id": integration_id,
            "job_type": job_type,
            "origin": origin,
        },
        commit=False,
    )
    return job, True


def schedule_due_meta_jobs(
    db: Session,
    *,
    settings: Settings | None = None,
    now: datetime | None = None,
) -> int:
    settings = settings or get_settings()
    current = _now(now)
    scheduled = 0
    if settings.meta_integration_health_check_enabled:
        query = (
            db.query(BusinessChannelIntegration)
            .join(Business, Business.id == BusinessChannelIntegration.business_id)
            .filter(
                Business.status == "active",
                BusinessChannelIntegration.integration_status.in_(("connected", "degraded")),
                BusinessChannelIntegration.next_health_check_at.is_not(None),
                BusinessChannelIntegration.next_health_check_at <= current,
            )
            .order_by(
                BusinessChannelIntegration.next_health_check_at, BusinessChannelIntegration.id
            )
            .limit(settings.meta_integration_health_batch_size)
        )
        if db.get_bind().dialect.name == "postgresql":
            query = query.with_for_update(skip_locked=True)
        for integration in query.all():
            due = integration.next_health_check_at or current
            _, created = enqueue_meta_integration_job(
                db,
                business_id=integration.business_id,
                integration_id=integration.id,
                job_type="health_check",
                origin="scheduler",
                idempotency_key=f"scheduler:health:{integration.id}:{due.isoformat()}",
                max_attempts=settings.meta_integration_failure_threshold,
                now=current,
            )
            integration.next_health_check_at = current + timedelta(
                hours=settings.meta_integration_health_check_interval_hours
            )
            scheduled += int(created)

    if settings.instagram_media_sync_enabled and settings.instagram_provider_enabled:
        from app.services.instagram_media_sync_service import enqueue_instagram_media_sync

        due_before = current.replace(tzinfo=timezone.utc) - timedelta(
            hours=settings.instagram_media_sync_interval_hours
        )
        integrations = (
            db.query(BusinessChannelIntegration)
            .join(Business, Business.id == BusinessChannelIntegration.business_id)
            .join(
                InstagramMediaSyncState,
                InstagramMediaSyncState.integration_id == BusinessChannelIntegration.id,
            )
            .filter(
                Business.status == "active",
                BusinessChannelIntegration.channel == "instagram",
                BusinessChannelIntegration.provider == "instagram",
                BusinessChannelIntegration.integration_status.in_(("connected", "degraded")),
                InstagramMediaSyncState.last_success_at.is_not(None),
                InstagramMediaSyncState.last_success_at <= due_before,
            )
            .order_by(InstagramMediaSyncState.last_success_at, BusinessChannelIntegration.id)
            .limit(settings.meta_integration_health_batch_size)
            .all()
        )
        for integration in integrations:
            try:
                _, created, _ = enqueue_instagram_media_sync(
                    db,
                    business_id=integration.business_id,
                    origin="scheduler",
                    settings=settings,
                )
            except ValueError:
                continue
            scheduled += int(created)

    interval_seconds = settings.meta_integration_cleanup_interval_hours * 3600
    cleanup_bucket = int(current.timestamp()) // interval_seconds
    instagram_businesses = {
        row[0]
        for row in db.query(InstagramOAuthAttempt.business_id)
        .join(Business, Business.id == InstagramOAuthAttempt.business_id)
        .filter(
            Business.status == "active",
            or_(
                InstagramOAuthAttempt.expires_at <= current,
                InstagramOAuthAttempt.status.in_(TERMINAL_ATTEMPT_STATUSES),
            )
        )
        .distinct()
        .limit(settings.meta_integration_health_batch_size)
        .all()
    }
    whatsapp_businesses = {
        row[0]
        for row in db.query(WhatsAppEmbeddedSignupAttempt.business_id)
        .join(Business, Business.id == WhatsAppEmbeddedSignupAttempt.business_id)
        .filter(
            Business.status == "active",
            or_(
                WhatsAppEmbeddedSignupAttempt.expires_at <= current,
                WhatsAppEmbeddedSignupAttempt.status.in_(TERMINAL_ATTEMPT_STATUSES),
            )
        )
        .distinct()
        .limit(settings.meta_integration_health_batch_size)
        .all()
    }
    for business_id in sorted(instagram_businesses | whatsapp_businesses)[
        : settings.meta_integration_health_batch_size
    ]:
        _, created = enqueue_meta_integration_job(
            db,
            business_id=business_id,
            integration_id=None,
            job_type="attempt_cleanup",
            origin="scheduler",
            idempotency_key=f"scheduler:cleanup:{business_id}:{cleanup_bucket}",
            max_attempts=settings.meta_integration_failure_threshold,
            now=current,
        )
        scheduled += int(created)
    return scheduled


def claim_meta_integration_jobs(
    db: Session,
    *,
    worker_id: str,
    limit: int,
    lock_ttl_seconds: int,
    now: datetime | None = None,
) -> list[int]:
    current = _now(now)
    eligible = or_(
        and_(MetaIntegrationJob.status == "queued", MetaIntegrationJob.available_at <= current),
        and_(MetaIntegrationJob.status == "retry", MetaIntegrationJob.next_retry_at <= current),
        and_(
            MetaIntegrationJob.status == "processing",
            MetaIntegrationJob.lock_expires_at < current,
        ),
    )
    query = (
        db.query(MetaIntegrationJob)
        .join(Business, Business.id == MetaIntegrationJob.business_id)
        .filter(eligible, Business.status == "active")
        .order_by(MetaIntegrationJob.available_at, MetaIntegrationJob.id)
        .limit(limit)
    )
    if db.get_bind().dialect.name == "postgresql":
        query = query.with_for_update(skip_locked=True)
    jobs = query.all()
    expires = current + timedelta(seconds=lock_ttl_seconds)
    for job in jobs:
        job.status = "processing"
        job.locked_by = worker_id
        job.lock_expires_at = expires
        job.processing_started_at = current
        job.attempt_count += 1
        job.updated_at = current
        record_audit(
            db,
            action="integration_health_check_started"
            if job.job_type == "health_check"
            else "integration_maintenance_job_started",
            business_id=job.business_id,
            resource_type="meta_integration_job",
            resource_id=job.id,
            metadata={"integration_id": job.integration_id, "job_type": job.job_type},
            commit=False,
        )
    db.flush()
    return [job.id for job in jobs]


def finish_meta_integration_job(
    db: Session,
    job: MetaIntegrationJob,
    *,
    duration_ms: int,
    now: datetime | None = None,
) -> None:
    current = _now(now)
    job.status = "completed"
    job.completed_at = current
    job.duration_ms = max(0, duration_ms)
    job.next_retry_at = None
    job.locked_by = None
    job.lock_expires_at = None
    job.last_error_code = None
    job.safe_error_message = None
    job.updated_at = current
    db.flush()


def fail_meta_integration_job(
    db: Session,
    job: MetaIntegrationJob,
    *,
    error_code: str,
    safe_message: str,
    retryable: bool,
    duration_ms: int,
    now: datetime | None = None,
) -> None:
    current = _now(now)
    exhausted = job.attempt_count >= job.max_attempts
    if retryable and not exhausted:
        job.status = "retry"
        job.next_retry_at = calculate_next_retry(job.attempt_count, now=current)
    else:
        job.status = "dead_letter" if exhausted else "failed"
        job.next_retry_at = None
        job.failed_at = current
    job.duration_ms = max(0, duration_ms)
    job.last_error_code = error_code[:120]
    job.safe_error_message = safe_message[:500]
    job.locked_by = None
    job.lock_expires_at = None
    job.updated_at = current
    record_audit(
        db,
        action=(
            "instagram_media_sync_job_failed"
            if job.job_type == "instagram_media_sync"
            else (
                "integration_health_check_failed"
                if job.job_type == "health_check"
                else (
                    "subscription_retry_failed"
                    if job.job_type == "retry_subscription"
                    else "integration_attempt_cleanup_failed"
                )
            )
        ),
        business_id=job.business_id,
        resource_type="meta_integration_job",
        resource_id=job.id,
        metadata={
            "integration_id": job.integration_id,
            "job_type": job.job_type,
            "safe_error_code": error_code[:120],
            "retryable": retryable,
        },
        commit=False,
    )
    db.flush()


def apply_integration_health_result(
    db: Session,
    *,
    job: MetaIntegrationJob,
    integration: BusinessChannelIntegration,
    result: IntegrationHealthResult,
    settings: Settings | None = None,
) -> bool:
    settings = settings or get_settings()
    previous_health = integration.health_status
    previous_integration = integration.integration_status
    failures = 0 if result.healthy else integration.consecutive_health_failures + 1
    health_status = result.health_status
    if result.retryable and failures >= settings.meta_integration_failure_threshold:
        health_status = "degraded"
    elif result.retryable and failures == 1 and health_status == "degraded":
        health_status = "warning"

    integration.health_status = health_status
    integration.last_health_check_at = result.checked_at.replace(tzinfo=None)
    integration.next_health_check_at = result.next_check_at.replace(tzinfo=None)
    integration.consecutive_health_failures = failures
    integration.health_error_code = result.safe_error_code
    integration.health_safe_error_message = result.safe_error_message
    safe_metadata: dict[str, Any] = {
        "token_expiry_status": result.token_expiry_status,
        "subscription_status": result.subscription_status,
        "asset_status": result.asset_status,
        "blocking": result.blocking,
        "reconnection_required": result.reconnection_required,
    }
    safe_metadata.update(
        {key: value for key, value in result.metadata.items() if key in SAFE_HEALTH_METADATA_KEYS}
    )
    integration.health_metadata_json = json.dumps(safe_metadata, sort_keys=True)

    if health_status == "revoked":
        integration.integration_status = "revoked"
    elif health_status == "suspended":
        integration.integration_status = "error"
    elif result.token_expiry_status in EXPIRED_EXPIRY_STATES:
        integration.integration_status = "expired"
    elif health_status == "degraded" and integration.integration_status == "connected":
        integration.integration_status = "degraded"
    elif result.healthy and integration.integration_status == "degraded":
        integration.integration_status = "connected"

    integration.last_verified_at = result.checked_at.replace(tzinfo=None)
    if result.healthy:
        integration.last_success_at = result.checked_at.replace(tzinfo=None)
    else:
        integration.last_error_at = result.checked_at.replace(tzinfo=None)

    recovered = result.healthy and previous_health not in {"unknown", "healthy"}
    if recovered:
        action = "integration_recovered"
    elif result.healthy:
        action = "integration_health_check_succeeded"
    elif result.token_expiry_status in EXPIRED_EXPIRY_STATES:
        action = "token_expired"
    elif result.token_expiry_status in {"expires_soon", "critical"}:
        action = "token_expiry_warning"
    elif result.safe_error_code and "permissions" in result.safe_error_code:
        action = "permissions_missing"
    elif result.subscription_status == "missing":
        action = "subscription_missing"
    else:
        action = "integration_health_degraded"
    record_audit(
        db,
        action=action,
        business_id=integration.business_id,
        resource_type="business_channel_integration",
        resource_id=integration.id,
        metadata={
            "job_id": job.id,
            "channel": integration.channel,
            "previous_health_status": previous_health,
            "health_status": health_status,
            "previous_integration_status": previous_integration,
            "integration_status": integration.integration_status,
            "safe_error_code": result.safe_error_code,
        },
        commit=False,
    )
    db.flush()
    return recovered


def _destroy_instagram_candidate(attempt: InstagramOAuthAttempt) -> bool:
    had_credentials = bool(attempt.candidate_encrypted_access_token)
    attempt.candidate_encrypted_access_token = None
    attempt.candidate_encryption_key_version = None
    attempt.candidate_token_expires_at = None
    attempt.candidate_granted_scopes = None
    return had_credentials


def _destroy_whatsapp_candidate(attempt: WhatsAppEmbeddedSignupAttempt) -> bool:
    had_credentials = bool(attempt.candidate_encrypted_access_token)
    attempt.candidate_encrypted_access_token = None
    attempt.candidate_encryption_key_version = None
    attempt.candidate_token_expires_at = None
    attempt.candidate_granted_scopes = None
    return had_credentials


def cleanup_meta_integration_attempts(
    db: Session,
    *,
    business_id: int,
    settings: Settings | None = None,
    batch_size: int | None = None,
    now: datetime | None = None,
) -> dict[str, int]:
    settings = settings or get_settings()
    current = _now(now)
    limit = batch_size or settings.meta_integration_health_batch_size
    cutoff = current - timedelta(days=settings.meta_expired_attempt_retention_days)
    expired = 0
    destroyed = 0
    deleted = 0

    cleanup_models: tuple[tuple[Any, Callable[[Any], bool]], ...] = (
        (InstagramOAuthAttempt, _destroy_instagram_candidate),
        (WhatsAppEmbeddedSignupAttempt, _destroy_whatsapp_candidate),
    )
    for model, destroy in cleanup_models:
        active_query = (
            db.query(model)
            .filter(
                model.business_id == business_id,
                model.status.in_(("pending", "processing", "candidate_ready")),
                model.expires_at <= current,
            )
            .order_by(model.expires_at, model.id)
            .limit(limit)
        )
        if db.get_bind().dialect.name == "postgresql":
            active_query = active_query.with_for_update(skip_locked=True)
        for attempt in active_query.all():
            destroyed_now = destroy(attempt)
            destroyed += int(destroyed_now)
            attempt.status = "expired"
            attempt.invalidated_at = current
            attempt.safe_error_code = "attempt_expired"
            attempt.safe_error_message = "Meta connection attempt expired"
            expired += 1
            record_audit(
                db,
                action="candidate_credentials_destroyed"
                if destroyed_now
                else "expired_attempt_cleaned",
                business_id=business_id,
                resource_type=model.__tablename__,
                resource_id=attempt.id,
                metadata={"status": "expired"},
                commit=False,
            )

        residual_query = (
            db.query(model)
            .filter(
                model.business_id == business_id,
                model.status.in_(TERMINAL_ATTEMPT_STATUSES),
                model.candidate_encrypted_access_token.is_not(None),
            )
            .order_by(model.id)
            .limit(limit)
        )
        if db.get_bind().dialect.name == "postgresql":
            residual_query = residual_query.with_for_update(skip_locked=True)
        for attempt in residual_query.all():
            if destroy(attempt):
                destroyed += 1
                record_audit(
                    db,
                    action="candidate_credentials_destroyed",
                    business_id=business_id,
                    resource_type=model.__tablename__,
                    resource_id=attempt.id,
                    metadata={"status": attempt.status},
                    commit=False,
                )

        terminal_query = (
            db.query(model)
            .filter(
                model.business_id == business_id,
                model.status.in_(TERMINAL_ATTEMPT_STATUSES),
                model.expires_at < cutoff,
            )
            .order_by(model.expires_at, model.id)
            .limit(limit)
        )
        if db.get_bind().dialect.name == "postgresql":
            terminal_query = terminal_query.with_for_update(skip_locked=True)
        for attempt in terminal_query.all():
            destroyed_now = destroy(attempt)
            destroyed += int(destroyed_now)
            record_audit(
                db,
                action="candidate_credentials_destroyed"
                if destroyed_now
                else "expired_attempt_cleaned",
                business_id=business_id,
                resource_type=model.__tablename__,
                resource_id=attempt.id,
                metadata={"status": attempt.status},
                commit=False,
            )
            db.delete(attempt)
            deleted += 1
    db.flush()
    return {"expired": expired, "credentials_destroyed": destroyed, "deleted": deleted}


def integration_health_metadata(integration: BusinessChannelIntegration) -> dict[str, Any]:
    try:
        value = json.loads(integration.health_metadata_json or "{}")
    except (TypeError, ValueError):
        return {}
    return value if isinstance(value, dict) else {}


def integration_health_blocks_delivery(integration: BusinessChannelIntegration) -> bool:
    metadata = integration_health_metadata(integration)
    return metadata.get("blocking") is True or integration.health_status in {
        "revoked",
        "suspended",
        "error",
    }


def serialize_integration_health(
    integration: BusinessChannelIntegration,
    *,
    control: BusinessChannelControl | None,
    include_internal: bool,
) -> dict[str, Any]:
    metadata = integration_health_metadata(integration)
    owner_approved = bool(control and control.status == "approved")
    delivery_enabled = bool(control and control.integrated_delivery_enabled)
    automation_enabled = bool(control and control.automation_enabled)
    available = bool(
        owner_approved
        and delivery_enabled
        and integration.integration_status in {"connected", "degraded"}
        and integration.encrypted_access_token
        and integration.encryption_key_version
        and not integration_credentials_expired(integration)
        and not integration_health_blocks_delivery(integration)
    )
    payload: dict[str, Any] = {
        "channel": integration.channel,
        "integration_status": integration.integration_status,
        "health_status": integration.health_status,
        "commercial_access": control.status if control else "not_allowed",
        "owner_approved": owner_approved,
        "integrated_delivery_enabled": delivery_enabled,
        "automation_enabled": automation_enabled,
        "integrated_delivery_available": available,
        "reconnection_required": bool(
            metadata.get("reconnection_required")
            or integration.integration_status in {"expired", "revoked", "error"}
        ),
        "last_health_check_at": integration.last_health_check_at,
        "next_health_check_at": integration.next_health_check_at,
        "last_success_at": integration.last_success_at,
        "last_error_at": integration.last_error_at,
        "token_expires_at": integration.token_expires_at,
        "token_expiry_status": metadata.get("token_expiry_status", "unknown"),
        "subscription_status": metadata.get("subscription_status", "unknown"),
        "asset_status": metadata.get("asset_status", "unknown"),
        "consecutive_health_failures": integration.consecutive_health_failures,
        "safe_error_code": integration.health_error_code,
        "safe_error_message": integration.health_safe_error_message,
    }
    if integration.channel == "whatsapp":
        try:
            provider_metadata = json.loads(integration.metadata_json or "{}")
        except (TypeError, ValueError):
            provider_metadata = {}
        payload["display_phone_number_redacted"] = (
            provider_metadata.get("display_phone_number_redacted")
            if isinstance(provider_metadata, dict)
            else None
        )
    if include_internal:
        payload.update(
            {
                "integration_id": integration.id,
                "provider": integration.provider,
                "diagnostic_metadata": {
                    key: value
                    for key, value in metadata.items()
                    if key in SAFE_HEALTH_METADATA_KEYS
                },
            }
        )
    return payload


def serialize_meta_integration_job(job: MetaIntegrationJob) -> dict[str, Any]:
    return {
        "id": job.id,
        "job_type": job.job_type,
        "status": job.status,
        "origin": job.origin,
        "attempt_count": job.attempt_count,
        "max_attempts": job.max_attempts,
        "available_at": job.available_at,
        "next_retry_at": job.next_retry_at,
        "completed_at": job.completed_at,
        "failed_at": job.failed_at,
        "duration_ms": job.duration_ms,
        "safe_error_code": job.last_error_code,
        "safe_error_message": job.safe_error_message,
        "created_at": job.created_at,
    }
