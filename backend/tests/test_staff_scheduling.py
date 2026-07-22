import json
import unittest
from datetime import date, datetime, timedelta

from fastapi import HTTPException
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.core.database import Base
from app.core.security import ensure_can_manage_booking, require_business_admin
from app.models import (
    AvailabilitySettings,
    Business,
    BusinessService,
    BusinessUser,
    BusinessUserAvailability,
    User,
)
from app.schemas.booking import BookingRequestCreate
from app.services.availability_service import (
    build_availability,
    business_weekday,
    get_available_slots,
    get_public_bookable_staff,
)
from app.services.booking_service import create_booking_request


class StaffSchedulingTest(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine("sqlite:///:memory:")
        Base.metadata.create_all(self.engine)
        self.db = sessionmaker(bind=self.engine)()
        self.target_date = date.today() + timedelta(days=2)
        self.business = Business(slug="staff-test", name="Staff test", status="active")
        self.db.add(self.business)
        self.db.flush()
        self.service = BusinessService(
            business_id=self.business.id,
            name="Service",
            duration_minutes=30,
            duration_text="30 min",
            active=True,
        )
        schedule = {str(day): [{"start": "09:00", "end": "18:00"}] for day in range(7)}
        self.settings = AvailabilitySettings(
            business_id=self.business.id,
            timezone="Europe/Madrid",
            slot_interval_minutes=30,
            buffer_between_bookings_minutes=0,
            min_notice_minutes=0,
            max_days_ahead=30,
            weekly_schedule_json=json.dumps(schedule),
        )
        self.admin_user = User(email="admin@test.local", name="Admin", is_active=True)
        self.staff_user_1 = User(email="staff1@test.local", name="One", is_active=True)
        self.staff_user_2 = User(email="staff2@test.local", name="Two", is_active=True)
        self.admin = BusinessUser(
            business=self.business, user=self.admin_user, role="business_admin", active=True
        )
        self.staff_1 = BusinessUser(
            business=self.business, user=self.staff_user_1, role="business_staff",
            active=True, bookable=True, show_schedule=True, public_name="One",
        )
        self.staff_2 = BusinessUser(
            business=self.business, user=self.staff_user_2, role="business_staff",
            active=True, bookable=True, show_schedule=True, public_name="Two",
        )
        self.db.add_all([
            self.business, self.service, self.settings, self.admin,
            self.staff_1, self.staff_2,
        ])
        self.db.flush()
        weekday = business_weekday(self.target_date)
        self.db.add_all([
            BusinessUserAvailability(
                business_user_id=self.staff_1.id, weekday=weekday,
                windows_json=json.dumps([{"start": "10:00", "end": "12:00"}]), active=True,
            ),
            BusinessUserAvailability(
                business_user_id=self.staff_2.id, weekday=weekday,
                windows_json=json.dumps([{"start": "11:00", "end": "13:00"}]), active=True,
            ),
        ])
        self.db.commit()

    def tearDown(self):
        self.db.close()
        self.engine.dispose()

    def payload(self, hour: str, staff_id=None):
        return BookingRequestCreate(
            customer_name="Customer",
            customer_phone="600000000",
            service_id=self.service.id,
            staff_business_user_id=staff_id,
            start_datetime=f"{self.target_date.isoformat()}T{hour}:00",
        )

    def test_staff_hours_aggregation_and_deterministic_assignment(self):
        first_slots = get_available_slots(
            self.db, business_slug=self.business.slug, service_id=self.service.id,
            date=self.target_date.isoformat(), staff_business_user_id=self.staff_1.id,
        )
        second_slots = get_available_slots(
            self.db, business_slug=self.business.slug, service_id=self.service.id,
            date=self.target_date.isoformat(), staff_business_user_id=self.staff_2.id,
        )
        self.assertIn("10:00", {slot["label"] for slot in first_slots})
        self.assertNotIn("10:00", {slot["label"] for slot in second_slots})
        self.assertIn("12:30", {slot["label"] for slot in second_slots})

        booking_1 = create_booking_request(
            self.db, business_slug=self.business.slug, payload=self.payload("11:00")
        )
        self.assertEqual(booking_1.staff_business_user_id, self.staff_1.id)

        booking_2 = create_booking_request(
            self.db, business_slug=self.business.slug, payload=self.payload("11:00")
        )
        self.assertEqual(booking_2.staff_business_user_id, self.staff_2.id)

        with self.assertRaisesRegex(ValueError, "slot_unavailable"):
            create_booking_request(
                self.db,
                business_slug=self.business.slug,
                payload=self.payload("11:00", self.staff_1.id),
            )

    def test_staff_cannot_administer_or_access_another_booking(self):
        with self.assertRaises(HTTPException) as denied:
            require_business_admin(self.business.slug, self.staff_user_1, self.db)
        self.assertEqual(denied.exception.status_code, 403)
        self.assertIs(require_business_admin(self.business.slug, self.admin_user, self.db), self.admin_user)

        booking = create_booking_request(
            self.db,
            business_slug=self.business.slug,
            payload=self.payload("10:00", self.staff_1.id),
        )
        with self.assertRaises(HTTPException) as denied_booking:
            ensure_can_manage_booking(
                self.db, business_slug=self.business.slug,
                booking=booking, user=self.staff_user_2,
            )
        self.assertEqual(denied_booking.exception.status_code, 403)
        ensure_can_manage_booking(
            self.db, business_slug=self.business.slug,
            booking=booking, user=self.staff_user_1,
        )

    def test_public_booking_requires_a_bookable_professional(self):
        self.staff_1.bookable = False
        self.staff_2.show_schedule = False
        self.db.commit()

        self.assertEqual(get_public_bookable_staff(self.db, self.business.id), [])
        self.assertEqual(
            get_available_slots(
                self.db,
                business_slug=self.business.slug,
                service_id=self.service.id,
                date=self.target_date.isoformat(),
            ),
            [],
        )
        availability = build_availability(
            self.db, business_slug=self.business.slug, days_ahead=3
        )
        self.assertTrue(
            all(not day["slots"] and not day["is_available"] for day in availability["availability"])
        )
        with self.assertRaisesRegex(ValueError, "no_bookable_staff"):
            create_booking_request(
                self.db,
                business_slug=self.business.slug,
                payload=self.payload("10:00"),
            )

    def test_removed_professional_is_never_public_or_selectable(self):
        self.staff_1.removed_at = datetime.utcnow()
        self.db.commit()

        public_ids = {item.id for item in get_public_bookable_staff(self.db, self.business.id)}
        self.assertNotIn(self.staff_1.id, public_ids)
        with self.assertRaisesRegex(ValueError, "staff_not_found"):
            get_available_slots(
                self.db,
                business_slug=self.business.slug,
                service_id=self.service.id,
                date=self.target_date.isoformat(),
                staff_business_user_id=self.staff_1.id,
            )


if __name__ == "__main__":
    unittest.main()
