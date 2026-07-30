from __future__ import annotations

from copy import deepcopy
from typing import Any

BASE_SCHEDULE = {
    "0": [],
    "1": [{"start": "10:00", "end": "14:00"}, {"start": "16:00", "end": "20:00"}],
    "2": [{"start": "10:00", "end": "14:00"}, {"start": "16:00", "end": "20:00"}],
    "3": [{"start": "10:00", "end": "14:00"}, {"start": "16:00", "end": "20:00"}],
    "4": [{"start": "10:00", "end": "14:00"}, {"start": "16:00", "end": "20:00"}],
    "5": [{"start": "10:00", "end": "14:00"}, {"start": "16:00", "end": "20:00"}],
    "6": [{"start": "10:00", "end": "14:00"}],
}

BASE_BOOKING_RULES = {
    "min_notice_minutes": 120,
    "max_days_ahead": 30,
    "slot_interval_minutes": 15,
    "buffer_between_bookings_minutes": 0,
    "auto_confirm_bookings": True,
    "cancellation_allowed": True,
    "cancellation_notice_minutes": 120,
    "reschedule_allowed": True,
    "max_simultaneous_bookings": 1,
}

BASE_AUTOMATIONS = {
    "automation_enabled": False,
    "auto_threshold": 80,
    "human_reply_pause_minutes": 60,
    "messages": {
        "welcome": "Hola, gracias por contactar con {{business_name}}.",
        "booking_confirmation": (
            "Tu reserva de {{service_name}} queda confirmada para "
            "{{booking_date}} a las {{booking_time}}."
        ),
    },
}

BASE_BRANDING = {
    "theme_key": "slate_gold",
    "template_key": "classic",
    "primary_color": "#334155",
    "secondary_color": "#0f172a",
    "accent_color": "#f59e0b",
    "background_color": "#f8fafc",
}


def _template(
    key: str,
    name: str,
    category: str,
    description: str,
    services: list[dict[str, Any]],
    *,
    branding: dict[str, Any] | None = None,
    schedule: dict[str, list[dict[str, str]]] | None = None,
) -> dict[str, Any]:
    return {
        "key": key,
        "name": name,
        "category": category,
        "description": description,
        "version": 1,
        "configuration": {
            "identity": {"category": category},
            "services": services,
            "schedules": {
                "timezone": "Europe/Madrid",
                "weekly_schedule": deepcopy(schedule or BASE_SCHEDULE),
            },
            "booking_rules": deepcopy(BASE_BOOKING_RULES),
            "branding": deepcopy(branding or BASE_BRANDING),
            "landing_content": {
                "landing_cta": "Reservar cita",
                "seo_title": name,
            },
            "automations": deepcopy(BASE_AUTOMATIONS),
        },
    }


SYSTEM_ONBOARDING_TEMPLATES = (
    _template(
        "generic",
        "Plantilla genérica",
        "Servicios",
        "Punto de partida neutral y editable.",
        [{"name": "Servicio inicial", "duration_minutes": 30, "bookable": True}],
    ),
    _template(
        "barbershop",
        "Barbería y peluquería",
        "Barbería",
        "Servicios habituales, agenda profesional y estética urbana.",
        [
            {"name": "Corte", "duration_minutes": 30, "bookable": True},
            {"name": "Corte y barba", "duration_minutes": 45, "bookable": True},
            {"name": "Barba", "duration_minutes": 20, "bookable": True},
        ],
        branding={**BASE_BRANDING, "theme_key": "amber_barber", "template_key": "urban"},
    ),
    _template(
        "beauty",
        "Manicura y estética",
        "Estética",
        "Servicios de belleza con duraciones y presentación orientativas.",
        [
            {"name": "Manicura", "duration_minutes": 45, "bookable": True},
            {"name": "Pedicura", "duration_minutes": 60, "bookable": True},
            {"name": "Tratamiento facial", "duration_minutes": 60, "bookable": True},
        ],
        branding={**BASE_BRANDING, "theme_key": "rose_beauty", "template_key": "beauty"},
    ),
    _template(
        "workshop",
        "Taller",
        "Taller",
        "Recepción de trabajos con aprobación y agenda diurna.",
        [
            {
                "name": "Diagnóstico",
                "duration_minutes": 45,
                "bookable": True,
                "requires_approval": True,
            },
            {
                "name": "Mantenimiento",
                "duration_minutes": 90,
                "bookable": True,
                "requires_approval": True,
            },
        ],
        schedule={
            "0": [],
            **{
                str(day): [
                    {"start": "09:00", "end": "14:00"},
                    {"start": "16:00", "end": "19:00"},
                ]
                for day in range(1, 6)
            },
            "6": [],
        },
    ),
    _template(
        "restaurant",
        "Restaurante",
        "Restauración",
        "Reservas por turnos con capacidad inicial conservadora.",
        [
            {"name": "Reserva de mesa", "duration_minutes": 90, "bookable": True},
            {"name": "Menú de grupo", "duration_minutes": 120, "bookable": True},
        ],
    ),
    _template(
        "clinic",
        "Clínica o consulta",
        "Salud",
        "Agenda de consulta con aprobación y aspecto clínico.",
        [
            {
                "name": "Primera consulta",
                "duration_minutes": 60,
                "bookable": True,
                "requires_approval": True,
            },
            {"name": "Seguimiento", "duration_minutes": 30, "bookable": True},
        ],
        branding={**BASE_BRANDING, "theme_key": "blue_clinic", "template_key": "clinic"},
    ),
)


FORBIDDEN_TEMPLATE_KEY_PARTS = (
    "password",
    "secret",
    "credential",
    "ciphertext",
    "access_token",
    "account_id",
    "customer_email",
    "customer_phone",
)


def template_has_forbidden_data(value: Any, *, path: str = "root") -> list[str]:
    findings: list[str] = []
    if isinstance(value, dict):
        for key, nested in value.items():
            normalized = str(key).casefold()
            if any(part in normalized for part in FORBIDDEN_TEMPLATE_KEY_PARTS):
                findings.append(f"{path}.{key}")
            findings.extend(template_has_forbidden_data(nested, path=f"{path}.{key}"))
    elif isinstance(value, list):
        for index, nested in enumerate(value):
            findings.extend(template_has_forbidden_data(nested, path=f"{path}[{index}]"))
    return findings
