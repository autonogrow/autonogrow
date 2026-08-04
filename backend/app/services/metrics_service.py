from __future__ import annotations

import hmac
import math
from collections import defaultdict
from datetime import datetime
from threading import Lock

from fastapi import HTTPException, Request
from sqlalchemy import func

from app.core.config import Settings, get_settings
from app.core.database import SessionLocal, safe_database_pool_status
from app.models import (
    AuditLog,
    AutomationCreditTransaction,
    BackupRecord,
    Booking,
    BusinessChannelIntegration,
    ChannelOutboxMessage,
    MetaIntegrationJob,
    SystemIncident,
    WebhookInboxEvent,
    WorkerHeartbeat,
)
from app.services.worker_heartbeat_service import heartbeat_is_stale

_lock = Lock()
_http_counts: dict[tuple[str, str, str], int] = defaultdict(int)
_http_duration: dict[tuple[str, str], tuple[int, float]] = defaultdict(lambda: (0, 0.0))


def record_http_request(method: str, route: str, status_code: int, duration: float) -> None:
    safe_route = route if route.startswith("/") else "unmatched"
    status_class = f"{status_code // 100}xx"
    with _lock:
        _http_counts[(method.upper(), safe_route, status_class)] += 1
        count, total = _http_duration[(method.upper(), safe_route)]
        _http_duration[(method.upper(), safe_route)] = (count + 1, total + max(duration, 0.0))


def metrics_authorized(request: Request, settings: Settings | None = None) -> bool:
    active = settings or get_settings()
    if not active.metrics_enabled:
        return False
    client_ip = request.client.host if request.client else ""
    if client_ip in active.metrics_allowed_ip_list:
        return True
    configured = active.metrics_auth_token
    supplied = request.headers.get("authorization", "")
    if supplied.lower().startswith("bearer "):
        supplied = supplied[7:]
    else:
        supplied = request.headers.get("x-metrics-token", "")
    return bool(configured and supplied and hmac.compare_digest(configured, supplied))


def require_metrics_access(request: Request) -> None:
    settings = get_settings()
    if not settings.metrics_enabled:
        raise HTTPException(status_code=404, detail="Not found")
    if not metrics_authorized(request, settings):
        raise HTTPException(status_code=403, detail="Forbidden")


def _labels(**values: str) -> str:
    escaped = [
        f'{key}="{value.replace(chr(92), chr(92) * 2).replace(chr(34), chr(92) + chr(34))}"'
        for key, value in values.items()
    ]
    return "{" + ",".join(escaped) + "}" if escaped else ""


def _metric(lines: list[str], name: str, value: int | float, **labels: str) -> None:
    numeric = value if isinstance(value, int) or math.isfinite(value) else 0
    lines.append(f"{name}{_labels(**labels)} {numeric}")


def render_metrics() -> str:
    settings = get_settings()
    lines = [
        "# HELP autonogrow_app_info Static release information.",
        "# TYPE autonogrow_app_info gauge",
    ]
    _metric(
        lines,
        "autonogrow_app_info",
        1,
        version=settings.app_version,
        release=settings.app_release_id,
    )
    with _lock:
        counts = dict(_http_counts)
        durations = dict(_http_duration)
    lines.extend(
        (
            "# TYPE autonogrow_http_requests_total counter",
            "# TYPE autonogrow_http_request_duration_seconds_sum counter",
        )
    )
    for (method, route, status_class), value in sorted(counts.items()):
        _metric(
            lines,
            "autonogrow_http_requests_total",
            value,
            method=method,
            route=route,
            status=status_class,
        )
    for (method, route), (count, total) in sorted(durations.items()):
        _metric(
            lines,
            "autonogrow_http_request_duration_seconds_count",
            count,
            method=method,
            route=route,
        )
        _metric(
            lines, "autonogrow_http_request_duration_seconds_sum", total, method=method, route=route
        )
    try:
        with SessionLocal() as db:
            _metric(lines, "autonogrow_database_health", 1)
            for key, value in safe_database_pool_status(db.get_bind()).items():
                if key != "dialect" and value is not None:
                    _metric(lines, f"autonogrow_database_pool_{key}", value)
            workers = db.query(WorkerHeartbeat).all()
            active = sum(
                not heartbeat_is_stale(row, stale_after_seconds=settings.worker_stale_after_seconds)
                for row in workers
            )
            _metric(lines, "autonogrow_workers_active", active)
            _metric(lines, "autonogrow_workers_stale", len(workers) - active)
            for queue_name, model in (
                ("inbox", WebhookInboxEvent),
                ("outbox", ChannelOutboxMessage),
            ):
                for status, value in db.query(model.status, func.count(model.id)).group_by(
                    model.status
                ):
                    _metric(
                        lines, "autonogrow_queue_messages", value, queue=queue_name, status=status
                    )
            for status, value in db.query(
                BusinessChannelIntegration.integration_status,
                func.count(BusinessChannelIntegration.id),
            ).group_by(BusinessChannelIntegration.integration_status):
                _metric(lines, "autonogrow_integrations", value, status=status)
            for status, value in db.query(
                BusinessChannelIntegration.health_status,
                func.count(BusinessChannelIntegration.id),
            ).group_by(BusinessChannelIntegration.health_status):
                _metric(lines, "autonogrow_meta_integrations_health", value, status=status)
            for job_type, status, value in db.query(
                MetaIntegrationJob.job_type,
                MetaIntegrationJob.status,
                func.count(MetaIntegrationJob.id),
            ).group_by(MetaIntegrationJob.job_type, MetaIntegrationJob.status):
                _metric(
                    lines,
                    "autonogrow_meta_integration_jobs",
                    value,
                    job_type=job_type,
                    status=status,
                )
            health_jobs = db.query(MetaIntegrationJob).filter(
                MetaIntegrationJob.job_type == "health_check"
            )
            _metric(
                lines,
                "autonogrow_meta_integration_checks_scheduled_total",
                health_jobs.count(),
            )
            _metric(
                lines,
                "autonogrow_meta_integration_checks_started_total",
                health_jobs.with_entities(
                    func.coalesce(func.sum(MetaIntegrationJob.attempt_count), 0)
                ).scalar(),
            )
            _metric(
                lines,
                "autonogrow_meta_integration_checks_succeeded_total",
                health_jobs.filter(MetaIntegrationJob.status == "completed").count(),
            )
            _metric(
                lines,
                "autonogrow_meta_integration_checks_failed_total",
                health_jobs.filter(
                    MetaIntegrationJob.status.in_(("failed", "dead_letter"))
                ).count(),
            )
            duration_count, duration_sum = (
                db.query(
                    func.count(MetaIntegrationJob.id),
                    func.coalesce(func.sum(MetaIntegrationJob.duration_ms), 0),
                )
                .filter(MetaIntegrationJob.duration_ms.is_not(None))
                .one()
            )
            _metric(lines, "autonogrow_meta_integration_job_duration_ms_count", duration_count)
            _metric(lines, "autonogrow_meta_integration_job_duration_ms_sum", duration_sum)
            oldest_meta_job = (
                db.query(func.min(MetaIntegrationJob.available_at))
                .filter(MetaIntegrationJob.status.in_(("queued", "retry")))
                .scalar()
            )
            oldest_age = (
                max(0.0, (datetime.utcnow() - oldest_meta_job).total_seconds())
                if oldest_meta_job
                else 0
            )
            _metric(lines, "autonogrow_meta_integration_oldest_queued_seconds", oldest_age)
            last_cleanup = (
                db.query(MetaIntegrationJob.completed_at)
                .filter(
                    MetaIntegrationJob.job_type == "attempt_cleanup",
                    MetaIntegrationJob.status == "completed",
                )
                .order_by(MetaIntegrationJob.completed_at.desc())
                .first()
            )
            _metric(
                lines,
                "autonogrow_meta_integration_last_maintenance_timestamp_seconds",
                last_cleanup[0].timestamp() if last_cleanup and last_cleanup[0] else 0,
            )
            for action in (
                "integration_recovered",
                "reconnection_requested",
                "subscription_retry_succeeded",
                "expired_attempt_cleaned",
                "candidate_credentials_destroyed",
            ):
                _metric(
                    lines,
                    f"autonogrow_{action}_total",
                    db.query(AuditLog).filter(AuditLog.action == action).count(),
                )
            for status, value in db.query(Booking.status, func.count(Booking.id)).group_by(
                Booking.status
            ):
                _metric(lines, "autonogrow_bookings", value, status=status)
            for transaction_type, value in db.query(
                AutomationCreditTransaction.transaction_type,
                func.count(AutomationCreditTransaction.id),
            ).group_by(AutomationCreditTransaction.transaction_type):
                _metric(
                    lines,
                    "autonogrow_credit_transactions_total",
                    value,
                    transaction_type=transaction_type,
                )
            _metric(
                lines,
                "autonogrow_incidents_open",
                db.query(SystemIncident)
                .filter(SystemIncident.status.in_(("open", "acknowledged")))
                .count(),
            )
            last_backup = db.query(BackupRecord).order_by(BackupRecord.created_at.desc()).first()
            _metric(
                lines,
                "autonogrow_backup_last_timestamp_seconds",
                last_backup.created_at.timestamp() if last_backup else 0,
            )
    except Exception:
        _metric(lines, "autonogrow_database_health", 0)
        _metric(lines, "autonogrow_metrics_collection_error", 1, component="database")
    return "\n".join(lines) + "\n"
