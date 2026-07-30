from __future__ import annotations

import json
import re
from typing import Any

from sqlalchemy import inspect, text
from sqlalchemy.orm import Session

from app.core.migration_state import head_revisions
from app.models import (
    AvailabilitySettings,
    Business,
    BusinessChannelIntegration,
    BusinessService,
    BusinessStaffProfile,
    BusinessUser,
    ConversationAutomationSettings,
)
from app.services.business_onboarding_service import readiness_version

READINESS_SCHEMA_VERSION = 1


def _check(
    key: str,
    label: str,
    status: str,
    severity: str,
    message: str,
    remediation: str,
    blocking: bool,
    related_step: str,
) -> dict[str, Any]:
    return {
        "key": key,
        "label": label,
        "status": status,
        "severity": severity,
        "message": message,
        "remediation": remediation,
        "blocking": blocking,
        "related_step": related_step,
    }


def _valid_schedule(settings: AvailabilitySettings | None) -> bool:
    if settings is None:
        return False
    try:
        schedule = json.loads(settings.weekly_schedule_json)
    except (TypeError, ValueError):
        return False
    if not isinstance(schedule, dict):
        return False
    for windows in schedule.values():
        if not isinstance(windows, list):
            return False
        ordered: list[tuple[str, str]] = []
        for window in windows:
            if not isinstance(window, dict):
                return False
            start, end = window.get("start"), window.get("end")
            if not isinstance(start, str) or not isinstance(end, str) or start >= end:
                return False
            ordered.append((start, end))
        ordered.sort()
        if any(current[1] > following[0] for current, following in zip(ordered, ordered[1:])):
            return False
    return any(schedule.values())


def _database_migration_check(db: Session) -> tuple[str, str, bool]:
    # Reuse the session connection. Opening an inspector from the Engine can
    # issue a rollback on SQLite's single pooled connection mid-transition.
    if "alembic_version" not in inspect(db.connection()).get_table_names():
        return "not_applicable", "Entorno local sin control Alembic consultable", False
    current = db.execute(text("SELECT version_num FROM alembic_version")).scalar_one_or_none()
    heads = head_revisions()
    if len(heads) == 1 and current == heads[0]:
        return "passed", "Base de datos en la revisión operativa vigente", False
    return "failed", "La base de datos no está en la revisión operativa vigente", True


def evaluate_business_readiness(db: Session, business: Business) -> dict[str, Any]:
    checks: list[dict[str, Any]] = []

    valid_slug = bool(re.fullmatch(r"[a-z0-9]+(?:-[a-z0-9]+)*", business.slug or ""))
    identity_ok = bool((business.name or "").strip()) and valid_slug
    checks.append(
        _check(
            "identity",
            "Identidad",
            "passed" if identity_ok else "failed",
            "critical" if not identity_ok else "info",
            "Nombre y slug son válidos"
            if identity_ok
            else "Falta un nombre o el slug no es válido",
            "Completa nombre y slug en Identidad",
            not identity_ok,
            "business_identity",
        )
    )

    contact_ok = bool(business.phone or business.public_email or business.address)
    checks.append(
        _check(
            "contact",
            "Contacto",
            "passed" if contact_ok else "warning",
            "medium" if not contact_ok else "info",
            "Existe un canal público de contacto" if contact_ok else "No hay contacto público",
            "Añade teléfono, email o dirección pública",
            False,
            "contact_and_location",
        )
    )

    bookable_services = (
        db.query(BusinessService)
        .filter(
            BusinessService.business_id == business.id,
            BusinessService.active.is_(True),
            BusinessService.bookable.is_(True),
            BusinessService.archived_at.is_(None),
        )
        .count()
    )
    checks.append(
        _check(
            "services",
            "Servicios",
            "passed" if bookable_services else "failed",
            "critical" if not bookable_services else "info",
            f"{bookable_services} servicios reservables"
            if bookable_services
            else "No existe ningún servicio reservable",
            "Crea y activa al menos un servicio reservable",
            not bool(bookable_services),
            "services",
        )
    )

    staff_count = (
        db.query(BusinessUser)
        .filter(
            BusinessUser.business_id == business.id,
            BusinessUser.active.is_(True),
            BusinessUser.bookable.is_(True),
        )
        .count()
        + db.query(BusinessStaffProfile)
        .filter(
            BusinessStaffProfile.business_id == business.id,
            BusinessStaffProfile.active.is_(True),
        )
        .count()
    )
    checks.append(
        _check(
            "staff",
            "Personal",
            "passed" if staff_count else "warning",
            "medium" if not staff_count else "info",
            f"{staff_count} perfiles disponibles" if staff_count else "No hay personal configurado",
            "Añade personal si el negocio asigna reservas por profesional",
            False,
            "staff",
        )
    )

    availability = (
        db.query(AvailabilitySettings)
        .filter(AvailabilitySettings.business_id == business.id)
        .first()
    )
    schedule_ok = _valid_schedule(availability)
    checks.append(
        _check(
            "schedules",
            "Horarios",
            "passed" if schedule_ok else "failed",
            "critical" if not schedule_ok else "info",
            "Horario semanal válido" if schedule_ok else "No existe un horario semanal válido",
            "Configura al menos un intervalo sin solapamientos",
            not schedule_ok,
            "schedules",
        )
    )

    booking_ok = bool(
        availability
        and availability.slot_interval_minutes > 0
        and availability.max_days_ahead > 0
        and availability.min_notice_minutes <= availability.max_days_ahead * 1440
        and availability.cancellation_notice_minutes >= 0
        and availability.max_simultaneous_bookings >= 1
    )
    checks.append(
        _check(
            "booking",
            "Reservas",
            "passed" if booking_ok else "failed",
            "critical" if not booking_ok else "info",
            "Reglas de reserva coherentes"
            if booking_ok
            else "Las reglas de reserva son incoherentes",
            "Revisa antelación, horizonte, intervalo y capacidad",
            not booking_ok,
            "booking_rules",
        )
    )

    branding_ok = bool(business.logo_url and business.primary_color)
    checks.append(
        _check(
            "branding",
            "Branding",
            "passed" if branding_ok else "warning",
            "low",
            "Logo y color configurados" if branding_ok else "El branding está incompleto",
            "Añade un logo; la ausencia no bloquea la activación",
            False,
            "branding",
        )
    )

    landing_ok = bool(business.headline and business.description)
    checks.append(
        _check(
            "landing",
            "Landing",
            "passed" if landing_ok else "warning",
            "low",
            "Contenido principal configurado" if landing_ok else "Contenido y SEO incompletos",
            "Añade titular, descripción y SEO básico",
            False,
            "landing_content",
        )
    )

    automation = (
        db.query(ConversationAutomationSettings)
        .filter(ConversationAutomationSettings.business_id == business.id)
        .first()
    )
    automation_status = (
        "passed" if automation and automation.automation_enabled else "not_applicable"
    )
    checks.append(
        _check(
            "automations",
            "Automatizaciones",
            automation_status,
            "info",
            "Automatizaciones configuradas"
            if automation_status == "passed"
            else "Automatizaciones desactivadas",
            "Actívalas solo cuando textos y plan estén revisados",
            False,
            "automations",
        )
    )

    connected_integrations = (
        db.query(BusinessChannelIntegration)
        .filter(
            BusinessChannelIntegration.business_id == business.id,
            BusinessChannelIntegration.integration_status == "connected",
        )
        .count()
    )
    checks.append(
        _check(
            "integrations",
            "Integraciones",
            "passed" if connected_integrations else "warning",
            "low",
            "Integración conectada" if connected_integrations else "No hay integración conectada",
            "Instagram es recomendado, pero no obligatorio para un negocio básico",
            False,
            "integrations",
        )
    )

    credits_ok = bool(
        automation
        and automation.included_credits_per_period >= 0
        and automation.additional_credits_balance >= 0
    )
    credits_blocking = bool(automation and automation.automation_enabled and not credits_ok)
    checks.append(
        _check(
            "credits",
            "Plan y créditos",
            "passed" if credits_ok else "failed" if credits_blocking else "warning",
            "critical" if credits_blocking else "medium",
            "Wallet y periodo inicializados"
            if credits_ok
            else "Plan o wallet aún no inicializados",
            "Configura el plan antes de activar automatizaciones",
            credits_blocking,
            "credits_and_plan",
        )
    )

    migration_status, migration_message, migration_blocking = _database_migration_check(db)
    archived = business.status == "archived"
    security_blocking = archived or migration_blocking
    checks.append(
        _check(
            "security",
            "Seguridad operativa",
            "failed" if security_blocking else migration_status,
            "critical" if security_blocking else "info",
            "El negocio está archivado" if archived else migration_message,
            "Restaura explícitamente el negocio o aplica la migración pendiente",
            security_blocking,
            "readiness_review",
        )
    )

    blocking_count = sum(1 for item in checks if item["blocking"] and item["status"] == "failed")
    warning_count = sum(1 for item in checks if item["status"] == "warning")
    points = sum(
        1
        if item["status"] in {"passed", "not_applicable"}
        else 0.5
        if item["status"] == "warning"
        else 0
        for item in checks
    )
    score = round(points * 100 / len(checks))
    return {
        "schema_version": READINESS_SCHEMA_VERSION,
        "business_id": business.id,
        "ready": blocking_count == 0,
        "score": score,
        "blocking_count": blocking_count,
        "warning_count": warning_count,
        "checks": checks,
        "version": readiness_version(business, checks),
    }
