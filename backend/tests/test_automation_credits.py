import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

from fastapi import HTTPException
from pydantic import ValidationError
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from starlette.requests import Request

from app.core.database import Base
from app.models import (
    AutomationCreditTransaction,
    Business,
    BusinessUser,
    Conversation,
    ConversationMessage,
    User,
)
from app.routers.conversations import admin_get_business_automation_credits
from app.routers.owner import (
    adjust_owner_business_automation_credits,
    list_owner_business_automation_credit_transactions,
    purchase_owner_business_automation_credits,
    renew_owner_business_automation_period,
)
from app.schemas.conversation import BusinessAutomationSettingsUpdate
from app.schemas.owner import (
    AutomationCreditAdjustmentRequest,
    AutomationCreditPurchaseRequest,
    OwnerAutomationPeriodRenewal,
)
from app.services.automation_credit_service import (
    consume_automation_credit,
    serialize_credit_summary,
)
from app.services.conversation_automation_service import (
    ensure_automation_configuration,
    process_inbound_automation,
)


class AutomationCreditsTest(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine("sqlite:///:memory:")
        Base.metadata.create_all(self.engine)
        self.db = sessionmaker(bind=self.engine)()
        self.business = Business(slug="credits-a", name="Credits A", status="active")
        self.other_business = Business(slug="credits-b", name="Credits B", status="active")
        self.owner = User(email="owner@credits.test", is_owner=True)
        self.admin = User(email="admin@credits.test")
        self.other_admin = User(email="other@credits.test")
        self.staff = User(email="staff@credits.test")
        self.customer = User(email="customer@credits.test")
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
        self.settings, self.rules = ensure_automation_configuration(self.db, self.business)
        self.settings.plan_key = "credits-plan"
        self.settings.monthly_auto_limit = 100
        self.settings.included_credits_per_period = 100
        self.settings.included_credits_used = 0
        self.settings.additional_credits_balance = 0
        self.settings.auto_used_current_period = 0
        self.settings.automation_enabled = True
        self.settings.period_started_at = datetime.now(timezone.utc) - timedelta(days=1)
        self.settings.period_ends_at = datetime.now(timezone.utc) + timedelta(days=29)
        self.settings.period_status = "active"
        self.db.commit()

    def tearDown(self):
        self.db.close()
        self.engine.dispose()

    def request(self, path="/automation-credits"):
        return Request(
            {
                "type": "http",
                "method": "POST",
                "path": path,
                "headers": [(b"x-request-id", b"credits-request")],
                "client": ("testclient", 50000),
            }
        )

    def purchase(self, *, credits=200, key="purchase-credits-001"):
        return purchase_owner_business_automation_credits(
            self.business.id,
            AutomationCreditPurchaseRequest(
                credits=credits,
                payment_amount=10,
                payment_method="bank_transfer",
                reason="Compra de créditos adicionales",
                external_reference="TRX-CREDITS",
                idempotency_key=key,
            ),
            self.request(),
            actor=self.owner,
            db=self.db,
        )

    def add_outbound(self, suffix):
        conversation = Conversation(
            business_id=self.business.id,
            channel="instagram",
            external_user_id=f"credit-user-{suffix}",
            status="pending",
        )
        self.db.add(conversation)
        self.db.flush()
        message = ConversationMessage(
            conversation_id=conversation.id,
            direction="outbound",
            sender_type="automation",
            body="Respuesta automática",
            delivery_status="sent",
        )
        self.db.add(message)
        self.db.flush()
        return conversation, message

    def test_purchase_only_adds_accumulating_credits_and_is_idempotent(self):
        old_start = self.settings.period_started_at
        old_end = self.settings.period_ends_at
        first = self.purchase()
        replay = self.purchase()
        self.assertEqual(first["additional_credits_balance"], 200)
        self.assertEqual(first["included_credits_used"], 0)
        self.assertEqual(first["total_available"], 300)
        self.assertTrue(replay["idempotent_replay"])
        self.assertEqual(replay["additional_credits_balance"], 200)
        self.assertEqual(self.settings.period_started_at, old_start)
        self.assertEqual(self.settings.period_ends_at, old_end)
        self.assertEqual(self.settings.plan_key, "credits-plan")
        self.assertEqual(
            self.db.query(AutomationCreditTransaction)
            .filter(AutomationCreditTransaction.transaction_type == "additional_credits_purchased")
            .count(),
            1,
        )

    def test_purchase_is_allowed_pending_but_cannot_be_consumed(self):
        self.settings.period_status = "pending_renewal"
        self.db.commit()
        self.purchase(credits=50, key="pending-purchase-001")
        conversation, inbound = self.add_outbound("pending")
        inbound.direction = "inbound"
        inbound.sender_type = "customer"
        inbound.body = "quiero una cita"
        rule = next(item for item in self.rules if item.intent == "booking_intent")
        rule.mode = "automatic"
        self.db.flush()
        with patch(
            "app.services.conversation_automation_service.send_outbound_message"
        ) as provider:
            result = process_inbound_automation(
                self.db,
                business=self.business,
                conversation=conversation,
                message=inbound,
            )
        self.assertEqual(result["reason"], "period_pending_renewal")
        provider.assert_not_called()
        self.assertEqual(self.settings.additional_credits_balance, 50)

    def test_consumption_uses_included_then_additional_and_message_is_idempotent(self):
        self.settings.included_credits_used = 99
        self.settings.additional_credits_balance = 2
        _, first_message = self.add_outbound("included")
        consumed, _ = consume_automation_credit(
            self.db, settings=self.settings, related_message_id=first_message.id
        )
        duplicate, _ = consume_automation_credit(
            self.db, settings=self.settings, related_message_id=first_message.id
        )
        self.assertTrue(consumed)
        self.assertFalse(duplicate)
        self.assertEqual(self.settings.included_credits_used, 100)
        self.assertEqual(self.settings.additional_credits_balance, 2)

        _, second_message = self.add_outbound("additional")
        consume_automation_credit(
            self.db, settings=self.settings, related_message_id=second_message.id
        )
        self.assertEqual(self.settings.included_credits_used, 100)
        self.assertEqual(self.settings.additional_credits_balance, 1)
        self.assertEqual(self.db.query(AutomationCreditTransaction).count(), 2)

    def test_no_credits_blocks_provider_with_safe_reason(self):
        self.settings.included_credits_used = 100
        self.settings.additional_credits_balance = 0
        conversation, inbound = self.add_outbound("exhausted")
        inbound.direction = "inbound"
        inbound.sender_type = "customer"
        inbound.body = "quiero una cita"
        rule = next(item for item in self.rules if item.intent == "booking_intent")
        rule.mode = "automatic"
        self.db.flush()
        with patch(
            "app.services.conversation_automation_service.send_outbound_message"
        ) as provider:
            result = process_inbound_automation(
                self.db,
                business=self.business,
                conversation=conversation,
                message=inbound,
            )
        provider.assert_not_called()
        self.assertEqual(result["reason"], "credits_exhausted")
        self.assertEqual(self.settings.auto_used_current_period, 0)

    def test_renewal_replaces_included_allowance_and_preserves_additional(self):
        self.settings.included_credits_used = 60
        self.settings.additional_credits_balance = 150
        self.settings.auto_used_current_period = 60
        self.db.commit()
        result = renew_owner_business_automation_period(
            self.business.id,
            OwnerAutomationPeriodRenewal(
                reason="Pago del nuevo periodo", confirm_active_period=True
            ),
            self.request("/automation-period-renewal"),
            idempotency_key="renew-credits-001",
            actor=self.owner,
            db=self.db,
        )
        self.assertEqual(result["credits"]["included_credits_remaining"], 100)
        self.assertEqual(result["credits"]["included_credits_used"], 0)
        self.assertEqual(result["credits"]["additional_credits_balance"], 150)
        self.assertEqual(result["credits"]["total_available"], 250)
        transaction = (
            self.db.query(AutomationCreditTransaction)
            .filter(AutomationCreditTransaction.transaction_type == "period_allowance_granted")
            .one()
        )
        self.assertEqual(transaction.amount, 100)
        self.assertEqual(transaction.additional_balance_after, 150)
        self.settings.payment_confirmed_at = datetime.now(timezone.utc) - timedelta(minutes=5)
        self.db.commit()
        second = renew_owner_business_automation_period(
            self.business.id,
            OwnerAutomationPeriodRenewal(reason="Segundo periodo", confirm_active_period=True),
            self.request("/automation-period-renewal"),
            idempotency_key="renew-credits-002",
            actor=self.owner,
            db=self.db,
        )
        self.assertEqual(second["credits"]["included_credits_remaining"], 100)
        self.assertEqual(second["credits"]["additional_credits_balance"], 150)
        self.assertEqual(
            self.db.query(AutomationCreditTransaction)
            .filter(AutomationCreditTransaction.transaction_type == "period_allowance_granted")
            .count(),
            2,
        )

    def test_adjustment_rejects_negative_balance_and_records_valid_change(self):
        self.settings.additional_credits_balance = 10
        self.db.commit()
        with self.assertRaises(HTTPException) as denied:
            adjust_owner_business_automation_credits(
                self.business.id,
                AutomationCreditAdjustmentRequest(
                    additional_delta=-11,
                    reason="Corrección inválida",
                    idempotency_key="adjust-negative-001",
                ),
                self.request(),
                actor=self.owner,
                db=self.db,
            )
        self.assertEqual(denied.exception.status_code, 422)
        self.db.rollback()
        result = adjust_owner_business_automation_credits(
            self.business.id,
            AutomationCreditAdjustmentRequest(
                additional_delta=25,
                reason="Corrección administrativa",
                idempotency_key="adjust-positive-001",
            ),
            self.request(),
            actor=self.owner,
            db=self.db,
        )
        self.assertEqual(result["additional_credits_balance"], 35)
        history = list_owner_business_automation_credit_transactions(
            self.business.id, limit=50, actor=self.owner, db=self.db
        )
        self.assertEqual(history[0]["transaction_type"], "manual_adjustment")

    def test_permissions_and_strict_admin_contract(self):
        summary = admin_get_business_automation_credits(
            self.business.slug, actor=self.admin, db=self.db
        )
        self.assertEqual(summary["included_credits_per_period"], 100)
        for actor in (self.admin, self.staff, self.customer):
            with self.subTest(actor=actor.email), self.assertRaises(HTTPException):
                purchase_owner_business_automation_credits(
                    self.business.id,
                    AutomationCreditPurchaseRequest(
                        credits=10,
                        reason="Intento no autorizado",
                        idempotency_key=f"denied-{actor.id:08d}",
                    ),
                    self.request(),
                    actor=actor,
                    db=self.db,
                )
        with self.assertRaises(HTTPException):
            admin_get_business_automation_credits(
                self.other_business.slug, actor=self.admin, db=self.db
            )
        for field, value in (
            ("included_credits_per_period", 1),
            ("included_credits_used", 1),
            ("additional_credits_balance", 1),
            ("purchase", True),
            ("adjustment", True),
            ("transaction", True),
            ("reset", True),
        ):
            with self.subTest(field=field), self.assertRaises(ValidationError):
                BusinessAutomationSettingsUpdate.model_validate({field: value})

    def test_summary_math_and_frontend_permissions(self):
        self.settings.included_credits_used = 25
        self.settings.additional_credits_balance = 150
        summary = serialize_credit_summary(self.settings)
        self.assertEqual(summary["included_credits_remaining"], 75)
        self.assertEqual(summary["total_available"], 225)
        root = Path(__file__).resolve().parents[2]
        owner_js = (root / "autonogrow-owner" / "owner.js").read_text(encoding="utf-8")
        admin_js = (root / "autonogrow-admin" / "admin.js").read_text(encoding="utf-8")
        self.assertIn("Añadir créditos adicionales", owner_js)
        self.assertIn("Ajustar saldo", owner_js)
        self.assertIn("Ver historial", owner_js)
        self.assertIn("Créditos adicionales", admin_js)
        self.assertNotIn("automation-credits/purchase", admin_js)
        self.assertNotIn("automation-credits/adjustment", admin_js)


if __name__ == "__main__":
    unittest.main()
