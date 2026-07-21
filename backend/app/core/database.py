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


def run_lightweight_migrations() -> None:
    inspector = inspect(engine)

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

    with engine.begin() as connection:
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
