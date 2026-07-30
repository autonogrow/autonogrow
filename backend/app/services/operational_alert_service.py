from __future__ import annotations

import hashlib
import hmac
import json
import logging
import smtplib
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from email.message import EmailMessage
from typing import Any, Callable

import requests
from sqlalchemy.orm import Session

from app.core.config import Settings, get_settings
from app.models import AuditLog, SystemIncident

logger = logging.getLogger(__name__)
OPERATIONAL_CATEGORY_PREFIX = "operational_"


@dataclass(frozen=True)
class AlertSignal:
    component: str
    condition: str
    severity: str
    safe_details: dict[str, Any] = field(default_factory=dict)

    @property
    def fingerprint(self) -> str:
        value = f"operations:{self.component}:{self.condition}".encode()
        return hashlib.sha256(value).hexdigest()


def evaluate_operational_alerts(
    snapshot: dict[str, Any], settings: Settings | None = None, now: datetime | None = None
) -> list[AlertSignal]:
    active = settings or get_settings()
    current = now or datetime.utcnow()
    signals: list[AlertSignal] = []
    if not snapshot.get("ready", True):
        signals.append(AlertSignal("readiness", "not_ready", "critical"))
    if snapshot.get("database") and not snapshot["database"].get("at_head", False):
        signals.append(AlertSignal("database", "migration_not_at_head", "critical"))
    workers = snapshot.get("workers", {})
    if active.worker_enabled and workers.get("active", 0) == 0:
        signals.append(AlertSignal("worker", "none_active", "critical"))
    elif workers.get("stale", 0):
        signals.append(AlertSignal("worker", "stale", "warning", {"count": workers["stale"]}))
    queues = snapshot.get("queues", {})
    backlog = int(queues.get("backlog", 0))
    if backlog >= active.alert_queue_backlog_critical:
        signals.append(AlertSignal("queues", "backlog", "critical", {"count": backlog}))
    elif backlog >= active.alert_queue_backlog_warning:
        signals.append(AlertSignal("queues", "backlog", "warning", {"count": backlog}))
    oldest_seconds = float(queues.get("oldest_seconds", 0) or 0)
    if oldest_seconds >= active.alert_queue_oldest_critical_seconds:
        signals.append(
            AlertSignal("queues", "oldest_pending", "critical", {"age_seconds": oldest_seconds})
        )
    elif oldest_seconds >= active.alert_queue_oldest_warning_seconds:
        signals.append(
            AlertSignal("queues", "oldest_pending", "warning", {"age_seconds": oldest_seconds})
        )
    if int(queues.get("dead_letters", 0)):
        signals.append(
            AlertSignal(
                "queues",
                "dead_letters",
                "critical",
                {"count": int(queues["dead_letters"])},
            )
        )
    free_percent = float(snapshot.get("storage", {}).get("free_percent", 100))
    if free_percent <= active.alert_disk_free_critical_percent:
        signals.append(
            AlertSignal("storage", "disk_free", "critical", {"free_percent": free_percent})
        )
    elif free_percent <= active.alert_disk_free_warning_percent:
        signals.append(
            AlertSignal("storage", "disk_free", "warning", {"free_percent": free_percent})
        )
    backup_at = snapshot.get("backups", {}).get("last_at")
    backup_status = snapshot.get("backups", {}).get("last_status")
    if backup_status in {"failed", "invalid"}:
        signals.append(AlertSignal("backup", "last_invalid", "critical"))
    if not backup_at:
        signals.append(AlertSignal("backup", "never_completed", "warning"))
    else:
        if isinstance(backup_at, str):
            backup_at = datetime.fromisoformat(backup_at.replace("Z", "+00:00")).replace(
                tzinfo=None
            )
        age = current - backup_at
        if age > timedelta(hours=active.alert_backup_max_age_hours):
            signals.append(
                AlertSignal(
                    "backup",
                    "too_old",
                    "critical",
                    {"age_hours": round(age.total_seconds() / 3600, 1)},
                )
            )
    restore_at = snapshot.get("backups", {}).get("last_restore_test_at")
    if restore_at:
        if isinstance(restore_at, str):
            restore_at = datetime.fromisoformat(restore_at.replace("Z", "+00:00")).replace(
                tzinfo=None
            )
        if current - restore_at > timedelta(days=active.alert_restore_test_max_age_days):
            signals.append(AlertSignal("backup", "restore_test_too_old", "warning"))
    else:
        signals.append(AlertSignal("backup", "restore_never_tested", "warning"))
    integration_errors = sum(
        int(snapshot.get("integrations", {}).get(status, 0))
        for status in ("error", "expired", "revoked")
    )
    if integration_errors:
        signals.append(
            AlertSignal(
                "integrations",
                "unavailable",
                "warning",
                {"count": integration_errors},
            )
        )
    return signals


def persist_operational_alerts(
    db: Session,
    signals: list[AlertSignal],
    *,
    settings: Settings | None = None,
    notify: bool = True,
    sender: Callable[[AlertSignal, bool], bool] | None = None,
    now: datetime | None = None,
) -> dict[str, int]:
    active = settings or get_settings()
    current = now or datetime.utcnow()
    cooldown = timedelta(minutes=active.alert_cooldown_minutes)
    active_keys = {signal.fingerprint for signal in signals}
    counts = {"opened": 0, "updated": 0, "resolved": 0, "notified": 0}
    for signal in signals:
        incident = (
            db.query(SystemIncident)
            .filter(SystemIncident.incident_key == signal.fingerprint)
            .first()
        )
        if incident is None:
            incident = SystemIncident(
                incident_key=signal.fingerprint,
                severity=signal.severity,
                category=f"{OPERATIONAL_CATEGORY_PREFIX}{signal.component}",
                status="open",
                channel="operations",
                provider="internal",
                operation=signal.condition,
                occurrence_count=1,
                first_occurred_at=current,
                last_occurred_at=current,
                safe_details_json=json.dumps(signal.safe_details, sort_keys=True),
                created_at=current,
                updated_at=current,
            )
            db.add(incident)
            db.flush()
            db.add(
                AuditLog(
                    action="operational_alert_opened",
                    resource_type="system_incident",
                    resource_id=str(incident.id),
                    metadata_json=json.dumps(
                        {"component": signal.component, "condition": signal.condition}
                    ),
                )
            )
            counts["opened"] += 1
        else:
            incident.occurrence_count += 1
            incident.last_occurred_at = current
            incident.updated_at = current
            incident.safe_details_json = json.dumps(signal.safe_details, sort_keys=True)
            incident.severity = signal.severity
            if incident.status in {"resolved", "ignored"}:
                incident.status = "open"
                incident.resolved_at = None
                incident.first_occurred_at = current
            counts["updated"] += 1
        should_notify = (
            notify
            and active.operational_alerts_enabled
            and (incident.notified_at is None or current - incident.notified_at >= cooldown)
        )
        if should_notify:
            delivered = sender(signal, False) if sender else _notify_channels(signal, False, active)
            if delivered:
                incident.notified_at = current
                counts["notified"] += 1
    unresolved = db.query(SystemIncident).filter(
        SystemIncident.category.like(f"{OPERATIONAL_CATEGORY_PREFIX}%"),
        SystemIncident.status.in_(("open", "acknowledged")),
    )
    for incident in unresolved:
        if incident.incident_key in active_keys:
            continue
        incident.status = "resolved"
        incident.resolved_at = current
        incident.updated_at = current
        counts["resolved"] += 1
        db.add(
            AuditLog(
                action="operational_alert_resolved",
                resource_type="system_incident",
                resource_id=str(incident.id),
                metadata_json=json.dumps(
                    {
                        "component": incident.category.removeprefix(OPERATIONAL_CATEGORY_PREFIX),
                        "condition": incident.operation,
                    }
                ),
            )
        )
        if notify and active.operational_alerts_enabled and incident.notified_at is not None:
            recovery = AlertSignal(
                incident.category.removeprefix(OPERATIONAL_CATEGORY_PREFIX),
                incident.operation,
                incident.severity,
            )
            if sender:
                sender(recovery, True)
            else:
                _notify_channels(recovery, True, active)
    db.flush()
    return counts


def _log_notification(signal: AlertSignal, recovery: bool) -> bool:
    logger.log(
        logging.INFO if recovery else logging.ERROR,
        "operational alert recovery" if recovery else "operational alert",
        extra={
            "event": "operational_alert_resolved" if recovery else "operational_alert_opened",
            "operation": f"{signal.component}.{signal.condition}",
            "result": "recovered" if recovery else signal.severity,
            "details": signal.safe_details,
        },
    )
    return True


def _notify_channels(signal: AlertSignal, recovery: bool, settings: Settings) -> bool:
    delivered = _log_notification(signal, recovery)
    payload = {
        "event": "resolved" if recovery else "open",
        "component": signal.component,
        "condition": signal.condition,
        "severity": signal.severity,
        "details": signal.safe_details,
        "release_id": settings.app_release_id,
    }
    recipients = [item for item in settings.alert_email_recipient_list if "@" in item]
    if recipients and settings.smtp_host and settings.smtp_from:
        message = EmailMessage()
        message["Subject"] = (
            f"[AutonoGrow] {'RECOVERY' if recovery else signal.severity.upper()} "
            f"{signal.component}.{signal.condition}"
        )
        message["From"] = settings.smtp_from
        message["To"] = ", ".join(recipients)
        message.set_content(json.dumps(payload, indent=2, sort_keys=True))
        try:
            with smtplib.SMTP(settings.smtp_host, settings.smtp_port, timeout=10) as smtp:
                if settings.smtp_use_tls:
                    smtp.starttls()
                if settings.smtp_username:
                    smtp.login(settings.smtp_username, settings.smtp_password)
                smtp.send_message(message)
        except (OSError, smtplib.SMTPException):
            logger.exception(
                "operational email notification failed",
                extra={"event": "operational_alert_email_failed"},
            )
    if settings.alert_webhook_url:
        body = json.dumps(payload, separators=(",", ":"), sort_keys=True).encode()
        headers = {"Content-Type": "application/json"}
        if settings.alert_webhook_secret:
            headers["X-AutonoGrow-Signature"] = hmac.new(
                settings.alert_webhook_secret.encode(), body, hashlib.sha256
            ).hexdigest()
        try:
            response = requests.post(
                settings.alert_webhook_url,
                data=body,
                headers=headers,
                timeout=10,
                allow_redirects=False,
            )
            response.raise_for_status()
        except requests.RequestException:
            logger.exception(
                "operational webhook notification failed",
                extra={"event": "operational_alert_webhook_failed"},
            )
    return delivered
