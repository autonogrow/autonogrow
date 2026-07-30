import unittest
from datetime import datetime, timedelta

from fastapi import HTTPException
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from starlette.requests import Request

from app.core.database import Base
from app.core.security import (
    get_current_user,
    require_business_access,
    require_business_admin,
)
from app.models import AuditLog, Booking, Business, BusinessService, BusinessUser, Customer, User
from app.routers.admin import (
    BookingInternalNotesUpdate,
    admin_create_service,
    admin_list_bookings,
    admin_list_services,
    admin_update_service,
    get_business_settings,
    update_booking_internal_notes,
    update_business_settings,
)
from app.routers.auth import serialize_user
from app.routers.staff import (
    StaffServicesUpdate,
    StaffUpdate,
    list_staff,
    remove_staff,
    update_staff,
    update_staff_services,
)
from app.schemas.business import BusinessSettingsUpdate
from app.schemas.service import AdminServiceCreate, AdminServiceUpdate


class OwnerSuperadminTest(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine("sqlite:///:memory:")
        Base.metadata.create_all(self.engine)
        self.db = sessionmaker(bind=self.engine)()

        self.owner = User(email="owner@superadmin.test", name="Owner", is_owner=True)
        self.admin_user = User(email="admin@superadmin.test", name="Admin")
        self.other_admin_user = User(email="other@superadmin.test", name="Other admin")
        self.staff_user = User(email="staff@superadmin.test", name="Staff")
        self.customer_user = User(email="customer@superadmin.test", name="Customer")
        self.business = Business(slug="owner-business", name="Owner business", status="active")
        self.other_business = Business(
            slug="other-business", name="Other business", status="active"
        )
        self.admin = BusinessUser(
            business=self.business,
            user=self.admin_user,
            role="business_admin",
            active=True,
        )
        self.other_admin = BusinessUser(
            business=self.other_business,
            user=self.other_admin_user,
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
            public_name="Staff",
        )
        self.service = BusinessService(
            business=self.business,
            name="Existing service",
            duration_minutes=30,
            active=True,
        )
        self.customer = Customer(
            business=self.business,
            name="Customer",
            phone="600000000",
        )
        self.booking = Booking(
            business=self.business,
            customer=self.customer,
            staff_business_user=self.staff,
            service=self.service,
            service_name=self.service.name,
            start_datetime=datetime.now() - timedelta(days=1),
            end_datetime=datetime.now() - timedelta(days=1, minutes=-30),
            preferred_date=(datetime.now() - timedelta(days=1)).date().isoformat(),
            preferred_time="10:00",
            status="completed",
        )
        self.db.add_all(
            [
                self.owner,
                self.admin_user,
                self.other_admin_user,
                self.staff_user,
                self.customer_user,
                self.business,
                self.other_business,
                self.admin,
                self.other_admin,
                self.staff,
                self.service,
                self.customer,
                self.booking,
            ]
        )
        self.db.commit()

    def tearDown(self):
        self.db.close()
        self.engine.dispose()

    def request(self, method="PATCH", path="/api/admin/test"):
        return Request(
            {
                "type": "http",
                "method": method,
                "path": path,
                "headers": [(b"user-agent", b"owner-superadmin-test")],
                "client": ("testclient", 50000),
            }
        )

    def test_owner_without_membership_can_manage_full_business_admin_surface(self):
        self.assertEqual(
            self.db.query(BusinessUser).filter(BusinessUser.user_id == self.owner.id).count(),
            0,
        )
        auth_payload = serialize_user(self.db, self.owner)
        self.assertTrue(auth_payload["is_owner"])
        self.assertEqual(auth_payload["businesses"], [])
        self.assertIs(require_business_access(self.business.slug, self.owner, self.db), self.owner)
        self.assertIs(require_business_admin(self.business.slug, self.owner, self.db), self.owner)

        settings = get_business_settings(self.business.slug, db=self.db)
        self.assertEqual(settings["name"], "Owner business")
        updated = update_business_settings(
            self.business.slug,
            BusinessSettingsUpdate(name="Managed by owner", active=True),
            self.request(),
            actor=self.owner,
            db=self.db,
        )
        self.assertEqual(updated["settings"]["name"], "Managed by owner")

        self.assertEqual(len(admin_list_services(self.business.slug, db=self.db)["services"]), 1)
        created = admin_create_service(
            self.business.slug,
            AdminServiceCreate(name="Owner service", duration_minutes=45),
            db=self.db,
        )["service"]
        changed = admin_update_service(
            self.business.slug,
            created["id"],
            AdminServiceUpdate(name="Updated owner service", active=False),
            db=self.db,
        )["service"]
        self.assertEqual(changed["name"], "Updated owner service")
        self.assertFalse(changed["active"])

        self.assertEqual(len(list_staff(self.business.slug, db=self.db)["staff"]), 2)
        staff_result = update_staff(
            self.business.slug,
            self.staff.id,
            StaffUpdate(public_name="Updated by owner"),
            self.request(),
            actor=self.owner,
            db=self.db,
        )
        self.assertEqual(staff_result["staff_member"]["public_name"], "Updated by owner")
        assigned = update_staff_services(
            self.business.slug,
            self.staff.id,
            StaffServicesUpdate(service_ids=[self.service.id]),
            self.request("PUT"),
            actor=self.owner,
            db=self.db,
        )
        self.assertEqual(assigned["staff_member"]["service_ids"], [self.service.id])

        bookings = admin_list_bookings(self.business.slug, actor=self.owner, db=self.db)["bookings"]
        self.assertEqual([item["id"] for item in bookings], [self.booking.id])
        notes = update_booking_internal_notes(
            self.business.slug,
            self.booking.id,
            BookingInternalNotesUpdate(internal_notes="Owner note"),
            self.request(),
            actor=self.owner,
            db=self.db,
        )
        self.assertEqual(notes["booking"]["internal_notes"], "Owner note")

        removed = remove_staff(
            self.business.slug,
            self.staff.id,
            self.request("DELETE"),
            actor=self.owner,
            db=self.db,
        )
        self.assertTrue(removed["ok"])
        reactivated = update_staff(
            self.business.slug,
            self.staff.id,
            StaffUpdate(active=True),
            self.request(),
            actor=self.owner,
            db=self.db,
        )
        self.assertTrue(reactivated["staff_member"]["active"])

        owner_audits = (
            self.db.query(AuditLog).filter(AuditLog.actor_user_id == self.owner.id).count()
        )
        self.assertGreaterEqual(owner_audits, 5)

    def test_non_owner_tenant_permissions_remain_isolated(self):
        self.assertIs(
            require_business_admin(self.business.slug, self.admin_user, self.db),
            self.admin_user,
        )
        with self.assertRaises(HTTPException) as wrong_business:
            require_business_admin(self.other_business.slug, self.admin_user, self.db)
        self.assertEqual(wrong_business.exception.status_code, 403)

        self.assertIs(
            require_business_access(self.business.slug, self.staff_user, self.db),
            self.staff_user,
        )
        with self.assertRaises(HTTPException) as staff_admin:
            require_business_admin(self.business.slug, self.staff_user, self.db)
        self.assertEqual(staff_admin.exception.status_code, 403)

        with self.assertRaises(HTTPException) as customer_denied:
            require_business_access(self.business.slug, self.customer_user, self.db)
        self.assertEqual(customer_denied.exception.status_code, 403)

        with self.assertRaises(HTTPException) as anonymous_denied:
            get_current_user(None)
        self.assertEqual(anonymous_denied.exception.status_code, 401)

    def test_owner_cannot_remove_the_only_active_business_admin(self):
        response = remove_staff(
            self.business.slug,
            self.admin.id,
            self.request("DELETE"),
            actor=self.owner,
            db=self.db,
        )
        self.assertEqual(response.status_code, 409)
        self.assertTrue(self.admin.active)


if __name__ == "__main__":
    unittest.main()
