from __future__ import annotations

import json
import os
import tempfile
import time
from datetime import datetime
from typing import Any

from sqlalchemy import func, text
from sqlalchemy.orm import Session

from app.core.config import get_settings, get_uploads_dir
from app.core.database import engine, safe_database_pool_status
from app.core.migration_state import inspect_database_migration_state
from app.models import (
    BackupRecord,
    BusinessChannelIntegration,
    ChannelOutboxMessage,
    SystemIncident,
    WebhookInboxEvent,
    WorkerHeartbeat,
)
from app.services.maintenance_service import maintenance_enabled
from app.services.storage_health_service import storage_health
from app.services.worker_heartbeat_service import heartbeat_is_stale

_PROCESS_STARTED = time.monotonic()


def _keyring_ready() -> bool:
    settings = get_settings()
    if not settings.instagram_provider_enabled:
        return True
    try:
        keys = json.loads(settings.integration_encryption_keys_json)
    except (TypeError, ValueError):
        return False
    return isinstance(keys, dict) and settings.integration_encryption_active_key_version in keys


def _uploads_writable() -> bool:
    uploads = get_uploads_dir()
    if not os.access(uploads, os.W_OK):
        return False
    try:
        with tempfile.NamedTemporaryFile(prefix=".ready-", dir=uploads, delete=True):
            return True
    except OSError:
        return False


def readiness_checks() -> tuple[bool, dict[str, Any]]:
    settings = get_settings()
    checks: dict[str, Any] = {}
    started = time.monotonic()
    try:
        with engine.connect() as connection:
            connection.execute(text("SELECT 1")).scalar_one()
        checks["database"] = True
    except Exception:
        checks["database"] = False
    try:
        migration = inspect_database_migration_state(engine)
        checks["migration"] = migration.is_at_head
    except Exception:
        checks["migration"] = False
    checks["keyring"] = _keyring_ready()
    checks["uploads"] = _uploads_writable()
    try:
        checks["disk"] = storage_health()["free_bytes"] >= settings.readiness_min_disk_free_bytes
    except Exception:
        checks["disk"] = False
    try:
        with Session(engine) as db:
            checks["maintenance"] = not maintenance_enabled(db)
    except Exception:
        checks["maintenance"] = False
    checks["timeout"] = time.monotonic() - started <= settings.readiness_timeout_seconds
    return all(checks.values()), checks


def _counts(
    db: Session, model: type[WebhookInboxEvent] | type[ChannelOutboxMessage]
) -> dict[str, int]:
    return {
        status: count
        for status, count in db.query(model.status, func.count(model.id)).group_by(model.status)
    }


def owner_system_health(db: Session) -> dict[str, Any]:
    settings = get_settings()
    started = time.perf_counter()
    db.execute(text("SELECT 1")).scalar_one()
    db_latency = round((time.perf_counter() - started) * 1000, 2)
    migration = inspect_database_migration_state(db.get_bind())
    workers = (
        db.query(WorkerHeartbeat).order_by(WorkerHeartbeat.last_seen_at.desc()).limit(100).all()
    )
    active_workers = [
        row
        for row in workers
        if not heartbeat_is_stale(row, stale_after_seconds=settings.worker_stale_after_seconds)
    ]
    inbox = _counts(db, WebhookInboxEvent)
    outbox = _counts(db, ChannelOutboxMessage)
    oldest = min(
        (
            value
            for value in (
                db.query(func.min(WebhookInboxEvent.available_at))
                .filter(WebhookInboxEvent.status.in_(("pending", "retry")))
                .scalar(),
                db.query(func.min(ChannelOutboxMessage.available_at))
                .filter(ChannelOutboxMessage.status.in_(("pending", "retry")))
                .scalar(),
            )
            if value is not None
        ),
        default=None,
    )
    last_backup = db.query(BackupRecord).order_by(BackupRecord.created_at.desc()).first()
    last_verified = (
        db.query(BackupRecord)
        .filter(BackupRecord.verified_at.is_not(None))
        .order_by(BackupRecord.verified_at.desc())
        .first()
    )
    last_restore = (
        db.query(BackupRecord)
        .filter(BackupRecord.restore_tested_at.is_not(None))
        .order_by(BackupRecord.restore_tested_at.desc())
        .first()
    )
    open_incidents = (
        db.query(SystemIncident).filter(SystemIncident.status.in_(("open", "acknowledged"))).count()
    )
    integration_counts = {
        status: count
        for status, count in db.query(
            BusinessChannelIntegration.integration_status,
            func.count(BusinessChannelIntegration.id),
        ).group_by(BusinessChannelIntegration.integration_status)
    }
    return {
        "backend": {
            "version": settings.app_version,
            "release_id": settings.app_release_id,
            "git_commit": settings.app_git_commit,
            "build_time": settings.app_build_time,
            "uptime_seconds": round(time.monotonic() - _PROCESS_STARTED, 2),
        },
        "database": {
            **safe_database_pool_status(db.get_bind()),
            "latency_ms": db_latency,
            "current_revisions": list(migration.current_revisions),
            "head_revisions": list(migration.head_revisions),
            "at_head": migration.is_at_head,
        },
        "workers": {
            "configured": settings.worker_enabled,
            "active": len(active_workers),
            "stale": len(workers) - len(active_workers),
            "last_heartbeat": workers[0].last_seen_at.isoformat() if workers else None,
            "versions": sorted({row.version for row in workers if row.version}),
        },
        "queues": {
            "inbox": inbox,
            "outbox": outbox,
            "oldest_pending_at": oldest.isoformat() if oldest else None,
        },
        "storage": storage_health(),
        "backups": {
            "last_at": last_backup.created_at.isoformat() if last_backup else None,
            "last_status": last_backup.status if last_backup else "never",
            "last_verified_at": last_verified.verified_at.isoformat() if last_verified else None,
            "last_restore_test_at": last_restore.restore_tested_at.isoformat()
            if last_restore
            else None,
        },
        "alerts": {"open_incidents": open_incidents},
        "integrations": integration_counts,
        "maintenance": maintenance_enabled(db),
        "generated_at": datetime.utcnow().isoformat(),
    }
