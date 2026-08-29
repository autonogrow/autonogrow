from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, time, timedelta, timezone, tzinfo
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from sqlalchemy.orm import Session

from app.models import AuditLog, InstagramContent, InstagramPublishJob, InstagramRemoteMedia
from app.services.instagram_publish_service import publish_outcome_requires_review

PREPUBLICATION_STATUSES = frozenset(
    {"draft", "ready_for_review", "changes_requested", "validated"}
)
ACTIVE_OR_ATTEMPTED_JOB_STATUSES = frozenset(
    {
        "queued",
        "claimed",
        "creating_container",
        "publishing",
        "simulating_publish",
        "published",
        "retry_wait",
        "failed",
        "action_required",
    }
)


@dataclass(frozen=True)
class CalendarContext:
    provider_timestamp: datetime | None = None
    publish_succeeded_at: datetime | None = None


def _as_utc(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def latest_publish_job(content: InstagramContent) -> InstagramPublishJob | None:
    current = max(content.versions, key=lambda version: version.version_number, default=None)
    if current is None:
        return None
    return max(
        (job for job in content.publish_jobs if job.content_version_id == current.id),
        key=lambda job: (_as_utc(job.created_at) or datetime.min.replace(tzinfo=timezone.utc), job.id),
        default=None,
    )


def successful_publish_job(content: InstagramContent) -> InstagramPublishJob | None:
    return max(
        (job for job in content.publish_jobs if job.status == "published"),
        key=lambda job: (
            _as_utc(job.published_at)
            or _as_utc(job.updated_at)
            or datetime.min.replace(tzinfo=timezone.utc),
            job.id,
        ),
        default=None,
    )


def load_calendar_contexts(
    db: Session, contents: list[InstagramContent]
) -> dict[int, CalendarContext]:
    content_ids = [content.id for content in contents]
    if not content_ids:
        return {}

    provider_by_content: dict[int, datetime] = {}
    remote_rows = (
        db.query(InstagramRemoteMedia)
        .filter(
            InstagramRemoteMedia.business_id == contents[0].business_id,
            InstagramRemoteMedia.internal_content_id.in_(content_ids),
            InstagramRemoteMedia.parent_id.is_(None),
            InstagramRemoteMedia.provider_timestamp.is_not(None),
        )
        .order_by(InstagramRemoteMedia.provider_timestamp.desc(), InstagramRemoteMedia.id.desc())
        .all()
    )
    for media in remote_rows:
        if media.internal_content_id is not None and media.provider_timestamp is not None:
            provider_by_content.setdefault(media.internal_content_id, media.provider_timestamp)

    job_to_content = {
        str(job.id): content.id
        for content in contents
        for job in content.publish_jobs
        if job.status == "published"
    }
    success_by_content: dict[int, datetime] = {}
    if job_to_content:
        events = (
            db.query(AuditLog)
            .filter(
                AuditLog.business_id == contents[0].business_id,
                AuditLog.action == "publish_succeeded",
                AuditLog.resource_type == "instagram_publish_job",
                AuditLog.resource_id.in_(job_to_content),
            )
            .order_by(AuditLog.created_at.desc(), AuditLog.id.desc())
            .all()
        )
        for event in events:
            content_id = job_to_content.get(str(event.resource_id))
            if content_id is not None:
                success_by_content.setdefault(content_id, event.created_at)

    return {
        content.id: CalendarContext(
            provider_timestamp=provider_by_content.get(content.id),
            publish_succeeded_at=success_by_content.get(content.id),
        )
        for content in contents
    }


def calendar_datetime(
    content: InstagramContent, context: CalendarContext | None = None
) -> tuple[datetime | None, str | None]:
    if content.status != "published":
        planned = _as_utc(content.planned_publish_at)
        return planned, "planned_publish_at" if planned else None

    context = context or CalendarContext()
    job = successful_publish_job(content)
    candidates = (
        (job.published_at if job else None, "publish_job.published_at"),
        (context.provider_timestamp, "instagram_remote_media.provider_timestamp"),
        (context.publish_succeeded_at, "audit.publish_succeeded.created_at"),
        (job.updated_at if job else None, "publish_job.updated_at"),
        (content.planned_publish_at, "planned_publish_at"),
    )
    for value, source in candidates:
        normalized = _as_utc(value)
        if normalized is not None:
            return normalized, source
    return None, None


def attention_details(content: InstagramContent) -> dict:
    job = latest_publish_job(content)
    status = job.status if job else None
    reason_key: str | None = None
    reason: str | None = None
    if status == "action_required" and job is not None:
        code = str(job.provider_error_code or "")
        if publish_outcome_requires_review(job):
            reason_key = "verify"
            reason = "Verifica en Instagram si la publicación llegó a completarse."
        elif any(part in code for part in ("authentication", "token", "permission")):
            reason_key = "reconnect"
            reason = "La conexión o los permisos de Instagram requieren atención."
        else:
            reason_key = "action_required"
            reason = job.safe_error_message or "Revisa el detalle antes de continuar."
    elif (status == "failed" and job is not None) or (
        status == "retry_wait" and job and job.attempt_count >= job.max_attempts
    ):
        reason_key = "failed"
        reason = job.safe_error_message or "No se pudo completar la publicación."
    elif content.status == "ready_for_review":
        reason_key = "ready_for_review"
        reason = "La publicación está lista para revisión."
    elif content.status == "changes_requested":
        reason_key = "changes_requested"
        reason = "Hay cambios solicitados pendientes."

    attention_at = _as_utc(content.planned_publish_at)
    if attention_at is None and status in {"action_required", "failed", "retry_wait"}:
        attention_at = _as_utc(job.scheduled_for if job else None)
    return {
        "attention_required": reason_key is not None,
        "attention_reason_key": reason_key,
        "attention_reason": reason,
        "attention_datetime": attention_at.isoformat() if attention_at else None,
    }


def calendar_semantics(
    content: InstagramContent, context: CalendarContext | None = None
) -> dict:
    value, source = calendar_datetime(content, context)
    latest_job = latest_publish_job(content)
    if content.archived_at is not None or content.status == "cancelled":
        bucket = "excluded"
    elif content.status == "published":
        bucket = "published"
    elif value is not None:
        bucket = "operational"
    elif content.status in PREPUBLICATION_STATUSES and (
        latest_job is None or latest_job.status not in ACTIVE_OR_ATTEMPTED_JOB_STATUSES
    ):
        bucket = "unscheduled"
    else:
        bucket = "excluded"
    return {
        "calendar_datetime": value.isoformat() if value else None,
        "calendar_datetime_source": source,
        "calendar_bucket": bucket,
        **attention_details(content),
    }


def operational_week_summary(
    contents: list[InstagramContent], *, now: datetime, timezone_name: str
) -> dict:
    current = _as_utc(now) or datetime.now(timezone.utc)
    try:
        local_zone: tzinfo = ZoneInfo(timezone_name)
    except ZoneInfoNotFoundError:
        local_zone = timezone.utc
    local_now = current.astimezone(local_zone)
    week_start_date = local_now.date() - timedelta(days=local_now.weekday())
    week_end_date = week_start_date + timedelta(days=7)
    week_start = datetime.combine(week_start_date, time.min, local_zone).astimezone(timezone.utc)
    week_end = datetime.combine(week_end_date, time.min, local_zone).astimezone(timezone.utc)

    upcoming = 0
    filled_future_days: set[str] = set()
    future_day_keys = {
        (local_now.date() + timedelta(days=offset)).isoformat()
        for offset in range((week_end_date - local_now.date()).days)
    }
    for content in contents:
        planned = _as_utc(content.planned_publish_at)
        if content.archived_at is not None or planned is None or not (current <= planned < week_end):
            continue
        job = latest_publish_job(content)
        if content.status == "scheduled" and job is not None and job.status == "queued":
            upcoming += 1
        if content.status in PREPUBLICATION_STATUSES | {"scheduled"}:
            filled_future_days.add(planned.astimezone(local_zone).date().isoformat())

    return {
        "week_start": week_start.isoformat(),
        "week_end": week_end.isoformat(),
        "upcoming_scheduled_count": upcoming,
        "future_gap_count": len(future_day_keys - filled_future_days),
    }
