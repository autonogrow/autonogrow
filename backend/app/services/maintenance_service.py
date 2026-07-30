from __future__ import annotations

from datetime import datetime

from sqlalchemy.orm import Session

from app.models import OperationalState

MAINTENANCE_KEY = "maintenance"


def maintenance_state(db: Session) -> OperationalState | None:
    return db.query(OperationalState).filter(OperationalState.key == MAINTENANCE_KEY).first()


def maintenance_enabled(db: Session) -> bool:
    row = maintenance_state(db)
    return bool(row and row.enabled)


def set_maintenance(
    db: Session,
    *,
    enabled: bool,
    safe_reason: str | None,
    updated_by_user_id: int | None = None,
    now: datetime | None = None,
) -> OperationalState:
    current = now or datetime.utcnow()
    row = maintenance_state(db)
    if row is None:
        row = OperationalState(key=MAINTENANCE_KEY, enabled=False)
        db.add(row)
    row.enabled = enabled
    row.safe_reason = (safe_reason or "").strip()[:500] or None
    row.updated_by_user_id = updated_by_user_id
    row.enabled_at = current if enabled else row.enabled_at
    row.disabled_at = current if not enabled else None
    row.updated_at = current
    db.flush()
    return row
