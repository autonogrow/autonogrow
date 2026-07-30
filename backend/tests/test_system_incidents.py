import json
import unittest
from datetime import datetime, timedelta
from types import SimpleNamespace
from unittest.mock import patch

from fastapi import HTTPException
from sqlalchemy import create_engine, inspect
from sqlalchemy.orm import sessionmaker

from app.core.config import Settings
from app.core.database import Base
from app.core.security import require_owner
from app.models import Business, BusinessChannelIntegration, SystemIncident, User
from app.routers.conversations import admin_list_business_incidents
from app.services.incident_service import (
    GENERIC_SEND_CLIENT_MESSAGE,
    INSTAGRAM_AUTH_CLIENT_MESSAGE,
    report_incident,
    resolve_related_incidents,
)
from app.services.instagram_provider import send_instagram_text_message
from app.services.queue_error_service import classify_queue_error


class SystemIncidentTest(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine("sqlite:///:memory:")
        Base.metadata.create_all(self.engine)
        self.db = sessionmaker(bind=self.engine)()
        self.business_a = Business(slug="incident-a", name="Incident A", status="active")
        self.business_b = Business(slug="incident-b", name="Incident B", status="active")
        self.db.add_all([self.business_a, self.business_b])
        self.db.flush()
        self.instagram_integration = BusinessChannelIntegration(
            business_id=self.business_a.id,
            channel="instagram",
            provider="instagram",
            external_account_id="ig-business",
            encrypted_access_token="test-ciphertext",
            encryption_key_version="v1",
            integration_status="connected",
        )
        self.db.add(self.instagram_integration)
        self.db.commit()

    def tearDown(self):
        self.db.close()
        self.engine.dispose()

    def settings(self, **overrides):
        values = {
            "app_env": "local",
            "frontend_origins": "http://127.0.0.1:5500",
            "incident_alerts_enabled": False,
            "incident_alert_min_severity": "high",
            "incident_dedup_window_minutes": 30,
            "instagram_provider_enabled": True,
            "instagram_access_token": "test-access-token",
            "instagram_business_account_id": "ig-business",
            "meta_graph_api_version": "v23.0",
        }
        values.update(overrides)
        return Settings(_env_file=None, **values)

    def alert_settings(self, **overrides):
        return self.settings(
            incident_alerts_enabled=True,
            incident_alert_email="ops@autonogrow.test",
            smtp_host="smtp.autonogrow.test",
            smtp_from="alerts@autonogrow.test",
            **overrides,
        )

    def report(self, *, business_id=None, code="190", now=None, settings=None, **overrides):
        return report_incident(
            self.db,
            category=overrides.get("category", "provider_authentication"),
            severity=overrides.get("severity", "high"),
            business_id=business_id or self.business_a.id,
            channel=overrides.get("channel", "instagram"),
            provider=overrides.get("provider", "instagram"),
            provider_error_code=code,
            operation=overrides.get("operation", "send_message"),
            conversation_id=overrides.get("conversation_id", 10),
            message_id=overrides.get("message_id", 20),
            safe_details=overrides.get(
                "safe_details",
                {"intent": "booking_intent", "http_status": 400},
            ),
            settings=settings or self.settings(),
            occurred_at=now,
        )

    def test_first_high_alerts_and_deduplicates_inside_window(self):
        start = datetime(2026, 7, 29, 10, 0)
        settings = self.alert_settings()
        with patch("app.services.incident_service._send_email") as send_email:
            first = self.report(now=start, settings=settings)
            second = self.report(now=start + timedelta(minutes=10), settings=settings)
            third = self.report(now=start + timedelta(minutes=31), settings=settings)

        self.assertEqual(first.id, second.id)
        self.assertEqual(first.id, third.id)
        self.assertEqual(third.occurrence_count, 3)
        self.assertEqual(send_email.call_count, 2)
        self.assertEqual(third.notified_at, start + timedelta(minutes=31))

    def test_schema_contains_required_incident_columns(self):
        columns = {item["name"] for item in inspect(self.engine).get_columns("system_incidents")}
        self.assertTrue(
            {
                "id",
                "incident_key",
                "severity",
                "category",
                "status",
                "business_id",
                "channel",
                "provider",
                "provider_error_code",
                "operation",
                "conversation_id",
                "message_id",
                "occurrence_count",
                "first_occurred_at",
                "last_occurred_at",
                "notified_at",
                "resolved_at",
                "safe_details_json",
                "created_at",
                "updated_at",
            }.issubset(columns)
        )

    def test_businesses_and_errors_are_not_grouped_incorrectly(self):
        first = self.report()
        other_business = self.report(business_id=self.business_b.id)
        other_error = self.report(code="10")
        self.assertEqual(self.db.query(SystemIncident).count(), 3)
        self.assertNotEqual(first.incident_key, other_business.incident_key)
        self.assertNotEqual(first.incident_key, other_error.incident_key)

    def test_safe_details_drop_tokens_payloads_and_message_bodies(self):
        incident = self.report(
            safe_details={
                "intent": "booking_intent",
                "http_status": 400,
                "access_token": "SECRET_TOKEN",
                "Authorization": "Bearer SECRET_TOKEN",
                "payload": {"message": "full customer conversation"},
                "body": "full customer conversation",
                "recommended_action": "Internal review",
            }
        )
        stored = json.loads(incident.safe_details_json)
        self.assertEqual(stored["intent"], "booking_intent")
        self.assertNotIn("access_token", stored)
        self.assertNotIn("Authorization", stored)
        self.assertNotIn("payload", stored)
        self.assertNotIn("body", stored)
        self.assertNotIn("SECRET_TOKEN", incident.safe_details_json)
        self.assertNotIn("full customer conversation", incident.safe_details_json)

    def test_disabled_smtp_and_smtp_failure_do_not_break_reporting(self):
        with patch("app.services.incident_service._send_email") as disabled_email:
            disabled = self.report(settings=self.settings())
        disabled_email.assert_not_called()
        self.assertEqual(disabled.status, "open")

        settings = self.alert_settings()
        with patch("app.services.incident_service._send_email", side_effect=OSError("mail down")):
            failed_mail = self.report(code="191", settings=settings)
        self.assertEqual(failed_mail.status, "open")
        self.assertIsNone(failed_mail.notified_at)

    def test_recovery_email_is_sent_only_for_a_previously_notified_incident(self):
        settings = self.alert_settings()
        with patch("app.services.incident_service._send_email") as send_email:
            incident = self.report(settings=settings)
            resolved = resolve_related_incidents(
                self.db,
                business_id=self.business_a.id,
                channel="instagram",
                provider="instagram",
                operation="send_message",
                settings=settings,
            )
        self.assertEqual(resolved, [incident])
        self.assertEqual(incident.status, "resolved")
        self.assertEqual(send_email.call_count, 2)

    def test_known_critical_category_cannot_be_underclassified(self):
        incident = self.report(
            code=None,
            category="security_incident",
            severity="low",
            provider=None,
            channel=None,
            operation="security_check",
        )
        self.assertEqual(incident.severity, "critical")

    def test_oauth_190_creates_high_safe_incident_and_success_resolves_it(self):
        classification = classify_queue_error(error_code="190", http_status=400)
        self.assertTrue(classification.blocked)
        incident = report_incident(
            self.db,
            category="integration_unavailable",
            severity="high",
            business_id=self.business_a.id,
            integration_id=self.instagram_integration.id,
            channel="instagram",
            provider="instagram",
            provider_error_code="190",
            operation="process_outbox_1",
            safe_details={"outbox_id": 1, "error_subcode": "463"},
        )
        self.assertEqual(incident.severity, "high")
        self.assertEqual(incident.category, "integration_unavailable")
        self.assertEqual(incident.provider_error_code, "190")
        self.assertNotIn("Customer-facing response body", incident.safe_details_json)
        resolve_related_incidents(
            self.db,
            business_id=self.business_a.id,
            integration_id=self.instagram_integration.id,
            channel="instagram",
            provider="instagram",
            operation="process_outbox_1",
        )
        self.db.commit()
        self.db.refresh(incident)
        self.assertEqual(incident.status, "resolved")
        self.assertIsNotNone(incident.resolved_at)

    def test_instagram_provider_preserves_safe_error_fields(self):
        response = SimpleNamespace(
            ok=False,
            status_code=400,
            json=lambda: {
                "error": {
                    "message": "contains internal provider text",
                    "code": 190,
                    "error_subcode": 463,
                    "type": "OAuthException",
                }
            },
        )
        with patch("app.services.instagram_provider.requests.post", return_value=response):
            result = send_instagram_text_message(
                "ig-customer",
                "Hello",
                access_token="test-access-token",
                external_account_id="ig-business",
                settings=self.settings(),
            )
        self.assertEqual(result.http_status, 400)
        self.assertEqual(result.error_code, "190")
        self.assertEqual(result.error_subcode, "463")
        self.assertEqual(result.error_type, "OAuthException")
        self.assertNotIn("internal provider text", result.error_message)
        self.assertNotIn("test-access-token", result.error_message)

    def test_business_incident_view_is_isolated_and_safe(self):
        self.report(business_id=self.business_a.id)
        self.report(business_id=self.business_b.id, code="191")
        result = admin_list_business_incidents(self.business_a.slug, db=self.db)
        self.assertEqual(len(result["incidents"]), 1)
        safe = result["incidents"][0]
        self.assertIn(INSTAGRAM_AUTH_CLIENT_MESSAGE, safe["message"])
        self.assertNotIn("provider_error_code", safe)
        self.assertNotIn("safe_details", safe)

    def test_global_panel_requires_owner_role(self):
        owner = User(email="owner@autonogrow.test", is_owner=True)
        admin = User(email="admin@business.test", is_owner=False)
        self.assertIs(require_owner(owner), owner)
        with self.assertRaises(HTTPException) as denied:
            require_owner(admin)
        self.assertEqual(denied.exception.status_code, 403)

    def test_settings_validate_enabled_alert_configuration(self):
        with self.assertRaises(ValueError):
            self.settings(incident_alerts_enabled=True)
        configured = self.alert_settings()
        self.assertTrue(configured.incident_alerts_enabled)

    def test_generic_failure_uses_generic_safe_message(self):
        incident = self.report(code="10", category="provider_send_failure", severity="medium")
        from app.services.incident_service import client_message_for_incident

        message = client_message_for_incident(incident)
        self.assertIn(GENERIC_SEND_CLIENT_MESSAGE, message)
        self.assertNotIn("OAuth", message)


if __name__ == "__main__":
    unittest.main()
