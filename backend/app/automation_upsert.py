"""Idempotently add missing conversation automation templates and rules.

Run from ``backend`` with ``python -m app.automation_upsert`` after applying the
schema migration through the normal application startup path.
"""

from app.core.database import SessionLocal, create_db_and_tables
from app.models import Business
from app.services.conversation_automation_service import ensure_automation_configuration


def upsert_all_business_automation() -> int:
    create_db_and_tables()
    db = SessionLocal()
    try:
        businesses = db.query(Business).order_by(Business.id).all()
        for business in businesses:
            ensure_automation_configuration(db, business)
        db.commit()
        return len(businesses)
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


if __name__ == "__main__":
    count = upsert_all_business_automation()
    print(f"Automation catalog upsert completed for {count} businesses.")
