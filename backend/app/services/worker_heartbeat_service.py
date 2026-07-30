from datetime import datetime, timedelta

from sqlalchemy.orm import Session

from app.models import WorkerHeartbeat


def update_worker_heartbeat(
    db: Session,
    *,
    worker_id: str,
    status: str,
    current_job_type: str | None = None,
    current_job_id: int | None = None,
    version: str | None = None,
    hostname: str | None = None,
    now: datetime | None = None,
) -> WorkerHeartbeat:
    current = now or datetime.utcnow()
    row = db.query(WorkerHeartbeat).filter(WorkerHeartbeat.worker_id == worker_id).first()
    if row is None:
        row = WorkerHeartbeat(
            worker_id=worker_id,
            worker_type="channel",
            status=status,
            started_at=current,
            last_seen_at=current,
        )
        db.add(row)
    row.status = status
    row.last_seen_at = current
    row.current_job_type = current_job_type
    row.current_job_id = current_job_id
    row.version = version
    row.hostname = hostname
    row.updated_at = current
    db.flush()
    return row


def heartbeat_is_stale(
    row: WorkerHeartbeat | None, *, stale_after_seconds: int, now: datetime | None = None
) -> bool:
    if row is None or row.status in {"stopped", "error"}:
        return True
    return row.last_seen_at < (now or datetime.utcnow()) - timedelta(seconds=stale_after_seconds)
