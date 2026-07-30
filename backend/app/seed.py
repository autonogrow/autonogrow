import json

from app.core.database import SessionLocal, create_db_and_tables
from app.models import (
    AvailabilityException,
    AvailabilitySettings,
    Booking,
    Business,
    BusinessService,
    Customer,
    MessageOutbox,
    ReviewRequest,
    SyncJob,
    WeeklyAvailability,
)

DEFAULT_WEEKLY_SCHEDULE = {
    0: [],
    1: [{"start": "10:00", "end": "20:00"}],
    2: [{"start": "10:00", "end": "20:00"}],
    3: [{"start": "10:00", "end": "20:00"}],
    4: [{"start": "10:00", "end": "20:00"}],
    5: [{"start": "10:00", "end": "20:00"}],
    6: [{"start": "10:00", "end": "14:00"}],
}

BARBERIA_WEEKLY_SCHEDULE = {
    0: [],
    1: [{"start": "10:00", "end": "14:00"}, {"start": "16:00", "end": "20:00"}],
    2: [{"start": "10:00", "end": "14:00"}, {"start": "16:00", "end": "20:00"}],
    3: [{"start": "10:00", "end": "14:00"}, {"start": "16:00", "end": "20:00"}],
    4: [{"start": "10:00", "end": "14:00"}, {"start": "16:00", "end": "20:00"}],
    5: [{"start": "10:00", "end": "14:00"}, {"start": "16:00", "end": "20:00"}],
    6: [{"start": "10:00", "end": "14:00"}],
}

MANICURA_WEEKLY_SCHEDULE = {
    0: [],
    1: [{"start": "10:00", "end": "20:00"}],
    2: [{"start": "10:00", "end": "20:00"}],
    3: [{"start": "10:00", "end": "20:00"}],
    4: [{"start": "10:00", "end": "20:00"}],
    5: [{"start": "10:00", "end": "20:00"}],
    6: [{"start": "10:00", "end": "14:00"}],
}

TEST_CUSTOMER_NAMES = {
    "Cliente Prueba",
    "Cliente Duplicado",
    "Cliente Buffer",
    "Cliente UI",
    "Cliente StartDatetime",
    "Cliente Review Sprint",
    "Cliente Review Sin URL",
    "Cliente Review UI",
    "Cliente WhatsApp Sprint",
}


BUSINESSES = [
    {
        "business": {
            "slug": "demo-manicura",
            "name": "Luna Nails Studio",
            "category": "Manicura y estética",
            "headline": "Reserva tu cita, consulta servicios y descubre nuestras promociones.",
            "description": "Especialistas en manicura semipermanente, pedicura y diseños personalizados.",
            "phone": "34600000000",
            "city": "Madrid",
            "address": "Calle Ejemplo 12, Madrid",
            "schedule": "Lunes a viernes, 10:00 - 20:00 · Sábados, 10:00 - 14:00",
            "maps_url": "https://www.google.com/maps",
            "instagram_url": "https://www.instagram.com/",
            "reviews_url": "https://www.google.com/search?q=demo+manicura+rese%C3%B1as",
            "primary_color": "#c026d3",
            "status": "active",
        },
        "services": [
            {
                "name": "Manicura semipermanente",
                "description": "Esmaltado semipermanente con preparación de uña.",
                "price_text": "25 €",
                "duration_text": "60 min",
                "duration_minutes": 60,
            },
            {
                "name": "Retirada + manicura",
                "description": "Retirada de esmalte anterior y nueva manicura.",
                "price_text": "30 €",
                "duration_text": "75 min",
                "duration_minutes": 75,
            },
            {
                "name": "Pedicura",
                "description": "Pedicura con limado, cuidado y esmaltado.",
                "price_text": "28 €",
                "duration_text": "60 min",
                "duration_minutes": 60,
            },
        ],
        "availability_settings": {
            "timezone": "Europe/Madrid",
            "slot_interval_minutes": 15,
            "buffer_between_bookings_minutes": 0,
            "min_notice_minutes": 180,
            "max_days_ahead": 30,
            "weekly_schedule": MANICURA_WEEKLY_SCHEDULE,
        },
    },
    {
        "business": {
            "slug": "demo-barberia",
            "name": "Brava Barber Club",
            "category": "Barbería",
            "headline": "Cortes, barba y degradados con reserva rápida.",
            "description": "Barbería especializada en corte clásico, degradado moderno y arreglo de barba.",
            "phone": "34600000001",
            "city": "Madrid",
            "address": "Calle Barbería 8, Madrid",
            "schedule": "Lunes a sábado, 10:00 - 21:00",
            "maps_url": "https://www.google.com/maps",
            "instagram_url": "https://www.instagram.com/",
            "reviews_url": "https://www.google.com/search?q=demo+barberia+rese%C3%B1as",
            "primary_color": "#334155",
            "status": "active",
        },
        "services": [
            {
                "name": "Corte de pelo",
                "description": "Corte a tijera o máquina con acabado profesional.",
                "price_text": "15 €",
                "duration_text": "30 min",
                "duration_minutes": 30,
            },
            {
                "name": "Corte + barba",
                "description": "Corte completo y arreglo de barba con perfilado.",
                "price_text": "22 €",
                "duration_text": "45 min",
                "duration_minutes": 45,
            },
            {
                "name": "Barba",
                "description": "Arreglo de barba con perfilado.",
                "price_text": "10 €",
                "duration_text": "20 min",
                "duration_minutes": 20,
            },
        ],
        "availability_settings": {
            "timezone": "Europe/Madrid",
            "slot_interval_minutes": 15,
            "buffer_between_bookings_minutes": 0,
            "min_notice_minutes": 120,
            "max_days_ahead": 30,
            "weekly_schedule": BARBERIA_WEEKLY_SCHEDULE,
        },
    },
    {
        "business": {
            "slug": "demo-taller",
            "name": "MotorFix Taller",
            "category": "Taller mecánico",
            "headline": "Solicita diagnóstico, revisión o presupuesto adjuntando fotos.",
            "description": "Taller para mantenimiento, diagnóstico inicial y presupuestos de reparación.",
            "phone": "34600000002",
            "city": "Madrid",
            "address": "Polígono Ejemplo, Nave 4, Madrid",
            "schedule": "Lunes a viernes, 08:30 - 18:30",
            "maps_url": "https://www.google.com/maps",
            "instagram_url": "https://www.instagram.com/",
            "reviews_url": "https://www.google.com/search?q=demo+taller+rese%C3%B1as",
            "primary_color": "#ea580c",
            "status": "active",
        },
        "services": [
            {
                "name": "Diagnóstico inicial",
                "description": "Revisión inicial del problema y orientación de reparación.",
                "price_text": "Desde 30 €",
                "duration_text": "30 min",
                "duration_minutes": 30,
            },
            {
                "name": "Cambio de aceite",
                "description": "Cambio de aceite y revisión básica de niveles.",
                "price_text": "Desde 60 €",
                "duration_text": "45 min",
                "duration_minutes": 45,
            },
            {
                "name": "Presupuesto de reparación",
                "description": "Solicitud de presupuesto con fotos del problema o golpe.",
                "price_text": "Consultar",
                "duration_text": "Variable",
                "duration_minutes": 30,
            },
        ],
        "availability_settings": {
            "timezone": "Europe/Madrid",
            "slot_interval_minutes": 15,
            "buffer_between_bookings_minutes": 0,
            "min_notice_minutes": 120,
            "max_days_ahead": 30,
            "weekly_schedule": DEFAULT_WEEKLY_SCHEDULE,
        },
    },
]

DEMO_BRANDING_DEFAULTS = {
    "demo-manicura": {"theme_key": "rose_beauty", "template_key": "beauty", "primary_color": "#be123c", "secondary_color": "#831843", "accent_color": "#f9a8d4", "background_color": "#fff1f2"},
    "demo-barberia": {"theme_key": "amber_barber", "template_key": "urban", "primary_color": "#92400e", "secondary_color": "#451a03", "accent_color": "#fbbf24", "background_color": "#fffbeb"},
    "demo-taller": {"theme_key": "slate_gold", "template_key": "minimal", "primary_color": "#334155", "secondary_color": "#0f172a", "accent_color": "#f59e0b", "background_color": "#f8fafc"},
}


def upsert_business(db, data: dict) -> Business:
    source_data = data["business"]
    business_data = {**DEMO_BRANDING_DEFAULTS.get(source_data["slug"], {}), **source_data}
    business_data.setdefault("logo_url", None)
    business_data.setdefault("logo_alt", None)

    business = db.query(Business).filter(Business.slug == business_data["slug"]).first()

    if business is None:
        business = Business(**business_data)
        db.add(business)
        db.flush()
    else:
        for key, value in business_data.items():
            if key == "slug":
                continue
            current_value = getattr(business, key)
            if current_value is None or (isinstance(current_value, str) and not current_value.strip()):
                setattr(business, key, value)
        db.flush()

    return business


def upsert_services(db, business: Business, services: list[dict]) -> None:
    existing_services = (
        db.query(BusinessService)
        .filter(BusinessService.business_id == business.id)
        .all()
    )

    if existing_services:
        return

    for service_data in services:
        db.add(BusinessService(business_id=business.id, active=True, **service_data))


def upsert_weekly_availability(db, business: Business, weekly_schedule: dict) -> None:
    for weekday, slots in weekly_schedule.items():
        existing_availability = (
            db.query(WeeklyAvailability)
            .filter(
                WeeklyAvailability.business_id == business.id,
                WeeklyAvailability.weekday == weekday,
            )
            .first()
        )

        slots_json = json.dumps(slots)

        if existing_availability is None:
            db.add(
                WeeklyAvailability(
                    business_id=business.id,
                    weekday=weekday,
                    slots_json=slots_json,
                    active=True,
                )
            )


def upsert_availability_settings(db, business: Business, settings_data: dict) -> None:
    weekly_schedule = {
        str(weekday): windows
        for weekday, windows in settings_data["weekly_schedule"].items()
    }
    existing_settings = (
        db.query(AvailabilitySettings)
        .filter(AvailabilitySettings.business_id == business.id)
        .first()
    )

    values = {
        "timezone": settings_data.get("timezone", "Europe/Madrid"),
        "slot_interval_minutes": settings_data.get("slot_interval_minutes", 15),
        "buffer_between_bookings_minutes": settings_data.get("buffer_between_bookings_minutes", 0),
        "min_notice_minutes": settings_data.get("min_notice_minutes", 120),
        "max_days_ahead": settings_data.get("max_days_ahead", 30),
        "weekly_schedule_json": json.dumps(weekly_schedule, ensure_ascii=False),
    }

    if existing_settings is None:
        db.add(AvailabilitySettings(business_id=business.id, **values))
    else:
        for key, value in values.items():
            current_value = getattr(existing_settings, key)
            if current_value is None or (isinstance(current_value, str) and not current_value.strip()):
                setattr(existing_settings, key, value)


def cleanup_demo_test_data(db) -> None:
    test_customers = (
        db.query(Customer)
        .filter(Customer.name.in_(TEST_CUSTOMER_NAMES))
        .all()
    )
    test_customer_ids = [customer.id for customer in test_customers]

    test_bookings_query = db.query(Booking).filter(Booking.source == "manual-test")

    if test_customer_ids:
        test_bookings_query = test_bookings_query.union(
            db.query(Booking).filter(Booking.customer_id.in_(test_customer_ids))
        )

    test_bookings = test_bookings_query.all()
    test_booking_ids = [booking.id for booking in test_bookings]
    candidate_customer_ids = {
        *test_customer_ids,
        *(booking.customer_id for booking in test_bookings),
    }

    if test_booking_ids:
        db.query(MessageOutbox).filter(
            MessageOutbox.booking_id.in_(test_booking_ids)
        ).delete(synchronize_session=False)
        db.query(ReviewRequest).filter(ReviewRequest.booking_id.in_(test_booking_ids)).delete(
            synchronize_session=False
        )
        db.query(SyncJob).filter(SyncJob.booking_id.in_(test_booking_ids)).delete(
            synchronize_session=False
        )
        db.query(Booking).filter(Booking.id.in_(test_booking_ids)).delete(
            synchronize_session=False
        )

    if candidate_customer_ids:
        customers_with_bookings = {
            customer_id
            for (customer_id,) in (
                db.query(Booking.customer_id)
                .filter(Booking.customer_id.in_(candidate_customer_ids))
                .distinct()
                .all()
            )
        }
        orphan_test_customer_ids = candidate_customer_ids - customers_with_bookings

        db.query(Customer).filter(Customer.id.in_(orphan_test_customer_ids)).delete(
            synchronize_session=False
        )

    db.query(MessageOutbox).filter(
        MessageOutbox.customer_name.in_(TEST_CUSTOMER_NAMES)
    ).delete(synchronize_session=False)

    db.query(AvailabilityException).filter(
        AvailabilityException.reason.like("Prueba%")
    ).delete(synchronize_session=False)


def seed() -> None:
    create_db_and_tables()

    db = SessionLocal()

    try:
        cleanup_demo_test_data(db)

        for item in BUSINESSES:
            business = upsert_business(db, item)
            upsert_services(db, business, item["services"])
            upsert_availability_settings(db, business, item["availability_settings"])
            upsert_weekly_availability(
                db,
                business,
                item["availability_settings"]["weekly_schedule"],
            )

        db.commit()

        print("Seed completado correctamente.")
        print("Negocios disponibles:")

        for item in BUSINESSES:
            print(f"- {item['business']['slug']}")

    finally:
        db.close()


if __name__ == "__main__":
    seed()
