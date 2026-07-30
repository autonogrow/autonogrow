import unittest
from types import SimpleNamespace
from unittest.mock import patch

from fastapi import HTTPException
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from starlette.requests import Request

from app.core.config import Settings
from app.core.database import Base
from app.core.security import get_current_user, require_business_access, require_business_admin
from app.models import Business, BusinessUser, Conversation, ConversationMessage, User
from app.routers.conversations import (
    admin_create_conversation,
    admin_create_conversation_template,
    admin_delete_conversation_template,
    admin_get_conversation,
    admin_list_conversation_templates,
    admin_list_conversations,
    admin_send_conversation_message,
    admin_update_conversation_status,
    admin_update_conversation_template,
    verify_test_webhook_secret,
)
from app.routers.conversations import (
    test_inbound_message as inbound_message_endpoint,
)
from app.schemas.conversation import (
    ConversationCreate,
    ConversationMessageCreate,
    ConversationStatusUpdate,
    ConversationTemplateCreate,
    ConversationTemplateUpdate,
    TestInboundMessageCreate,
)
from app.services.conversation_service import render_template


class ConversationsTest(unittest.TestCase):
    def setUp(self):
        self.public_origin_patcher = patch(
            "app.services.conversation_service.get_settings",
            return_value=SimpleNamespace(frontend_origin_list=["http://127.0.0.1:5500"]),
        )
        self.public_origin_patcher.start()
        self.engine = create_engine("sqlite:///:memory:")
        Base.metadata.create_all(self.engine)
        self.db = sessionmaker(bind=self.engine)()
        self.business_a = Business(
            slug="conversation-a",
            name="Business A",
            address="Calle A 1",
            phone="600000001",
            status="active",
        )
        self.business_b = Business(slug="conversation-b", name="Business B", status="active")
        self.owner = User(email="owner@conversation.test", is_owner=True)
        self.admin_user = User(email="admin@conversation.test")
        self.other_admin_user = User(email="other@conversation.test")
        self.staff_user = User(email="staff@conversation.test")
        self.customer_user = User(email="customer@conversation.test")
        self.admin = BusinessUser(
            business=self.business_a,
            user=self.admin_user,
            role="business_admin",
            active=True,
        )
        self.other_admin = BusinessUser(
            business=self.business_b,
            user=self.other_admin_user,
            role="business_admin",
            active=True,
        )
        self.staff = BusinessUser(
            business=self.business_a,
            user=self.staff_user,
            role="business_staff",
            active=True,
        )
        self.db.add_all(
            [
                self.business_a,
                self.business_b,
                self.owner,
                self.admin_user,
                self.other_admin_user,
                self.staff_user,
                self.customer_user,
                self.admin,
                self.other_admin,
                self.staff,
            ]
        )
        self.db.commit()

    def tearDown(self):
        self.public_origin_patcher.stop()
        self.db.close()
        self.engine.dispose()

    def request(self, method="POST"):
        return Request(
            {
                "type": "http",
                "method": method,
                "path": "/api/admin/businesses/conversation-a/conversations",
                "headers": [],
                "client": ("testclient", 50000),
            }
        )

    def create_manual(self, name="Ana", message="Hola, quiero una cita"):
        require_business_admin(self.business_a.slug, self.admin_user, self.db)
        return admin_create_conversation(
            self.business_a.slug,
            ConversationCreate(channel="manual", customer_name=name, initial_message=message),
            self.request(),
            actor=self.admin_user,
            db=self.db,
        )["conversation"]

    def test_admin_create_list_filter_search_and_tenant_isolation(self):
        first = self.create_manual()
        admin_create_conversation(
            self.business_a.slug,
            ConversationCreate(
                channel="whatsapp",
                customer_name="Bea",
                customer_phone="611111111",
                external_user_id="wa-1",
                initial_message="Precio de servicios",
            ),
            self.request(),
            actor=self.admin_user,
            db=self.db,
        )
        result = admin_list_conversations(
            self.business_a.slug,
            status="pending",
            channel="manual",
            q="Ana",
            limit=50,
            offset=0,
            db=self.db,
        )
        self.assertEqual(result["total"], 1)
        self.assertEqual(result["conversations"][0]["id"], first["id"])

        other = Conversation(
            business_id=self.business_b.id,
            channel="instagram",
            external_user_id="ig-other",
            status="pending",
        )
        self.db.add(other)
        self.db.commit()
        all_a = admin_list_conversations(
            self.business_a.slug,
            status=None,
            channel=None,
            q=None,
            limit=100,
            offset=0,
            db=self.db,
        )
        self.assertNotIn(other.id, {item["id"] for item in all_a["conversations"]})
        with self.assertRaises(HTTPException) as hidden:
            admin_get_conversation(self.business_a.slug, other.id, db=self.db)
        self.assertEqual(hidden.exception.status_code, 404)

        with self.assertRaises(HTTPException) as cross_tenant:
            require_business_access(self.business_b.slug, self.admin_user, self.db)
        self.assertEqual(cross_tenant.exception.status_code, 403)
        self.assertIs(
            require_business_access(self.business_b.slug, self.owner, self.db),
            self.owner,
        )
        owner_result = admin_list_conversations(
            self.business_b.slug,
            status=None,
            channel=None,
            q=None,
            limit=50,
            offset=0,
            db=self.db,
        )
        self.assertEqual([item["id"] for item in owner_result["conversations"]], [other.id])

    def test_staff_can_view_reply_and_change_status_but_not_manage_templates(self):
        conversation = self.create_manual()
        self.assertIs(
            require_business_access(self.business_a.slug, self.staff_user, self.db),
            self.staff_user,
        )
        detail = admin_get_conversation(self.business_a.slug, conversation["id"], db=self.db)[
            "conversation"
        ]
        self.assertEqual(len(detail["messages"]), 1)
        listed = admin_list_conversations(
            self.business_a.slug,
            status=None,
            channel=None,
            q=None,
            limit=50,
            offset=0,
            db=self.db,
        )
        self.assertEqual(listed["total"], 1)

        sent = admin_send_conversation_message(
            self.business_a.slug,
            conversation["id"],
            ConversationMessageCreate(body="Te ayudamos a reservar"),
            self.request(),
            actor=self.staff_user,
            db=self.db,
        )
        self.assertEqual(sent["conversation"]["status"], "replied")
        self.assertEqual(sent["message"]["delivery_status"], "sent")

        closed = admin_update_conversation_status(
            self.business_a.slug,
            conversation["id"],
            ConversationStatusUpdate(status="closed"),
            self.request("PATCH"),
            actor=self.staff_user,
            db=self.db,
        )
        self.assertEqual(closed["conversation"]["status"], "closed")
        reopened = admin_update_conversation_status(
            self.business_a.slug,
            conversation["id"],
            ConversationStatusUpdate(status="pending"),
            self.request("PATCH"),
            actor=self.staff_user,
            db=self.db,
        )
        self.assertEqual(reopened["conversation"]["status"], "pending")

        with self.assertRaises(HTTPException) as denied:
            require_business_admin(self.business_a.slug, self.staff_user, self.db)
        self.assertEqual(denied.exception.status_code, 403)
        with self.assertRaises(HTTPException):
            require_business_access(self.business_a.slug, self.customer_user, self.db)
        with self.assertRaises(HTTPException) as anonymous:
            get_current_user(None)
        self.assertEqual(anonymous.exception.status_code, 401)

    def test_inbound_webhook_creates_then_reuses_conversation(self):
        first = inbound_message_endpoint(
            TestInboundMessageCreate(
                business_slug=self.business_a.slug,
                channel="instagram",
                external_user_id="ig-user-123",
                customer_name="Cliente Instagram",
                customer_username="cliente_demo",
                body="Hola",
            ),
            x_autonogrow_webhook_secret=None,
            db=self.db,
        )
        second = inbound_message_endpoint(
            TestInboundMessageCreate(
                business_slug=self.business_a.slug,
                channel="instagram",
                external_user_id="ig-user-123",
                body="Quería una cita",
            ),
            x_autonogrow_webhook_secret=None,
            db=self.db,
        )
        self.assertTrue(first["created"])
        self.assertFalse(second["created"])
        self.assertEqual(first["conversation_id"], second["conversation_id"])
        self.assertEqual(
            self.db.query(ConversationMessage)
            .filter(ConversationMessage.conversation_id == first["conversation_id"])
            .count(),
            2,
        )
        self.assertIsNotNone(
            self.db.query(ConversationMessage)
            .filter(ConversationMessage.conversation_id == first["conversation_id"])
            .first()
            .raw_payload_json
        )
        conversation = self.db.get(Conversation, first["conversation_id"])
        self.assertEqual(conversation.status, "pending")
        self.assertEqual(conversation.last_message_text, "Quería una cita")

    def test_templates_seed_render_and_admin_creation(self):
        listed = admin_list_conversation_templates(self.business_a.slug, db=self.db)["templates"]
        self.assertEqual(len(listed), 8)
        welcome = next(item for item in listed if item["name"] == "Mensaje de bienvenida")
        self.assertIn("Business A", welcome["rendered_body"])
        self.assertIn(
            "http://127.0.0.1:5500/autonogrow-landing/?b=conversation-a",
            welcome["rendered_body"],
        )

        created = admin_create_conversation_template(
            self.business_a.slug,
            ConversationTemplateCreate(
                name="Personalizada",
                body="Hola {business_name}: {business_phone} {business_address}",
            ),
            self.request(),
            actor=self.admin_user,
            db=self.db,
        )["template"]
        self.assertEqual(created["rendered_body"], "Hola Business A: 600000001 Calle A 1")
        updated = admin_update_conversation_template(
            self.business_a.slug,
            created["id"],
            ConversationTemplateUpdate(body="Reserva en {public_booking_url}"),
            self.request("PATCH"),
            actor=self.admin_user,
            db=self.db,
        )["template"]
        self.assertEqual(
            updated["rendered_body"],
            "Reserva en http://127.0.0.1:5500/autonogrow-landing/?b=conversation-a",
        )
        deleted = admin_delete_conversation_template(
            self.business_a.slug,
            created["id"],
            self.request("DELETE"),
            actor=self.admin_user,
            db=self.db,
        )
        self.assertTrue(deleted["ok"])
        self.assertEqual(
            render_template("Reserva: {public_booking_url}", self.business_a),
            "Reserva: http://127.0.0.1:5500/autonogrow-landing/?b=conversation-a",
        )
        self.business_a.address = None
        self.assertEqual(
            render_template("Estamos en {business_address}", self.business_a),
            "Puedes ver la información del negocio aquí: http://127.0.0.1:5500/autonogrow-landing/?b=conversation-a",
        )

    def test_public_booking_url_uses_first_configured_frontend_origin(self):
        with patch.dict(
            "os.environ",
            {"FRONTEND_ORIGINS": "https://staging.autonogrow.es"},
        ):
            settings = Settings(_env_file=None, app_env="local")
        business = Business(slug="estudio-prueba", name="Estudio Prueba")

        with patch(
            "app.services.conversation_service.get_settings",
            return_value=settings,
        ):
            rendered = render_template(
                "Reserva: {public_booking_url}",
                business,
            )

        self.assertEqual(
            rendered,
            "Reserva: https://staging.autonogrow.es/autonogrow-landing/?b=estudio-prueba",
        )

        with patch(
            "app.services.conversation_service.get_settings",
            return_value=SimpleNamespace(
                frontend_origin_list=[
                    "https://staging.autonogrow.es/",
                    "https://admin.autonogrow.es",
                ]
            ),
        ):
            rendered_from_first_origin = render_template(
                "{public_booking_url}",
                business,
            )

        self.assertEqual(
            rendered_from_first_origin,
            "https://staging.autonogrow.es/autonogrow-landing/?b=estudio-prueba",
        )

    def test_public_booking_url_keeps_relative_fallback_without_origins(self):
        with patch(
            "app.services.conversation_service.get_settings",
            return_value=SimpleNamespace(frontend_origin_list=[]),
        ):
            rendered = render_template(
                "Reserva: {public_booking_url}",
                self.business_a,
            )

        self.assertEqual(
            rendered,
            "Reserva: /autonogrow-landing/?b=conversation-a",
        )

    def test_webhook_secret_is_required_outside_local(self):
        with patch(
            "app.routers.conversations.get_settings",
            return_value=SimpleNamespace(
                app_env="production", webhook_test_secret="configured-secret"
            ),
        ):
            with self.assertRaises(HTTPException) as missing:
                verify_test_webhook_secret(None)
            self.assertEqual(missing.exception.status_code, 403)
            verify_test_webhook_secret("configured-secret")


if __name__ == "__main__":
    unittest.main()
