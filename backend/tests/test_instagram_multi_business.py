import asyncio
import base64
import json
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from fastapi import HTTPException
from pydantic import ValidationError
from sqlalchemy import create_engine
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import sessionmaker
from starlette.requests import Request

from app.core.config import Settings
from app.core.database import Base
from app.models import (
    AuditLog,
    Business,
    BusinessChannelIntegration,
    BusinessUser,
    Conversation,
    ConversationMessage,
    SystemIncident,
    User,
)
from app.routers.conversations import admin_get_business_integration_status
from app.routers.instagram_webhook import receive_instagram_webhook
from app.routers.owner import (
    create_owner_business_instagram_integration,
    delete_owner_business_instagram_credentials,
    disconnect_owner_business_instagram_integration,
    reconnect_owner_business_instagram_integration,
)
from app.schemas.owner import (
    InstagramIntegrationCreateRequest,
    InstagramIntegrationDisconnectRequest,
    InstagramIntegrationReconnectRequest,
)
from app.services.conversation_automation_service import (
    ensure_automation_configuration,
    process_inbound_automation,
)
from app.services.conversation_service import add_message
from app.services.integration_crypto_service import (
    IntegrationCryptoError,
    decrypt_secret,
    encrypt_secret,
)
from app.services.instagram_integration_service import (
    integration_expiration_state,
    migrate_global_instagram_integration,
    oauth_failure_status,
    resolve_instagram_integration_for_event,
    send_business_instagram_message,
    validate_persisted_integration_secrets,
)
from app.services.instagram_provider import InstagramVerificationResult, ProviderSendResult


class InstagramMultiBusinessIntegrationTest(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine("sqlite:///:memory:")
        Base.metadata.create_all(self.engine)
        self.db = sessionmaker(bind=self.engine)()
        self.business_a = Business(slug="multi-a", name="Multi A", status="active")
        self.business_b = Business(slug="multi-b", name="Multi B", status="active")
        self.owner = User(email="owner@multi.test", is_owner=True)
        self.admin_a = User(email="admin-a@multi.test")
        self.admin_b = User(email="admin-b@multi.test")
        self.staff = User(email="staff@multi.test")
        self.customer = User(email="customer@multi.test")
        self.db.add_all(
            [
                self.business_a,
                self.business_b,
                self.owner,
                self.admin_a,
                self.admin_b,
                self.staff,
                self.customer,
            ]
        )
        self.db.flush()
        self.db.add_all(
            [
                BusinessUser(business_id=self.business_a.id, user_id=self.admin_a.id, role="business_admin", active=True),
                BusinessUser(business_id=self.business_b.id, user_id=self.admin_b.id, role="business_admin", active=True),
                BusinessUser(business_id=self.business_a.id, user_id=self.staff.id, role="business_staff", active=True),
            ]
        )
        self.db.commit()
        key = base64.urlsafe_b64encode(b"A" * 32).decode("ascii")
        old_key = base64.urlsafe_b64encode(b"B" * 32).decode("ascii")
        self.settings = Settings(
            _env_file=None,
            app_env="local",
            frontend_origins="http://127.0.0.1:5500",
            meta_graph_api_version="v23.0",
            instagram_provider_enabled=True,
            instagram_require_signature=False,
            integration_encryption_keys_json=json.dumps({"v1": key, "old": old_key}),
            integration_encryption_active_key_version="v1",
        )

    def tearDown(self):
        self.db.close()
        self.engine.dispose()

    def request(self, method="POST", path="/integrations/instagram", body=b""):
        sent = False

        async def receive():
            nonlocal sent
            if sent:
                return {"type": "http.request", "body": b"", "more_body": False}
            sent = True
            return {"type": "http.request", "body": body, "more_body": False}

        return Request(
            {
                "type": "http",
                "method": method,
                "path": path,
                "headers": [(b"x-request-id", b"multi-request")],
                "client": ("127.0.0.1", 50000),
            },
            receive,
        )

    def verification(self, account_id):
        return InstagramVerificationResult(
            ok=True,
            account_id=account_id,
            account_name=f"account-{account_id[-1]}",
            provider_status="available",
            scopes=("instagram_business_basic", "instagram_business_manage_messages"),
        )

    def add_integration(self, business, account_id, token, **overrides):
        ciphertext, version = encrypt_secret(token, settings=self.settings)
        integration = BusinessChannelIntegration(
            business_id=business.id,
            channel="instagram",
            provider="instagram",
            external_account_id=account_id,
            encrypted_access_token=ciphertext,
            encryption_key_version=version,
            integration_status=overrides.pop("integration_status", "connected"),
            connected_at=datetime.now(timezone.utc),
            **overrides,
        )
        self.db.add(integration)
        self.db.commit()
        return integration

    def test_authenticated_encryption_rotation_contract_and_tampering(self):
        token = "secret-token-A"
        ciphertext, version = encrypt_secret(token, settings=self.settings)
        self.assertNotEqual(ciphertext, token)
        self.assertNotIn(token, ciphertext)
        self.assertEqual(version, "v1")
        self.assertEqual(decrypt_secret(ciphertext, version, settings=self.settings), token)
        with self.assertRaises(IntegrationCryptoError):
            decrypt_secret(ciphertext[:-2] + "AA", version, settings=self.settings)
        wrong = Settings(
            _env_file=None,
            integration_encryption_keys_json=json.dumps(
                {"v1": base64.urlsafe_b64encode(b"Z" * 32).decode("ascii")}
            ),
            integration_encryption_active_key_version="v1",
        )
        with self.assertRaises(IntegrationCryptoError):
            decrypt_secret(ciphertext, version, settings=wrong)
        with self.assertRaises(IntegrationCryptoError):
            decrypt_secret(ciphertext, "missing", settings=self.settings)

    def test_external_account_is_unique_and_cannot_move_between_businesses(self):
        self.add_integration(self.business_a, "account-unique", "token-A")
        self.db.add(
            BusinessChannelIntegration(
                business_id=self.business_b.id,
                channel="instagram",
                provider="instagram",
                external_account_id="account-unique",
                integration_status="pending",
            )
        )
        with self.assertRaises(IntegrityError):
            self.db.commit()
        self.db.rollback()

    def test_owner_create_encrypts_and_never_returns_or_audits_token(self):
        secret = "top-secret-instagram-token"
        payload = InstagramIntegrationCreateRequest(
            external_account_id="account-create",
            access_token=secret,
            reason="Alta inicial segura",
        )
        with patch(
            "app.routers.owner.verify_instagram_access_token",
            return_value=self.verification("account-create"),
        ), patch(
            "app.services.integration_crypto_service.get_settings",
            return_value=self.settings,
        ):
            response = create_owner_business_instagram_integration(
                self.business_a.id,
                payload,
                self.request(),
                actor=self.owner,
                db=self.db,
            )
        integration = self.db.query(BusinessChannelIntegration).one()
        audit = self.db.query(AuditLog).one()
        self.assertNotIn(secret, integration.encrypted_access_token)
        self.assertEqual(
            decrypt_secret(
                integration.encrypted_access_token,
                integration.encryption_key_version,
                settings=self.settings,
            ),
            secret,
        )
        serialized = json.dumps(response, default=str)
        self.assertNotIn(secret, serialized)
        self.assertNotIn("encrypted_access_token", serialized)
        self.assertNotIn(secret, audit.metadata_json)
        with self.assertRaises(ValidationError):
            InstagramIntegrationCreateRequest.model_validate(
                {
                    "external_account_id": "x",
                    "access_token": "long-enough-token",
                    "reason": "Alta",
                    "business_id": self.business_b.id,
                }
            )

    def test_webhook_routes_two_businesses_and_unmapped_is_safe(self):
        self.add_integration(self.business_a, "account-A", "token-A")
        self.add_integration(self.business_b, "account-B", "token-B")
        payload = {
            "object": "instagram",
            "entry": [
                {
                    "messaging": [
                        {
                            "sender": {"id": "customer-A"},
                            "recipient": {"id": "account-A"},
                            "timestamp": 1,
                            "message": {"mid": "mid-A", "text": "Texto A"},
                        },
                        {
                            "sender": {"id": "customer-B"},
                            "recipient": {"id": "account-B"},
                            "timestamp": 2,
                            "message": {"mid": "mid-B", "text": "Texto B"},
                        },
                        {
                            "sender": {"id": "unknown-customer"},
                            "recipient": {"id": "unknown-account"},
                            "timestamp": 3,
                            "message": {"mid": "mid-unknown", "text": "Sensitive body"},
                        },
                    ]
                }
            ],
        }
        raw = json.dumps(payload).encode("utf-8")
        with patch("app.routers.instagram_webhook.get_settings", return_value=self.settings):
            result = asyncio.run(receive_instagram_webhook(self.request(body=raw), db=self.db))
        self.assertEqual(result["processed"], 2)
        self.assertEqual(result["ignored"], 1)
        rows = self.db.query(Conversation).order_by(Conversation.business_id).all()
        self.assertEqual([item.business_id for item in rows], [self.business_a.id, self.business_b.id])
        incident = self.db.query(SystemIncident).filter(
            SystemIncident.category == "instagram_unmapped_account"
        ).one()
        self.assertNotIn("Sensitive body", incident.safe_details_json)
        self.assertNotIn("unknown-account", incident.safe_details_json)

    def test_inbound_uses_recipient_and_echo_uses_sender(self):
        integration_a = self.add_integration(self.business_a, "account-A", "token-A")
        integration_b = self.add_integration(self.business_b, "account-B", "token-B")
        inbound = resolve_instagram_integration_for_event(
            self.db,
            sender_id="customer",
            recipient_id="account-A",
            is_echo=False,
        )
        echo = resolve_instagram_integration_for_event(
            self.db,
            sender_id="account-B",
            recipient_id="customer",
            is_echo=True,
        )
        self.assertEqual(inbound.id, integration_a.id)
        self.assertEqual(echo.id, integration_b.id)

    def test_each_business_send_uses_only_its_own_decrypted_token(self):
        self.add_integration(self.business_a, "account-A", "token-A")
        self.add_integration(self.business_b, "account-B", "token-B")
        observed = []

        def fake_send(recipient_id, text, **kwargs):
            observed.append((recipient_id, kwargs["external_account_id"], kwargs["access_token"]))
            return ProviderSendResult("sent", f"mid-{recipient_id}")

        with patch(
            "app.services.instagram_integration_service.send_instagram_text_message",
            side_effect=fake_send,
        ):
            send_business_instagram_message(
                self.db,
                business_id=self.business_a.id,
                recipient_id="customer-A",
                text="A",
                settings=self.settings,
            )
            send_business_instagram_message(
                self.db,
                business_id=self.business_b.id,
                recipient_id="customer-B",
                text="B",
                settings=self.settings,
            )
        self.assertEqual(
            observed,
            [
                ("customer-A", "account-A", "token-A"),
                ("customer-B", "account-B", "token-B"),
            ],
        )

    def test_decryption_failure_is_isolated_and_incident_contains_no_secret(self):
        integration = self.add_integration(
            self.business_a, "account-corrupt", "never-log-this-token"
        )
        integration.encrypted_access_token = integration.encrypted_access_token[:-2] + "AA"
        self.db.commit()
        result, _ = send_business_instagram_message(
            self.db,
            business_id=self.business_a.id,
            recipient_id="customer",
            text="No enviar",
            settings=self.settings,
        )
        self.assertEqual(result.error_code, "integration_decryption_failed")
        self.assertEqual(integration.integration_status, "error")
        incident = self.db.query(SystemIncident).filter(
            SystemIncident.category == "integration_decryption_failed"
        ).one()
        serialized = incident.safe_details_json
        self.assertNotIn("never-log-this-token", serialized)
        self.assertNotIn(integration.encrypted_access_token, serialized)

    def test_expired_and_disconnected_integrations_block_without_provider_or_credit(self):
        expired = self.add_integration(
            self.business_a,
            "account-expired",
            "token-expired",
            token_expires_at=datetime.now(timezone.utc) - timedelta(seconds=1),
        )
        with patch("app.services.instagram_integration_service.send_instagram_text_message") as provider:
            result, _ = send_business_instagram_message(
                self.db,
                business_id=self.business_a.id,
                recipient_id="customer",
                text="No enviar",
                settings=self.settings,
            )
        provider.assert_not_called()
        self.assertEqual(result.error_code, "integration_expired")
        self.assertEqual(expired.integration_status, "expired")

        automation, rules = ensure_automation_configuration(self.db, self.business_a)
        automation.automation_enabled = True
        automation.period_started_at = datetime.now(timezone.utc) - timedelta(days=1)
        automation.period_ends_at = datetime.now(timezone.utc) + timedelta(days=29)
        automation.period_status = "active"
        next(item for item in rules if item.intent == "booking_intent").mode = "automatic"
        conversation = Conversation(
            business_id=self.business_a.id,
            channel="instagram",
            external_user_id="customer",
            status="pending",
        )
        self.db.add(conversation)
        self.db.flush()
        inbound = add_message(
            self.db,
            conversation=conversation,
            direction="inbound",
            sender_type="customer",
            body="quiero una cita",
        )
        with patch("app.services.conversation_service.get_settings", return_value=self.settings):
            automation_result = process_inbound_automation(
                self.db,
                business=self.business_a,
                conversation=conversation,
                message=inbound,
            )
        self.assertEqual(automation_result["action"], "automatic_failed")
        self.assertEqual(automation.included_credits_used, 0)

    def test_oauth_failure_changes_only_the_correct_integration(self):
        integration_a = self.add_integration(self.business_a, "account-A", "token-A")
        integration_b = self.add_integration(self.business_b, "account-B", "token-B")
        with patch(
            "app.services.instagram_integration_service.send_instagram_text_message",
            return_value=ProviderSendResult("failed", error_code="190", error_type="OAuthException"),
        ):
            send_business_instagram_message(
                self.db,
                business_id=self.business_a.id,
                recipient_id="customer",
                text="A",
                settings=self.settings,
            )
        self.assertEqual(integration_a.integration_status, "revoked")
        self.assertEqual(integration_b.integration_status, "connected")

    def test_reconnect_disconnect_delete_and_admin_read_only_status(self):
        integration = self.add_integration(self.business_a, "account-A", "old-token")
        reconnect = InstagramIntegrationReconnectRequest(
            external_account_id="account-A",
            access_token="new-secret-token",
            reason="Rotación por seguridad",
        )
        with patch(
            "app.routers.owner.verify_instagram_access_token",
            return_value=self.verification("account-A"),
        ), patch(
            "app.services.integration_crypto_service.get_settings",
            return_value=self.settings,
        ):
            response = reconnect_owner_business_instagram_integration(
                self.business_a.id,
                reconnect,
                self.request(),
                actor=self.owner,
                db=self.db,
            )
        self.assertEqual(response["integration_status"], "connected")
        self.assertEqual(
            decrypt_secret(
                integration.encrypted_access_token,
                integration.encryption_key_version,
                settings=self.settings,
            ),
            "new-secret-token",
        )
        admin = admin_get_business_integration_status(
            self.business_a.slug,
            actor=self.admin_a,
            db=self.db,
        )
        self.assertEqual(admin["state"], "connected")
        self.assertNotIn("account", json.dumps(admin).lower())
        with self.assertRaises(HTTPException):
            admin_get_business_integration_status(
                self.business_b.slug,
                actor=self.admin_a,
                db=self.db,
            )
        disconnect_owner_business_instagram_integration(
            self.business_a.id,
            InstagramIntegrationDisconnectRequest(reason="Baja temporal"),
            self.request(),
            actor=self.owner,
            db=self.db,
        )
        blocked, _ = send_business_instagram_message(
            self.db,
            business_id=self.business_a.id,
            recipient_id="customer",
            text="No enviar",
            settings=self.settings,
        )
        self.assertEqual(blocked.error_code, "integration_disconnected")
        deleted = delete_owner_business_instagram_credentials(
            self.business_a.id,
            InstagramIntegrationDisconnectRequest(reason="Baja definitiva"),
            self.request(method="DELETE"),
            actor=self.owner,
            db=self.db,
        )
        self.assertFalse(deleted["has_credentials"])
        self.assertIsNone(integration.encrypted_access_token)
        for actor in (self.admin_a, self.staff, self.customer):
            with self.subTest(actor=actor.email), self.assertRaises(HTTPException):
                disconnect_owner_business_instagram_integration(
                    self.business_a.id,
                    InstagramIntegrationDisconnectRequest(reason="No autorizado"),
                    self.request(),
                    actor=actor,
                    db=self.db,
                )

    def test_legacy_migration_is_encrypted_idempotent_and_requires_key(self):
        migration_settings = self.settings.model_copy(
            update={
                "instagram_access_token": "legacy-secret-token",
                "instagram_business_account_id": "legacy-account",
                "instagram_default_business_slug": self.business_a.slug,
            }
        )
        with patch(
            "app.services.instagram_integration_service.logger.warning"
        ) as warning:
            first = migrate_global_instagram_integration(
                self.db, settings=migration_settings
            )
        self.assertNotIn("legacy-secret-token", str(warning.call_args_list))
        self.db.commit()
        second = migrate_global_instagram_integration(self.db, settings=migration_settings)
        self.assertEqual(first.id, second.id)
        self.assertNotIn("legacy-secret-token", first.encrypted_access_token)
        self.assertEqual(self.db.query(BusinessChannelIntegration).count(), 1)
        self.assertEqual(
            self.db.query(AuditLog)
            .filter(AuditLog.action == "instagram_global_integration_migrated")
            .count(),
            1,
        )
        validate_persisted_integration_secrets(self.db, settings=migration_settings)

        missing_key = migration_settings.model_copy(
            update={"integration_encryption_keys_json": ""}
        )
        self.db.delete(first)
        self.db.commit()
        with self.assertRaises(IntegrationCryptoError):
            migrate_global_instagram_integration(self.db, settings=missing_key)

    def test_expiration_warning_window(self):
        integration = self.add_integration(
            self.business_a,
            "account-warning",
            "token",
            token_expires_at=datetime.now(timezone.utc) + timedelta(days=6),
        )
        expired, soon, remaining = integration_expiration_state(integration)
        self.assertFalse(expired)
        self.assertTrue(soon)
        self.assertLessEqual(remaining, 6)
        self.assertEqual(oauth_failure_status("190", "463"), "expired")
        self.assertEqual(oauth_failure_status("190", "467"), "revoked")

    def test_frontend_keeps_credentials_owner_only_and_ephemeral(self):
        root = Path(__file__).resolve().parents[2]
        owner_js = (root / "autonogrow-owner" / "owner.js").read_text(encoding="utf-8")
        admin_js = (root / "autonogrow-admin" / "admin.js").read_text(encoding="utf-8")
        self.assertIn('data-integration-token type="password"', owner_js)
        self.assertIn("payload.access_token = \"\"", owner_js)
        self.assertIn("integrations/instagram", owner_js)
        self.assertIn("integrations/status", admin_js)
        self.assertNotIn("integrations/instagram/reconnect", admin_js)
        self.assertNotIn("data-integration-token", admin_js)


if __name__ == "__main__":
    unittest.main()
