import unittest

from fastapi import HTTPException
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from starlette.requests import Request

from app.core.database import Base, run_lightweight_migrations
from app.models import (
    Business,
    BusinessService,
    BusinessUser,
    BusinessUserService,
    User,
)
from app.routers.staff import (
    StaffServicesUpdate,
    list_public_staff,
    update_staff_services,
)


class StaffServicesTest(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine("sqlite:///:memory:")
        Base.metadata.create_all(self.engine)
        self.db = sessionmaker(bind=self.engine)()
        self.business = Business(slug="services-test", name="Services", status="active")
        self.admin_user = User(email="admin@services.test", name="Admin", is_active=True)
        self.staff_user = User(email="staff@services.test", name="Staff", is_active=True)
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
        )
        self.service_1 = BusinessService(
            business=self.business,
            name="Service one",
            duration_minutes=30,
            active=True,
        )
        self.service_2 = BusinessService(
            business=self.business,
            name="Service two",
            duration_minutes=30,
            active=True,
        )
        self.db.add_all(
            [
                self.business,
                self.admin_user,
                self.staff_user,
                self.admin,
                self.staff,
                self.service_1,
                self.service_2,
            ]
        )
        self.db.commit()

    def tearDown(self):
        self.db.close()
        self.engine.dispose()

    def request(self):
        return Request(
            {
                "type": "http",
                "method": "PUT",
                "path": f"/api/admin/businesses/{self.business.slug}/staff/{self.staff.id}/services",
                "headers": [],
                "client": ("testclient", 50000),
            }
        )

    def test_business_admin_assigns_services_and_public_filter_uses_them(self):
        response = update_staff_services(
            self.business.slug,
            self.staff.id,
            StaffServicesUpdate(service_ids=[self.service_2.id]),
            self.request(),
            actor=self.admin_user,
            db=self.db,
        )
        self.assertEqual(response["staff_member"]["service_ids"], [self.service_2.id])

        first = list_public_staff(
            self.business.slug, service_id=self.service_1.id, db=self.db
        )
        second = list_public_staff(
            self.business.slug, service_id=self.service_2.id, db=self.db
        )
        self.assertEqual(first["staff"], [])
        self.assertEqual([item["id"] for item in second["staff"]], [self.staff.id])

    def test_staff_role_cannot_assign_services(self):
        with self.assertRaises(HTTPException) as denied:
            update_staff_services(
                self.business.slug,
                self.staff.id,
                StaffServicesUpdate(service_ids=[self.service_1.id]),
                self.request(),
                actor=self.staff_user,
                db=self.db,
            )
        self.assertEqual(denied.exception.status_code, 403)

    def test_non_bookable_staff_cannot_receive_service_assignments(self):
        self.staff.bookable = False
        self.db.commit()
        with self.assertRaises(HTTPException) as conflict:
            update_staff_services(
                self.business.slug,
                self.staff.id,
                StaffServicesUpdate(service_ids=[self.service_1.id]),
                self.request(),
                actor=self.admin_user,
                db=self.db,
            )
        self.assertEqual(conflict.exception.status_code, 409)


class StaffServicesMigrationTest(unittest.TestCase):
    def test_existing_professionals_are_backfilled_once_and_new_ones_are_not(self):
        engine = create_engine("sqlite:///:memory:")
        Base.metadata.create_all(engine)
        db = sessionmaker(bind=engine)()
        business = Business(slug="migration-test", name="Migration", status="active")
        existing_user = User(email="existing@migration.test", is_active=True)
        existing = BusinessUser(
            business=business,
            user=existing_user,
            role="business_staff",
            active=True,
            bookable=True,
            show_schedule=True,
        )
        services = [
            BusinessService(business=business, name="One", active=True),
            BusinessService(business=business, name="Two", active=True),
        ]
        db.add_all([business, existing_user, existing, *services])
        db.commit()

        run_lightweight_migrations(engine)
        run_lightweight_migrations(engine)
        self.assertEqual(
            db.query(BusinessUserService)
            .filter(BusinessUserService.business_user_id == existing.id)
            .count(),
            2,
        )

        new_user = User(email="new@migration.test", is_active=True)
        new_member = BusinessUser(
            business=business,
            user=new_user,
            role="business_staff",
            active=True,
            bookable=True,
            show_schedule=True,
        )
        db.add_all([new_user, new_member])
        db.commit()
        run_lightweight_migrations(engine)
        self.assertEqual(
            db.query(BusinessUserService)
            .filter(BusinessUserService.business_user_id == new_member.id)
            .count(),
            0,
        )
        db.close()
        engine.dispose()


if __name__ == "__main__":
    unittest.main()
