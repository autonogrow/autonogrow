import json
import unittest
from datetime import datetime, timedelta

from fastapi import HTTPException
from fastapi.responses import JSONResponse
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from starlette.requests import Request

from app.core.database import Base
from app.core.security import require_business_access
from app.models import Booking, Business, BusinessUser, Customer, User
from app.routers.staff import StaffUpdate, remove_staff, update_staff
from app.services.availability_service import get_public_bookable_staff
from app.services.booking_service import serialize_booking


class StaffRemovalTest(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine("sqlite:///:memory:")
        Base.metadata.create_all(self.engine)
        self.db = sessionmaker(bind=self.engine)()
        self.business = Business(slug="removal-test", name="Removal test", status="active")
        self.admin_user = User(email="admin@removal.test", name="Admin", is_active=True)
        self.staff_user = User(email="staff@removal.test", name="Staff", is_active=True)
        self.admin = BusinessUser(
            business=self.business,
            user=self.admin_user,
            role="business_admin",
            active=True,
        )
        self.staff = BusinessUser(
            business=self.business,
            user=self.staff_user,
            role="business_staff",
            active=True,
            bookable=True,
            show_schedule=True,
            public_name="Profesional historico",
        )
        self.customer = Customer(
            business=self.business,
            name="Cliente prueba",
            phone="600123123",
        )
        self.db.add_all([self.business, self.admin, self.staff, self.customer])
        self.db.commit()

    def tearDown(self):
        self.db.close()
        self.engine.dispose()

    def request(self, method="DELETE"):
        return Request(
            {
                "type": "http",
                "method": method,
                "path": "/api/admin/businesses/removal-test/staff/1",
                "headers": [],
                "client": ("testclient", 50000),
            }
        )

    def add_booking(self, *, status, starts_at):
        booking = Booking(
            business=self.business,
            customer=self.customer,
            staff_business_user=self.staff,
            service_name="Servicio prueba",
            start_datetime=starts_at,
            end_datetime=starts_at + timedelta(minutes=30),
            preferred_date=starts_at.date().isoformat(),
            preferred_time=starts_at.strftime("%H:%M"),
            status=status,
        )
        self.db.add(booking)
        self.db.commit()
        return booking

    def test_future_booking_returns_structured_conflict(self):
        booking = self.add_booking(
            status="confirmed", starts_at=datetime.now() + timedelta(days=2)
        )

        response = remove_staff(
            self.business.slug,
            self.staff.id,
            self.request(),
            actor=self.admin_user,
            db=self.db,
        )

        self.assertIsInstance(response, JSONResponse)
        self.assertEqual(response.status_code, 409)
        body = json.loads(response.body)
        self.assertEqual(body["detail"], "member_has_future_bookings")
        self.assertEqual(
            body["bookings"],
            [
                {
                    "id": booking.id,
                    "date": booking.start_datetime.date().isoformat(),
                    "start_time": booking.start_datetime.strftime("%H:%M"),
                    "customer_name": "Cliente prueba",
                    "customer_phone": "600123123",
                    "service_name": "Servicio prueba",
                    "status": "confirmed",
                }
            ],
        )
        self.assertTrue(self.staff.active)

    def test_terminal_history_is_preserved_after_soft_delete(self):
        booking = self.add_booking(
            status="completed", starts_at=datetime.now() - timedelta(days=2)
        )

        response = remove_staff(
            self.business.slug,
            self.staff.id,
            self.request(),
            actor=self.admin_user,
            db=self.db,
        )

        self.assertTrue(response["ok"])
        self.db.refresh(self.staff)
        self.assertFalse(self.staff.active)
        self.assertFalse(self.staff.bookable)
        self.assertFalse(self.staff.show_schedule)
        self.assertIsNotNone(self.staff.removed_at)
        self.assertEqual(get_public_bookable_staff(self.db, self.business.id), [])
        self.assertEqual(
            serialize_booking(booking)["staff_display_name"], "Profesional historico"
        )
        with self.assertRaises(HTTPException) as denied:
            require_business_access(self.business.slug, self.staff_user, self.db)
        self.assertEqual(denied.exception.status_code, 403)

    def test_staff_cannot_remove_a_member(self):
        with self.assertRaises(HTTPException) as denied:
            remove_staff(
                self.business.slug,
                self.admin.id,
                self.request(),
                actor=self.staff_user,
                db=self.db,
            )
        self.assertEqual(denied.exception.status_code, 403)

    def test_only_active_admin_cannot_remove_self(self):
        response = remove_staff(
            self.business.slug,
            self.admin.id,
            self.request(),
            actor=self.admin_user,
            db=self.db,
        )

        self.assertEqual(response.status_code, 409)
        self.assertEqual(json.loads(response.body)["detail"], "last_active_admin")
        self.assertTrue(self.admin.active)

    def test_patch_cannot_bypass_safe_removal(self):
        with self.assertRaises(HTTPException) as conflict:
            update_staff(
                self.business.slug,
                self.staff.id,
                StaffUpdate(active=False),
                self.request("PATCH"),
                actor=self.admin_user,
                db=self.db,
            )
        self.assertEqual(conflict.exception.status_code, 409)
        self.assertTrue(self.staff.active)

    def test_only_admin_cannot_downgrade_own_role(self):
        with self.assertRaises(HTTPException) as conflict:
            update_staff(
                self.business.slug,
                self.admin.id,
                StaffUpdate(role="business_staff"),
                self.request("PATCH"),
                actor=self.admin_user,
                db=self.db,
            )
        self.assertEqual(conflict.exception.status_code, 409)
        self.assertEqual(self.admin.role, "business_admin")


if __name__ == "__main__":
    unittest.main()
