import hashlib
import json
from typing import Any

from fastapi import Request
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.observability import redact_sensitive
from app.models.audit_log import AuditLog
from app.models.user import User


def _hash(value: str | None) -> str | None:
    if not value:
        return None
    secret = get_settings().session_secret or "local-audit-salt"
    return hashlib.sha256(f"{secret}:{value}".encode("utf-8")).hexdigest()


def record_audit(
    db: Session,
    *,
    action: str,
    request: Request | None = None,
    actor: User | None = None,
    business_id: int | None = None,
    resource_type: str | None = None,
    resource_id: int | str | None = None,
    metadata: dict[str, Any] | None = None,
    commit: bool = True,
) -> AuditLog:
    request_id = getattr(request.state, "request_id", None) if request else None
    safe_metadata: dict[str, Any] | None = redact_sensitive(dict(metadata or {}))
    if request_id:
        assert safe_metadata is not None
        safe_metadata.setdefault("request_id", request_id)
    safe_metadata = safe_metadata or None
    item = AuditLog(
        actor_user_id=actor.id if actor else None,
        actor_email=actor.email if actor else None,
        business_id=business_id,
        action=action,
        resource_type=resource_type,
        resource_id=str(resource_id) if resource_id is not None else None,
        ip_hash=_hash(request.client.host if request and request.client else None),
        user_agent_hash=_hash(request.headers.get("user-agent") if request else None),
        metadata_json=json.dumps(safe_metadata, ensure_ascii=False, sort_keys=True)
        if safe_metadata
        else None,
    )
    db.add(item)
    if commit:
        db.commit()
    else:
        db.flush()
    return item
