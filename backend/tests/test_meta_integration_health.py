import base64
import json
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import patch

import pytest
from pydantic import ValidationError
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.core.config import Settings
from app.core.database import Base
from app.models import (
    Business,
    BusinessChannelControl,
    BusinessChannelIntegration,
    InstagramOAuthAttempt,
    MetaIntegrationJob,
    User,
)
from app.services.instagram_login_provider import InstagramLoginProviderError
from app.services.integration_crypto_service import encrypt_secret
from app.services.meta_integration_health_checkers import (
    check_instagram_integration_health,
    check_whatsapp_integration_health,
    health_checker_for_provider,
)
from app.services.meta_integration_health_contracts import (
    IntegrationHealthResult,
    UnsupportedIntegrationHealthProvider,
)
from app.services.meta_integration_job_service import (
    apply_integration_health_result,
    claim_meta_integration_jobs,
    cleanup_meta_integration_attempts,
    enqueue_meta_integration_job,
    integration_health_blocks_delivery,
    serialize_integration_health,
)
from app.services.whatsapp_embedded_signup_provider import WhatsAppEmbeddedSignupProviderError
from app.workers.channel_worker import ChannelWorker


def health_settings(**overrides):
    key = base64.urlsafe_b64encode(b"h" * 32).decode()
    values = {
        "app_env": "test",
        "meta_app_id": "123456789",
        "meta_app_secret": "meta-secret",
        "instagram_login_client_id": "123456789",
        "instagram_login_graph_api_version": "v23.0",
        "whatsapp_embedded_signup_graph_api_version": "v23.0",
        "integration_encryption_keys_json": json.dumps({"v1": key}),
        "integration_encryption_active_key_version": "v1",
    }
    values.update(overrides)
    return Settings(_env_file=None, **values)


@pytest.fixture
def health_db(tmp_path):
    engine = create_engine(
        f"sqlite:///{tmp_path / 'health.db'}", connect_args={"check_same_thread": False}
    )
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, autoflush=False, autocommit=False)
    with factory() as db:
        yield db, factory
    engine.dispose()


def integration_context(db, settings, *, channel="instagram", slug="health-business"):
    business = Business(slug=slug, name=slug, status="active")
    owner = User(email=f"owner-{slug}@example.com", name="Owner", is_owner=True)
    db.add_all([business, owner])
    db.flush()
    ciphertext, version = encrypt_secret("safe-test-token", settings=settings)
    integration = BusinessChannelIntegration(
        business_id=business.id,
        channel=channel,
        provider=channel,
        external_account_id="1234567001" if channel == "instagram" else "1234567002",
        provider_account_id="1234567003" if channel == "whatsapp" else None,
        encrypted_access_token=ciphertext,
        encryption_key_version=version,
        token_expires_at=datetime.utcnow() + timedelta(days=30),
        granted_scopes_json=json.dumps(
            [
                "instagram_business_basic",
                "instagram_business_manage_messages",
            ]
            if channel == "instagram"
            else [
                "business_management",
                "whatsapp_business_management",
                "whatsapp_business_messaging",
            ]
        ),
        integration_status="connected",
        metadata_json=(
            json.dumps({"meta_business_id": "1234567004"}) if channel == "whatsapp" else None
        ),
    )
    control = BusinessChannelControl(
        business_id=business.id,
        channel=channel,
        status="approved",
        connector_policy="business_admin",
        connection_mode="oauth" if channel == "instagram" else "embedded_signup",
        integrated_delivery_enabled=True,
        automation_enabled=True,
        created_by_user_id=owner.id,
    )
    db.add_all([integration, control])
    db.commit()
    return business, owner, integration, control


def test_health_configuration_ranges_are_enforced():
    settings = health_settings()
    assert settings.meta_integration_health_check_enabled is True
    with pytest.raises(ValidationError):
        health_settings(meta_token_expiry_warning_days=3, meta_token_expiry_critical_days=3)
    with pytest.raises(ValidationError):
        health_settings(
            meta_integration_health_job_timeout_seconds=90,
            meta_integration_health_lock_ttl_seconds=90,
        )


def test_instagram_health_checks_identity_scopes_subscription_and_expiry(health_db):
    db, _ = health_db
    settings = health_settings()
    _, _, integration, _ = integration_context(db, settings)
    profile = SimpleNamespace(
        external_account_id=integration.external_account_id,
        account_type="BUSINESS",
    )
    with (
        patch(
            "app.services.meta_integration_health_checkers.get_instagram_account_profile",
            return_value=profile,
        ),
        patch(
            "app.services.meta_integration_health_checkers.instagram_messages_subscription_active",
            return_value=True,
        ),
    ):
        result = check_instagram_integration_health(
            integration,
            access_token="not-logged",
            settings=settings,
        )
    assert result.health_status == "healthy"
    assert result.subscription_status == "active"
    assert result.asset_status == "active"

    integration.token_expires_at = datetime.utcnow() - timedelta(minutes=1)
    expired = check_instagram_integration_health(
        integration,
        access_token="not-logged",
        settings=settings,
    )
    assert expired.health_status == "action_required"
    assert expired.blocking is True
    assert expired.reconnection_required is True


def test_instagram_health_accepts_message_subscription_with_different_item_id(health_db):
    db, _ = health_db
    settings = health_settings(instagram_login_client_id="instagram-oauth-client-id")
    _, _, integration, _ = integration_context(db, settings)
    profile = SimpleNamespace(
        external_account_id=integration.external_account_id,
        account_type="BUSINESS",
    )
    response = SimpleNamespace(
        ok=True,
        status_code=200,
        json=lambda: {
            "data": [
                {
                    "id": "different-subscription-item-id",
                    "subscribed_fields": ["messages"],
                }
            ]
        },
    )

    with (
        patch(
            "app.services.meta_integration_health_checkers.get_instagram_account_profile",
            return_value=profile,
        ),
        patch("app.services.instagram_login_provider.requests.get", return_value=response),
    ):
        result = check_instagram_integration_health(
            integration,
            access_token="not-logged",
            settings=settings,
        )

    assert result.health_status == "healthy"
    assert result.subscription_status == "active"


def test_instagram_missing_subscription_is_repairable(health_db):
    db, _ = health_db
    settings = health_settings()
    _, _, integration, _ = integration_context(db, settings)
    profile = SimpleNamespace(
        external_account_id=integration.external_account_id,
        account_type="CREATOR",
    )
    with (
        patch(
            "app.services.meta_integration_health_checkers.get_instagram_account_profile",
            return_value=profile,
        ),
        patch(
            "app.services.meta_integration_health_checkers.instagram_messages_subscription_active",
            side_effect=[False, True],
        ),
        patch(
            "app.services.meta_integration_health_checkers.subscribe_instagram_messages_webhook"
        ) as subscribe,
    ):
        repaired = check_instagram_integration_health(
            integration,
            access_token="not-logged",
            settings=settings,
            repair_subscription=True,
        )
    subscribe.assert_called_once()
    assert repaired.health_status == "healthy"


def test_whatsapp_health_checks_token_waba_phone_and_subscription(health_db):
    db, _ = health_db
    settings = health_settings()
    _, _, integration, _ = integration_context(db, settings, channel="whatsapp")
    inspected = SimpleNamespace(expires_at=datetime.now(timezone.utc) + timedelta(days=30))
    assets = SimpleNamespace(
        registration_status="registered", phone_status="GREEN:VERIFIED:CLOUD_API"
    )
    with (
        patch(
            "app.services.meta_integration_health_checkers.inspect_whatsapp_business_token",
            return_value=inspected,
        ),
        patch(
            "app.services.meta_integration_health_checkers.verify_whatsapp_embedded_signup_assets",
            return_value=assets,
        ),
        patch(
            "app.services.meta_integration_health_checkers.whatsapp_app_subscription_active",
            return_value=True,
        ),
    ):
        result = check_whatsapp_integration_health(
            integration,
            access_token="not-logged",
            settings=settings,
        )
    assert result.health_status == "healthy"
    assert result.metadata["phone_status"].startswith("GREEN")


def test_unknown_health_provider_fails_safely():
    with pytest.raises(UnsupportedIntegrationHealthProvider, match="not supported"):
        health_checker_for_provider("unknown-provider")


def test_transient_provider_failures_never_revoke(health_db):
    db, _ = health_db
    settings = health_settings()
    _, _, instagram, _ = integration_context(db, settings)
    with patch(
        "app.services.meta_integration_health_checkers.get_instagram_account_profile",
        side_effect=InstagramLoginProviderError(
            "profile_failed", "Instagram is temporarily unavailable"
        ),
    ):
        instagram_result = check_instagram_integration_health(
            instagram, access_token="not-logged", settings=settings
        )
    assert instagram_result.health_status == "warning"
    assert instagram_result.retryable is True
    assert instagram_result.reconnection_required is False

    _, _, whatsapp, _ = integration_context(
        db, settings, channel="whatsapp", slug="transient-whatsapp"
    )
    with patch(
        "app.services.meta_integration_health_checkers.inspect_whatsapp_business_token",
        side_effect=WhatsAppEmbeddedSignupProviderError(
            "token_inspection_failed", "Meta is temporarily unavailable"
        ),
    ):
        whatsapp_result = check_whatsapp_integration_health(
            whatsapp, access_token="not-logged", settings=settings
        )
    assert whatsapp_result.health_status == "warning"
    assert whatsapp_result.retryable is True
    assert whatsapp_result.reconnection_required is False


def test_job_dedup_claim_and_abandoned_recovery(health_db):
    db, factory = health_db
    settings = health_settings()
    business, owner, integration, _ = integration_context(db, settings)
    first, created = enqueue_meta_integration_job(
        db,
        business_id=business.id,
        integration_id=integration.id,
        job_type="health_check",
        origin="owner",
        actor_user_id=owner.id,
    )
    second, replay_created = enqueue_meta_integration_job(
        db,
        business_id=business.id,
        integration_id=integration.id,
        job_type="health_check",
        origin="owner",
        actor_user_id=owner.id,
    )
    db.commit()
    assert created is True
    assert replay_created is False
    assert first.id == second.id

    assert claim_meta_integration_jobs(
        db, worker_id="worker-one", limit=1, lock_ttl_seconds=60
    ) == [first.id]
    db.commit()
    with factory() as other:
        assert (
            claim_meta_integration_jobs(other, worker_id="worker-two", limit=1, lock_ttl_seconds=60)
            == []
        )
        row = other.get(MetaIntegrationJob, first.id)
        row.lock_expires_at = datetime.utcnow() - timedelta(seconds=1)
        other.commit()
        assert claim_meta_integration_jobs(
            other, worker_id="worker-two", limit=1, lock_ttl_seconds=60
        ) == [first.id]


def test_job_cannot_target_another_business(health_db):
    db, _ = health_db
    settings = health_settings()
    business, _, integration, _ = integration_context(db, settings)
    other = Business(slug="other-health", name="Other", status="active")
    db.add(other)
    db.commit()
    with pytest.raises(ValueError, match="unavailable"):
        enqueue_meta_integration_job(
            db,
            business_id=other.id,
            integration_id=integration.id,
            job_type="health_check",
            origin="owner",
        )
    assert integration.business_id == business.id


def test_revoked_result_blocks_without_changing_commercial_controls(health_db):
    db, _ = health_db
    settings = health_settings()
    business, owner, integration, control = integration_context(db, settings)
    job, _ = enqueue_meta_integration_job(
        db,
        business_id=business.id,
        integration_id=integration.id,
        job_type="health_check",
        origin="owner",
        actor_user_id=owner.id,
    )
    now = datetime.now(timezone.utc)
    result = IntegrationHealthResult(
        health_status="revoked",
        healthy=False,
        retryable=False,
        blocking=True,
        reconnection_required=True,
        safe_error_code="token_revoked",
        safe_error_message="Authorization is no longer valid",
        token_expiry_status="unknown",
        subscription_status="unknown",
        asset_status="inaccessible",
        checked_at=now,
        next_check_at=now + timedelta(hours=24),
    )
    apply_integration_health_result(
        db, job=job, integration=integration, result=result, settings=settings
    )
    db.commit()
    assert integration.integration_status == "revoked"
    assert integration_health_blocks_delivery(integration) is True
    assert control.status == "approved"
    assert control.integrated_delivery_enabled is True
    assert control.automation_enabled is True
    assert (
        serialize_integration_health(integration, control=control, include_internal=False)[
            "integrated_delivery_available"
        ]
        is False
    )


def test_cleanup_expires_attempt_and_destroys_candidate_without_touching_integration(health_db):
    db, _ = health_db
    settings = health_settings()
    business, owner, integration, control = integration_context(db, settings)
    ciphertext, version = encrypt_secret("temporary-candidate", settings=settings)
    attempt = InstagramOAuthAttempt(
        business_id=business.id,
        user_id=owner.id,
        channel_control_id=control.id,
        purpose="reconnect",
        status="candidate_ready",
        state_hash="a" * 64,
        session_fingerprint_hash="b" * 64,
        return_path="/autonogrow-admin/index.html",
        created_at=datetime.now(timezone.utc) - timedelta(hours=2),
        expires_at=datetime.now(timezone.utc) - timedelta(minutes=1),
        candidate_external_account_id="1234567999",
        candidate_encrypted_access_token=ciphertext,
        candidate_encryption_key_version=version,
    )
    db.add(attempt)
    db.commit()
    result = cleanup_meta_integration_attempts(db, business_id=business.id, settings=settings)
    db.commit()
    assert result == {"expired": 1, "credentials_destroyed": 1, "deleted": 0}
    assert attempt.status == "expired"
    assert attempt.candidate_encrypted_access_token is None
    assert db.get(BusinessChannelIntegration, integration.id) is not None


def test_worker_schedules_claims_and_checks_outside_request_without_enabling_capabilities(
    health_db,
):
    db, factory = health_db
    settings = health_settings(
        worker_id="health-worker",
        meta_integration_health_batch_size=2,
    )
    _, _, integration, control = integration_context(db, settings)
    integration.next_health_check_at = datetime.utcnow() - timedelta(seconds=1)
    control.integrated_delivery_enabled = False
    control.automation_enabled = False
    db.commit()
    checked = datetime.now(timezone.utc)

    def checker(integration_snapshot, *, access_token, settings, repair_subscription=False):
        assert integration_snapshot.id == integration.id
        assert access_token == "safe-test-token"
        assert repair_subscription is False
        return IntegrationHealthResult(
            health_status="healthy",
            healthy=True,
            retryable=False,
            blocking=False,
            reconnection_required=False,
            safe_error_code=None,
            safe_error_message=None,
            token_expiry_status="valid",
            subscription_status="active",
            asset_status="active",
            checked_at=checked,
            next_check_at=checked + timedelta(hours=24),
        )

    worker = ChannelWorker(settings=settings, session_factory=factory, sleep=lambda _: None)
    with patch("app.workers.channel_worker.health_checker_for_provider", return_value=checker):
        assert worker.run_once() == 1
    db.expire_all()
    refreshed = db.get(BusinessChannelIntegration, integration.id)
    refreshed_control = db.get(BusinessChannelControl, control.id)
    assert refreshed.health_status == "healthy"
    assert refreshed.consecutive_health_failures == 0
    assert refreshed_control.integrated_delivery_enabled is False
    assert refreshed_control.automation_enabled is False
    assert db.query(MetaIntegrationJob).one().status == "completed"


def test_worker_blocks_a_previously_healthy_unknown_provider(health_db):
    db, factory = health_db
    settings = health_settings(
        worker_id="unknown-provider-worker",
        meta_integration_health_check_enabled=False,
    )
    business, _, integration, control = integration_context(db, settings)
    integration.channel = "unknown-provider"
    integration.provider = "unknown-provider"
    integration.health_status = "healthy"
    job, created = enqueue_meta_integration_job(
        db,
        business_id=business.id,
        integration_id=integration.id,
        job_type="health_check",
        origin="system",
    )
    db.commit()
    assert created is True

    worker = ChannelWorker(settings=settings, session_factory=factory, sleep=lambda _: None)
    assert worker.run_once() == 1

    db.expire_all()
    refreshed = db.get(BusinessChannelIntegration, integration.id)
    refreshed_control = db.get(BusinessChannelControl, control.id)
    refreshed_job = db.get(MetaIntegrationJob, job.id)
    assert refreshed.health_status == "error"
    assert refreshed.health_error_code == "unsupported_integration_provider"
    assert integration_health_blocks_delivery(refreshed) is True
    assert refreshed.integration_status == "connected"
    assert refreshed_control.integrated_delivery_enabled is True
    assert refreshed_control.automation_enabled is True
    assert refreshed_job.status == "failed"


def test_worker_retries_subscription_when_repair_does_not_recover(health_db):
    db, factory = health_db
    settings = health_settings(
        worker_id="subscription-retry-worker",
        meta_integration_health_check_enabled=False,
    )
    business, _, integration, _ = integration_context(db, settings)
    job, _ = enqueue_meta_integration_job(
        db,
        business_id=business.id,
        integration_id=integration.id,
        job_type="retry_subscription",
        origin="system",
    )
    db.commit()
    checked = datetime.now(timezone.utc)

    def checker(integration_snapshot, *, access_token, settings, repair_subscription=False):
        assert repair_subscription is True
        return IntegrationHealthResult(
            health_status="degraded",
            healthy=False,
            retryable=True,
            blocking=False,
            reconnection_required=False,
            safe_error_code="instagram_subscription_missing",
            safe_error_message="Subscription is still missing",
            token_expiry_status="valid",
            subscription_status="missing",
            asset_status="active",
            checked_at=checked,
            next_check_at=checked + timedelta(hours=1),
        )

    worker = ChannelWorker(settings=settings, session_factory=factory, sleep=lambda _: None)
    with patch("app.workers.channel_worker.health_checker_for_provider", return_value=checker):
        assert worker.run_once() == 1

    db.expire_all()
    refreshed_job = db.get(MetaIntegrationJob, job.id)
    assert refreshed_job.status == "retry"
    assert refreshed_job.attempt_count == 1
    assert refreshed_job.next_retry_at is not None


def test_worker_completes_retry_when_message_subscription_is_already_active(health_db):
    db, factory = health_db
    settings = health_settings(
        instagram_login_client_id="instagram-oauth-client-id",
        worker_id="healthy-subscription-retry-worker",
        meta_integration_health_check_enabled=False,
    )
    business, _, integration, _ = integration_context(db, settings)
    job, _ = enqueue_meta_integration_job(
        db,
        business_id=business.id,
        integration_id=integration.id,
        job_type="retry_subscription",
        origin="system",
    )
    db.commit()
    profile = SimpleNamespace(
        external_account_id=integration.external_account_id,
        account_type="BUSINESS",
    )
    response = SimpleNamespace(
        ok=True,
        status_code=200,
        json=lambda: {
            "data": [
                {
                    "id": "different-subscription-item-id",
                    "subscribed_fields": ["messages"],
                }
            ]
        },
    )

    worker = ChannelWorker(settings=settings, session_factory=factory, sleep=lambda _: None)
    with (
        patch(
            "app.services.meta_integration_health_checkers.get_instagram_account_profile",
            return_value=profile,
        ),
        patch("app.services.instagram_login_provider.requests.get", return_value=response),
        patch(
            "app.services.meta_integration_health_checkers.subscribe_instagram_messages_webhook"
        ) as subscribe,
    ):
        assert worker.run_once() == 1

    db.expire_all()
    refreshed_integration = db.get(BusinessChannelIntegration, integration.id)
    refreshed_job = db.get(MetaIntegrationJob, job.id)
    assert refreshed_integration.health_status == "healthy"
    assert (
        json.loads(refreshed_integration.health_metadata_json)["subscription_status"] == "active"
    )
    assert refreshed_job.status == "completed"
    assert refreshed_job.next_retry_at is None
    assert refreshed_job.last_error_code is None
    subscribe.assert_not_called()


@pytest.mark.parametrize("job_status", ("queued", "retry"))
def test_suspended_business_meta_jobs_are_not_claimed(health_db, job_status):
    db, _factory = health_db
    business, _owner, integration, _control = integration_context(
        db, health_settings(), slug=f"suspended-meta-{job_status}"
    )
    business.status = "suspended"
    job = MetaIntegrationJob(
        business_id=business.id,
        integration_id=integration.id,
        job_type="health_check",
        status=job_status,
        idempotency_key=f"suspended-meta:{job_status}",
        origin="system",
        available_at=datetime.utcnow() - timedelta(seconds=1),
        next_retry_at=(
            datetime.utcnow() - timedelta(seconds=1) if job_status == "retry" else None
        ),
    )
    db.add(job)
    db.commit()

    claimed = claim_meta_integration_jobs(
        db,
        worker_id="status-worker",
        limit=10,
        lock_ttl_seconds=60,
    )

    assert claimed == []
    assert db.get(MetaIntegrationJob, job.id).status == job_status
