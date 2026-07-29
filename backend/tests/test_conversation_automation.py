import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from fastapi import HTTPException
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.orm import sessionmaker
from starlette.requests import Request

from app.core.database import Base, run_lightweight_migrations
from app.core.security import require_business_access, require_business_admin
from app.models import (
    Business,
    BusinessUser,
    Conversation,
    ConversationAutomationRule,
    ConversationAutomationSettings,
    ConversationMessage,
    ConversationSuggestion,
    ConversationTemplate,
    User,
)
from app.routers.conversations import (
    admin_get_conversation_automation,
    admin_get_conversation_automation_state,
    admin_list_conversation_suggestions,
    admin_send_conversation_message,
    admin_send_conversation_suggestion,
    admin_update_conversation_automation_rule,
    admin_update_conversation_automation_settings,
    admin_update_conversation_automation_state,
    admin_update_conversation_suggestion,
    test_inbound_message as inbound_message_endpoint,
)
from app.schemas.conversation import (
    ConversationAutomationRuleUpdate,
    ConversationAutomationSettingsUpdate,
    ConversationAutomationControlUpdate,
    ConversationMessageCreate,
    ConversationSuggestionUpdate,
    TestInboundMessageCreate,
)
from app.services.conversation_automation_service import (
    ensure_automation_configuration,
)
from app.services.conversation_intent_service import detect_intent, normalize_text
from app.services.conversation_service import send_outbound_message as service_send_outbound_message


class ConversationAutomationTest(unittest.TestCase):
    def setUp(self):
        self.public_origin_patcher = patch(
            "app.services.conversation_service.get_settings",
            return_value=SimpleNamespace(
                frontend_origin_list=["http://127.0.0.1:5500"]
            ),
        )
        self.public_origin_patcher.start()
        self.engine = create_engine("sqlite:///:memory:")
        Base.metadata.create_all(self.engine)
        self.db = sessionmaker(bind=self.engine)()
        self.business_a = Business(
            slug="automation-a",
            name="Automation A",
            address="Calle A 1",
            status="active",
        )
        self.business_b = Business(
            slug="automation-b",
            name="Automation B",
            address="Calle B 2",
            status="active",
        )
        self.owner = User(email="owner@automation.test", is_owner=True)
        self.admin_user = User(email="admin@automation.test")
        self.other_admin_user = User(email="other-admin@automation.test")
        self.staff_user = User(email="staff@automation.test")
        self.customer_user = User(email="customer@automation.test")
        self.db.add_all(
            [
                self.business_a,
                self.business_b,
                self.owner,
                self.admin_user,
                self.other_admin_user,
                self.staff_user,
                self.customer_user,
            ]
        )
        self.db.flush()
        self.db.add_all(
            [
                BusinessUser(
                    business_id=self.business_a.id,
                    user_id=self.admin_user.id,
                    role="business_admin",
                    active=True,
                ),
                BusinessUser(
                    business_id=self.business_a.id,
                    user_id=self.staff_user.id,
                    role="business_staff",
                    active=True,
                ),
                BusinessUser(
                    business_id=self.business_b.id,
                    user_id=self.other_admin_user.id,
                    role="business_admin",
                    active=True,
                ),
            ]
        )
        self.db.commit()

    def tearDown(self):
        self.public_origin_patcher.stop()
        self.db.close()
        self.engine.dispose()

    def request(self, method="PATCH"):
        return Request(
            {
                "type": "http",
                "method": method,
                "path": "/api/admin/businesses/automation-a/conversation-automation",
                "headers": [],
                "client": ("testclient", 50000),
            }
        )

    def configure(
        self,
        business,
        *,
        enabled=True,
        intent="booking_intent",
        mode="semi_automatic",
    ):
        settings, rules = ensure_automation_configuration(self.db, business)
        settings.automation_enabled = enabled
        settings.period_started_at = datetime.now(timezone.utc) - timedelta(days=1)
        settings.period_ends_at = datetime.now(timezone.utc) + timedelta(days=29)
        settings.period_status = "active"
        rule = next(item for item in rules if item.intent == intent)
        rule.mode = mode
        rule.active = True
        self.db.commit()
        return settings, rule

    def inbound(self, body, *, business=None, external_user_id=None):
        business = business or self.business_a
        external_user_id = external_user_id or f"user-{body}"
        return inbound_message_endpoint(
            TestInboundMessageCreate(
                business_slug=business.slug,
                channel="instagram",
                external_user_id=external_user_id,
                body=body,
            ),
            x_autonogrow_webhook_secret=None,
            db=self.db,
        )

    def test_normalizer_and_initial_intents(self):
        self.assertEqual(normalize_text(" ¿Hay que pedir cita?  "), "hay que pedir cita")
        cases = (
            ("hay que pedir cita?", "booking_intent", True),
            ("¿tenéis hueco?", "booking_intent", True),
            ("¿cuánto cuesta?", "price_intent", True),
            ("¿dónde estáis?", "location_intent", True),
            ("me habéis cobrado mal", "complaint_intent", True),
        )
        for text, expected_intent, safe_for_auto in cases:
            with self.subTest(text=text):
                detected = detect_intent(text)
                self.assertEqual(detected.intent, expected_intent)
                self.assertGreaterEqual(detected.confidence, 80)
                self.assertEqual(detected.safe_for_auto, safe_for_auto)

        cancellation = detect_intent("quiero cancelar mi cita")
        self.assertEqual(cancellation.intent, "cancel_reschedule_intent")
        self.assertTrue(cancellation.safe_for_auto)
        unknown = detect_intent("Necesito información adicional")
        self.assertEqual(unknown.intent, "unknown")
        self.assertTrue(unknown.safe_for_auto)

    def test_lightweight_migration_adds_intent_columns_to_existing_conversations(self):
        legacy_settings = ConversationAutomationSettings(
            business_id=self.business_a.id,
            automation_enabled=True,
            monthly_auto_limit=321,
            auto_used_current_period=123,
            period_yyyymm="2026-07",
            on_limit_reached="semi_automatic",
            auto_threshold=80,
            human_reply_pause_minutes=60,
        )
        self.db.add(legacy_settings)
        self.db.commit()
        with self.engine.begin() as connection:
            connection.execute(text("DROP INDEX ix_conversations_detected_intent"))
            connection.execute(text("DROP INDEX ix_conversations_automation_paused_until"))
            connection.execute(text("ALTER TABLE conversations DROP COLUMN detected_intent"))
            connection.execute(text("ALTER TABLE conversations DROP COLUMN intent_confidence"))
            connection.execute(text("ALTER TABLE conversations DROP COLUMN matched_patterns_json"))
            connection.execute(text("ALTER TABLE conversations DROP COLUMN automation_mode"))
            connection.execute(text("ALTER TABLE conversations DROP COLUMN automation_paused_until"))
            connection.execute(text("ALTER TABLE conversations DROP COLUMN automation_pause_reason"))
            connection.execute(text("ALTER TABLE conversations DROP COLUMN automation_pause_updated_by"))
            connection.execute(text("ALTER TABLE conversations DROP COLUMN automation_pause_updated_at"))
            connection.execute(
                text(
                    "ALTER TABLE conversation_automation_settings "
                    "DROP COLUMN human_reply_pause_minutes"
                )
            )
            for column_name in (
                "plan_key",
                "automation_feature_enabled",
                "instagram_channel_enabled",
                "whatsapp_channel_enabled",
                "allowed_limit_behaviors_json",
                "period_started_at",
                "period_ends_at",
                "payment_confirmed_at",
                "period_status",
            ):
                connection.execute(
                    text(
                        "ALTER TABLE conversation_automation_settings "
                        f"DROP COLUMN {column_name}"
                    )
                )

        run_lightweight_migrations(self.engine)
        run_lightweight_migrations(self.engine)

        columns = {
            column["name"] for column in inspect(self.engine).get_columns("conversations")
        }
        self.assertTrue(
            {
                "detected_intent",
                "intent_confidence",
                "matched_patterns_json",
                "automation_mode",
                "automation_paused_until",
                "automation_pause_reason",
                "automation_pause_updated_by",
                "automation_pause_updated_at",
            }
            <= columns
        )
        settings_columns = {
            column["name"]
            for column in inspect(self.engine).get_columns(
                "conversation_automation_settings"
            )
        }
        self.assertIn("human_reply_pause_minutes", settings_columns)
        self.assertTrue(
            {
                "plan_key",
                "automation_feature_enabled",
                "instagram_channel_enabled",
                "whatsapp_channel_enabled",
                "allowed_limit_behaviors_json",
                "period_started_at",
                "period_ends_at",
                "payment_confirmed_at",
                "period_status",
            } <= settings_columns
        )
        with self.engine.connect() as connection:
            preserved = connection.execute(
                text(
                    "SELECT monthly_auto_limit, auto_used_current_period, period_yyyymm, "
                    "period_started_at, period_ends_at, payment_confirmed_at, period_status "
                    "FROM conversation_automation_settings WHERE business_id = :business_id"
                ),
                {"business_id": self.business_a.id},
            ).one()
        self.assertEqual(tuple(preserved[:3]), (321, 123, "2026-07"))
        migrated_start = datetime.fromisoformat(str(preserved[3]))
        migrated_end = datetime.fromisoformat(str(preserved[4]))
        self.assertEqual(migrated_end - migrated_start, timedelta(days=30))
        self.assertIsNone(preserved[5])
        self.assertEqual(preserved[6], "active")

    def test_catalog_upsert_adds_missing_items_without_overwriting_or_duplicates(self):
        customized = ConversationTemplate(
            business_id=self.business_a.id,
            name="Respuesta segura a queja",
            body="Texto personalizado del negocio",
            active=True,
        )
        self.db.add(customized)
        self.db.commit()

        _, first_rules = ensure_automation_configuration(self.db, self.business_a)
        self.db.commit()
        first_template_count = (
            self.db.query(ConversationTemplate)
            .filter(ConversationTemplate.business_id == self.business_a.id)
            .count()
        )
        first_rule_count = (
            self.db.query(ConversationAutomationRule)
            .filter(ConversationAutomationRule.business_id == self.business_a.id)
            .count()
        )
        _, second_rules = ensure_automation_configuration(self.db, self.business_a)
        self.db.commit()

        self.assertEqual(customized.body, "Texto personalizado del negocio")
        self.assertEqual(first_template_count, 8)
        self.assertEqual(first_rule_count, 10)
        self.assertEqual(len(first_rules), 10)
        self.assertEqual(len(second_rules), 10)
        self.assertEqual(
            self.db.query(ConversationTemplate)
            .filter(
                ConversationTemplate.business_id == self.business_a.id,
                ConversationTemplate.name == "Respuesta segura a queja",
            )
            .count(),
            1,
        )
        for intent in (
            "complaint_intent",
            "human_intent",
            "cancel_reschedule_intent",
            "unknown",
        ):
            rule = next(item for item in second_rules if item.intent == intent)
            self.assertEqual(rule.mode, "disabled")
            self.assertIsNotNone(rule.template_id)

    def test_disabled_by_default_only_records_inbound(self):
        result = self.inbound("hay que pedir cita?", external_user_id="disabled")
        settings = self.db.query(ConversationAutomationSettings).one()
        conversation = self.db.get(Conversation, result["conversation_id"])

        self.assertFalse(settings.automation_enabled)
        self.assertEqual(result["automation"]["action"], "manual")
        self.assertEqual(conversation.detected_intent, "booking_intent")
        self.assertEqual(len(conversation.messages), 1)
        self.assertEqual(self.db.query(ConversationSuggestion).count(), 0)

    def test_unknown_intent_can_send_safe_acknowledgement_and_stays_pending(self):
        self.configure(
            self.business_a,
            enabled=True,
            intent="unknown",
            mode="automatic",
        )

        result = self.inbound(
            "Necesito información adicional",
            external_user_id="unknown",
        )

        self.assertEqual(result["automation"]["detection"]["intent"], "unknown")
        self.assertEqual(result["automation"]["action"], "automatic")
        self.assertEqual(
            self.db.query(ConversationMessage)
            .filter(ConversationMessage.direction == "outbound")
            .count(),
            1,
        )
        conversation = self.db.get(Conversation, result["conversation_id"])
        self.assertEqual(conversation.status, "pending")

    def test_semi_automatic_creates_suggestion_without_credit(self):
        settings, _ = self.configure(self.business_a, mode="semi_automatic")
        result = self.inbound("tenéis hueco?", external_user_id="semi")
        conversation = self.db.get(Conversation, result["conversation_id"])
        suggestion = self.db.query(ConversationSuggestion).one()

        self.assertEqual(result["automation"]["action"], "suggestion")
        self.assertEqual(suggestion.status, "pending")
        self.assertIn("autonogrow-landing", suggestion.body)
        self.assertEqual(settings.auto_used_current_period, 0)
        self.assertEqual(conversation.status, "pending")
        self.assertEqual(len(conversation.messages), 1)

    def test_fifteen_minute_pause_skips_automatic_send_without_credit(self):
        settings, _ = self.configure(self.business_a, mode="automatic")
        conversation = Conversation(
            business_id=self.business_a.id,
            channel="instagram",
            external_user_id="paused-15",
            status="pending",
        )
        self.db.add(conversation)
        self.db.commit()

        updated = admin_update_conversation_automation_state(
            self.business_a.slug,
            conversation.id,
            ConversationAutomationControlUpdate(action="pause", duration_minutes=15),
            self.request(),
            actor=self.staff_user,
            db=self.db,
        )
        result = self.inbound("reservar", external_user_id="paused-15")

        self.assertEqual(updated["automation"]["block_reason"], "conversation_automation_paused")
        self.assertEqual(result["automation"]["status"], "skipped")
        self.assertEqual(result["automation"]["reason"], "conversation_automation_paused")
        self.assertEqual(result["automation"]["action"], "suggestion")
        self.assertEqual(settings.auto_used_current_period, 0)
        self.assertEqual(
            self.db.query(ConversationMessage)
            .filter(ConversationMessage.direction == "outbound")
            .count(),
            0,
        )

    def test_expired_pause_allows_next_inbound_only(self):
        settings, _ = self.configure(self.business_a, mode="automatic")
        conversation = Conversation(
            business_id=self.business_a.id,
            channel="instagram",
            external_user_id="expired-pause",
            status="pending",
            automation_mode="automatic",
            automation_paused_until=datetime.utcnow() - timedelta(seconds=1),
            automation_pause_reason="manual_control",
        )
        self.db.add(conversation)
        self.db.commit()

        result = self.inbound("quiero una cita", external_user_id="expired-pause")
        self.db.refresh(conversation)

        self.assertEqual(result["automation"]["action"], "automatic")
        self.assertEqual(settings.auto_used_current_period, 1)
        self.assertIsNone(conversation.automation_paused_until)
        self.assertIsNone(conversation.automation_pause_reason)

    def test_manual_mode_skips_then_resume_allows_automatic_send(self):
        settings, _ = self.configure(self.business_a, mode="automatic")
        conversation = Conversation(
            business_id=self.business_a.id,
            channel="instagram",
            external_user_id="manual-mode",
            status="pending",
        )
        self.db.add(conversation)
        self.db.commit()

        admin_update_conversation_automation_state(
            self.business_a.slug,
            conversation.id,
            ConversationAutomationControlUpdate(action="manual", duration_minutes=-1),
            self.request(),
            actor=self.staff_user,
            db=self.db,
        )
        skipped = self.inbound("reservar", external_user_id="manual-mode")
        state = admin_get_conversation_automation_state(
            self.business_a.slug,
            conversation.id,
            db=self.db,
        )
        self.assertEqual(skipped["automation"]["reason"], "conversation_manual_mode")
        self.assertEqual(state["automation"]["mode"], "manual")
        self.assertEqual(settings.auto_used_current_period, 0)

        admin_update_conversation_automation_state(
            self.business_a.slug,
            conversation.id,
            ConversationAutomationControlUpdate(action="resume"),
            self.request(),
            actor=self.staff_user,
            db=self.db,
        )
        sent = self.inbound("quiero una cita", external_user_id="manual-mode")
        self.assertEqual(sent["automation"]["action"], "automatic")
        self.assertEqual(settings.auto_used_current_period, 1)

    def test_successful_panel_reply_starts_default_human_pause(self):
        settings, _ = self.configure(self.business_a, mode="automatic")
        conversation = Conversation(
            business_id=self.business_a.id,
            channel="manual",
            external_user_id="panel-human",
            status="pending",
        )
        self.db.add(conversation)
        self.db.commit()

        result = admin_send_conversation_message(
            self.business_a.slug,
            conversation.id,
            ConversationMessageCreate(body="Respuesta humana"),
            self.request("POST"),
            actor=self.staff_user,
            db=self.db,
        )
        self.db.refresh(conversation)

        self.assertEqual(result["message"]["sender_type"], "business")
        self.assertEqual(conversation.automation_pause_reason, "human_reply")
        self.assertEqual(conversation.automation_pause_updated_by, self.staff_user.id)
        self.assertGreater(
            conversation.automation_paused_until,
            datetime.utcnow() + timedelta(minutes=59),
        )
        self.assertEqual(settings.auto_used_current_period, 0)

    def test_global_human_pause_setting_accepts_supported_values(self):
        result = admin_update_conversation_automation_settings(
            self.business_a.slug,
            ConversationAutomationSettingsUpdate(human_reply_pause_minutes=240),
            self.request(),
            actor=self.admin_user,
            db=self.db,
        )
        self.assertEqual(result["settings"]["human_reply_pause_minutes"], 240)

    def test_human_reply_does_not_reactivate_manual_mode(self):
        self.configure(self.business_a, mode="automatic")
        conversation = Conversation(
            business_id=self.business_a.id,
            channel="manual",
            external_user_id="manual-human-reply",
            status="pending",
            automation_mode="manual",
            automation_pause_reason="manual_control",
        )
        self.db.add(conversation)
        self.db.commit()

        admin_send_conversation_message(
            self.business_a.slug,
            conversation.id,
            ConversationMessageCreate(body="Seguimos atendiendo manualmente"),
            self.request("POST"),
            actor=self.staff_user,
            db=self.db,
        )
        self.db.refresh(conversation)

        self.assertEqual(conversation.automation_mode, "manual")
        self.assertIsNone(conversation.automation_paused_until)

    def test_automatic_sends_approved_template_and_consumes_credit(self):
        settings, _ = self.configure(self.business_a, mode="automatic")
        result = self.inbound("hay que pedir cita?", external_user_id="automatic")
        conversation = self.db.get(Conversation, result["conversation_id"])
        outbound = (
            self.db.query(ConversationMessage)
            .filter(
                ConversationMessage.conversation_id == conversation.id,
                ConversationMessage.direction == "outbound",
            )
            .one()
        )

        self.assertEqual(result["automation"]["action"], "automatic")
        self.assertEqual(outbound.sender_type, "automation")
        self.assertEqual(outbound.delivery_status, "simulated")
        self.assertIn('"intent": "booking_intent"', outbound.raw_payload_json)
        self.assertIn(
            "http://127.0.0.1:5500/autonogrow-landing/?b=automation-a",
            outbound.body,
        )
        self.assertEqual(settings.auto_used_current_period, 1)
        self.assertEqual(conversation.status, "replied")

    def test_welcome_responds_once_per_24_hours_then_responds_again(self):
        settings, _ = self.configure(
            self.business_a,
            intent="welcome_intent",
            mode="automatic",
        )

        first = self.inbound("Hola", external_user_id="welcome-cooldown")
        second = self.inbound("Hola", external_user_id="welcome-cooldown")
        conversation = self.db.get(Conversation, first["conversation_id"])

        self.assertEqual(first["automation"]["action"], "automatic")
        self.assertEqual(second["automation"]["status"], "skipped")
        self.assertEqual(second["automation"]["reason"], "welcome_already_sent")
        self.assertEqual(conversation.detected_intent, "welcome_intent")
        self.assertEqual(
            self.db.query(ConversationMessage)
            .filter(
                ConversationMessage.conversation_id == conversation.id,
                ConversationMessage.direction == "inbound",
            )
            .count(),
            2,
        )
        self.assertEqual(
            self.db.query(ConversationMessage)
            .filter(
                ConversationMessage.conversation_id == conversation.id,
                ConversationMessage.direction == "outbound",
            )
            .count(),
            1,
        )
        self.assertEqual(settings.auto_used_current_period, 1)

        old_time = datetime.utcnow() - timedelta(hours=24, seconds=1)
        for saved_message in conversation.messages:
            saved_message.created_at = old_time
        self.db.commit()

        third = self.inbound("Hola", external_user_id="welcome-cooldown")

        self.assertEqual(third["automation"]["action"], "automatic")
        self.assertEqual(
            self.db.query(ConversationMessage)
            .filter(
                ConversationMessage.conversation_id == conversation.id,
                ConversationMessage.direction == "outbound",
            )
            .count(),
            2,
        )
        self.assertEqual(settings.auto_used_current_period, 2)

    def test_welcome_cooldown_supports_legacy_automation_messages(self):
        settings, _ = self.configure(
            self.business_a,
            intent="welcome_intent",
            mode="automatic",
        )
        first = self.inbound("Hola", external_user_id="legacy-welcome")
        outbound = (
            self.db.query(ConversationMessage)
            .filter(
                ConversationMessage.conversation_id == first["conversation_id"],
                ConversationMessage.direction == "outbound",
            )
            .one()
        )
        outbound.raw_payload_json = None
        self.db.commit()

        second = self.inbound("Buenas", external_user_id="legacy-welcome")

        self.assertEqual(second["automation"]["status"], "skipped")
        self.assertEqual(second["automation"]["reason"], "welcome_already_sent")
        self.assertEqual(settings.auto_used_current_period, 1)

    def test_same_intent_cooldown_does_not_consume_credit(self):
        settings, _ = self.configure(self.business_a, mode="automatic")

        first = self.inbound("reservar", external_user_id="intent-cooldown")
        second = self.inbound("quiero una cita", external_user_id="intent-cooldown")

        self.assertEqual(first["automation"]["action"], "automatic")
        self.assertEqual(second["automation"]["status"], "skipped")
        self.assertEqual(second["automation"]["reason"], "intent_cooldown")
        self.assertEqual(settings.auto_used_current_period, 1)

    def test_welcome_does_not_block_a_different_automatic_intent(self):
        settings, _ = self.configure(self.business_a, mode="automatic")
        _, rules = ensure_automation_configuration(self.db, self.business_a)
        for intent in ("welcome_intent", "booking_intent"):
            rule = next(item for item in rules if item.intent == intent)
            rule.mode = "automatic"
            rule.active = True
        self.db.commit()

        welcome = self.inbound("Hola", external_user_id="different-intents")
        booking = self.inbound("quiero una cita", external_user_id="different-intents")

        self.assertEqual(welcome["automation"]["action"], "automatic")
        self.assertEqual(booking["automation"]["action"], "automatic")
        self.assertEqual(settings.auto_used_current_period, 2)
        self.assertEqual(
            self.db.query(ConversationMessage)
            .filter(ConversationMessage.direction == "outbound")
            .count(),
            2,
        )

    def test_limit_reached_falls_back_to_suggestion_without_more_credit(self):
        settings, _ = self.configure(self.business_a, mode="automatic")
        settings.monthly_auto_limit = 1
        settings.auto_used_current_period = 1
        self.db.commit()

        result = self.inbound("quiero una cita", external_user_id="limited")
        conversation = self.db.get(Conversation, result["conversation_id"])

        self.assertEqual(result["automation"]["action"], "suggestion")
        self.assertTrue(result["automation"]["limit_reached"])
        self.assertEqual(settings.auto_used_current_period, 1)
        self.assertEqual(conversation.status, "pending")
        self.assertEqual(
            self.db.query(ConversationMessage)
            .filter(ConversationMessage.direction == "outbound")
            .count(),
            0,
        )
        self.assertEqual(self.db.query(ConversationSuggestion).count(), 1)

    def test_legacy_month_marker_does_not_reset_usage(self):
        settings, _ = self.configure(self.business_a, mode="automatic")
        settings.period_yyyymm = "2000-01"
        settings.auto_used_current_period = 999
        self.db.commit()

        self.inbound("reservar", external_user_id="new-period")

        self.assertEqual(settings.period_yyyymm, "2000-01")
        self.assertEqual(settings.auto_used_current_period, 1000)

    def test_admin_and_owner_can_edit_but_staff_cannot(self):
        with self.assertRaises(HTTPException) as denied:
            require_business_admin(self.business_a.slug, self.staff_user, self.db)
        self.assertEqual(denied.exception.status_code, 403)
        self.assertIs(
            require_business_admin(self.business_a.slug, self.admin_user, self.db),
            self.admin_user,
        )
        self.assertIs(
            require_business_admin(self.business_a.slug, self.owner, self.db),
            self.owner,
        )

        settings, _ = ensure_automation_configuration(self.db, self.business_a)
        settings.period_started_at = datetime.now(timezone.utc) - timedelta(days=1)
        settings.period_ends_at = datetime.now(timezone.utc) + timedelta(days=29)
        settings.period_status = "active"
        self.db.commit()

        admin_update_conversation_automation_settings(
            self.business_a.slug,
            ConversationAutomationSettingsUpdate(automation_enabled=True),
            self.request(),
            actor=self.admin_user,
            db=self.db,
        )
        config = admin_get_conversation_automation(
            self.business_a.slug,
            actor=self.admin_user,
            db=self.db,
        )
        booking_rule = next(
            rule for rule in config["rules"] if rule["intent"] == "booking_intent"
        )
        updated_rule = admin_update_conversation_automation_rule(
            self.business_a.slug,
            "booking_intent",
            ConversationAutomationRuleUpdate(
                mode="automatic",
                template_id=booking_rule["template_id"],
            ),
            self.request(),
            actor=self.admin_user,
            db=self.db,
        )
        reloaded_config = admin_get_conversation_automation(
            self.business_a.slug,
            actor=self.admin_user,
            db=self.db,
        )
        reloaded_booking_rule = next(
            rule
            for rule in reloaded_config["rules"]
            if rule["intent"] == "booking_intent"
        )
        owner_result = admin_update_conversation_automation_settings(
            self.business_a.slug,
            ConversationAutomationSettingsUpdate(auto_threshold=90),
            self.request(),
            actor=self.owner,
            db=self.db,
        )
        self.assertEqual(updated_rule["rule"]["mode"], "automatic")
        self.assertEqual(reloaded_booking_rule["mode"], "automatic")
        self.assertTrue(owner_result["settings"]["automation_enabled"])
        self.assertEqual(owner_result["settings"]["auto_threshold"], 90)

    def test_frontend_uses_consistent_automatic_mode_value(self):
        admin_js = (
            Path(__file__).resolve().parents[2]
            / "autonogrow-admin"
            / "admin.js"
        ).read_text(encoding="utf-8")

        self.assertIn('<option value="automatic"', admin_js)
        self.assertIn(
            'mode: row.querySelector(".conversation-automation-rule-mode").value',
            admin_js,
        )
        self.assertIn('body.rule?.mode !== payload.mode', admin_js)
        self.assertIn("conversationAutomationLabel", admin_js)
        self.assertIn("conversation-automation-duration", admin_js)
        self.assertIn("conversation-human-reply-pause", admin_js)
        self.assertIn("toggleConversationAutomation", admin_js)

    def test_staff_can_modify_use_and_dismiss_suggestions(self):
        self.configure(self.business_a, mode="semi_automatic")
        first = self.inbound("reservar", external_user_id="suggestion-use")
        second = self.inbound("quiero una cita", external_user_id="suggestion-dismiss")
        third = self.inbound("tenéis hueco", external_user_id="suggestion-patch-use")
        suggestions = self.db.query(ConversationSuggestion).order_by(ConversationSuggestion.id).all()
        self.assertIs(
            require_business_access(self.business_a.slug, self.staff_user, self.db),
            self.staff_user,
        )

        sent = admin_send_conversation_message(
            self.business_a.slug,
            first["conversation_id"],
            ConversationMessageCreate(
                body=suggestions[0].body,
                suggestion_id=suggestions[0].id,
            ),
            self.request("POST"),
            actor=self.staff_user,
            db=self.db,
        )
        dismissed = admin_update_conversation_suggestion(
            self.business_a.slug,
            suggestions[1].id,
            ConversationSuggestionUpdate(status="dismissed"),
            self.request(),
            actor=self.staff_user,
            db=self.db,
        )
        marked_used = admin_update_conversation_suggestion(
            self.business_a.slug,
            suggestions[2].id,
            ConversationSuggestionUpdate(status="used"),
            self.request(),
            actor=self.staff_user,
            db=self.db,
        )

        self.assertEqual(suggestions[0].status, "used")
        self.assertEqual(sent["message"]["sender_type"], "business")
        self.assertEqual(dismissed["suggestion"]["status"], "dismissed")
        self.assertEqual(marked_used["suggestion"]["status"], "used")
        self.assertNotEqual(first["conversation_id"], second["conversation_id"])
        self.assertNotEqual(second["conversation_id"], third["conversation_id"])
        with self.assertRaises(HTTPException):
            require_business_access(
                self.business_a.slug,
                self.customer_user,
                self.db,
            )

    def test_staff_sends_suggestion_as_business_without_consuming_credit(self):
        settings, _ = self.configure(self.business_a, mode="semi_automatic")
        inbound = self.inbound("reservar", external_user_id="suggestion-direct-send")
        suggestion = self.db.query(ConversationSuggestion).one()

        result = admin_send_conversation_suggestion(
            self.business_a.slug,
            suggestion.id,
            self.request("POST"),
            actor=self.staff_user,
            db=self.db,
        )

        conversation = self.db.get(Conversation, inbound["conversation_id"])
        self.assertEqual(result["message"]["body"], suggestion.body)
        self.assertEqual(result["message"]["sender_type"], "business")
        self.assertEqual(result["message"]["delivery_status"], "simulated")
        self.assertEqual(result["suggestion"]["status"], "used")
        self.assertEqual(result["conversation"]["status"], "replied")
        self.assertEqual(conversation.last_message_text, suggestion.body)
        self.assertIsNotNone(conversation.last_message_at)
        self.assertIsNotNone(conversation.last_outbound_at)
        self.assertEqual(settings.auto_used_current_period, 0)

    def test_failed_suggestion_send_keeps_suggestion_pending(self):
        settings, _ = self.configure(self.business_a, mode="semi_automatic")
        inbound = self.inbound("reservar", external_user_id="suggestion-send-fails")
        suggestion = self.db.query(ConversationSuggestion).one()

        def fail_after_outbound_was_prepared(
            db,
            *,
            conversation,
            body,
            sender_type,
        ):
            service_send_outbound_message(
                db,
                conversation=conversation,
                body=body,
                sender_type=sender_type,
            )
            raise RuntimeError("simulated send failure")

        with patch(
            "app.routers.conversations.send_outbound_message",
            side_effect=fail_after_outbound_was_prepared,
        ):
            with self.assertRaises(HTTPException) as failed:
                admin_send_conversation_suggestion(
                    self.business_a.slug,
                    suggestion.id,
                    self.request("POST"),
                    actor=self.staff_user,
                    db=self.db,
                )

        self.assertEqual(failed.exception.status_code, 500)
        self.assertEqual(failed.exception.detail, "No se pudo enviar la sugerencia")
        self.db.expire_all()
        persisted_suggestion = self.db.get(ConversationSuggestion, suggestion.id)
        conversation = self.db.get(Conversation, inbound["conversation_id"])
        self.assertEqual(persisted_suggestion.status, "pending")
        self.assertEqual(conversation.status, "pending")
        self.assertEqual(
            self.db.query(ConversationMessage)
            .filter(
                ConversationMessage.conversation_id == conversation.id,
                ConversationMessage.direction == "outbound",
            )
            .count(),
            0,
        )
        self.assertEqual(settings.auto_used_current_period, 0)

    def test_configuration_and_suggestions_are_tenant_isolated(self):
        self.configure(self.business_a, mode="semi_automatic")
        self.configure(self.business_b, mode="semi_automatic")
        result_a = self.inbound("reservar", business=self.business_a, external_user_id="a")
        result_b = self.inbound("reservar", business=self.business_b, external_user_id="b")
        suggestion_b = (
            self.db.query(ConversationSuggestion)
            .filter(ConversationSuggestion.conversation_id == result_b["conversation_id"])
            .one()
        )

        listed_a = admin_list_conversation_suggestions(
            self.business_a.slug,
            result_a["conversation_id"],
            db=self.db,
        )
        self.assertEqual(len(listed_a["suggestions"]), 1)
        self.assertNotEqual(listed_a["suggestions"][0]["id"], suggestion_b.id)
        with self.assertRaises(HTTPException) as hidden_conversation:
            admin_list_conversation_suggestions(
                self.business_a.slug,
                result_b["conversation_id"],
                db=self.db,
            )
        self.assertEqual(hidden_conversation.exception.status_code, 404)
        with self.assertRaises(HTTPException) as hidden_suggestion:
            admin_update_conversation_suggestion(
                self.business_a.slug,
                suggestion_b.id,
                ConversationSuggestionUpdate(status="dismissed"),
                self.request(),
                actor=self.admin_user,
                db=self.db,
            )
        self.assertEqual(hidden_suggestion.exception.status_code, 404)

        config_a = admin_get_conversation_automation(
            self.business_a.slug,
            actor=self.admin_user,
            db=self.db,
        )
        config_b = admin_get_conversation_automation(
            self.business_b.slug,
            actor=self.owner,
            db=self.db,
        )
        self.assertNotEqual(config_a["settings"]["id"], config_b["settings"]["id"])
        self.assertTrue(
            all(rule["business_id"] == self.business_a.id for rule in config_a["rules"])
        )


if __name__ == "__main__":
    unittest.main()
