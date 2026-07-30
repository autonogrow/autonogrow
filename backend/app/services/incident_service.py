from __future__ import annotations

import hashlib
import json
import logging
import smtplib
from datetime import datetime, timedelta, timezone
from email.message import EmailMessage
from typing import Any
from zoneinfo import ZoneInfo

from sqlalchemy.orm import Session

from app.core.config import Settings, get_settings
from app.core.observability import request_id_context
from app.models import SystemIncident

logger = logging.getLogger(__name__)

SEVERITY_ORDER = {"low": 0, "medium": 1, "high": 2, "critical": 3}
SEVERITY_LABELS = {
    "low": "BAJA",
    "medium": "MEDIA",
    "high": "ALTA",
    "critical": "CRÍTICA",
}
ACTIVE_STATUSES = ("open", "acknowledged")
SAFE_DETAIL_KEYS = {
    "error_type",
    "error_subcode",
    "http_status",
    "intent",
    "impact",
    "recommended_action",
    "retryable",
    "component",
    "source",
    "external_account_id",
    "event_type",
    "provider_message_id",
    "integration_status",
    "request_id",
}
DEFAULT_CATEGORY_SEVERITIES = {
    "database_unavailable": "critical",
    "connection_timeout": "high",
    "deadlock_detected": "medium",
    "lock_timeout": "medium",
    "pool_timeout": "high",
    "serialization_failure": "medium",
    "database_statement_timeout": "high",
    "onboarding_template_failed": "high",
    "onboarding_clone_failed": "high",
    "onboarding_activation_failed": "critical",
    "onboarding_readiness_error": "high",
    "onboarding_media_copy_failed": "high",
    "onboarding_plan_initialization_failed": "high",
    "tenant_isolation_failure": "critical",
    "security_incident": "critical",
    "backend_unavailable": "critical",
    "webhook_unavailable": "critical",
    "provider_authentication": "high",
    "invalid_credentials": "high",
    "channel_delivery_failure": "high",
    "provider_disconnected": "high",
    "business_automation_blocked": "high",
    "provider_timeout": "medium",
    "message_format_rejected": "medium",
    "attachment_incompatible": "medium",
    "provider_temporary_error": "medium",
    "provider_send_failure": "medium",
    "instagram_authentication": "high",
    "instagram_token_expired": "high",
    "instagram_token_revoked": "high",
    "instagram_verification_failed": "medium",
    "instagram_unmapped_account": "medium",
    "integration_decryption_failed": "high",
    "polling_failure": "low",
    "interface_recoverable": "low",
    "static_resource_failure": "low",
}

INSTAGRAM_AUTH_CLIENT_MESSAGE = (
    "La conexión con Instagram necesita revisión. El equipo de AutonoGrow ya ha sido "
    "avisado y gestionará la incidencia."
)
GENERIC_SEND_CLIENT_MESSAGE = (
    "No se ha podido enviar el mensaje. El equipo de AutonoGrow ha recibido el aviso y "
    "revisará la incidencia."
)


def incident_reference(incident: SystemIncident) -> str:
    occurred = incident.first_occurred_at or incident.created_at or datetime.utcnow()
    return f"AGW-{occurred:%Y%m%d}-{incident.id:05d}"


def build_incident_key(
    *,
    business_id: int | None,
    provider: str | None,
    channel: str | None,
    provider_error_code: str | int | None,
    operation: str,
    integration_id: int | None = None,
) -> str:
    parts = (
        str(business_id or "global"),
        (provider or "none").strip().lower(),
        (channel or "none").strip().lower(),
        str(provider_error_code or "none").strip().lower(),
        operation.strip().lower(),
        str(integration_id or "none"),
    )
    digest = hashlib.sha256("\x1f".join(parts).encode("utf-8")).hexdigest().upper()
    return f"AGW-{digest[:32]}"


def sanitize_safe_details(value: dict[str, Any] | None) -> dict[str, Any]:
    if not isinstance(value, dict):
        return {}
    result: dict[str, Any] = {}
    for key in SAFE_DETAIL_KEYS:
        item = value.get(key)
        if isinstance(item, bool) or item is None:
            if item is not None:
                result[key] = item
        elif isinstance(item, (int, float)):
            result[key] = item
        elif isinstance(item, str):
            result[key] = item[:500]
    return result


def classify_provider_error(
    *,
    provider: str,
    error_code: str | int | None,
    error_type: str | None = None,
    timed_out: bool = False,
) -> tuple[str, str]:
    normalized_provider = provider.strip().lower()
    normalized_code = str(error_code) if error_code is not None else None
    normalized_type = (error_type or "").strip().lower()
    if normalized_provider == "instagram" and normalized_code == "190":
        return "instagram_token_revoked", "high"
    if any(marker in normalized_type for marker in ("oauth", "authentication", "invalid_token")):
        return (
            "instagram_authentication"
            if normalized_provider == "instagram"
            else "provider_authentication",
            "high",
        )
    if timed_out:
        return "provider_timeout", "medium"
    return "provider_send_failure", "medium"


def enforce_incident_severity(category: str, severity: str, provider_error_code: str | None) -> str:
    minimum = DEFAULT_CATEGORY_SEVERITIES.get(category)
    if provider_error_code == "190":
        minimum = "high"
    if minimum and SEVERITY_ORDER[minimum] > SEVERITY_ORDER[severity]:
        return minimum
    return severity


def client_message_for_incident(incident: SystemIncident) -> str:
    message = (
        INSTAGRAM_AUTH_CLIENT_MESSAGE
        if incident.category
        in {
            "provider_authentication",
            "instagram_authentication",
            "instagram_token_expired",
            "instagram_token_revoked",
            "integration_decryption_failed",
        }
        and incident.channel == "instagram"
        else GENERIC_SEND_CLIENT_MESSAGE
    )
    return f"{message} Incidencia: {incident_reference(incident)}."


def _safe_details(incident: SystemIncident) -> dict[str, Any]:
    try:
        parsed = json.loads(incident.safe_details_json or "{}")
    except (TypeError, ValueError):
        return {}
    return parsed if isinstance(parsed, dict) else {}


def serialize_incident(
    incident: SystemIncident, *, include_safe_details: bool = True
) -> dict[str, Any]:
    payload = {
        "id": incident.id,
        "incident_id": incident_reference(incident),
        "status": incident.status,
        "severity": incident.severity,
        "category": incident.category,
        "business_id": incident.business_id,
        "integration_id": incident.integration_id,
        "business_slug": incident.business.slug if incident.business else None,
        "business_name": incident.business.name if incident.business else None,
        "channel": incident.channel,
        "provider": incident.provider,
        "provider_error_code": incident.provider_error_code,
        "operation": incident.operation,
        "conversation_id": incident.conversation_id,
        "message_id": incident.message_id,
        "occurrence_count": incident.occurrence_count,
        "first_occurred_at": incident.first_occurred_at.isoformat(),
        "last_occurred_at": incident.last_occurred_at.isoformat(),
        "notified_at": incident.notified_at.isoformat() if incident.notified_at else None,
        "resolved_at": incident.resolved_at.isoformat() if incident.resolved_at else None,
        "created_at": incident.created_at.isoformat() if incident.created_at else None,
        "updated_at": incident.updated_at.isoformat() if incident.updated_at else None,
    }
    if include_safe_details:
        payload["safe_details"] = _safe_details(incident)
    return payload


def _incident_email(incident: SystemIncident, *, recovery: bool = False) -> tuple[str, str]:
    details = _safe_details(incident)
    business_slug = incident.business.slug if incident.business else "global"
    business_name = incident.business.name if incident.business else "Sin negocio asociado"
    utc_time = incident.last_occurred_at.replace(tzinfo=timezone.utc)
    local_time = utc_time.astimezone(ZoneInfo("Europe/Madrid"))
    prefix = (
        "Recuperación"
        if recovery
        else (
            "Fallo de conexión con Instagram"
            if incident.category
            in {
                "provider_authentication",
                "instagram_authentication",
                "instagram_token_expired",
                "instagram_token_revoked",
                "integration_decryption_failed",
            }
            and incident.channel == "instagram"
            else incident.category.replace("_", " ").capitalize()
        )
    )
    subject = f"[AutonoGrow][{SEVERITY_LABELS[incident.severity]}] {prefix} — {business_slug}"
    body = "\n".join(
        (
            f"Incidencia: {incident_reference(incident)}",
            f"Estado: {incident.status}",
            f"Fecha UTC: {utc_time.isoformat()}",
            f"Fecha Europe/Madrid: {local_time.isoformat()}",
            f"Severidad: {incident.severity}",
            f"Negocio: {incident.business_id or '-'} / {business_slug} / {business_name}",
            f"Canal: {incident.channel or '-'}",
            f"Proveedor: {incident.provider or '-'}",
            f"Código proveedor: {incident.provider_error_code or '-'}",
            f"Operación: {incident.operation}",
            f"conversation_id: {incident.conversation_id or '-'}",
            f"message_id local: {incident.message_id or '-'}",
            f"Intent: {details.get('intent', '-')}",
            f"Ocurrencias: {incident.occurrence_count}",
            f"Impacto: {details.get('impact', 'Operación no completada; el resto del panel sigue disponible.')}",
            f"Acción recomendada: {details.get('recommended_action', 'Revisar la conexión y el estado del proveedor.')}",
        )
    )
    return subject, body


def _send_email(settings: Settings, subject: str, body: str) -> None:
    message = EmailMessage()
    message["Subject"] = subject
    message["From"] = settings.smtp_from.strip()
    message["To"] = settings.incident_alert_email.strip()
    message.set_content(body)
    with smtplib.SMTP(settings.smtp_host.strip(), settings.smtp_port, timeout=10) as smtp:
        if settings.smtp_use_tls:
            smtp.starttls()
        if settings.smtp_username.strip():
            smtp.login(settings.smtp_username.strip(), settings.smtp_password)
        smtp.send_message(message)


def _notify(incident: SystemIncident, settings: Settings, *, recovery: bool = False) -> bool:
    if not settings.incident_alerts_enabled:
        return False
    subject, body = _incident_email(incident, recovery=recovery)
    try:
        _send_email(settings, subject, body)
    except Exception as error:
        logger.error(
            "Incident email failed: incident_id=%s error_type=%s",
            incident_reference(incident),
            type(error).__name__,
        )
        return False
    return True


def report_incident(
    db: Session,
    category: str,
    severity: str,
    business_id: int | None,
    channel: str | None,
    provider: str | None,
    provider_error_code: str | int | None,
    operation: str,
    integration_id: int | None = None,
    conversation_id: int | None = None,
    message_id: int | None = None,
    safe_details: dict[str, Any] | None = None,
    *,
    settings: Settings | None = None,
    occurred_at: datetime | None = None,
) -> SystemIncident:
    normalized_severity = severity.strip().lower()
    if normalized_severity not in SEVERITY_ORDER:
        raise ValueError("Invalid incident severity")
    normalized_category = category.strip().lower()
    normalized_operation = operation.strip().lower()
    if not normalized_category or not normalized_operation:
        raise ValueError("Incident category and operation are required")
    now = occurred_at or datetime.utcnow()
    code = str(provider_error_code)[:80] if provider_error_code is not None else None
    normalized_severity = enforce_incident_severity(normalized_category, normalized_severity, code)
    key = build_incident_key(
        business_id=business_id,
        provider=provider,
        channel=channel,
        provider_error_code=code,
        operation=normalized_operation,
        integration_id=integration_id,
    )
    incident = db.query(SystemIncident).filter(SystemIncident.incident_key == key).first()
    if incident is None:
        incident = SystemIncident(
            incident_key=key,
            severity=normalized_severity,
            category=normalized_category,
            status="open",
            business_id=business_id,
            integration_id=integration_id,
            channel=channel.strip().lower() if channel else None,
            provider=provider.strip().lower() if provider else None,
            provider_error_code=code,
            operation=normalized_operation,
            conversation_id=conversation_id,
            message_id=message_id,
            occurrence_count=1,
            first_occurred_at=now,
            last_occurred_at=now,
            safe_details_json=json.dumps(
                sanitize_safe_details(
                    {**(safe_details or {}), "request_id": request_id_context.get()}
                ),
                ensure_ascii=False,
            ),
            created_at=now,
            updated_at=now,
        )
        db.add(incident)
        db.flush()
    else:
        incident.occurrence_count += 1
        incident.last_occurred_at = now
        incident.updated_at = now
        incident.conversation_id = conversation_id or incident.conversation_id
        incident.message_id = message_id or incident.message_id
        incident.safe_details_json = json.dumps(
            sanitize_safe_details({**(safe_details or {}), "request_id": request_id_context.get()}),
            ensure_ascii=False,
        )
        if SEVERITY_ORDER[normalized_severity] > SEVERITY_ORDER[incident.severity]:
            incident.severity = normalized_severity
        if incident.status in {"resolved", "ignored"}:
            incident.status = "open"
            incident.resolved_at = None
        db.flush()

    active_settings = settings or get_settings()
    window = timedelta(minutes=active_settings.incident_dedup_window_minutes)
    should_alert = (
        SEVERITY_ORDER[incident.severity]
        >= SEVERITY_ORDER[active_settings.incident_alert_min_severity]
        and incident.status in ACTIVE_STATUSES
        and (incident.notified_at is None or now - incident.notified_at >= window)
    )
    if should_alert and _notify(incident, active_settings):
        incident.notified_at = now
        incident.updated_at = now

    logger.warning(
        "Incident reported: incident_id=%s incident_key=%s... severity=%s category=%s "
        "business_id=%s provider=%s code=%s occurrence_count=%s",
        incident_reference(incident),
        incident.incident_key[:12],
        incident.severity,
        incident.category,
        incident.business_id,
        incident.provider,
        incident.provider_error_code,
        incident.occurrence_count,
    )
    return incident


def resolve_related_incidents(
    db: Session,
    *,
    business_id: int | None,
    channel: str | None,
    provider: str | None,
    operation: str,
    integration_id: int | None = None,
    settings: Settings | None = None,
    resolved_at: datetime | None = None,
) -> list[SystemIncident]:
    now = resolved_at or datetime.utcnow()
    query = db.query(SystemIncident).filter(
        SystemIncident.business_id == business_id,
        SystemIncident.channel == channel,
        SystemIncident.provider == provider,
        SystemIncident.operation == operation,
        SystemIncident.status.in_(ACTIVE_STATUSES),
    )
    if integration_id is not None:
        query = query.filter(SystemIncident.integration_id == integration_id)
    rows = query.all()
    active_settings = settings or get_settings()
    for incident in rows:
        incident.status = "resolved"
        incident.resolved_at = now
        incident.updated_at = now
        if (
            active_settings.incident_recovery_email_enabled
            and incident.notified_at is not None
            and _notify(incident, active_settings, recovery=True)
        ):
            incident.notified_at = now
        logger.info(
            "Incident resolved: incident_id=%s severity=%s category=%s business_id=%s",
            incident_reference(incident),
            incident.severity,
            incident.category,
            incident.business_id,
        )
    return rows
