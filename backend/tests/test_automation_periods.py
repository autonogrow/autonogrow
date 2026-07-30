import json
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

from fastapi import HTTPException
from pydantic import ValidationError
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from starlette.requests import Request

from app.core.database import Base, run_lightweight_migrations
from app.models import (
    AuditLog,
    AutomationCreditTransaction,
    Business,
    BusinessUser,
    Conversation,
    ConversationAutomationSettings,
    ConversationMessage,
    User,
)
from app.routers.owner import (
    adjust_owner_business_automation_period,
    renew_owner_business_automation_period,
)
from app.schemas.owner import (
    OwnerAutomationPeriodAdjustment,
    OwnerAutomationPeriodRenewal,
)
from app.services.conversation_automation_service import (
    ensure_automation_configuration,
    process_inbound_automation,
    serialize_settings,
    sync_automation_period_status,
)


class AutomationMovingPeriodTest(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine("sqlite:///:memory:")
        Base.metadata.create_all(self.engine)
        self.db = sessionmaker(bind=self.engine)()
        self.business = Business(slug="moving-period", name="Moving Period", status="active")
        self.owner = User(email="owner@moving.test", is_owner=True)
        self.admin = User(email="admin@moving.test")
        self.db.add_all([self.business, self.owner, self.admin])
        self.db.flush()
        self.db.add(
            BusinessUser(
                business_id=self.business.id,
                user_id=self.admin.id,
                role="business_admin",
                active=True,
            )
        )
        self.db.commit()
        self.settings, self.rules = ensure_automation_configuration(self.db, self.business)
        self.settings.plan_key = "growth"
        self.settings.monthly_auto_limit = 450
        self.settings.auto_used_current_period = 73
        self.settings.included_credits_per_period = 450
        self.settings.included_credits_used = 73
        self.settings.automation_enabled = True
        self.settings.instagram_channel_enabled = False
        self.settings.whatsapp_channel_enabled = True
        self.db.commit()

    def tearDown(self):
        self.db.close()
        self.engine.dispose()

    def request(self, *, request_id="period-request"):
        return Request(
            {
                "type": "http",
                "method": "POST",
                "path": f"/api/owner/businesses/{self.business.id}/automation-period-renewal",
                "headers": [(b"x-request-id", request_id.encode("ascii"))],
                "client": ("testclient", 50000),
            }
        )

    def renew(self, **overrides):
        values = {
            "reason": "Pago recibido por transferencia",
            "amount": 40.0,
            "payment_method": "bank_transfer",
            "external_reference": "TRX-001",
        }
        values.update(overrides)
        return renew_owner_business_automation_period(
            self.business.id,
            OwnerAutomationPeriodRenewal(**values),
            self.request(),
            idempotency_key="renewal-key-1",
            actor=self.owner,
            db=self.db,
        )

    def test_first_payment_starts_exactly_thirty_days_and_preserves_entitlements(self):
        legacy_marker = self.settings.period_yyyymm
        result = self.renew()
        started_at = datetime.fromisoformat(
            result["settings"]["period_started_at"].replace("Z", "+00:00")
        )
        ends_at = datetime.fromisoformat(
            result["settings"]["period_ends_at"].replace("Z", "+00:00")
        )

        self.assertEqual(ends_at - started_at, timedelta(days=30))
        self.assertEqual(result["settings"]["period_status"], "active")
        self.assertEqual(result["settings"]["auto_used_current_period"], 0)
        self.assertEqual(result["settings"]["auto_limit_per_period"], 450)
        self.assertEqual(result["settings"]["plan"], "growth")
        self.assertFalse(result["settings"]["instagram_channel_enabled"])
        self.assertTrue(result["settings"]["whatsapp_channel_enabled"])
        self.assertEqual(self.settings.period_yyyymm, legacy_marker)
        self.assertTrue(result["settings"]["payment_confirmed_at"].endswith("Z"))

        logs = self.db.query(AuditLog).order_by(AuditLog.id).all()
        self.assertEqual(
            [item.action for item in logs],
            [
                "automation_payment_confirmed",
                "automation_period_renewed",
                "automation_period_allowance_granted",
            ],
        )
        metadata = json.loads(logs[-1].metadata_json)
        self.assertEqual(metadata["owner_user_id"], self.owner.id)
        self.assertEqual(metadata["old_usage"], 73)
        self.assertEqual(metadata["new_usage"], 0)
        self.assertEqual(metadata["monthly_auto_limit"], 450)
        self.assertEqual(metadata["request_id"], "period-request")

    def test_early_renewal_requires_confirmation_and_replay_is_idempotent(self):
        first = self.renew()
        first_start = first["settings"]["period_started_at"]
        audit_count = self.db.query(AuditLog).count()

        replay = self.renew()
        self.assertTrue(replay["idempotent_replay"])
        self.assertEqual(replay["settings"]["period_started_at"], first_start)
        self.assertEqual(self.db.query(AuditLog).count(), audit_count)

        self.settings.payment_confirmed_at = datetime.now(timezone.utc) - timedelta(minutes=5)
        self.db.commit()
        with self.assertRaises(HTTPException) as denied:
            renew_owner_business_automation_period(
                self.business.id,
                OwnerAutomationPeriodRenewal(reason="Segundo pago"),
                self.request(request_id="early-renewal"),
                idempotency_key="different-key",
                actor=self.owner,
                db=self.db,
            )
        self.assertEqual(denied.exception.status_code, 409)

    def test_business_admin_cannot_confirm_payment(self):
        with self.assertRaises(HTTPException) as denied:
            renew_owner_business_automation_period(
                self.business.id,
                OwnerAutomationPeriodRenewal(reason="Intento de pago"),
                self.request(),
                idempotency_key="admin-payment-attempt",
                actor=self.admin,
                db=self.db,
            )
        self.assertEqual(denied.exception.status_code, 403)
        with self.assertRaises(ValidationError):
            OwnerAutomationPeriodRenewal(
                reason="Referencia inválida",
                external_reference="4111 1111 1111 1111",
            )

    def test_expiry_is_lazy_once_and_never_resets_or_renews(self):
        old_start = datetime.now(timezone.utc) - timedelta(days=31)
        old_end = datetime.now(timezone.utc) - timedelta(days=1)
        self.settings.period_started_at = old_start
        self.settings.period_ends_at = old_end
        self.settings.payment_confirmed_at = old_start
        self.settings.period_status = "active"
        self.settings.auto_used_current_period = 73
        self.db.commit()

        self.assertTrue(sync_automation_period_status(self.settings, db=self.db))
        self.assertFalse(sync_automation_period_status(self.settings, db=self.db))
        self.db.commit()
        self.assertEqual(self.settings.period_status, "pending_renewal")
        self.assertEqual(self.settings.auto_used_current_period, 73)
        self.assertEqual(self.settings.period_started_at, old_start.replace(tzinfo=None))
        self.assertEqual(self.settings.period_ends_at, old_end.replace(tzinfo=None))
        self.assertEqual(
            self.db.query(AuditLog).filter(AuditLog.action == "automation_period_expired").count(),
            1,
        )

    def test_expired_period_blocks_provider_and_credit_but_keeps_inbound(self):
        self.settings.period_started_at = datetime.now(timezone.utc) - timedelta(days=31)
        self.settings.period_ends_at = datetime.now(timezone.utc) - timedelta(seconds=1)
        self.settings.period_status = "active"
        self.settings.instagram_channel_enabled = True
        self.settings.auto_used_current_period = 12
        booking_rule = next(rule for rule in self.rules if rule.intent == "booking_intent")
        booking_rule.mode = "automatic"
        booking_rule.active = True
        conversation = Conversation(
            business_id=self.business.id,
            channel="instagram",
            external_user_id="expired-customer",
            status="pending",
        )
        self.db.add(conversation)
        self.db.flush()
        inbound = ConversationMessage(
            conversation_id=conversation.id,
            direction="inbound",
            sender_type="customer",
            body="quiero una cita",
        )
        self.db.add(inbound)
        self.db.flush()

        with patch(
            "app.services.conversation_automation_service.send_outbound_message"
        ) as provider_send:
            result = process_inbound_automation(
                self.db,
                business=self.business,
                conversation=conversation,
                message=inbound,
            )
        self.assertEqual(result["status"], "skipped")
        self.assertEqual(result["reason"], "period_pending_renewal")
        provider_send.assert_not_called()
        self.assertEqual(self.settings.auto_used_current_period, 12)
        self.assertEqual(
            self.db.query(ConversationMessage)
            .filter(ConversationMessage.direction == "inbound")
            .count(),
            1,
        )

    def test_late_payment_starts_now_and_manual_suspension_survives(self):
        expired_end = datetime.now(timezone.utc) - timedelta(days=4)
        self.settings.period_started_at = expired_end - timedelta(days=30)
        self.settings.period_ends_at = expired_end
        self.settings.period_status = "suspended"
        self.settings.automation_feature_enabled = False
        self.settings.automation_enabled = False
        self.db.commit()

        before = datetime.now(timezone.utc)
        result = self.renew()
        new_start = datetime.fromisoformat(
            result["settings"]["period_started_at"].replace("Z", "+00:00")
        )
        self.assertGreaterEqual(new_start, before)
        self.assertNotEqual(new_start, expired_end)
        self.assertEqual(result["settings"]["period_status"], "suspended")
        self.assertFalse(result["settings"]["automation_feature_enabled"])

    def test_period_adjustment_is_not_a_payment_and_preserves_usage(self):
        self.renew()
        payment_at = self.settings.payment_confirmed_at
        self.settings.auto_used_current_period = 9
        self.db.commit()
        start = datetime.now(timezone.utc) - timedelta(hours=1)
        end = start + timedelta(days=30)
        result = adjust_owner_business_automation_period(
            self.business.id,
            OwnerAutomationPeriodAdjustment(
                reason="Corrección de fecha operativa",
                period_started_at=start,
                period_ends_at=end,
                period_status="active",
                confirm_no_payment=True,
            ),
            self.request(request_id="adjust-period"),
            actor=self.owner,
            db=self.db,
        )
        self.assertEqual(result["settings"]["auto_used_current_period"], 9)
        self.assertEqual(self.settings.payment_confirmed_at, payment_at)
        self.assertEqual(
            self.db.query(AuditLog).filter(AuditLog.action == "automation_period_adjusted").count(),
            1,
        )
        with self.assertRaises(ValidationError):
            OwnerAutomationPeriodAdjustment(
                reason="Corrección",
                period_started_at=start,
                period_ends_at=end,
                confirm_no_payment=False,
            )

    def test_serialized_period_uses_mobile_dates_not_legacy_month(self):
        start = datetime(2026, 8, 17, 12, tzinfo=timezone.utc)
        self.settings.period_yyyymm = "1999-01"
        self.settings.period_started_at = start
        self.settings.period_ends_at = start + timedelta(days=30)
        self.settings.period_status = "active"
        payload = serialize_settings(self.settings)
        self.assertEqual(payload["period_started_at"], "2026-08-17T12:00:00Z")
        self.assertEqual(payload["period_ends_at"], "2026-09-16T12:00:00Z")
        self.assertEqual(payload["period_status"], "active")

    def test_migration_preserves_existing_commercial_configuration(self):
        original = {
            "plan": self.settings.plan_key,
            "limit": self.settings.monthly_auto_limit,
            "usage": self.settings.auto_used_current_period,
            "instagram": self.settings.instagram_channel_enabled,
            "whatsapp": self.settings.whatsapp_channel_enabled,
            "behaviors": self.settings.allowed_limit_behaviors_json,
        }
        run_lightweight_migrations(self.engine)
        self.db.expire_all()
        first_start = self.db.get(
            ConversationAutomationSettings, self.settings.id
        ).period_started_at
        run_lightweight_migrations(self.engine)
        self.db.expire_all()
        migrated = self.db.get(ConversationAutomationSettings, self.settings.id)
        self.assertEqual(migrated.plan_key, original["plan"])
        self.assertEqual(migrated.monthly_auto_limit, original["limit"])
        self.assertEqual(migrated.auto_used_current_period, original["usage"])
        self.assertEqual(migrated.instagram_channel_enabled, original["instagram"])
        self.assertEqual(migrated.whatsapp_channel_enabled, original["whatsapp"])
        self.assertEqual(migrated.allowed_limit_behaviors_json, original["behaviors"])
        self.assertEqual(migrated.period_started_at, first_start)
        self.assertIsNone(migrated.payment_confirmed_at)
        self.assertEqual(migrated.additional_credits_balance, 0)
        opening = (
            self.db.query(AutomationCreditTransaction)
            .filter(AutomationCreditTransaction.transaction_type == "migration_opening_balance")
            .one()
        )
        self.assertEqual(opening.additional_balance_after, 0)

    def test_frontends_separate_payment_from_admin_period_view(self):
        root = Path(__file__).resolve().parents[2]
        owner_js = (root / "autonogrow-owner" / "owner.js").read_text(encoding="utf-8")
        admin_js = (root / "autonogrow-admin" / "admin.js").read_text(encoding="utf-8")
        self.assertIn("Confirmar pago y renovar 30 días", owner_js)
        self.assertIn("Corrección administrativa del periodo", owner_js)
        self.assertNotIn("automation-period-renewal", admin_js)
        self.assertNotIn("Reinicio previsto", admin_js)
        self.assertNotIn("primer día", admin_js.lower())
        self.assertIn("Periodo pendiente de renovación", admin_js)


if __name__ == "__main__":
    unittest.main()
