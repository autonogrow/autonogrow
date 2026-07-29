import json
import unittest
from pathlib import Path

from fastapi import HTTPException
from pydantic import ValidationError
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from starlette.requests import Request

from app.core.database import Base
from app.core.security import require_business_admin, require_owner
from app.models import AuditLog, Business, BusinessUser, Conversation, User
from app.routers.conversations import (
    admin_get_conversation_automation,
    admin_update_conversation_automation_settings,
)
from app.routers.owner import (
    adjust_owner_business_automation_usage,
    get_owner_business_automation_settings,
    reset_owner_business_automation_period,
    update_owner_business_automation_settings,
)
from app.schemas.conversation import BusinessAutomationSettingsUpdate
from app.schemas.owner import (
    OwnerAutomationPeriodReset,
    OwnerAutomationUsageAdjustment,
    OwnerBusinessAutomationSettingsUpdate,
)
from app.services.conversation_automation_service import ensure_automation_configuration
from app.services.conversation_service import send_outbound_message


class AutomationPermissionsTest(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine("sqlite:///:memory:")
        Base.metadata.create_all(self.engine)
        self.db = sessionmaker(bind=self.engine)()
        self.business = Business(slug="quota-a", name="Quota A", status="active")
        self.other_business = Business(slug="quota-b", name="Quota B", status="active")
        self.owner = User(email="owner@quota.test", is_owner=True)
        self.admin = User(email="admin@quota.test")
        self.other_admin = User(email="other@quota.test")
        self.staff = User(email="staff@quota.test")
        self.customer = User(email="customer@quota.test")
        self.db.add_all(
            [
                self.business,
                self.other_business,
                self.owner,
                self.admin,
                self.other_admin,
                self.staff,
                self.customer,
            ]
        )
        self.db.flush()
        self.db.add_all(
            [
                BusinessUser(
                    business_id=self.business.id,
                    user_id=self.admin.id,
                    role="business_admin",
                    active=True,
                ),
                BusinessUser(
                    business_id=self.other_business.id,
                    user_id=self.other_admin.id,
                    role="business_admin",
                    active=True,
                ),
                BusinessUser(
                    business_id=self.business.id,
                    user_id=self.staff.id,
                    role="business_staff",
                    active=True,
                ),
            ]
        )
        self.db.commit()
        self.settings, _ = ensure_automation_configuration(self.db, self.business)
        self.settings.monthly_auto_limit = 250
        self.settings.auto_used_current_period = 25
        self.db.commit()

    def tearDown(self):
        self.db.close()
        self.engine.dispose()

    def request(self, method="PATCH"):
        return Request(
            {
                "type": "http",
                "method": method,
                "path": "/api/owner/businesses/1/automation-settings",
                "headers": [
                    (b"user-agent", b"automation-permissions-test"),
                    (b"x-request-id", b"req-automation-1"),
                ],
                "client": ("testclient", 50000),
            }
        )

    def test_business_admin_can_read_limit_and_usage(self):
        result = admin_get_conversation_automation(
            self.business.slug, actor=self.admin, db=self.db
        )
        self.assertEqual(result["settings"]["auto_limit_per_period"], 250)
        self.assertEqual(result["settings"]["auto_used_current_period"], 25)
        self.assertEqual(result["usage"]["used"], 25)
        self.assertIn("period_end", result["usage"])

    def test_business_schema_rejects_all_owner_only_and_extra_fields(self):
        forbidden_payloads = (
            {"monthly_auto_limit": 999},
            {"auto_limit_per_period": 999},
            {"auto_used_current_period": 0},
            {"period_yyyymm": "2099-01"},
            {"reset_usage": True},
            {"plan": "premium"},
            {"billing": {"price": 1}},
            {"unexpected": "mass-assignment"},
        )
        for payload in forbidden_payloads:
            with self.subTest(payload=payload), self.assertRaises(ValidationError):
                BusinessAutomationSettingsUpdate.model_validate(payload)

    def test_business_admin_can_pause_and_reactivate_when_feature_is_enabled(self):
        disabled = admin_update_conversation_automation_settings(
            self.business.slug,
            BusinessAutomationSettingsUpdate(automation_enabled=False),
            self.request(),
            actor=self.admin,
            db=self.db,
        )
        self.assertFalse(disabled["settings"]["automation_enabled"])
        enabled = admin_update_conversation_automation_settings(
            self.business.slug,
            BusinessAutomationSettingsUpdate(automation_enabled=True),
            self.request(),
            actor=self.admin,
            db=self.db,
        )
        self.assertTrue(enabled["settings"]["automation_enabled"])
        self.assertEqual(enabled["settings"]["auto_limit_per_period"], 250)

    def test_business_admin_cannot_select_behavior_not_allowed_by_owner(self):
        self.settings.allowed_limit_behaviors_json = json.dumps(["disabled"])
        self.db.commit()
        with self.assertRaises(HTTPException) as denied:
            admin_update_conversation_automation_settings(
                self.business.slug,
                BusinessAutomationSettingsUpdate(on_limit_reached="semi_automatic"),
                self.request(),
                actor=self.admin,
                db=self.db,
            )
        self.assertEqual(denied.exception.status_code, 403)

    def test_admin_staff_customer_and_cross_tenant_permissions(self):
        self.assertIs(
            require_business_admin(self.business.slug, self.admin, self.db), self.admin
        )
        for user, slug in (
            (self.admin, self.other_business.slug),
            (self.staff, self.business.slug),
            (self.customer, self.business.slug),
        ):
            with self.subTest(user=user.email), self.assertRaises(HTTPException) as denied:
                require_business_admin(slug, user, self.db)
            self.assertEqual(denied.exception.status_code, 403)
        with self.assertRaises(HTTPException):
            admin_get_conversation_automation(
                self.business.slug, actor=self.staff, db=self.db
            )

    def test_owner_changes_limit_plan_and_entitlements_with_audit(self):
        result = update_owner_business_automation_settings(
            self.business.id,
            OwnerBusinessAutomationSettingsUpdate(
                plan="growth",
                auto_limit_per_period=500,
                allowed_limit_behaviors=["disabled"],
                on_limit_reached="disabled",
                instagram_channel_enabled=False,
                reason="Cambio de plan solicitado",
            ),
            self.request(),
            actor=self.owner,
            db=self.db,
        )
        self.assertEqual(result["settings"]["plan"], "growth")
        self.assertEqual(result["settings"]["auto_limit_per_period"], 500)
        self.assertFalse(result["settings"]["instagram_channel_enabled"])
        actions = {
            item.action
            for item in self.db.query(AuditLog)
            .filter(AuditLog.business_id == self.business.id)
            .all()
        }
        self.assertIn("business_plan_changed", actions)
        self.assertIn("automation_limit_changed", actions)
        audit = self.db.query(AuditLog).filter(
            AuditLog.action == "automation_limit_changed"
        ).one()
        metadata = json.loads(audit.metadata_json)
        self.assertEqual(metadata["old_value"], 250)
        self.assertEqual(metadata["new_value"], 500)
        self.assertEqual(metadata["request_id"], "req-automation-1")

    def test_owner_adjusts_usage_and_resets_period_with_required_reason(self):
        adjusted = adjust_owner_business_automation_usage(
            self.business.id,
            OwnerAutomationUsageAdjustment(
                new_usage=40, reason="Corrección de conciliación"
            ),
            self.request("POST"),
            actor=self.owner,
            db=self.db,
        )
        self.assertEqual(adjusted["settings"]["auto_used_current_period"], 40)
        reset = reset_owner_business_automation_period(
            self.business.id,
            OwnerAutomationPeriodReset(reason="Inicio administrativo de ciclo"),
            self.request("POST"),
            actor=self.owner,
            db=self.db,
        )
        self.assertEqual(reset["settings"]["auto_used_current_period"], 0)
        actions = [item.action for item in self.db.query(AuditLog).all()]
        self.assertIn("automation_usage_adjusted", actions)
        self.assertIn("automation_period_reset", actions)
        with self.assertRaises(ValidationError):
            OwnerAutomationUsageAdjustment.model_validate({"new_usage": 5, "reason": ""})
        with self.assertRaises(ValidationError):
            OwnerAutomationPeriodReset.model_validate({"reason": ""})

    def test_negative_values_are_rejected_and_zero_limit_is_allowed(self):
        with self.assertRaises(ValidationError):
            OwnerBusinessAutomationSettingsUpdate(auto_limit_per_period=-1)
        with self.assertRaises(ValidationError):
            OwnerAutomationUsageAdjustment(new_usage=-1, reason="Invalid value")
        valid = OwnerBusinessAutomationSettingsUpdate(auto_limit_per_period=0)
        self.assertEqual(valid.auto_limit_per_period, 0)

    def test_owner_suspension_cannot_be_reversed_by_business_admin(self):
        update_owner_business_automation_settings(
            self.business.id,
            OwnerBusinessAutomationSettingsUpdate(
                automation_feature_enabled=False, reason="Suspensión contractual"
            ),
            self.request(),
            actor=self.owner,
            db=self.db,
        )
        with self.assertRaises(HTTPException) as denied:
            admin_update_conversation_automation_settings(
                self.business.slug,
                BusinessAutomationSettingsUpdate(automation_enabled=True),
                self.request(),
                actor=self.admin,
                db=self.db,
            )
        self.assertEqual(denied.exception.status_code, 403)

    def test_owner_disabled_channel_blocks_manual_delivery_without_changing_usage(self):
        self.settings.instagram_channel_enabled = False
        self.settings.auto_used_current_period = 25
        conversation = Conversation(
            business_id=self.business.id,
            channel="instagram",
            external_user_id="ig-policy-user",
            status="pending",
        )
        self.db.add(conversation)
        self.db.commit()
        delivery = send_outbound_message(
            self.db,
            conversation=conversation,
            body="Manual response",
            sender_type="business",
        )
        self.assertFalse(delivery.ok)
        self.assertFalse(delivery.provider_attempted)
        self.assertIn("no está habilitado", delivery.client_error_message)
        self.assertEqual(self.settings.auto_used_current_period, 25)

    def test_non_owner_cannot_call_sensitive_owner_endpoint(self):
        with self.assertRaises(HTTPException) as denied:
            update_owner_business_automation_settings(
                self.business.id,
                OwnerBusinessAutomationSettingsUpdate(auto_limit_per_period=900),
                self.request(),
                actor=self.admin,
                db=self.db,
            )
        self.assertEqual(denied.exception.status_code, 403)
        self.assertIs(require_owner(self.owner), self.owner)

    def test_frontends_expose_correct_controls(self):
        root = Path(__file__).resolve().parents[2]
        admin_js = (root / "autonogrow-admin" / "admin.js").read_text(encoding="utf-8")
        owner_js = (root / "autonogrow-owner" / "owner.js").read_text(encoding="utf-8")
        self.assertNotIn('id="conversation-automation-limit"', admin_js)
        self.assertNotIn("monthly_auto_limit: Number", admin_js)
        self.assertIn("El límite de mensajes forma parte de tu plan", admin_js)
        self.assertIn('data-owner-automation-limit', owner_js)
        self.assertIn('data-owner-automation-action="usage"', owner_js)
        self.assertIn('data-owner-automation-action="reset"', owner_js)


if __name__ == "__main__":
    unittest.main()
