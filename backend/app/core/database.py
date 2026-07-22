from sqlalchemy import create_engine, inspect, text
from sqlalchemy.orm import DeclarativeBase, sessionmaker

from app.core.config import get_database_url


class Base(DeclarativeBase):
    pass


DATABASE_URL = get_database_url()

connect_args = {}

if DATABASE_URL.startswith("sqlite"):
    connect_args = {"check_same_thread": False}


engine = create_engine(
    DATABASE_URL,
    connect_args=connect_args,
    echo=False,
)

SessionLocal = sessionmaker(
    bind=engine,
    autoflush=False,
    autocommit=False,
)


def get_db():
    db = SessionLocal()

    try:
        yield db
    finally:
        db.close()


def create_db_and_tables() -> None:
    import app.models  # noqa: F401

    Base.metadata.create_all(bind=engine)
    run_lightweight_migrations()


def run_lightweight_migrations(target_engine=None) -> None:
    migration_engine = target_engine or engine
    inspector = inspect(migration_engine)

    table_names = inspector.get_table_names()
    if "bookings" not in table_names:
        return

    existing_columns = {column["name"] for column in inspector.get_columns("bookings")}
    booking_columns = {
        "duration_minutes": "INTEGER",
        "start_datetime": "DATETIME",
        "end_datetime": "DATETIME",
        "customer_user_id": "INTEGER",
        "customer_email": "VARCHAR(320)",
        "public_manage_token": "VARCHAR(255)",
        "created_by_user": "BOOLEAN NOT NULL DEFAULT 0",
        "staff_business_user_id": "INTEGER",
        "internal_notes": "TEXT",
    }

    with migration_engine.begin() as connection:
        connection.execute(
            text(
                "CREATE TABLE IF NOT EXISTS app_migrations ("
                "name VARCHAR(200) PRIMARY KEY, "
                "applied_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP)"
            )
        )
        for column_name, column_type in booking_columns.items():
            if column_name not in existing_columns:
                connection.execute(
                    text(f"ALTER TABLE bookings ADD COLUMN {column_name} {column_type}")
                )

        connection.execute(
            text("CREATE INDEX IF NOT EXISTS ix_bookings_customer_user_id ON bookings (customer_user_id)")
        )
        connection.execute(
            text("CREATE INDEX IF NOT EXISTS ix_bookings_customer_email ON bookings (customer_email)")
        )
        connection.execute(
            text("CREATE UNIQUE INDEX IF NOT EXISTS ix_bookings_public_manage_token ON bookings (public_manage_token)")
        )
        connection.execute(
            text("CREATE INDEX IF NOT EXISTS ix_bookings_staff_business_user_id ON bookings (staff_business_user_id)")
        )

        if "business_users" in table_names:
            business_user_columns = {
                column["name"] for column in inspector.get_columns("business_users")
            }
            staff_columns = {
                "public_name": "VARCHAR(200)",
                "bookable": "BOOLEAN NOT NULL DEFAULT 0",
                "show_schedule": "BOOLEAN NOT NULL DEFAULT 1",
                "bio": "TEXT",
                "avatar_url": "TEXT",
                "removed_at": "DATETIME",
            }
            for column_name, column_type in staff_columns.items():
                if column_name not in business_user_columns:
                    connection.execute(
                        text(f"ALTER TABLE business_users ADD COLUMN {column_name} {column_type}")
                    )

        if "businesses" in table_names:
            business_columns = {column["name"] for column in inspector.get_columns("businesses")}
            branding_columns = {
                "secondary_color": "VARCHAR(20)",
                "accent_color": "VARCHAR(20)",
                "background_color": "VARCHAR(20)",
                "theme_key": "VARCHAR(40)",
                "template_key": "VARCHAR(40)",
                "logo_url": "TEXT",
                "logo_alt": "VARCHAR(240)",
            }
            for column_name, column_type in branding_columns.items():
                if column_name not in business_columns:
                    connection.execute(text(f"ALTER TABLE businesses ADD COLUMN {column_name} {column_type}"))

        if "conversations" in table_names:
            conversation_columns = {
                column["name"] for column in inspector.get_columns("conversations")
            }
            automation_columns = {
                "detected_intent": "VARCHAR(60)",
                "intent_confidence": "INTEGER",
                "matched_patterns_json": "TEXT",
            }
            for column_name, column_type in automation_columns.items():
                if column_name not in conversation_columns:
                    connection.execute(
                        text(
                            f"ALTER TABLE conversations ADD COLUMN {column_name} {column_type}"
                        )
                    )
            connection.execute(
                text(
                    "CREATE INDEX IF NOT EXISTS ix_conversations_detected_intent "
                    "ON conversations (detected_intent)"
                )
            )

        migration_name = "2026_07_backfill_business_user_services"
        migration_applied = connection.execute(
            text("SELECT 1 FROM app_migrations WHERE name = :name"),
            {"name": migration_name},
        ).first()
        if migration_applied is None:
            connection.execute(
                text(
                    "INSERT INTO business_user_services "
                    "(business_user_id, service_id, created_at) "
                    "SELECT bu.id, s.id, CURRENT_TIMESTAMP "
                    "FROM business_users bu "
                    "JOIN services s ON s.business_id = bu.business_id "
                    "WHERE bu.active IS TRUE AND bu.bookable IS TRUE "
                    "AND bu.show_schedule IS TRUE AND bu.removed_at IS NULL "
                    "AND s.active IS TRUE "
                    "AND NOT EXISTS ("
                    "SELECT 1 FROM business_user_services existing "
                    "WHERE existing.business_user_id = bu.id)"
                )
            )
            connection.execute(
                text("INSERT INTO app_migrations (name) VALUES (:name)"),
                {"name": migration_name},
            )
