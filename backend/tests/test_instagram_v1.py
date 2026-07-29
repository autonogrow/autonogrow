import asyncio
import hashlib
import hmac
import json
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from fastapi import HTTPException
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from starlette.requests import Request

from app.core.config import Settings
from app.core.database import Base
from app.core.security import get_current_user, require_business_access
from app.models import (
    Business,
    BusinessUser,
    Conversation,
    ConversationMessage,
    ConversationSuggestion,
    User,
)
from app.routers.conversations import (
    admin_send_conversation_message,
    admin_send_conversation_suggestion,
)
from app.routers.instagram_webhook import (
    receive_instagram_webhook,
    verify_instagram_webhook,
)
from app.schemas.conversation import ConversationMessageCreate
from app.services.conversation_automation_service import (
    ensure_automation_configuration,
    process_inbound_automation,
)
from app.services.conversation_service import add_message
from app.services.instagram_provider import (
    ProviderSendResult,
    is_instagram_provider_configured,
    parse_instagram_webhook,
    send_instagram_text_message,
    verify_meta_signature,
)


class InstagramV1Test(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine("sqlite:///:memory:")
        Base.metadata.create_all(self.engine)
        self.db = sessionmaker(bind=self.engine)()
        self.business_a = Business(
            slug="instagram-a",
            name="Instagram A",
            status="active",
        )
        self.business_b = Business(
            slug="instagram-b",
            name="Instagram B",
            status="active",
        )
        self.admin_user = User(email="admin@instagram.test")
        self.staff_user = User(email="staff@instagram.test")
        self.customer_user = User(email="customer@instagram.test")
        self.db.add_all(
            [
                self.business_a,
                self.business_b,
                self.admin_user,
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
            ]
        )
        self.db.commit()

    def tearDown(self):
        self.db.close()
        self.engine.dispose()

    def settings(self, **overrides):
        values = {
            "app_env": "local",
            "frontend_origins": "http://127.0.0.1:5500",
            "meta_app_id": "app-123",
            "meta_app_secret": "meta-secret",
            "meta_verify_token": "verify-token",
            "meta_graph_api_version": "v23.0",
            "instagram_access_token": "test-access-token",
            "instagram_business_account_id": "ig-business-1",
            "instagram_default_business_slug": self.business_a.slug,
            "instagram_provider_enabled": False,
            "instagram_require_signature": False,
        }
        values.update(overrides)
        return Settings(_env_file=None, **values)

    def request(self, method="POST", path="/api/admin/businesses/instagram-a/conversations"):
        return Request(
            {
                "type": "http",
                "method": method,
                "path": path,
                "headers": [],
                "client": ("testclient", 50000),
            }
        )

    def webhook_request(self, raw_body: bytes):
        sent = False

        async def receive():
            nonlocal sent
            if sent:
                return {"type": "http.request", "body": b"", "more_body": False}
            sent = True
            return {"type": "http.request", "body": raw_body, "more_body": False}

        return Request(
            {
                "type": "http",
                "method": "POST",
                "path": "/api/webhooks/instagram",
                "headers": [],
                "client": ("127.0.0.1", 50000),
            },
            receive,
        )

    def payload(
        self,
        *,
        sender="ig-customer-1",
        recipient="ig-business-1",
        mid="mid-1",
        text="Hola",
        attachments=None,
        is_echo=False,
    ):
        if is_echo and sender == "ig-customer-1" and recipient == "ig-business-1":
            sender, recipient = recipient, sender
        message = {"mid": mid}
        if text is not None:
            message["text"] = text
        if attachments is not None:
            message["attachments"] = attachments
        if is_echo:
            message["is_echo"] = True
        return {
            "object": "instagram",
            "entry": [
                {
                    "id": recipient,
                    "messaging": [
                        {
                            "sender": {"id": sender},
                            "recipient": {"id": recipient},
                            "timestamp": int(datetime.now(timezone.utc).timestamp() * 1000),
                            "message": message,
                        }
                    ],
                }
            ],
        }

    def post_webhook(self, payload, settings, signature=None):
        raw_body = json.dumps(payload).encode("utf-8")
        with patch("app.routers.instagram_webhook.get_settings", return_value=settings):
            return asyncio.run(
                receive_instagram_webhook(
                    self.webhook_request(raw_body),
                    x_hub_signature_256=signature,
                    db=self.db,
                )
            )

    def create_instagram_conversation(self, *, business=None, user_id="ig-user"):
        business = business or self.business_a
        conversation = Conversation(
            business_id=business.id,
            channel="instagram",
            external_user_id=user_id,
            status="pending",
        )
        self.db.add(conversation)
        self.db.commit()
        return conversation

    def test_get_verification_accepts_correct_token_and_rejects_wrong_token(self):
        settings = self.settings()
        with patch("app.routers.instagram_webhook.get_settings", return_value=settings):
            response = verify_instagram_webhook(
                hub_mode="subscribe",
                hub_verify_token="verify-token",
                hub_challenge="12345",
            )
            self.assertEqual(response.body, b"12345")
            with self.assertRaises(HTTPException) as denied:
                verify_instagram_webhook(
                    hub_mode="subscribe",
                    hub_verify_token="wrong-token",
                    hub_challenge="12345",
                )
        self.assertEqual(denied.exception.status_code, 403)

    def test_signature_validation_and_required_signature(self):
        raw_body = json.dumps(self.payload()).encode("utf-8")
        valid_signature = "sha256=" + hmac.new(
            b"meta-secret",
            raw_body,
            hashlib.sha256,
        ).hexdigest()
        self.assertTrue(verify_meta_signature(raw_body, valid_signature, "meta-secret"))
        self.assertFalse(verify_meta_signature(raw_body, "sha256=invalid", "meta-secret"))

        settings = self.settings(instagram_require_signature=True)
        with patch("app.routers.instagram_webhook.get_settings", return_value=settings):
            with self.assertRaises(HTTPException) as invalid:
                asyncio.run(
                    receive_instagram_webhook(
                        self.webhook_request(raw_body),
                        x_hub_signature_256="sha256=invalid",
                        db=self.db,
                    )
                )
        self.assertEqual(invalid.exception.status_code, 403)

    def test_local_webhook_accepts_no_signature_and_saves_text(self):
        result = self.post_webhook(self.payload(), self.settings())
        message = self.db.query(ConversationMessage).one()
        conversation = self.db.query(Conversation).one()

        self.assertEqual(result["processed"], 1)
        self.assertEqual(message.body, "Hola")
        self.assertEqual(message.provider_message_id, "mid-1")
        self.assertIn('"sender"', message.raw_payload_json)
        self.assertEqual(conversation.channel, "instagram")
        self.assertEqual(conversation.external_user_id, "ig-customer-1")
        self.assertEqual(conversation.business_id, self.business_a.id)

    def test_attachment_is_saved_and_non_message_events_are_ignored(self):
        attachment_payload = self.payload(
            mid="mid-attachment",
            text=None,
            attachments=[{"type": "image", "payload": {"url": "https://example.test/image"}}],
        )
        result = self.post_webhook(attachment_payload, self.settings())
        self.assertEqual(result["processed"], 1)
        self.assertEqual(self.db.query(ConversationMessage).one().body, "[Adjunto recibido]")

        ignored_payload = {
            "object": "instagram",
            "entry": [
                {
                    "messaging": [
                        {"sender": {"id": "u"}, "recipient": {"id": "ig-business-1"}, "read": {}},
                        self.payload(mid="echo", is_echo=True)["entry"][0]["messaging"][0],
                    ]
                }
            ],
        }
        parsed = parse_instagram_webhook(
            ignored_payload,
            business_account_id="ig-business-1",
        )
        self.assertEqual(len(parsed), 1)
        self.assertTrue(parsed[0].is_echo)

    def test_manual_instagram_echo_creates_outbound_and_starts_pause(self):
        result = self.post_webhook(
            self.payload(mid="echo-manual", text="Respuesta desde Instagram", is_echo=True),
            self.settings(),
        )
        message = self.db.query(ConversationMessage).one()
        conversation = self.db.query(Conversation).one()

        self.assertEqual(result["processed"], 1)
        self.assertEqual(result["echoes"], 1)
        self.assertEqual(result["automation"], [])
        self.assertEqual(message.direction, "outbound")
        self.assertEqual(message.sender_type, "business")
        self.assertEqual(message.delivery_status, "sent")
        self.assertEqual(message.provider_message_id, "echo-manual")
        self.assertEqual(conversation.external_user_id, "ig-customer-1")
        self.assertEqual(conversation.automation_pause_reason, "human_reply")
        self.assertGreater(conversation.automation_paused_until, datetime.utcnow())

    def test_repeated_echo_is_idempotent(self):
        payload = self.payload(mid="echo-repeat", text="Una sola vez", is_echo=True)
        first = self.post_webhook(payload, self.settings())
        second = self.post_webhook(payload, self.settings())

        self.assertEqual(first["echoes"], 1)
        self.assertEqual(second["duplicates"], 1)
        self.assertEqual(self.db.query(ConversationMessage).count(), 1)

    def test_panel_outbound_without_mid_is_reconciled_by_unique_match(self):
        conversation = self.create_instagram_conversation(user_id="ig-customer-1")
        local = add_message(
            self.db,
            conversation=conversation,
            direction="outbound",
            sender_type="business",
            body="Respuesta pendiente",
            delivery_status="pending",
        )
        self.db.commit()

        result = self.post_webhook(
            self.payload(mid="echo-reconciled", text="  RESPUESTA pendiente! ", is_echo=True),
            self.settings(),
        )
        self.db.refresh(local)

        self.assertEqual(result["reconciled"], 1)
        self.assertEqual(self.db.query(ConversationMessage).count(), 1)
        self.assertEqual(local.provider_message_id, "echo-reconciled")
        self.assertEqual(local.delivery_status, "sent")

    def test_ambiguous_local_matches_are_not_merged(self):
        conversation = self.create_instagram_conversation(user_id="ig-customer-1")
        for _ in range(2):
            add_message(
                self.db,
                conversation=conversation,
                direction="outbound",
                sender_type="business",
                body="Texto repetido",
                delivery_status="pending",
            )
        self.db.commit()

        result = self.post_webhook(
            self.payload(mid="echo-ambiguous", text="Texto repetido", is_echo=True),
            self.settings(),
        )

        self.assertEqual(result["reconciled"], 0)
        self.assertEqual(result["echoes"], 1)
        self.assertEqual(self.db.query(ConversationMessage).count(), 3)
        self.assertEqual(
            self.db.query(ConversationMessage)
            .filter(ConversationMessage.provider_message_id == "echo-ambiguous")
            .count(),
            1,
        )

    def test_automatic_message_echo_reconciles_without_human_pause(self):
        conversation = self.create_instagram_conversation(user_id="ig-customer-1")
        automatic = add_message(
            self.db,
            conversation=conversation,
            direction="outbound",
            sender_type="automation",
            body="Respuesta automática",
            delivery_status="pending",
        )
        self.db.commit()

        result = self.post_webhook(
            self.payload(mid="echo-automatic", text="Respuesta automática", is_echo=True),
            self.settings(),
        )
        self.db.refresh(conversation)
        self.db.refresh(automatic)

        self.assertEqual(result["reconciled"], 1)
        self.assertEqual(automatic.provider_message_id, "echo-automatic")
        self.assertIsNone(conversation.automation_paused_until)

    def test_automatic_echo_with_existing_mid_does_not_duplicate_or_consume_again(self):
        conversation = self.create_instagram_conversation(user_id="ig-customer-1")
        settings_row, _ = ensure_automation_configuration(self.db, self.business_a)
        settings_row.auto_used_current_period = 1
        add_message(
            self.db,
            conversation=conversation,
            direction="outbound",
            sender_type="automation",
            body="Respuesta ya enviada",
            provider_message_id="automatic-existing-mid",
            delivery_status="sent",
        )
        self.db.commit()

        result = self.post_webhook(
            self.payload(
                mid="automatic-existing-mid",
                text="Respuesta ya enviada",
                is_echo=True,
            ),
            self.settings(),
        )
        self.db.refresh(settings_row)
        self.db.refresh(conversation)

        self.assertEqual(result["duplicates"], 1)
        self.assertEqual(self.db.query(ConversationMessage).count(), 1)
        self.assertEqual(settings_row.auto_used_current_period, 1)
        self.assertIsNone(conversation.automation_paused_until)

    def test_attachment_echo_is_persisted_without_automation(self):
        result = self.post_webhook(
            self.payload(
                mid="echo-attachment",
                text=None,
                attachments=[{"type": "image", "payload": {"url": "https://example.test/safe-image"}}],
                is_echo=True,
            ),
            self.settings(),
        )
        message = self.db.query(ConversationMessage).one()

        self.assertEqual(result["echoes"], 1)
        self.assertEqual(result["automation"], [])
        self.assertEqual(message.body, "[Adjunto enviado]")
        self.assertIn('"attachments"', message.raw_payload_json)

    def test_echo_provider_id_is_isolated_between_businesses(self):
        other_conversation = self.create_instagram_conversation(
            business=self.business_b,
            user_id="other-customer",
        )
        add_message(
            self.db,
            conversation=other_conversation,
            direction="outbound",
            sender_type="business",
            body="Otro negocio",
            provider_message_id="shared-mid",
            delivery_status="sent",
        )
        self.db.commit()

        result = self.post_webhook(
            self.payload(mid="shared-mid", text="Negocio correcto", is_echo=True),
            self.settings(),
        )

        self.assertEqual(result["echoes"], 1)
        self.assertEqual(result["duplicates"], 0)
        self.assertEqual(
            self.db.query(ConversationMessage)
            .join(Conversation)
            .filter(Conversation.business_id == self.business_a.id)
            .count(),
            1,
        )

    def test_webhook_reuses_conversation_and_is_idempotent(self):
        settings = self.settings()
        first = self.post_webhook(self.payload(mid="mid-first"), settings)
        second = self.post_webhook(
            self.payload(mid="mid-second", text="Segundo mensaje"),
            settings,
        )
        duplicate = self.post_webhook(self.payload(mid="mid-second"), settings)

        self.assertEqual(first["processed"], 1)
        self.assertEqual(second["processed"], 1)
        self.assertEqual(duplicate["duplicates"], 1)
        self.assertEqual(self.db.query(Conversation).count(), 1)
        self.assertEqual(self.db.query(ConversationMessage).count(), 2)

    def test_distinct_provider_ids_with_identical_text_are_debounced(self):
        settings_row, rules = ensure_automation_configuration(self.db, self.business_a)
        settings_row.automation_enabled = True
        settings_row.period_started_at = datetime.now(timezone.utc) - timedelta(days=1)
        settings_row.period_ends_at = datetime.now(timezone.utc) + timedelta(days=29)
        settings_row.period_status = "active"
        booking_rule = next(rule for rule in rules if rule.intent == "booking_intent")
        booking_rule.mode = "automatic"
        self.db.commit()

        provider_settings = self.settings()
        first = self.post_webhook(
            self.payload(mid="mid-identical-1", text="Quiero una cita"),
            provider_settings,
        )
        second = self.post_webhook(
            self.payload(mid="mid-identical-2", text="  QUIERO una cita! "),
            provider_settings,
        )

        self.assertEqual(first["automation"][0]["action"], "automatic")
        self.assertEqual(second["automation"][0]["status"], "skipped")
        self.assertEqual(
            second["automation"][0]["reason"],
            "identical_message_debounce",
        )
        self.assertEqual(settings_row.auto_used_current_period, 1)
        self.assertEqual(
            self.db.query(ConversationMessage)
            .filter(ConversationMessage.direction == "inbound")
            .count(),
            2,
        )
        self.assertEqual(
            self.db.query(ConversationMessage)
            .filter(ConversationMessage.direction == "outbound")
            .count(),
            1,
        )

    def test_same_provider_id_remains_idempotent_with_automation_enabled(self):
        settings_row, rules = ensure_automation_configuration(self.db, self.business_a)
        settings_row.automation_enabled = True
        settings_row.period_started_at = datetime.now(timezone.utc) - timedelta(days=1)
        settings_row.period_ends_at = datetime.now(timezone.utc) + timedelta(days=29)
        settings_row.period_status = "active"
        welcome_rule = next(rule for rule in rules if rule.intent == "welcome_intent")
        welcome_rule.mode = "automatic"
        self.db.commit()

        provider_settings = self.settings()
        first = self.post_webhook(
            self.payload(mid="mid-auto-idempotent", text="Hola"),
            provider_settings,
        )
        duplicate = self.post_webhook(
            self.payload(mid="mid-auto-idempotent", text="Hola"),
            provider_settings,
        )

        self.assertEqual(first["automation"][0]["action"], "automatic")
        self.assertEqual(duplicate["processed"], 0)
        self.assertEqual(duplicate["duplicates"], 1)
        self.assertEqual(settings_row.auto_used_current_period, 1)
        self.assertEqual(
            self.db.query(ConversationMessage)
            .filter(ConversationMessage.direction == "inbound")
            .count(),
            1,
        )
        self.assertEqual(
            self.db.query(ConversationMessage)
            .filter(ConversationMessage.direction == "outbound")
            .count(),
            1,
        )

    def test_webhook_ignores_unmapped_recipient(self):
        result = self.post_webhook(
            self.payload(recipient="another-account"),
            self.settings(),
        )
        self.assertEqual(result["processed"], 0)
        self.assertEqual(result["ignored"], 1)
        self.assertEqual(self.db.query(ConversationMessage).count(), 0)

    def test_provider_configuration_and_safe_send_contract(self):
        disabled = self.settings(instagram_provider_enabled=False)
        configured = self.settings(instagram_provider_enabled=True)
        self.assertFalse(is_instagram_provider_configured(disabled))
        self.assertTrue(is_instagram_provider_configured(configured))
        response = SimpleNamespace(
            ok=True,
            json=lambda: {"recipient_id": "ig-user", "message_id": "out-mid-1"},
        )
        with patch("app.services.instagram_provider.requests.post", return_value=response) as post:
            result = send_instagram_text_message(
                "ig-user",
                "Respuesta",
                settings=configured,
            )

        self.assertTrue(result.ok)
        self.assertEqual(result.provider_message_id, "out-mid-1")
        url = post.call_args.args[0]
        kwargs = post.call_args.kwargs
        self.assertEqual(
            url,
            "https://graph.instagram.com/v23.0/me/messages",
        )
        self.assertNotIn("test-access-token", url)
        self.assertEqual(kwargs["json"]["recipient"]["id"], "ig-user")
        self.assertEqual(kwargs["json"]["message"]["text"], "Respuesta")
        self.assertEqual(kwargs["timeout"], 10.0)

    def test_provider_error_is_safe_and_token_is_not_logged(self):
        settings = self.settings(instagram_provider_enabled=True)
        response = SimpleNamespace(
            ok=False,
            json=lambda: {"error": {"code": 190, "message": "provider detail"}},
        )
        with patch("app.services.instagram_provider.requests.post", return_value=response), patch(
            "logging.Logger._log"
        ) as logger_log:
            result = send_instagram_text_message("ig-user", "Respuesta", settings=settings)

        self.assertEqual(result.delivery_status, "failed")
        self.assertEqual(
            result.error_message,
            "Instagram provider rejected the message (code 190)",
        )
        self.assertNotIn(settings.instagram_access_token, result.error_message)
        logger_log.assert_not_called()

    def test_manual_outbound_uses_simulated_fallback_when_provider_is_disabled(self):
        conversation = self.create_instagram_conversation()
        settings = self.settings(instagram_provider_enabled=False)
        with patch("app.services.conversation_service.get_settings", return_value=settings):
            result = admin_send_conversation_message(
                self.business_a.slug,
                conversation.id,
                ConversationMessageCreate(body="Respuesta interna"),
                self.request(),
                actor=self.staff_user,
                db=self.db,
            )

        self.assertEqual(result["message"]["delivery_status"], "simulated")
        self.assertIsNone(result["message"]["provider_message_id"])
        self.assertFalse(result["provider_configured"])

    def test_manual_outbound_provider_success_and_failure(self):
        settings = self.settings(instagram_provider_enabled=True)
        success_conversation = self.create_instagram_conversation(user_id="success-user")
        with patch("app.services.conversation_service.get_settings", return_value=settings), patch(
            "app.services.conversation_service.send_instagram_text_message",
            return_value=ProviderSendResult("sent", "provider-out-1"),
        ):
            sent = admin_send_conversation_message(
                self.business_a.slug,
                success_conversation.id,
                ConversationMessageCreate(body="Respuesta real"),
                self.request(),
                actor=self.admin_user,
                db=self.db,
            )
        self.assertEqual(sent["message"]["delivery_status"], "sent")
        self.assertEqual(sent["message"]["provider_message_id"], "provider-out-1")

        failed_conversation = self.create_instagram_conversation(user_id="failed-user")
        with patch("app.services.conversation_service.get_settings", return_value=settings), patch(
            "app.services.conversation_service.send_instagram_text_message",
            return_value=ProviderSendResult("failed", error_message="safe failure"),
        ):
            with self.assertRaises(HTTPException) as failed:
                admin_send_conversation_message(
                    self.business_a.slug,
                    failed_conversation.id,
                    ConversationMessageCreate(body="No entregado"),
                    self.request(),
                    actor=self.admin_user,
                    db=self.db,
                )
        self.assertEqual(failed.exception.status_code, 502)
        self.db.refresh(failed_conversation)
        failed_message = (
            self.db.query(ConversationMessage)
            .filter(ConversationMessage.conversation_id == failed_conversation.id)
            .one()
        )
        self.assertEqual(failed_message.delivery_status, "failed")
        self.assertEqual(failed_conversation.status, "pending")
        self.assertIsNone(failed_conversation.automation_paused_until)

    def test_suggestion_send_uses_provider_without_automatic_credit(self):
        conversation = self.create_instagram_conversation(user_id="suggestion-user")
        settings_row, _ = ensure_automation_configuration(self.db, self.business_a)
        suggestion = ConversationSuggestion(
            conversation_id=conversation.id,
            intent="booking_intent",
            confidence=95,
            body="Puedes reservar aquí",
            status="pending",
        )
        self.db.add(suggestion)
        self.db.commit()
        provider_settings = self.settings(instagram_provider_enabled=True)

        with patch("app.services.conversation_service.get_settings", return_value=provider_settings), patch(
            "app.services.conversation_service.send_instagram_text_message",
            return_value=ProviderSendResult("sent", "suggestion-provider-mid"),
        ):
            result = admin_send_conversation_suggestion(
                self.business_a.slug,
                suggestion.id,
                self.request(),
                actor=self.staff_user,
                db=self.db,
            )

        self.assertEqual(result["suggestion"]["status"], "used")
        self.assertEqual(result["message"]["sender_type"], "business")
        self.assertEqual(result["message"]["provider_message_id"], "suggestion-provider-mid")
        self.assertEqual(settings_row.auto_used_current_period, 0)

    def test_automatic_uses_provider_and_failure_does_not_consume_credit(self):
        provider_settings = self.settings(instagram_provider_enabled=True)
        settings_row, rules = ensure_automation_configuration(self.db, self.business_a)
        settings_row.automation_enabled = True
        settings_row.period_started_at = datetime.now(timezone.utc) - timedelta(days=1)
        settings_row.period_ends_at = datetime.now(timezone.utc) + timedelta(days=29)
        settings_row.period_status = "active"
        booking_rule = next(rule for rule in rules if rule.intent == "booking_intent")
        booking_rule.mode = "automatic"
        self.db.commit()

        success_conversation = self.create_instagram_conversation(user_id="auto-success")
        success_inbound = add_message(
            self.db,
            conversation=success_conversation,
            direction="inbound",
            sender_type="customer",
            body="quiero una cita",
        )
        with patch("app.services.conversation_service.get_settings", return_value=provider_settings), patch(
            "app.services.conversation_service.send_instagram_text_message",
            return_value=ProviderSendResult("sent", "auto-provider-mid"),
        ):
            success = process_inbound_automation(
                self.db,
                business=self.business_a,
                conversation=success_conversation,
                message=success_inbound,
            )
        self.assertEqual(success["action"], "automatic")
        self.assertEqual(success["delivery_status"], "sent")
        self.assertEqual(settings_row.auto_used_current_period, 1)

        settings_row.auto_used_current_period = 0
        failed_conversation = self.create_instagram_conversation(user_id="auto-failed")
        failed_inbound = add_message(
            self.db,
            conversation=failed_conversation,
            direction="inbound",
            sender_type="customer",
            body="quiero una cita",
        )
        with patch("app.services.conversation_service.get_settings", return_value=provider_settings), patch(
            "app.services.conversation_service.send_instagram_text_message",
            return_value=ProviderSendResult("failed", error_message="safe failure"),
        ):
            failed = process_inbound_automation(
                self.db,
                business=self.business_a,
                conversation=failed_conversation,
                message=failed_inbound,
            )
        self.assertEqual(failed["action"], "automatic_failed")
        self.assertEqual(failed["delivery_status"], "failed")
        self.assertEqual(settings_row.auto_used_current_period, 0)
        self.assertEqual(failed_conversation.status, "pending")

        retry_inbound = add_message(
            self.db,
            conversation=failed_conversation,
            direction="inbound",
            sender_type="customer",
            body="quiero una cita",
        )
        with patch("app.services.conversation_service.get_settings", return_value=provider_settings), patch(
            "app.services.conversation_service.send_instagram_text_message",
            return_value=ProviderSendResult("sent", "auto-provider-retry-mid"),
        ):
            retry = process_inbound_automation(
                self.db,
                business=self.business_a,
                conversation=failed_conversation,
                message=retry_inbound,
            )
        self.assertEqual(retry["action"], "automatic")
        self.assertEqual(settings_row.auto_used_current_period, 1)

    def test_outbound_permissions_and_tenant_isolation(self):
        other_conversation = self.create_instagram_conversation(
            business=self.business_b,
            user_id="other-user",
        )
        with self.assertRaises(HTTPException):
            require_business_access(self.business_a.slug, self.customer_user, self.db)
        with self.assertRaises(HTTPException):
            get_current_user(None)
        with self.assertRaises(HTTPException) as hidden:
            admin_send_conversation_message(
                self.business_a.slug,
                other_conversation.id,
                ConversationMessageCreate(body="No permitido"),
                self.request(),
                actor=self.admin_user,
                db=self.db,
            )
        self.assertEqual(hidden.exception.status_code, 404)

    def test_admin_exposes_provider_and_delivery_indicators(self):
        admin_js = (
            Path(__file__).resolve().parents[2]
            / "autonogrow-admin"
            / "admin.js"
        ).read_text(encoding="utf-8")
        admin_styles = (
            Path(__file__).resolve().parents[2]
            / "autonogrow-admin"
            / "styles.css"
        ).read_text(encoding="utf-8")
        self.assertIn("Instagram conectado", admin_js)
        self.assertIn("Instagram no conectado · modo interno", admin_js)
        self.assertIn("conversation-delivery-failed", admin_styles)
        self.assertIn("Instagram real no está conectado", admin_js)


if __name__ == "__main__":
    unittest.main()
